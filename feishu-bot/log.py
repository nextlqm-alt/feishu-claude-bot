"""共享对话日志——所有飞书↔Claude交互记录"""

import time
from collections import deque

# 保留最近 500 条事件
events: deque[dict] = deque(maxlen=500)


def add(chat_id: str, event_type: str, content: str, detail: dict = None):
    events.append({
        "time": time.strftime("%H:%M:%S"),
        "chat": chat_id[-8:],  # 只保留 chat_id 后8位
        "type": event_type,
        "content": content,
        "detail": detail or {},
    })
