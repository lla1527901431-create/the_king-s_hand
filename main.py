"""启动入口。

本地调试与公网部署共用这一个文件，靠环境变量区分：

    本地：.env 里 DEBUG=true
          python main.py            -> 127.0.0.1:8000 + 热重载

    公网：服务器环境变量 DEBUG=false（默认）
          python main.py            -> HOST/PORT 指定的地址，无热重载

环境变量：
    HOST      监听地址，默认 127.0.0.1（只允许本机访问）
              部署到服务器/容器时设为 0.0.0.0
    PORT      监听端口，默认 8000
    DEBUG     是否开启热重载，默认 false。**生产环境必须为 false**
              （热重载会持续监视文件、多起一个进程，是开发专用）
    WORKERS   工作进程数，默认 1
              注意：对话历史目前存在进程内存里，多进程会导致
              "同一个人刷到不同进程时上下文丢失"。要调大请先看 README 说明。
    LOG_LEVEL 日志级别，默认 INFO
"""

import os

import uvicorn

from server.logging_config import get_logger, setup_logging


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("PORT", "8000"))
    debug = _as_bool(os.getenv("DEBUG", "false"))
    workers = int(os.getenv("WORKERS", "1"))

    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    logger = get_logger("main")

    logger.info("启动 The King's Hand  host=%s port=%s debug=%s workers=%s",
                host, port, debug, workers)
    if debug:
        logger.warning("DEBUG=true 是开发模式：开启热重载。公网部署请设为 false。")

    # 启动自检：配置有问题就在这里明确报出来，而不是等第一个请求失败
    try:
        import config

        for warning in config.startup_check():
            logger.warning("配置提醒：%s", warning)
    except Exception as e:
        logger.error("启动自检失败：%s: %s", type(e).__name__, e)
        raise

    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=debug,
        workers=1 if debug else workers,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        # 反代（Nginx）转发时保留真实客户端 IP
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
