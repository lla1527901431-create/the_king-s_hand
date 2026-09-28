"""用户自己填的密钥（DeepSeek key / QQ 邮箱授权码）。

存储：public.user_secrets 表的 payload 字段（jsonb）。
敏感字段用 agent/crypto.py 在服务端加密后入库，数据库里只有密文。

对外只暴露"有没有配"的状态，**任何接口都不返回明文**。
明文只在后端内存里短暂存在，用于构造本次请求的 LLM 客户端 / 发邮件。
"""

from __future__ import annotations

from datetime import datetime

from agent import crypto, db

TABLE = "user_secrets"
COLUMNS = "payload"
SENSITIVE = ("deepseek_key", "smtp_pass")
PLAINTEXT = ("smtp_user",)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_payload() -> dict:
    rows = db.select(TABLE, columns=COLUMNS, limit=1)
    if not rows:
        return {}
    payload = rows[0].get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def _write_payload(payload: dict) -> None:
    db.upsert(TABLE, {"payload": payload}, on_conflict="user_id", returning=False)


def save_secrets(secrets: dict) -> dict:
    """合并保存用户提交的密钥。

    只覆盖提交了的字段：例如只想更新 DeepSeek key 时，不必重填 QQ 授权码。
    传空字符串表示"不修改该字段"，不是"清空"。
    """
    payload = _load_payload()

    for field in SENSITIVE:
        value = (secrets.get(field) or "").strip()
        if value:
            payload[field] = crypto.encrypt(value)

    for field in PLAINTEXT:
        value = (secrets.get(field) or "").strip()
        if value:
            payload[field] = value

    payload["updated_at"] = _now()
    _write_payload(payload)
    return crypto.payload_status(payload)


def load_secrets() -> dict:
    """取出并解密成明文。**只在服务端使用，绝不要写进日志或返回给前端。**"""
    return crypto.decrypt_payload(_load_payload())


def get_secret(name: str, default: str = "") -> str:
    """取单个明文密钥。"""
    return load_secrets().get(name) or default


def status() -> dict:
    """给前端看的状态（不含任何明文）。"""
    return crypto.payload_status(_load_payload())


def delete_secrets() -> None:
    """清空该用户的密钥记录（RLS 保证只删到自己的）。"""
    payload = _load_payload()
    if not payload:
        return
    # 密钥是"合并在同一行"的，所以只能整行删除
    db.delete(TABLE, {"user_id": "not.is.null"})
