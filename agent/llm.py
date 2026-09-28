"""LLM 客户端。

多用户改造的关键变化：**LLM 客户端不再全局唯一**。

以前是模块加载时创建一个全局 llm / executor，现在每个用户用自己的
DeepSeek key，所以必须"按请求构造"。这里只负责造客户端，缓存和复用
交给上层（server/agent_runner.py）。

key 的优先级：
    1. 用户自己在页面上填的（存 Supabase，加密）
    2. 服务器的 DEEPSEEK_API_KEY 环境变量（仅作为本机调试时的兜底）
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class CredentialsMissing(RuntimeError):
    """既没有用户自己的 key，也没有服务器兜底的 key。"""


def _clean_key(key: str | None) -> str:
    """校验并清理 key。

    这里刻意把可疑字符揪出来报错，而不是默默拼进请求 —— 中文占位符、
    带空格、换行是最常见的配置错误，直接说清楚比让 API 报 401 友好。
    """
    text = (key or "").strip()
    if not text:
        return ""
    if not text.isascii():
        raise CredentialsMissing(
            "DeepSeek API Key 含有非 ASCII 字符（是不是还留着中文占位符？）"
        )
    return text


def resolve_credentials(
    deepseek_key: str | None = None,
    model: str | None = None,
) -> dict:
    """决定这次请求用哪个 key / 模型 / 地址。"""
    key = _clean_key(deepseek_key) or _clean_key(os.getenv("DEEPSEEK_API_KEY"))
    if not key:
        raise CredentialsMissing(
            "还没有配置 DeepSeek API Key。请在页面上填入你自己的 Key 后再试。"
        )
    return {
        "api_key": key,
        "model": (model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip(),
        "base_url": (os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).strip(),
        "memory_model": (
            os.getenv("MEMORY_MODEL") or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL
        ).strip(),
    }


def build_llm(
    deepseek_key: str | None = None,
    model: str | None = None,
) -> ChatOpenAI:
    """构造对话用的 LLM。默认 temperature=0，输出稳定、减少随机性。"""
    creds = resolve_credentials(deepseek_key, model)
    return ChatOpenAI(
        model=creds["model"],
        api_key=creds["api_key"],
        base_url=creds["base_url"],
        temperature=0,
        timeout=60,
        max_retries=2,
    )


def build_memory_llm(
    deepseek_key: str | None = None,
    model: str | None = None,
) -> ChatOpenAI:
    """构造记忆蒸馏用的 LLM（可以用更便宜的模型）。"""
    creds = resolve_credentials(deepseek_key, model)
    return ChatOpenAI(
        model=creds["memory_model"],
        api_key=creds["api_key"],
        base_url=creds["base_url"],
        temperature=0,
        timeout=60,
        max_retries=2,
    )


def credentials_source(deepseek_key: str | None = None) -> str:
    """告诉调用方这次用的是谁的 key（用于日志，不涉及密钥内容）。"""
    if _clean_key(deepseek_key):
        return "user"
    if _clean_key(os.getenv("DEEPSEEK_API_KEY")):
        return "server"
    return "none"
