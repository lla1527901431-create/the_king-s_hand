"""集中配置。

所有模块都从这里取配置，不要在别处直接 os.getenv —— 这样启动时能一次性
做完整性检查，而不是运行时才在某处炸掉。

安全约定：
* 真正的密钥（DeepSeek key / QQ 授权码）由用户在页面上填写，
  加密后存进数据库，**不在这里读取**。
* 这里只放"服务器自己的配置"：Supabase 地址与 publishable key、
  以及用于加密用户密钥的主密钥。
* mask() 用于日志：只输出前后几位，避免密钥出现在日志或终端里。
"""

import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# .env 只作为兜底：已存在的系统环境变量优先（load_dotenv 默认不覆盖）。
load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_secret(name: str, default: str = "", required: bool = False) -> str:
    value = (os.getenv(name) or default).strip()
    if required and not value:
        raise RuntimeError(
            f"缺少环境变量 {name}。请设置它（Windows 可用："
            f'setx {name} "..."）或写进项目根目录的 .env。'
        )
    return value


def mask(value: str) -> str:
    """只用于日志输出，例如 sk-0448****b562。"""
    value = value or ""
    if not value:
        return "(空)"
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}****{value[-4:]}"


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL = get_secret("SUPABASE_URL", required=True).rstrip("/")
SUPABASE_KEY = get_secret("SUPABASE_PUBLISHABLE_KEY", required=True)

# 用于加密用户密钥的主密钥（base64，32 字节）
SECRET_MASTER_KEY = get_secret("SECRET_MASTER_KEY")

# ---------------------------------------------------------------------------
# 网络参数：到 *.supabase.co 的链路可能不稳定，所以超时偏短、重试偏多。
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = float(get_secret("SUPABASE_TIMEOUT", "10"))
REQUEST_RETRIES = int(get_secret("SUPABASE_RETRIES", "3"))
RETRY_BACKOFF = float(get_secret("SUPABASE_RETRY_BACKOFF", "0.8"))

# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
# 对话上下文保留的最近消息数（按用户分别计算）
RECENT_HISTORY_MAX = int(get_secret("RECENT_HISTORY_MAX", "10"))

# 某个用户多久没说话就回收他的对话上下文（分钟）。
# 对话历史存在进程内存里，不回收的话每个来过一次的用户都会永久占一份。
RECENT_HISTORY_IDLE_MINUTES = int(get_secret("RECENT_HISTORY_IDLE_MINUTES", "30"))

# Cookie 是否带 Secure 标记。本机 http 调试必须为 false，
# 一旦部署到 HTTPS（公网），必须设成 true。
COOKIE_SECURE = get_secret("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")

# 调试模式：开启热重载，并让 /health 返回诊断细节。
# ⚠️ 公网部署必须为 false（main.py 会据此决定是否 reload）。
DEBUG = get_secret("DEBUG", "false").lower() in ("1", "true", "yes")


def startup_check() -> list[str]:
    """启动自检。返回警告列表；致命问题直接抛异常。"""
    warnings: list[str] = []

    if not SUPABASE_URL.startswith("https://"):
        raise RuntimeError(f"SUPABASE_URL 看起来不对：{SUPABASE_URL!r}")
    if not SUPABASE_URL.endswith(".supabase.co"):
        warnings.append("SUPABASE_URL 不是 *.supabase.co，确认用的是自定义域名吗？")

    if len(SUPABASE_KEY) < 30:
        raise RuntimeError("SUPABASE_PUBLISHABLE_KEY 长度异常，请检查")
    if "service_role" in SUPABASE_KEY:
        raise RuntimeError(
            "检测到 SUPABASE 里放的是 service_role key！"
            "它拥有绕过全部 RLS 的权限，绝不能放进这个项目。请改用 publishable key。"
        )

    if not SECRET_MASTER_KEY:
        warnings.append(
            "SECRET_MASTER_KEY 未设置：用户填写的 DeepSeek key / QQ 授权码将无法加密保存。"
            "请运行 python tools/gen_master_key.py 生成，并离线备份。"
        )
    else:
        # 长度必须正好 32 字节（AES-256），否则加解密会在运行时才失败。
        # 这个检查是踩过坑之后加的：手抄密钥时漏掉一个字符，base64 长度差 1、
        # 解码后 31 字节，直到用户点"保存"报错才发现。
        try:
            from agent import crypto

            crypto._load_key()
            warnings.append(
                f"SECRET_MASTER_KEY 指纹：{crypto.key_fingerprint()}"
                "（部署时用它核对服务器与本机的密钥是否一致）"
            )
        except Exception as e:
            raise RuntimeError(
                f"SECRET_MASTER_KEY 不合法，服务无法安全地加解密用户密钥：{e}"
            ) from e

    if not COOKIE_SECURE:
        warnings.append(
            "COOKIE_SECURE 为 false：仅适合本机 http 调试。"
            "部署到公网 HTTPS 时必须设置 COOKIE_SECURE=true，否则 cookie 可能被窃听。"
        )

    if not os.getenv("DEEPSEEK_API_KEY"):
        # 这是**正常情况**（用户自己填 key），所以措辞不要说成像是出错
        warnings.append(
            f"未配置服务器兜底 DEEPSEEK_API_KEY —— 这是预期行为："
            f"用户需在页面上填自己的 Key。日志里的 key_source 会显示 u=user。"
        )

    return warnings
