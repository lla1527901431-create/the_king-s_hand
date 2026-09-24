import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

from icalendar import Calendar, Event


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


def send_ics_email(events: list, to_email: str) -> tuple[bool, str]:
    """把 ics 作为附件发到指定邮箱。返回 (成功?, 提示信息)。"""
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")

    if not all([host, user, password]):
        return False, "SMTP 配置缺失，请检查 .env"

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
            host, port, timeout=15, local_hostname="localhost"
        ) as server:
            server.login(user, password)
            server.send_message(msg)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"发送失败：{e}"

    return True, f"已发送到 {to_email}"