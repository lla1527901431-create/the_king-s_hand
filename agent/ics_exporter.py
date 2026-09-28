import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

from icalendar import Calendar, Event

# SMTP 入口固定为 QQ 邮箱，不接受用户指定主机（防 SSRF）
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465


def _parse_dt(s: str) -> datetime | None:
    """把 'YYYY-MM-DD HH:MM' 转成 datetime。解析失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def build_ics(events: list) -> str:
    """把事件列表转成 ics 文本。"""
    cal = Calendar()
    cal.add("prodid", "-//The King's Hand//CN")
    cal.add("version", "2.0")

    for evt in events:
        start = _parse_dt(evt.get("start", ""))
        end = _parse_dt(evt.get("end", ""))
        if start is None:
            continue
        if end is None:
            end = start

        e = Event()
        e.add("uid", str(evt.get("id", "")) + "@the-kings-hand")
        e.add("summary", evt.get("title", ""))
        e.add("dtstart", start)
        e.add("dtend", end)

        if evt.get("location"):
            e.add("location", evt["location"])
        if evt.get("note"):
            e.add("description", evt["note"])

        cal.add_component(e)

    return cal.to_ical().decode("utf-8")


def send_ics_email(
    events: list,
    to_email: str,
    smtp_user: str = "",
    smtp_pass: str = "",
) -> tuple[bool, str]:
    """把 ics 作为附件发到指定邮箱。返回 (成功?, 提示信息)。

    凭据来自**用户自己填的** 邮箱 + 授权码（存在 user_secrets 里，加密）。
    也支持回落到 .env 里的 SMTP_*，方便本机调试。

    ⚠️ 主机和端口是**写死的**，不接受用户传入：
       允许用户指定 SMTP 主机 = 让服务器去连任意地址 = SSRF，
       可以被用来扫描内网。所以只允许 QQ 邮箱的固定入口。
    """
    user = (smtp_user or os.getenv("SMTP_USER") or "").strip()
    password = (smtp_pass or os.getenv("SMTP_PASS") or "").strip()

    if not user or not password:
        return False, "还没有配置邮箱授权码，请先在页面上填写你的 QQ 邮箱和 16 位授权码。"

    if not to_email or "@" not in to_email:
        return False, "收件邮箱格式不正确。"

    if not events:
        return False, "没有可导出的事件"

    ics_text = build_ics(events)

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = "The King's Hand 日历导出"
    msg.set_content(
        f"附件是您的日历事件，共 {len(events)} 条。\n在手机上点击附件即可导入日历。",
        charset="utf-8",
    )
    msg.add_attachment(
        ics_text.encode("utf-8"),
        maintype="text",
        subtype="calendar",
        filename="the_kings_hand.ics",
    )

    try:
        with smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, timeout=15, local_hostname="localhost"
        ) as server:
            server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        return False, "邮箱授权码不正确（注意：这里要填 QQ 邮箱的 16 位授权码，不是登录密码）。"
    except Exception as e:
        # 不要把异常原文直接抛给前端：SMTP 报错里可能带主机名和用户名
        return False, f"发送失败：{type(e).__name__}"

    return True, f"已发送到 {to_email}"