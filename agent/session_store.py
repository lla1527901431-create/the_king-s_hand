"""会话层：Supabase Auth 的登录 / 续期 / 登出。

安全模型（HttpOnly cookie 方案）：

    浏览器                          后端                        Supabase
      │  POST /session/login ──────> │ ── 验密码 ─────────────> │
      │                              │ <── access + refresh ─── │
      │                              ├─ 两个 token 都塞进 HttpOnly cookie
      │ <── Set-Cookie ───────────── │
      │                                 (JS 读不到；数据库也不存)
      │
      │  GET /events（浏览器自动带 cookie）
      │ ───────────────────────────> │ 从 cookie 取 access_token 设进上下文
      │                              │ ── 带 JWT 查 PostgREST ─> │  RLS 判定
      │
      │  access_token 过期（约 1h）
      │  POST /session/refresh ─────> │ ── 用 refresh cookie 换新 ─> │
      │ <── 新 cookie ────────────── │

两条 Cookie：
    kh_access   短命（跟 Supabase 的 access_token 同寿命），真正用来鉴权
    kh_refresh  长命，只用于 POST /session/refresh

为什么这样比 localStorage 安全：
    页面就算被注入恶意 JS，也**读不到**这两个 cookie（HttpOnly 的含义）。
    代价是多了 CSRF 攻击面，用 SameSite=Lax + Origin 校验来防。
"""

from __future__ import annotations

import logging

import requests

import config
from agent import db, http_client

logger = logging.getLogger("agent.session")

ACCESS_COOKIE = "kh_access"
REFRESH_COOKIE = "kh_refresh"

# access_token 有效期未知时，cookie 按这个长度设置（Supabase 默认约 1 小时）
DEFAULT_ACCESS_MAX_AGE = 3600
REFRESH_MAX_AGE = 60 * 60 * 24 * 30  # 30 天


class AuthError(RuntimeError):
    """登录 / 续期失败。message 已是给用户看的中文。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _auth_url(path: str) -> str:
    return f"{config.SUPABASE_URL}/auth/v1/{path.lstrip('/')}"


def _headers() -> dict[str, str]:
    return {
        "apikey": config.SUPABASE_KEY,
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict, *, label: str) -> dict:
    """调 Supabase Auth。失败时翻译成人话。

    走 agent/http_client.py 的连接池 —— 登录本身要飞一次跨境往返，
    复用连接能从 5 秒级降到 0.5 秒级。
    """
    try:
        resp = http_client.request(
            "POST",
            _auth_url(path),
            headers=_headers(),
            json_body=payload,
        )
    except requests.exceptions.Timeout as e:
        raise AuthError("连接登录服务超时，请检查网络后重试。", status=504) from e
    except requests.exceptions.RequestException as e:
        raise AuthError("无法连接登录服务，请检查网络。", status=502) from e

    if resp.status_code >= 400:
        raise AuthError(_translate(resp.text, label), status=resp.status_code)

    return resp.json()


def _translate(body: str, label: str) -> str:
    import json

    code = ""
    message = body[:200]
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            code = str(data.get("error_code") or data.get("code") or "")
            message = str(data.get("msg") or data.get("message") or message)
    except Exception:
        pass

    if code in ("invalid_credentials", "invalid_grant"):
        # Supabase 故意不区分"密码错"和"邮箱未确认"，这里保持模糊但给出可操作建议
        return "邮箱或密码不正确。如果你刚注册，可能还需要先点邮件里的确认链接。"
    if code == "email_not_confirmed":
        return "邮箱还没确认，请先点注册邮件里的链接。"
    if code in ("user_already_exists", "email_exists"):
        return "这个邮箱已经注册过了，直接登录即可。"
    if code == "over_email_send_rate_limit":
        return "注册邮件发送过于频繁（免费版内置邮件服务每小时只有几封），请稍后再试。"
    if code == "email_address_invalid":
        return "这个邮箱地址不被接受，请换一个真实可用的邮箱。"
    if code == "weak_password":
        return "密码太简单了，请换一个更复杂的。"
    if code == "signup_disabled":
        return "当前项目已关闭注册。"
    return f"{label}失败：{message}"


def login(email: str, password: str) -> dict:
    """邮箱密码登录。返回 access/refresh token 与用户信息。"""
    email = (email or "").strip()
    if not email or "@" not in email:
        raise AuthError("请输入有效的邮箱地址。")
    if not password:
        raise AuthError("请输入密码。")

    data = _post(
        "token?grant_type=password",
        {"email": email, "password": password},
        label="登录",
    )

    access = data.get("access_token")
    refresh = data.get("refresh_token")
    if not access or not refresh:
        raise AuthError("登录返回的数据不完整，请重试。", status=502)

    user = data.get("user") or {}
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": int(data.get("expires_in") or DEFAULT_ACCESS_MAX_AGE),
        "user_id": user.get("id") or "",
        "email": user.get("email") or email,
    }


def register(email: str, password: str) -> dict:
    """注册新用户。

    返回里带 needs_confirmation：
        True  — 项目开着邮箱验证，用户要去点邮件链接才能登录
        False — 已直接拿到会话（邮箱验证关闭时是这个情况）

    注意：Supabase 对已注册邮箱的 signup 可能返回一个假的用户对象
    （防止探测"这个邮箱注册过没有"），所以这里不做"已存在"的判断，
    交给后续登录时报错。
    """
    email = (email or "").strip()
    if not email or "@" not in email:
        raise AuthError("请输入有效的邮箱地址。")
    if len(password or "") < 6:
        raise AuthError("密码至少 6 位。")

    data = _post("signup", {"email": email, "password": password}, label="注册")

    access = data.get("access_token")
    refresh = data.get("refresh_token")
    user = data.get("user") or {}

    if access and refresh:
        return {
            "needs_confirmation": False,
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": int(data.get("expires_in") or DEFAULT_ACCESS_MAX_AGE),
            "user_id": user.get("id") or "",
            "email": user.get("email") or email,
        }

    return {
        "needs_confirmation": True,
        "user_id": user.get("id") or "",
        "email": user.get("email") or email,
        "message": "注册成功。请到邮箱里点确认链接，然后回来登录。",
    }


def resend_confirmation(email: str) -> None:
    """重发确认邮件（用于用户没收到信时）。"""
    email = (email or "").strip()
    if not email or "@" not in email:
        raise AuthError("请输入有效的邮箱地址。")
    _post("resend", {"type": "signup", "email": email}, label="重发确认邮件")


def refresh(refresh_token: str) -> dict:
    """用 refresh_token 换新的 access_token。"""
    if not refresh_token:
        raise AuthError("登录状态已失效，请重新登录。", status=401)

    data = _post(
        "token?grant_type=refresh_token",
        {"refresh_token": refresh_token},
        label="续期",
    )
    access = data.get("access_token")
    new_refresh = data.get("refresh_token") or refresh_token
    if not access:
        raise AuthError("续期返回的数据不完整，请重新登录。", status=502)

    user = data.get("user") or {}
    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "expires_in": int(data.get("expires_in") or DEFAULT_ACCESS_MAX_AGE),
        "user_id": user.get("id") or "",
        "email": user.get("email") or "",
    }


def logout(access_token: str) -> None:
    """让 Supabase 撤销这个会话。失败不阻塞（本地 cookie 照清）。"""
    if not access_token:
        return
    try:
        http_client.request(
            "POST",
            _auth_url("logout"),
            headers={**_headers(), "Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:
        logger.warning("撤销会话失败（忽略，本地 cookie 照清）：%s", type(e).__name__)


def user_id_of(access_token: str) -> str:
    """从 access_token 里解出 user_id（不验签，仅用于展示与日志）。"""
    try:
        from server.auth import decode_claims

        return str(decode_claims(access_token).get("sub") or "")
    except Exception:
        return ""


def set_auth_context(access_token: str) -> None:
    """把 token 放进 db 层的上下文，后续查询自动带上这个身份。"""
    db.set_current_token(access_token)
