from datetime import datetime
from langchain_core.tools import tool
from agent.calendar_store import add_event as _add_event, list_events as _list_events

@tool
def get_current_time() -> str:
    """获取当前日期和时间。当用户询问现在几点、今天日期时使用。"""
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

@tool
def add(a: int, b: int) -> int:
    """计算两个整数之和。当用户询问两数相加时使用。"""
    return a + b

@tool
def add_calendar_event(title: str, start: str, end: str, note: str = "") -> str:
    """向本地日历添加一个事件，重复的事件跳过添加
    title: 事件标题，比如 '陪女朋友吃饭'。
    start: 开始时间，格式必须是 'YYYY-MM-DD HH:MM'，例如 '2026-09-17 18:00'。
    end: 结束时间，格式同上。
    note: 可选备注。
    """
    event = _add_event(title, start, end, note)
    return f"已添加事件：{event['title']}，{event['start']} 到 {event['end']}"

@tool
def list_calendar_events() -> str:
    """列出本地日历里的所有事件。当用户询问自己的日程安排时使用。"""
    events = _list_events()
    if not events:
        return "当前没有任何事件。"
    lines = []
    for e in events:
        lines.append(f"- {e['start']} ~ {e['end']}：{e['title']}")
        #lines.append()把每个事件格式化成一行Markdown文本，方便阅读。
        #Markdown格式的列表项以“- ”开头，后面跟着事件的开始时间、结束时间和标题。
    return "\n".join(lines)