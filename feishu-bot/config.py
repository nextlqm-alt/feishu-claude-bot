"""
配置 — 从环境变量读取飞书凭证
"""
import os
from dotenv import load_dotenv

load_dotenv()

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")
FEISHU_VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
