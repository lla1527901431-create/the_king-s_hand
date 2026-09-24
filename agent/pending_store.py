import json
from pathlib import Path

PENDING_FILE = Path(__file__).parent.parent / "data" / "pending.json"


def _empty() -> dict:
    return {"confirmed": [], "planned": []}


def load_pending() -> dict:
    if not PENDING_FILE.exists():
        return _empty()
    text = PENDING_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return _empty()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _empty()
    data.setdefault("confirmed", [])
    data.setdefault("planned", [])
    return data


def save_pending(data: dict) -> None:
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_pending(task: dict) -> dict:
    """把任务加到 confirmed 或 planned。task 必须有 id。
    有 start 就进 confirmed，没 start 就进 planned。"""
    data = load_pending()
    bucket = "confirmed" if task.get("start") else "planned"
    data[bucket].append(task)
    save_pending(data)
    return task


def delete_pending(task_id: str) -> bool:
    """从任一库删除。返回是否删掉了。"""
    data = load_pending()
    before = len(data["confirmed"]) + len(data["planned"])
    data["confirmed"] = [t for t in data["confirmed"] if t.get("id") != task_id]
    data["planned"] = [t for t in data["planned"] if t.get("id") != task_id]
    after = len(data["confirmed"]) + len(data["planned"])
    if after == before:
        return False
    save_pending(data)
    return True


def update_pending(task_id: str, fields: dict) -> dict | None:
    """更新某条任务的字段。如果 start 从无到有，会自动从 planned 移到 confirmed。
    反之从有到无，会从 confirmed 移到 planned。返回更新后的任务，找不到返回 None。"""
    data = load_pending()

    found = None
    for bucket in ("confirmed", "planned"):
        for t in data[bucket]:
            if t.get("id") == task_id:
                found = t
                data[bucket].remove(t)
                break
        if found:
            break

    if found is None:
        return None

    found.update(fields)

    new_bucket = "confirmed" if found.get("start") else "planned"
    data[new_bucket].append(found)
    save_pending(data)
    return found


def pop_pending(task_id: str) -> dict | None:
    """从库中移出并返回该任务。找不到返回 None。"""
    data = load_pending()

    for bucket in ("confirmed", "planned"):
        for t in data[bucket]:
            if t.get("id") == task_id:
                data[bucket].remove(t)
                save_pending(data)
                return t
    return None


def format_pending_text(data: dict) -> str:
    """把两个库拼成一段文本，给 LLM 看。"""
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