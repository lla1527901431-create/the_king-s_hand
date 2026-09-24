import json
from pathlib import Path

MEMORY_FILE = Path(__file__).parent.parent / "data" / "memory.json"


def _empty() -> dict:
    return {"facts": [], "preferences": [], "last_updated": ""}


def load_memory() -> dict:
    if not MEMORY_FILE.exists():
        return _empty()
    text = MEMORY_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return _empty()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _empty()
    data.setdefault("facts", [])
    data.setdefault("preferences", [])
    data.setdefault("last_updated", "")
    return data


def save_memory(memory: dict) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def format_memory_text(memory: dict) -> str:
    facts = memory.get("facts", [])
    prefs = memory.get("preferences", [])
    lines = []
    if facts:
        lines.append("关于用户的事实：")
        for f in facts:
            lines.append(f"- {f}")
    if prefs:
        lines.append("用户的偏好：")
        for p in prefs:
            lines.append(f"- {p}")
    return "\n".join(lines) if lines else "（暂无长期记忆）"