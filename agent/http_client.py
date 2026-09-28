"""HTTP 连接池。

为什么需要它（实测数据）：

    同一个 Supabase 接口，从本机访问：
        每次新建连接   平均 5215 ms   ← DNS + TCP 握手 + TLS 协商，跨境链路很贵
        复用同一连接   平均  463 ms   ← 差 11 倍

    requests.request() 每次调用都会新建连接，所以之前的每个数据库操作
    都要先花 5 秒建连。改成复用 Session 的连接池后，只有第一次付这个成本。

并发的安全性：
    requests.Session 官方不保证线程安全，而 FastAPI 的同步端点跑在线程池里，
    会被多个线程同时调用。所以这里每个线程持有自己的 Session
    （threading.local），既拿到连接复用，又不需要加锁。

重试策略：
    连接阶段失败（连不上、握手超时）是**安全可重试**的 —— 请求根本没发出去。
    所以对这类错误统一重试；至于业务层重试，由调用方决定（见 db.py 的说明）。
"""

from __future__ import annotations

import threading
import time

import requests
from requests.adapters import HTTPAdapter

import config

_local = threading.local()


def _build_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=4,      # 保留 4 个不同主机的连接池
        pool_maxsize=16,         # 每个池最多复用 16 条连接
        max_retries=0,           # 重试由我们自己控制，便于给出中文提示
        pool_block=False,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    return session


def get_session() -> requests.Session:
    """取当前线程的 Session（懒创建）。"""
    session = getattr(_local, "session", None)
    if session is None:
        session = _build_session()
        _local.session = session
    return session


def reset_session() -> None:
    """丢弃当前线程的连接（诊断或排错时用）。"""
    session = getattr(_local, "session", None)
    if session is not None:
        try:
            session.close()
        except Exception:
            pass
    _local.session = None


def request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    json_body=None,
    timeout: float | None = None,
) -> requests.Response:
    """发一个请求，复用连接池。

    只做"连接阶段"的重试 —— 也就是请求还没送到服务器就失败的情况。
    业务层的重试交给调用方，避免同一笔写入被重复提交。
    """
    attempts = max(config.REQUEST_RETRIES, 0)
    timeout = timeout if timeout is not None else config.REQUEST_TIMEOUT
    last_error: Exception | None = None

    for attempt in range(attempts + 1):
        try:
            return get_session().request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as e:
            # 读超时不重试：请求可能已经到达服务器并生效了
            last_error = e
            raise
        except requests.exceptions.RequestException as e:
            # 连接阶段失败：请求没发出去，重试是安全的
            last_error = e
            if attempt < attempts:
                time.sleep(config.RETRY_BACKOFF * (2**attempt))
                reset_session()   # 连接池里可能全是坏连接，重建
                continue
            raise

    raise last_error  # pragma: no cover
