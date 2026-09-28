"""待确认 / 待计划任务的数据访问。

存储从 data/pending.json 换成 Supabase 的 public.pending_tasks 表。

一个结构性变化：原来用 {"confirmed": [...], "planned": [...]} 两个数组表达分组，
数据库里改成一个 bucket 字段。但**对外的返回结构保持不变**，
所以前端 static/app.js 一行都不用改。

隔离同样由 RLS 保证，这里不自行过滤用户。
"""

from __future__ import annotations

from agent import db

TABLE = "pending_tasks"
COLUMNS = "id,title,start_at,end_at,location,note,bucket"


def _empty() -> dict:
    return {"confirmed": [], "planned": []}


def _row_to_task(row: dict) -> dict:
    """数据库行 -> 前端认识的形状。

    时间翻回 'YYYY-MM-DD HH:MM'，前端只认这个格式。
    """
    return {
        "id": row.get("id"),
        "title": row.get("title") or "",
        "start": db.from_db_time(row.get("start_at")) or None,
        "end": db.from_db_time(row.get("end_at")) or None,
        "location": row.get("location") or "",
        "note": row.get("note") or "",
    }


def _bucket_of(start: str | None) -> str:
    """有明确开始时间 -> 待确认；没有 -> 待计划。"""
    return "confirmed" if start else "planned"


def load_pending() -> dict:
    """读出两个桶，组装成 {"confirmed": [...], "planned": [...]}。

    返回结构与原来的 JSON 版本完全一致，前端无需改动。
    """
    rows = db.select(TABLE, columns=COLUMNS, order="created_at.asc")
    data = _empty()
    for row in rows:
        task = _row_to_task(row)
        # 以数据库里的 bucket 为准；万一它和 start 不一致，按 start 修正
        bucket = row.get("bucket") or _bucket_of(task["start"])
        if bucket not in ("confirmed", "planned"):
            bucket = _bucket_of(task["start"])
        data[bucket].append(task)
    return data


def add_pending(task: dict) -> dict:
    """把任务加到 confirmed 或 planned。task 必须有 id。"""
    start = task.get("start") or None
    row = {
        "id": task["id"],
        "title": task.get("title", ""),
        "start_at": db.to_db_time(start),
        "end_at": db.to_db_time(task.get("end")),
        "location": task.get("location") or "",
        "note": task.get("note") or "",
        "bucket": _bucket_of(start),
    }
    inserted = db.insert(TABLE, row)
    return _row_to_task(inserted[0]) if inserted else _row_to_task(row)


def delete_pending(task_id: str) -> bool:
    """按 id 删除任务（两个桶一起找）。返回是否删掉了。"""
    deleted = db.delete(TABLE, {"id": f"eq.{task_id}"})
    return bool(deleted)


def update_pending(task_id: str, fields: dict) -> dict | None:
    """更新某条任务。start 从无到有会自动从 planned 移到 confirmed，反之亦然。"""
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

    # 只有 start 参与修改时才重算桶，避免把用户已有的分桶无端改掉
    if "start_at" in payload:
        payload["bucket"] = _bucket_of(payload["start_at"])

    updated = db.update(TABLE, {"id": f"eq.{task_id}"}, payload)
    return _row_to_task(updated[0]) if updated else None


def pop_pending(task_id: str) -> dict | None:
    """取出并删除该任务（用于"确认"：先拿走，再写进日历）。找不到返回 None。"""
    removed = db.delete(TABLE, {"id": f"eq.{task_id}"})
    return _row_to_task(removed[0]) if removed else None


def get_pending(task_id: str) -> dict | None:
    """只读地取一条任务（pop_pending 会删，这个不会）。"""
    rows = db.select(TABLE, columns=COLUMNS, filters={"id": f"eq.{task_id}"}, limit=1)
    return _row_to_task(rows[0]) if rows else None


def format_pending_text(data: dict) -> str:
    """把两个桶拼成一段文本，给 LLM 看。

    纯函数（不碰数据库），保留下来以备后用 —— 目前项目里还没有调用点。
    """
    confirmed = data.get("confirmed", [])
    planned = data.get("planned", [])
    lines = []

    if confirmed:
        lines.append("【待确认任务】")
        for t in confirmed:
            time_str = f"{t.get('start', '')}"
            if t.get("end"):
                time_str += f" ~ {t['end']}"
            loc = f"，地点 {t['location']}" if t.get("location") else ""
            note = f"，备注 {t['note']}" if t.get("note") else ""
            lines.append(f"- {t.get('title', '')}（{time_str}）{loc}{note}")

    if planned:
        lines.append("【待计划任务】")
        for t in planned:
            loc = f"，地点 {t['location']}" if t.get("location") else ""
            note = f"，备注 {t['note']}" if t.get("note") else ""
            lines.append(f"- {t.get('title', '')}{loc}{note}")

    if not lines:
        return "（暂无待确认或待计划任务）"

    return "\n".join(lines)
