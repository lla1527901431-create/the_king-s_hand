"""日历事件的数据访问。

存储位置从 data/events.json 换成了 Supabase 的 public.events 表。
隔离由数据库的 RLS 保证（auth.uid() = user_id），这里不自行过滤用户。

对外的函数签名和返回结构**保持不变**，这样 server/app.py 和前端不用改。
新增的只有可选的 user 参数（通常不需要传：身份由 db 层从当前请求的
JWT contextvar 取）。
"""

from __future__ import annotations

import uuid

from agent import db

TABLE = "events"
FIELDS = ("title", "start", "end", "location", "note")
COLUMNS = "id,title,start_at,end_at,location,note"


def _new_id() -> str:
    """沿用原来的 8 位短 id 风格，前端无需改动。"""
    return uuid.uuid4().hex[:8]


def _row_to_event(row: dict) -> dict:
    """把数据库行（start_at/end_at）翻成前端认识的形状（start/end）。

    时间要翻回 'YYYY-MM-DD HH:MM'：前端 static/app.js 的 parseDateTime
    只认这个格式，直接给 ISO 字符串会导致日历画不出任何事件。
    """
    return {
        "id": row.get("id"),
        "title": row.get("title") or "",
        "start": db.from_db_time(row.get("start_at")),
        "end": db.from_db_time(row.get("end_at")),
        "location": row.get("location") or "",
        "note": row.get("note") or "",
    }


def add_event(
    title: str,
    start: str,
    end: str | None,
    location: str = "",
    note: str = "",
) -> dict:
    """新增一个事件。start/end 用 'YYYY-MM-DD HH:MM'；end 可以为空。"""
    row = {
        "id": _new_id(),
        "title": title,
        "start_at": db.to_db_time(start),
        "end_at": db.to_db_time(end),
        "location": location or "",
        "note": note or "",
    }
    inserted = db.insert(TABLE, row)
    return _row_to_event(inserted[0]) if inserted else _row_to_event(row)


def list_events() -> list[dict]:
    """列出自己的全部事件，按开始时间排序。"""
    rows = db.select(
        TABLE,
        columns=COLUMNS,
        filters={},
        order="start_at.asc",
    )
    return [_row_to_event(r) for r in rows]


def update_event(event_id: str, fields: dict) -> dict | None:
    """按 id 修改事件。只更新 fields 里出现的键。找不到返回 None。"""
    payload: dict = {}
    if "title" in fields:
        payload["title"] = fields["title"]
    if "start" in fields:
        payload["start_at"] = db.to_db_time(fields["start"])
    if "end" in fields:
        payload["end_at"] = db.to_db_time(fields["end"])
    if "location" in fields:
        payload["location"] = fields["location"] or ""
    if "note" in fields:
        payload["note"] = fields["note"] or ""

    if not payload:
        return None

    # RLS 已经保证了只能改到自己的行；查不到说明 id 不存在或不属于自己
    updated = db.update(TABLE, {"id": f"eq.{event_id}"}, payload)
    return _row_to_event(updated[0]) if updated else None


def delete_event(event_id: str) -> bool:
    """按 id 删除事件。返回是否删掉了。"""
    deleted = db.delete(TABLE, {"id": f"eq.{event_id}"})
    return bool(deleted)


def find_conflicts(start: str, end: str | None) -> list[dict]:
    """找出与 [start, end) 重叠的事件。

    这是 README 里承诺过、但一直没实现的功能。以前靠模型自己比对时间，
    现在改成确定性的代码判断。

    重叠判定：已有事件开始 < 新事件结束，且已有事件结束 > 新事件开始。
    end 为空时按"零时长"处理（只看开始时间是否落在别人区间内）。
    """
    if not start:
        return []

    end_value = end or start
    rows = db.select(
        TABLE,
        columns=COLUMNS,
        filters={
            "start_at": f"lt.{db.to_db_time(end_value)}",
            "end_at": f"gt.{db.to_db_time(start)}",
        },
        order="start_at.asc",
    )
    return [_row_to_event(r) for r in rows]
