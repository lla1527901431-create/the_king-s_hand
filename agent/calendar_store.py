import json
import uuid
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data" / "events.json"


def _load() -> list:
    if not DATA_FILE.exists():
        return []
    text = DATA_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return json.loads(text)


def _save(events: list) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_event(
    title: str,
    start: str,
    end: str,
    location: str = "",
    note: str = "",
) -> dict:
    events = _load()
    event = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "start": start,
        "end": end,
        "location": location,
        "note": note,
    }
    events.append(event)
    _save(events)
    return event


def list_events() -> list:
    return _load()

def update_event(event_id: str, fields: dict) -> dict | None:
    """按 id 修改事件。只更新 fields 里出现的键。找不到返回 None。"""
    events = _load()
    for evt in events:
        if evt.get("id") == event_id:
            for key in ("title", "start", "end", "location", "note"):
                if key in fields:
                    evt[key] = fields[key]
            _save(events)
            return evt
    return None


def delete_event(event_id: str) -> bool:
    """按 id 删除事件。返回是否删掉了。"""
    events = _load()
    before = len(events)
    events = [e for e in events if e.get("id") != event_id]
    if len(events) == before:
        return False
    _save(events)
    return True