"""
飞书 Bot — 接收消息 → 调 Claude → 回复

支持三级权限控制：/safe | /unsafe | /full
"""

import asyncio
import json
import logging
import os
import time
import uuid

from lark_oapi import Client as LarkClient
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

import claude
import config
import log

logger = logging.getLogger(__name__)

HELP_TEXT = """**📋 命令**
• `/safe` — 安全模式（只读+编辑，不允许 Bash）
• `/unsafe` — 标准模式（允许 Bash，**默认**）
• `/full` — 完整模式（允许所有工具）
• `/new` — 重置会话
• `/sessions` — 列出所有会话
• `/switch <id>` — 切换到指定会话
• `/clear <id>` — 删除指定会话
• `/status` — 查看状态"""


class FeishuBot:
    def __init__(self):
        # chat_id → {session_id, turn, is_first, running, perm_level}
        self.sessions: dict[str, dict] = {}

    def _get_sess(self, chat_id: str, force_new: bool = False) -> dict:
        if chat_id not in self.sessions:
            if not force_new:
                # 尝试复用磁盘上最近一次会话，避免每次连接都创建新会话
                recent = claude.list_sessions()
                if recent:
                    newest = recent[0]  # 已按 mtime 降序排列
                    cwd = newest["cwd"] if newest["cwd"] and os.path.isdir(newest["cwd"]) else None
                    self.sessions[chat_id] = {
                        "session_id": newest["sid"],
                        "turn": 0,
                        "is_first": False,  # 恢复已有会话
                        "perm_level": "unsafe",
                        "cwd": cwd,
                        "just_resumed": True,  # 首次回复时告知用户
                    }
                    return self.sessions[chat_id]
            # 无磁盘会话或强制新建
            self.sessions[chat_id] = {
                "session_id": str(uuid.uuid4()),
                "turn": 0,
                "is_first": True,
                "perm_level": "unsafe",
                "cwd": None,
            }
        return self.sessions[chat_id]

    # ---- SDK 同步回调 ----

    def handle_message(self, event: P2ImMessageReceiveV1) -> None:
        msg = event.event.message if event and event.event else None
        if not msg:
            return
        text = _extract_text(msg.content, msg.message_type)
        if not text:
            return
        logger.info(f"[{msg.chat_id}] {text[:100]}")
        loop = asyncio.get_event_loop()
        loop.create_task(self._handle(msg.chat_id, msg.message_id, text.strip()))

    def handle_noop(self, _event) -> None:
        pass

    # ---- 异步消息处理 ----

    async def _handle(self, chat_id: str, msg_id: str, text: str):
        if text.startswith("/"):
            await self._command(chat_id, msg_id, text)
        else:
            await self._chat(chat_id, msg_id, text)

    async def _chat(self, chat_id: str, msg_id: str, text: str):
        sess = self._get_sess(chat_id)

        if sess.get("running"):
            _reply(msg_id, "⚠️ 上一个任务还在执行中，请稍候。")
            return

        sess["running"] = True
        start = time.time()

        log.add(chat_id, "👤", text)

        try:
            result, new_sid = await claude.run(
                text, sess["session_id"], sess["is_first"],
                perm_level=sess["perm_level"], chat_id=chat_id,
                cwd=sess.get("cwd"),
            )
            sess["session_id"] = new_sid
            sess["is_first"] = False
            sess["turn"] += 1

            elapsed = time.time() - start
            footer = f"\n\n---\n⏱ {elapsed:.1f}s | #{sess['turn']} | 🔒{sess['perm_level']}"

            # 首次连接且自动恢复了磁盘会话 → 告知用户
            prefix = ""
            if sess.pop("just_resumed", False):
                prefix = f"📋 已恢复会话 `{new_sid[:8]}...` | 🔒{sess['perm_level']}\n\n"

            _reply(msg_id, prefix + (result.strip() or "(无输出)") + footer)

        except Exception as e:
            logger.exception(f"Error [{chat_id}]: {e}")
            _reply(msg_id, f"❌ 出错了: {e}")
        finally:
            sess["running"] = False

    async def _command(self, chat_id: str, msg_id: str, cmd: str):
        if cmd == "/new":
            self.sessions.pop(chat_id, None)
            sess = self._get_sess(chat_id, force_new=True)
            _reply(msg_id, f"✅ 新会话 `{sess['session_id'][:8]}...` | 🔒{sess['perm_level']}")

        elif cmd in ("/safe", "/unsafe", "/full"):
            level = cmd[1:]  # "safe", "unsafe", "full"
            sess = self._get_sess(chat_id)
            sess["perm_level"] = level
            desc = {"safe": "只读+编辑", "unsafe": "允许 Bash", "full": "全部工具"}
            _reply(msg_id, f"🔓 权限切换为 **{level}** ({desc.get(level, level)})")

        elif cmd == "/status":
            sess = self.sessions.get(chat_id)
            if sess:
                s = "🟢 运行中" if sess.get("running") else "⏸ 空闲"
                _reply(msg_id,
                    f"**状态**: {s}\n"
                    f"**轮次**: {sess['turn']}\n"
                    f"**权限**: 🔒{sess['perm_level']}\n"
                    f"**会话**: `{sess['session_id'][:16]}...`")
            else:
                _reply(msg_id, "ℹ️ 无活跃会话")

        elif cmd == "/sessions":
            disk_sessions = claude.list_sessions()
            if not disk_sessions:
                _reply(msg_id, "ℹ️ 磁盘上暂无 Claude Code 会话")
                return

            current_sid = self.sessions.get(chat_id, {}).get("session_id", "")
            tracked_sids = {s["session_id"] for s in self.sessions.values()}
            lines = [f"**📋 所有 Claude Code 会话 ({len(disk_sessions)} 个)**\n"]
            for s in disk_sessions:
                if s["sid"] == current_sid:
                    marker = "🟢"  # 当前 chat 的会话
                elif s["sid"] in tracked_sids:
                    marker = "🔗"  # 其他 chat 在使用
                else:
                    marker = "  "
                lines.append(
                    f"{marker} `{s['short_id']}` {s['age']} {s['size_kb']}KB "
                    f"#{s['turns']}轮 [{s['cwd']}]\n"
                    f"     _{s['title'][:60]}_"
                )
            _reply(msg_id, "\n".join(lines))

        elif cmd.startswith("/switch "):
            target = cmd.split(" ", 1)[1].strip()
            matched_sid = None

            # 1. 先查内存中的活跃会话
            for cid, s in self.sessions.items():
                if cid.endswith(target):
                    matched_sid = s["session_id"]
                    break

            # 2. 再查磁盘上的所有会话
            matched_cwd = None
            if matched_sid is None:
                for s in claude.list_sessions():
                    if s["sid"].startswith(target) or s["short_id"] == target:
                        matched_sid = s["sid"]
                        matched_cwd = s["cwd"]
                        break

            if matched_sid is None:
                _reply(msg_id, f"❌ 未找到匹配 `{target}` 的会话。用 `/sessions` 查看所有会话。")
                return

            # 创建/更新当前 chat 的会话，指向目标 session_id
            sess = self._get_sess(chat_id)
            sess["session_id"] = matched_sid
            sess["is_first"] = False
            sess["turn"] = 0
            if matched_cwd:
                sess["cwd"] = matched_cwd

            cwd_info = f"\n📁 `{matched_cwd}`" if matched_cwd else ""
            _reply(msg_id,
                f"✅ 已切换到 `{matched_sid[:8]}...`{cwd_info}\n"
                f"下次消息将恢复该会话的上下文。")

        elif cmd.startswith("/clear "):
            target = cmd.split(" ", 1)[1].strip()
            ok, info = claude.delete_session(target)

            if ok:
                # 删的是当前 chat 的活跃会话 → 重置
                sess = self.sessions.get(chat_id)
                if sess and sess["session_id"] == info:
                    self.sessions.pop(chat_id, None)
                    _reply(msg_id, f"🗑 已删除 `{info[:8]}...`（当前会话已重置）")
                else:
                    _reply(msg_id, f"🗑 已删除 `{info[:8]}...`")
            else:
                _reply(msg_id, f"❌ {info}")

        elif cmd == "/help":
            _reply(msg_id, HELP_TEXT)

        else:
            _reply(msg_id, f"未知命令 `{cmd}`\n\n{HELP_TEXT}")


# ---- 同步飞书 API ----

def _reply(msg_id: str, text: str):
    try:
        client = (
            LarkClient.builder()
            .app_id(config.FEISHU_APP_ID)
            .app_secret(config.FEISHU_APP_SECRET)
            .build()
        )
        body = (
            ReplyMessageRequestBody.builder()
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .msg_type("text")
            .build()
        )
        req = ReplyMessageRequest.builder().message_id(msg_id).request_body(body).build()
        resp = client.im.v1.message.reply(req)
        if not resp.success():
            logger.error(f"Reply failed: {resp.code} {resp.msg}")
    except Exception as e:
        logger.exception(f"Reply error: {e}")


def _extract_text(content: str, msg_type: str) -> str:
    if not content:
        return ""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    return data.get("text", content)
