"""用户密钥的加解密（信封加密）。

为什么要加密存库：
    用户填的 DeepSeek key / QQ 授权码要"登录后自动调取"，就必须持久化。
    直接存明文的话，一旦 Supabase 被拖库，所有人的 key 就全泄露了。
    所以这里用 AES-256-GCM 在**服务端**加密，只有密文进入数据库。

密钥分层：
    SECRET_MASTER_KEY（主密钥，只在服务器的 .env / 系统环境变量里）
        └── 加密 ──> user_secrets.payload 里的密文

    主密钥**永不进入数据库、永不进 git、永不写日志**。
    ⚠️ 主密钥丢失 = 已保存的所有用户密钥永久无法解密，请离线备份。

格式：v1.<base64(nonce)>.<base64(ciphertext+tag)>，带版本号便于以后轮换算法。
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config

VERSION = "v1"
NONCE_BYTES = 12          # GCM 标准 nonce 长度
KEY_BYTES = 32            # AES-256

_cached_key: bytes | None = None


class CryptoNotConfigured(RuntimeError):
    """主密钥没配置好。"""


def generate_master_key() -> str:
    """生成一个新的主密钥（base64 字符串）。只用于初始化，不要在运行时调用。"""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii")


def _load_key() -> bytes:
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    raw = (config.SECRET_MASTER_KEY or "").strip()
    if not raw:
        raise CryptoNotConfigured(
            "SECRET_MASTER_KEY 未配置，无法加密/解密用户密钥。"
            "请运行 python tools/gen_master_key.py 生成并写入 .env。"
        )
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as e:
        raise CryptoNotConfigured(f"SECRET_MASTER_KEY 不是合法的 base64：{e}") from e

    if len(key) != KEY_BYTES:
        raise CryptoNotConfigured(
            f"SECRET_MASTER_KEY 解出来是 {len(key)} 字节，需要 {KEY_BYTES} 字节（AES-256）。"
            "请重新生成。"
        )
    _cached_key = key
    return key


def is_configured() -> bool:
    try:
        _load_key()
        return True
    except CryptoNotConfigured:
        return False


def key_fingerprint() -> str:
    """主密钥的指纹（sha256 前 12 位十六进制）。

    用于**核对不同环境用的是不是同一把密钥** —— 部署时把本地的指纹和
    服务器日志里的指纹一比就知道，而不需要把密钥本身抄来抄去。

    ⚠️ 这是单向哈希，不能反推出密钥；但仍然只该出现在自己的日志里。
    """
    import hashlib

    try:
        return hashlib.sha256(_load_key()).hexdigest()[:12]
    except CryptoNotConfigured:
        return "(未配置)"


def encrypt(plaintext: str) -> str:
    """加密一个字符串。返回 v1.<nonce>.<密文> 形式。"""
    if plaintext is None:
        raise ValueError("待加密内容不能为空")
    key = _load_key()
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return ".".join([
        VERSION,
        base64.urlsafe_b64encode(nonce).decode("ascii"),
        base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    ])


def decrypt(token: str) -> str:
    """解密 encrypt() 的结果。"""
    if not token:
        return ""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != VERSION:
        raise ValueError("密文格式不正确（期望 v1.<nonce>.<data>）")
    try:
        nonce = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        ciphertext = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
    except Exception as e:
        raise ValueError(f"密文不是合法 base64：{e}") from e
    try:
        plaintext = AESGCM(_load_key()).decrypt(nonce, ciphertext, None)
    except Exception as e:
        raise ValueError(
            "解密失败：主密钥可能变了，或者密文被篡改。"
            "如果换过 SECRET_MASTER_KEY，已保存的用户密钥无法恢复，需要让用户重填。"
        ) from e
    return plaintext.decode("utf-8")


# ---------------------------------------------------------------------------
# 给 user_secrets.payload 用的小工具
#
# payload 里哪些字段要加密由这里统一约定：
#   加密：deepseek_key / smtp_pass
#   明文：smtp_user（邮箱本身不算敏感）、updated_at
# ---------------------------------------------------------------------------
SENSITIVE_FIELDS = ("deepseek_key", "smtp_pass")
PLAIN_FIELDS = ("smtp_user",)


def encrypt_payload(secrets: dict) -> dict:
    """把用户提交的明文密钥转成可入库的 payload（敏感字段加密）。"""
    out: dict = {}
    for field in SENSITIVE_FIELDS:
        value = (secrets.get(field) or "").strip()
        if value:
            out[field] = encrypt(value)
    for field in PLAIN_FIELDS:
        value = (secrets.get(field) or "").strip()
        if value:
            out[field] = value
    return out


def decrypt_payload(payload: dict | None) -> dict:
    """把库里的 payload 还原成明文（仅在服务端内存中使用，绝不写日志）。"""
    payload = payload or {}
    out: dict = {}
    for field in SENSITIVE_FIELDS:
        token = payload.get(field)
        if not token:
            continue
        try:
            out[field] = decrypt(token)
        except ValueError as e:
            # 单个字段解不开不应该让整个请求崩掉，但要留下可诊断的痕迹
            out[field] = ""
            out.setdefault("_errors", []).append(f"{field}: {e}")
    for field in PLAIN_FIELDS:
        if payload.get(field):
            out[field] = payload[field]
    return out


def payload_status(payload: dict | None) -> dict:
    """给前端看的状态：只告诉用户"有没有配"，绝不返回明文。"""
    payload = payload or {}
    return {
        "has_deepseek_key": bool(payload.get("deepseek_key")),
        "smtp_user": payload.get("smtp_user") or "",
        "has_smtp_pass": bool(payload.get("smtp_pass")),
        "updated_at": payload.get("updated_at") or "",
    }


def dumps_safe(secrets: dict) -> str:
    """调试输出用：把敏感字段替换成掩码，避免打日志时泄露。"""
    safe = dict(secrets or {})
    for field in SENSITIVE_FIELDS:
        if safe.get(field):
            safe[field] = config.mask(safe[field])
    return json.dumps(safe, ensure_ascii=False)
