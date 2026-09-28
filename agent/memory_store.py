"""长期记忆的数据访问。

存储从 data/memory.json 换成 Supabase 的 public.memories 表，一个用户一行。

记忆分三块：
    facts        用户**明确说过**的稳定事实（身份、单位、学历…）
    observations 观察台账：每条只记"某次发生了什么"，不下结论。
                 同一个现象被观察到多次，才由蒸馏升级成 preferences。
                 这样才能区分"一次偶然"和"反复出现"。
    preferences  稳定的偏好与习惯（可以由 observations 归纳而来）

对外结构 {"facts": [...], "observations": [...], "preferences": [...], "last_updated": "..."}。
"""

from __future__ import annotations

import logging

from agent import db

logger = logging.getLogger("agent.store")

TABLE = "memories"
COLUMNS = "facts,observations,preferences,updated_at"

# 观察台账最多保留多少条（超出后丢掉最旧的，避免无限膨胀）
MAX_OBSERVATIONS = 30


def _empty() -> dict:
    return {"facts": [], "observations": [], "preferences": [], "last_updated": ""}


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _row_to_memory(row: dict) -> dict:
    return {
        "facts": _as_list(row.get("facts")),
        "observations": _as_list(row.get("observations")),
        "preferences": _as_list(row.get("preferences")),
        # 转成本地 'YYYY-MM-DD HH:MM'，和 events / pending 的对外格式保持一致
        "last_updated": db.from_db_time(row.get("updated_at")),
    }


def _write(payload: dict) -> None:
    """写记忆。数据库缺 observations 列时自动降级并提示。

    抽成一个函数是为了避免"每处都记得处理"这种疏漏 —— 之前 load / save /
    clear 三个入口各写一遍，结果漏了两处。
    """
    try:
        db.upsert(TABLE, payload, on_conflict="user_id", returning=False)
    except db.SupabaseError as e:
        if e.code not in ("PGRST204", "42703") or "observations" not in payload:
            raise
        logger.warning(
            "数据库里没有 observations 列，本次降级为只存 facts/preferences。"
            "请执行 sql/03_add_observations.sql 以启用观察台账。"
        )
        payload = {k: v for k, v in payload.items() if k != "observations"}
        db.upsert(TABLE, payload, on_conflict="user_id", returning=False)


def _read() -> dict:
    """读记忆。同样处理缺列的情况。"""
    try:
        rows = db.select(TABLE, columns=COLUMNS, limit=1)
    except db.SupabaseError as e:
        if e.code not in ("PGRST204", "42703"):
            raise
        rows = db.select(TABLE, columns="facts,preferences,updated_at", limit=1)
    return _row_to_memory(rows[0]) if rows else _empty()


def load_memory() -> dict:
    """读自己的记忆。没有记录时返回空结构（不新建行）。"""
    return _read()


def save_memory(memory: dict) -> None:
    """整体覆盖式保存记忆（和原来的 JSON 版本语义一致）。"""
    observations = _as_list(memory.get("observations"))
    if len(observations) > MAX_OBSERVATIONS:
        observations = observations[-MAX_OBSERVATIONS:]

    _write({
        "facts": _as_list(memory.get("facts")),
        "observations": observations,
        "preferences": _as_list(memory.get("preferences")),
    })


def clear_memory() -> dict:
    """清空记忆内容，但保留这一行。"""
    _write({"facts": [], "observations": [], "preferences": []})
    return _empty()


def format_memory_text(memory: dict) -> str:
    """把记忆拼成给 LLM 看的文本。

    观察台账只有在条数够多时才展示 —— 只观察过一两次的行为不该影响判断，
    展示出来反而容易让模型过度解读。这一点和蒸馏规则是一致的。
    """
    facts = _as_list(memory.get("facts"))
    prefs = _as_list(memory.get("preferences"))
    observations = _as_list(memory.get("observations"))

    lines = []
    if facts:
        lines.append("关于用户的事实：")
        for f in facts:
            lines.append(f"- {f}")
    if prefs:
        lines.append("用户的偏好：")
        for p in prefs:
            lines.append(f"- {p}")
    if len(observations) >= 3:
        lines.append("（以下是多次观察到的行为记录，供参考，不要直接当成结论复述）")
        for o in observations[-10:]:
            lines.append(f"- {o}")

    return "\n".join(lines) if lines else "（暂无长期记忆）"
