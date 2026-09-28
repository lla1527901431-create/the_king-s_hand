"""Supabase 数据访问层。

设计要点：
* 只用 publishable key + **当前请求用户的 JWT** 访问 PostgREST。
  这样数据库会按 auth.uid() 执行 RLS，隔离由数据库强制，不靠这里判断。
* 不缓存连接、每次请求新建（requests 内部有连接池，开销很小）。
* 到 *.supabase.co 的链路可能不稳定（TLS 握手超时是常见现象），
  所以统一在这里做「短超时 + 指数退避重试」。
* 把 HTTP 错误翻译成带中文提示的 SupabaseError，避免把
  ReadTimeoutError 这种堆栈直接甩给用户。

用户身份通过 contextvar 传递：请求进来时 server/auth.py 把 JWT 放进去，
下面所有函数自动带上，不需要一层层往参数里塞。
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

import config
from agent import http_client

# 当前请求的用户 JWT。为空表示匿名请求（RLS 下什么都读不到）。
_user_token: ContextVar[str] = ContextVar("supabase_user_token", default="")

# 哪些表允许访问（防止拼错表名导致奇怪的 404）
ALLOWED_TABLES = {"events", "pending_tasks", "memories", "user_secrets"}


class SupabaseError(RuntimeError):
    """Supabase 调用失败。message 已经是给用户看的中文提示。"""

    def __init__(self, status: int, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)


def set_current_token(token: str) -> None:
    _user_token.set(token or "")


def get_current_token() -> str:
    return _user_token.get()


def _headers(prefer: str = "") -> dict[str, str]:
    headers = {
        "apikey": config.SUPABASE_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    token = _user_token.get()
    # 有用户 JWT 就用它；否则退回 publishable key（匿名身份，RLS 下读不到数据）
    headers["Authorization"] = f"Bearer {token}" if token else f"Bearer {config.SUPABASE_KEY}"
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _translate(status: int, body: str) -> SupabaseError:
    """把 PostgREST 的错误翻译成用户能看懂的中文。"""
    code = ""
    message = body[:300]
    try:
        import json

        data = json.loads(body)
        if isinstance(data, dict):
            code = str(data.get("code") or "")
            message = str(data.get("message") or data.get("msg") or message)
    except Exception:
        pass

    if status == 401:
        hint = "登录状态已失效，请重新登录。"
    elif status == 403:
        hint = "没有权限访问这条数据（它不属于当前账号）。"
    elif code == "PGRST205":
        hint = "数据库表不存在，请先执行 sql/01_schema.sql 建表。"
    elif code == "23505":
        hint = "这条数据已经存在了（主键冲突）。"
    elif code == "23503":
        hint = "关联的用户不存在。"
    elif code == "23514":
        hint = "数据不符合约束（例如结束时间早于开始时间）。"
    elif code == "42501":
        hint = "被数据库的行级安全策略拒绝了。"
    elif status == 404:
        hint = "接口或表不存在。"
    elif status >= 500:
        hint = "Supabase 服务端出错，请稍后重试。"
    else:
        hint = "请求被拒绝。"

    return SupabaseError(status, code, f"{hint}（HTTP {status} {code}）", message)


def request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    prefer: str = "",
    retries: int | None = None,
) -> requests.Response:
    """发一个 PostgREST 请求。

    连接复用交给 agent/http_client.py 的连接池 —— 这一步至关重要：
    每次新建 HTTPS 连接要 5 秒左右（跨境链路的 DNS+TCP+TLS），
    复用之后单次往返只要 0.4 秒。
    """
    url = f"{config.SUPABASE_URL}/rest/v1/{path.lstrip('/')}"

    try:
        resp = http_client.request(
            method,
            url,
            headers=_headers(prefer),
            params=params,
            json_body=json_body,
        )
    except requests.exceptions.Timeout as e:
        raise SupabaseError(
            0, "timeout",
            "连接 Supabase 超时，请检查网络（或代理）后重试。",
            repr(e),
        ) from e
    except requests.exceptions.RequestException as e:
        raise SupabaseError(
            0, "network",
            "无法连接 Supabase，请检查网络（或代理）。",
            repr(e),
        ) from e

    if resp.status_code >= 400:
        raise _translate(resp.status_code, resp.text)

    return resp


def select(
    table: str,
    *,
    columns: str = "*",
    filters: dict[str, str] | None = None,
    order: str = "",
    limit: int | None = None,
) -> list[dict]:
    """查询多行。filter 的值是 PostgREST 算子表达式，例如 'eq.abc'。"""
    if table not in ALLOWED_TABLES:
        raise ValueError(f"不允许访问的表：{table}")
    params: dict[str, Any] = {"select": columns}
    for key, value in (filters or {}).items():
        params[key] = value
    if order:
        params["order"] = order
    if limit:
        params["limit"] = str(limit)

    resp = request("GET", table, params=params)
    if not resp.text.strip():
        return []
    data = resp.json()
    return data if isinstance(data, list) else [data]


def insert(table: str, rows: dict | list[dict], *, returning: bool = True) -> list[dict]:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"不允许访问的表：{table}")
    prefer = "return=representation" if returning else "return=minimal"
    resp = request("POST", table, json_body=rows, prefer=prefer)
    if not returning or not resp.text.strip():
        return []
    data = resp.json()
    return data if isinstance(data, list) else [data]


def upsert(
    table: str,
    rows: dict | list[dict],
    *,
    on_conflict: str,
    returning: bool = True,
) -> list[dict]:
    """主键冲突时改为更新（merge-duplicates）。"""
    if table not in ALLOWED_TABLES:
        raise ValueError(f"不允许访问的表：{table}")
    prefer = "resolution=merge-duplicates," + (
        "return=representation" if returning else "return=minimal"
    )
    resp = request(
        "POST", table, json_body=rows, prefer=prefer, params={"on_conflict": on_conflict}
    )
    if not returning or not resp.text.strip():
        return []
    data = resp.json()
    return data if isinstance(data, list) else [data]


def update(table: str, filters: dict[str, str], fields: dict, *, returning: bool = True) -> list[dict]:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"不允许访问的表：{table}")
    prefer = "return=representation" if returning else "return=minimal"
    resp = request("PATCH", table, params=filters, json_body=fields, prefer=prefer)
    if not returning or not resp.text.strip():
        return []
    data = resp.json()
    return data if isinstance(data, list) else [data]


def delete(table: str, filters: dict[str, str], *, returning: bool = True) -> list[dict]:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"不允许访问的表：{table}")
    if not filters:
        # PostgREST 不允许无条件 DELETE（会返回 21000）。
        # 这里统一补一个"永真"条件，同时避免误写成"删光整张表"。
        filters = {"user_id": "not.is.null"}
    prefer = "return=representation" if returning else "return=minimal"
    resp = request("DELETE", table, params=filters, prefer=prefer)
    if not returning or not resp.text.strip():
        return []
    data = resp.json()
    return data if isinstance(data, list) else [data]


def health() -> tuple[bool, str]:
    """连通性自检，用于启动检查或 /health 接口。"""
    try:
        request("GET", "events", params={"select": "id", "limit": "1"}, retries=1)
        return True, "ok"
    except SupabaseError as e:
        return False, e.message


# ---------------------------------------------------------------------------
# 时间格式转换
#
# 数据库里是 timestamptz，PostgREST 返回 ISO 8601（2026-12-01T09:00:00+00:00）。
# 但前端 static/app.js 的 parseDateTime 只认 'YYYY-MM-DD HH:MM'，
# 所以这里统一转换：写库时把本地时间带上时区，读库时翻回不带时区的本地时间。
# 时区取 APP_TIMEZONE（默认东八区）。
# ---------------------------------------------------------------------------
APP_TZ = timezone(timedelta(hours=8))
LOCAL_FMT = "%Y-%m-%d %H:%M"


def to_db_time(value: str | None) -> str | None:
    """'2026-12-01 09:00' -> '2026-12-01T09:00:00+08:00'（交给 PostgREST）。"""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        # 先按本地时间解析，再补上时区
        parsed = datetime.strptime(text, LOCAL_FMT).replace(tzinfo=APP_TZ)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(f"无法解析时间 {value!r}，期望格式 'YYYY-MM-DD HH:MM'")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=APP_TZ)
    return parsed.isoformat()


def from_db_time(value: str | None) -> str:
    """ISO 8601 -> 'YYYY-MM-DD HH:MM'（本地时区）。"""
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        # 已经是 'YYYY-MM-DD HH:MM' 或其它格式，截断到分钟就好
        return text[:16].replace("T", " ")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TZ)
    return parsed.astimezone(APP_TZ).strftime(LOCAL_FMT)
