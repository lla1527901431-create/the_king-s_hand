"""日志配置。

为什么不用 print（生产环境的实际差别）：

    print 打出来的东西没有时间戳、没有级别、没有请求/用户标识、也不落盘。
    线上出问题时，你无法回答"这是什么时候的事""是哪个用户""是错误还是提示"
    "同一秒的三个请求哪几条属于同一次对话"。

    配置好 logging 之后，每条日志长这样：

        2026-09-28 15:42:11 | WARNING  | chat   | req=7f3a r=user | DeepSeek 调用超时
        └── 什么时候 ──────┘ └─ 级别 ─┘ └模块┘ └─ 谁 ────────┘ └─ 发生了什么 ─┘

    这样才做到：按时间查、按用户查、按级别过滤、把 ERROR 接告警、日志落盘长期保留。

请求上下文（请求 id / 用户 id / key 来源）由 server/logging_config.py 的
request_context 通过 contextvar 提供，日志格式里自动带上，不用每处手写。
"""

from __future__ import annotations

import logging
import os
import sys
from contextvars import ContextVar

# 这些字段由 contextvar 提供，每条日志自动带上
_ctx_request_id: ContextVar[str] = ContextVar("log_request_id", default="-")
_ctx_user_id: ContextVar[str] = ContextVar("log_user_id", default="-")
_ctx_key_source: ContextVar[str] = ContextVar("log_key_source", default="-")

_configured = False

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-7s | req=%(request_id)s u=%(user_id)s k=%(key_source)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def set_request_id(value: str) -> None:
    _ctx_request_id.set(value or "-")


def set_user_id(value: str) -> None:
    _ctx_user_id.set(value or "-")


def set_key_source(value: str) -> None:
    _ctx_key_source.set(value or "-")


def _short_id(value: str) -> str:
    """用户 id 是 uuid，日志里只留前 8 位就够定位，也不至于刷屏。"""
    value = value or "-"
    return value[:8] if len(value) > 12 else value


class _ContextFilter(logging.Filter):
    """把 contextvar 里的值塞进每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or _ctx_request_id.get()
        uid = getattr(record, "user_id", None) or _ctx_user_id.get()
        record.user_id = _short_id(uid)
        record.key_source = getattr(record, "key_source", None) or _ctx_key_source.get()
        return True


def setup_logging(level: str | None = None) -> None:
    """初始化日志。重复调用是安全的。"""
    global _configured
    if _configured:
        return

    level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    # uvicorn 自带的 access 日志格式太啰嗦（每个静态文件都打一行），
    # 我们有自己的请求日志中间件，这里把它的级别调高减少噪音。
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    # httpx / openai 的调试日志在 INFO 级别会非常吵
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """取 logger。顺便保证 logging 已经初始化过。"""
    setup_logging()
    return logging.getLogger(name)
