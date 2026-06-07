"""
飞书 Claude Code Bot — 入口

WebSocket 长连接模式，无需公网穿透。
"""

import asyncio
import logging
import signal
import sys

from lark_oapi.core.enum import LogLevel
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.ws import Client as WsClient

import bot
import config
import webui

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# 日志级别映射: str → LogLevel
_LOG_MAP = {"DEBUG": LogLevel.DEBUG, "INFO": LogLevel.INFO, "WARNING": LogLevel.WARNING, "ERROR": LogLevel.ERROR}


def main():
    logger.info("Starting Feishu Claude Bot...")

    # 启动本地监控面板
    webui.start(8080)

    if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
        logger.error("请先配置 .env 文件中的 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        sys.exit(1)

    feishu_bot = bot.FeishuBot()

    handler = (
        EventDispatcherHandler.builder(config.FEISHU_ENCRYPT_KEY, config.FEISHU_VERIFICATION_TOKEN)
        .register_p2_im_message_receive_v1(feishu_bot.handle_message)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(feishu_bot.handle_noop)
        .register_p2_im_message_message_read_v1(feishu_bot.handle_noop)
        .build()
    )

    ws = WsClient(
        app_id=config.FEISHU_APP_ID,
        app_secret=config.FEISHU_APP_SECRET,
        event_handler=handler,
        log_level=_LOG_MAP.get(config.LOG_LEVEL.upper(), LogLevel.INFO),
    )

    try:
        ws.start()  # 阻塞，内部管理 event loop
    except KeyboardInterrupt:
        logger.info("Bye")


if __name__ == "__main__":
    main()
