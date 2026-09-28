#业务逻辑都在 agent_runner.py 和 agent/ 里，这里只做"接口"

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from agent import secrets_store, session_store
from agent.calendar_store import add_event, delete_event, list_events, update_event
from agent.ics_exporter import build_ics, send_ics_email
from agent.llm import CredentialsMissing
from agent.pending_store import (
    add_pending,
    delete_pending,
    load_pending,
    pop_pending,
    update_pending,
)
from server.agent_runner import chat, reset_history
from server.auth import (
    CSRF_HEADER,
    REFRESH_COOKIE,
    TokenInfo,
    clear_session_cookies,
    csrf_protect,
    current_token,
    db_errors,
    set_session_cookies,
)

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="The King's Hand")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# 统一错误输出：给前端一个可编程判断的 auth_code
# ---------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    code = (exc.headers or {}).get("X-Auth-Code", "") if exc.headers else ""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "auth_code": code},
    )


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class ResendRequest(BaseModel):
    email: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    output: str
    steps: list
    tasks: list = []
    key_source: str = ""


class AddPendingRequest(BaseModel):
    id: str
    title: str
    start: str | None = None
    end: str | None = None
    location: str = ""
    note: str = ""


class IdRequest(BaseModel):
    id: str


class UpdatePendingRequest(BaseModel):
    id: str
    title: str
    start: str | None = None
    end: str | None = None
    location: str = ""
    note: str = ""


class ExportEmailRequest(BaseModel):
    to_email: str


class EventUpdateRequest(BaseModel):
    id: str
    title: str
    start: str
    end: str
    location: str = ""
    note: str = ""


class EventDeleteRequest(BaseModel):
    id: str


class CredentialsRequest(BaseModel):
    """用户自己填的密钥。全部可选：只想更新其中一个就只传那一个。"""

    deepseek_key: str = ""
    smtp_user: str = ""
    smtp_pass: str = ""


class MemoryUpdateRequest(BaseModel):
    """整块覆盖式更新记忆。只传想改的块。"""

    facts: list[str] | None = None
    observations: list[str] | None = None
    preferences: list[str] | None = None


def _user_credentials() -> dict:
    """取出当前用户的 DeepSeek 凭据（已解密）。

    ⚠️ 明文只在内存里短暂存在，绝不写日志、绝不返回给前端。
    """
    try:
        secrets = secrets_store.load_secrets()
    except Exception as e:
        print(f"[credentials] 读取失败：{type(e).__name__}: {e}")
        return {}
    key = secrets.get("deepseek_key") or ""
    return {"deepseek_key": key} if key else {}


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    from agent import crypto, db

    ok, message = db.health()
    return {
        "status": "ok" if ok else "degraded",
        "supabase": message,
        "crypto_configured": crypto.is_configured(),
        "cookie_secure": config.COOKIE_SECURE,
    }


# ---------------------------------------------------------------------------
# 会话（登录 / 续期 / 登出）
# ---------------------------------------------------------------------------
@app.post("/session/login")
def session_login(req: LoginRequest, response: Response):
    try:
        result = session_store.login(req.email, req.password)
    except session_store.AuthError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e

    set_session_cookies(
        response,
        result["access_token"],
        result["refresh_token"],
        access_max_age=result["expires_in"],
    )
    return {"status": "ok", "user_id": result["user_id"], "email": result["email"]}


@app.post("/session/register")
def session_register(req: RegisterRequest, response: Response):
    try:
        result = session_store.register(req.email, req.password)
    except session_store.AuthError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e

    if result.get("needs_confirmation"):
        # 项目开着邮箱验证：注册成功但不能立刻登录
        return {
            "status": "needs_confirmation",
            "email": result["email"],
            "message": result.get("message", "请到邮箱点确认链接后再登录。"),
        }

    set_session_cookies(
        response,
        result["access_token"],
        result["refresh_token"],
        access_max_age=result["expires_in"],
    )
    return {"status": "ok", "user_id": result["user_id"], "email": result["email"]}


@app.post("/session/resend")
def session_resend(req: ResendRequest):
    try:
        session_store.resend_confirmation(req.email)
    except session_store.AuthError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e
    return {"status": "ok", "message": "确认邮件已重新发送，请查收（注意垃圾邮件）。"}


@app.get("/session")
def session_info(request: Request):
    """告诉前端"现在登录着吗、你是谁"。不抛 401，便于页面初始化判断。"""
    token = (request.cookies.get("kh_access") or "").strip()
    if not token:
        return {"authenticated": False}
    try:
        from server.auth import decode_claims

        claims = decode_claims(token)
    except Exception:
        return {"authenticated": False}

    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp < datetime.now().timestamp():
        return {"authenticated": False, "expired": True}

    return {
        "authenticated": True,
        "user_id": str(claims.get("sub") or ""),
        "email": claims.get("email") or "",
    }


@app.post("/session/refresh")
def session_refresh(request: Request, response: Response):
    """用 refresh cookie 换新的 access token。

    这个接口**不需要 CSRF 校验**：它不改任何业务数据，且必须能在
    access_token 过期后调用（那时 current_token 会直接拒绝）。
    """
    refresh_token = (request.cookies.get(REFRESH_COOKIE) or "").strip()
    try:
        result = session_store.refresh(refresh_token)
    except session_store.AuthError as e:
        clear_session_cookies(response)
        raise HTTPException(status_code=e.status, detail=e.message) from e

    set_session_cookies(
        response,
        result["access_token"],
        result["refresh_token"],
        access_max_age=result["expires_in"],
    )
    return {"status": "ok", "user_id": result["user_id"], "email": result["email"]}


@app.post("/session/logout")
def session_logout(request: Request, response: Response, _: None = Depends(csrf_protect)):
    token = (request.cookies.get("kh_access") or "").strip()
    session_store.logout(token)
    clear_session_cookies(response)
    return {"status": "ok"}


@app.get("/me")
def me(user: TokenInfo = Depends(current_token)):
    """告诉前端"你是谁、有没有配 key"。不返回任何密钥内容。"""
    with db_errors():
        status = secrets_store.status()
    return {
        "user_id": user.user_id,
        "email": user.claims.get("email") or "",
        "credentials": status,
    }


# ---------------------------------------------------------------------------
# 用户密钥
# ---------------------------------------------------------------------------
@app.get("/credentials")
def get_credentials(user: TokenInfo = Depends(current_token)):
    """只返回"有没有配"，不返回明文。"""
    with db_errors():
        return {"credentials": secrets_store.status()}


@app.post("/credentials")
def save_credentials(
    req: CredentialsRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    if not req.deepseek_key and not req.smtp_user and not req.smtp_pass:
        raise HTTPException(status_code=400, detail="没有提交任何要保存的内容。")

    with db_errors():
        try:
            status = secrets_store.save_secrets(
                {
                    "deepseek_key": req.deepseek_key,
                    "smtp_user": req.smtp_user,
                    "smtp_pass": req.smtp_pass,
                }
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"保存失败：{e}") from e
    return {"status": "ok", "credentials": status}


@app.delete("/credentials")
def delete_credentials(
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    with db_errors():
        secrets_store.delete_secrets()
    return {"status": "ok", "credentials": secrets_store.status()}


# ---------------------------------------------------------------------------
# 对话
# ---------------------------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    req: ChatRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空。")

    credentials = _user_credentials()

    with db_errors():
        try:
            result = chat(req.message, user_id=user.user_id, credentials=credentials)
        except CredentialsMissing as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            print(f"[chat] 失败：{type(e).__name__}: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"对话处理失败（{type(e).__name__}）。如果是刚配置完 key，请确认 key 有效。",
            ) from e
    return result


@app.post("/reset")
def reset_endpoint(
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    """清空当前用户的对话上下文（不动长期记忆、不动日历）。"""
    reset_history(user.user_id)
    return {"status": "ok", "scope": "chat_history_only"}


# ---------------------------------------------------------------------------
# 长期记忆（给"我的记忆"面板用）
# ---------------------------------------------------------------------------
@app.get("/memory")
def get_memory(user: TokenInfo = Depends(current_token)):
    """读出自己的长期记忆。

    这是"AI 记错了怎么办"的兜底：用户能看见记了什么，并自己改。
    """
    from agent.memory_store import load_memory

    with db_errors():
        data = load_memory()
    return {
        "memory": {
            "facts": data.get("facts", []),
            "observations": data.get("observations", []),
            "preferences": data.get("preferences", []),
            "last_updated": data.get("last_updated", ""),
        }
    }


@app.post("/memory/update")
def update_memory(
    req: MemoryUpdateRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    """整块覆盖式更新记忆（只传要改的块，其它块保持不变）。"""
    from agent.memory_store import load_memory, save_memory

    with db_errors():
        memory = load_memory()
        if req.facts is not None:
            memory["facts"] = [f for f in req.facts if str(f).strip()]
        if req.observations is not None:
            memory["observations"] = [o for o in req.observations if str(o).strip()]
        if req.preferences is not None:
            memory["preferences"] = [p for p in req.preferences if str(p).strip()]
        save_memory(memory)
        updated = load_memory()

    return {
        "status": "ok",
        "memory": {
            "facts": updated.get("facts", []),
            "observations": updated.get("observations", []),
            "preferences": updated.get("preferences", []),
            "last_updated": updated.get("last_updated", ""),
        },
    }


@app.post("/memory/clear")
def clear_memory_endpoint(
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    """清空全部长期记忆。"""
    from agent.memory_store import clear_memory

    with db_errors():
        clear_memory()
    return {"status": "ok", "memory": {"facts": [], "observations": [], "preferences": [], "last_updated": ""}}


# ---------------------------------------------------------------------------
# 日历
# ---------------------------------------------------------------------------
@app.get("/events")
def list_events_endpoint(user: TokenInfo = Depends(current_token)):
    with db_errors():
        return {"events": list_events()}


@app.post("/event/update")
def event_update_endpoint(
    req: EventUpdateRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    fields = {
        "title": req.title,
        "start": req.start,
        "end": req.end,
        "location": req.location,
        "note": req.note,
    }
    with db_errors():
        result = update_event(req.id, fields)
    if result is None:
        return {"status": "not_found"}
    return {"status": "ok", "event": result}


@app.post("/event/delete")
def event_delete_endpoint(
    req: EventDeleteRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    with db_errors():
        ok = delete_event(req.id)
    return {"status": "ok" if ok else "not_found"}


# ---------------------------------------------------------------------------
# 待确认 / 待计划
# ---------------------------------------------------------------------------
@app.get("/pending")
def pending_endpoint(user: TokenInfo = Depends(current_token)):
    with db_errors():
        return load_pending()


@app.post("/pending/add")
def add_pending_endpoint(
    req: AddPendingRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    with db_errors():
        add_pending(req.model_dump())
    return {"status": "ok"}


@app.post("/pending/delete")
def delete_pending_endpoint(
    req: IdRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    with db_errors():
        ok = delete_pending(req.id)
    return {"status": "ok" if ok else "not_found"}


@app.post("/pending/update")
def update_pending_endpoint(
    req: UpdatePendingRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    fields = {
        "title": req.title,
        "start": req.start,
        "end": req.end,
        "location": req.location,
        "note": req.note,
    }
    with db_errors():
        result = update_pending(req.id, fields)
    if result is None:
        return {"status": "not_found"}
    return {"status": "ok", "task": result}


@app.post("/pending/confirm")
def confirm_pending_endpoint(
    req: IdRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    with db_errors():
        task = pop_pending(req.id)
        if task is None:
            return {"status": "not_found"}

        # 只有开始时间时补一个默认时长，否则会把 end 为空的事件写进日历
        start_text = task.get("start")
        if start_text and not task.get("end"):
            try:
                start_dt = datetime.strptime(start_text, "%Y-%m-%d %H:%M")
                task["end"] = (start_dt + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass

        event = add_event(
            task["title"],
            task["start"],
            task["end"],
            task.get("location", ""),
            task.get("note", ""),
        )
    return {"status": "ok", "event": event}


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
@app.get("/export_ics")
def export_ics_endpoint(user: TokenInfo = Depends(current_token)):
    with db_errors():
        events = list_events()
    ics_text = build_ics(events)
    return Response(
        content=ics_text,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="the_kings_hand.ics"'},
    )


@app.post("/export_email")
def export_email_endpoint(
    req: ExportEmailRequest,
    user: TokenInfo = Depends(current_token),
    _: None = Depends(csrf_protect),
):
    with db_errors():
        events = list_events()

    # 用**当前用户自己**的 QQ 邮箱与授权码发送
    secrets = {}
    try:
        secrets = secrets_store.load_secrets()
    except Exception as e:
        print(f"[export] 读取用户邮箱配置失败：{type(e).__name__}")

    ok, msg = send_ics_email(
        events,
        req.to_email,
        smtp_user=secrets.get("smtp_user", ""),
        smtp_pass=secrets.get("smtp_pass", ""),
    )
    return {"status": "ok" if ok else "error", "message": msg}
