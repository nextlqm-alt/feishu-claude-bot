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
• `/s` — 会话列表（带编号）
• `/ss` — 当前会话
• `/n` — 新会话
• `/sw <#|id>` — 切换，如 `/sw 2`
• `/clr <#|id>` — 删除，如 `/clr 3`
• `/c` — 取消当前任务
• `/safe` `/unsafe` `/full` — 权限
• `/h` — 帮助
也可用完整命令: `/sessions` `/switch` `/clear` `/cancel` `/new` `/status` `/help`"""


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
            await _reply(msg_id, "⚠️ 上一个任务还在执行中，请稍候。")
            return

        sess["running"] = True
        start = time.time()

        log.add(chat_id, "👤", text)

        cancel_evt = asyncio.Event()
        sess["cancel_evt"] = cancel_evt

        try:
            result, new_sid = await claude.run(
                text, sess["session_id"], sess["is_first"],
                perm_level=sess["perm_level"], chat_id=chat_id,
                cwd=sess.get("cwd"), cancel_evt=cancel_evt,
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

            await _reply(msg_id,prefix + (result.strip() or "(无输出)") + footer)

        except Exception as e:
            logger.exception(f"Error [{chat_id}]: {e}")
            await _reply(msg_id,f"❌ 出错了: {e}")
        finally:
            sess["running"] = False
            sess.pop("cancel_evt", None)

    def _switch_sess(self, chat_id: str, sid: str, cwd: str = None):
        """将当前 chat 切换到指定 sid"""
        sess = self._get_sess(chat_id)
        sess["session_id"] = sid
        sess["is_first"] = False
        sess["turn"] = 0
        if cwd:
            sess["cwd"] = cwd

    def _resolve_sess(self, target: str) -> tuple:
        """按编号或 ID 查找会话，返回 (sid, cwd)。未找到返回 (None, None)。"""
        disks = claude.list_sessions()
        # 数字 → 按列表编号（1-based）
        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(disks):
                return disks[idx]["sid"], disks[idx]["cwd"]
            return None, None
        # 字符串 → 按 ID 前缀或 short_id 匹配
        for s in disks:
            if s["sid"].startswith(target) or s["short_id"] == target:
                return s["sid"], s["cwd"]
        return None, None

    async def _command(self, chat_id: str, msg_id: str, cmd: str):
        if cmd in ("/new", "/n"):
            self.sessions.pop(chat_id, None)
            sess = self._get_sess(chat_id, force_new=True)
            await _reply(msg_id,f"✅ 新会话 `{sess['session_id'][:8]}...` | 🔒{sess['perm_level']}")

        elif cmd in ("/safe", "/unsafe", "/full"):
            level = cmd[1:]  # "safe", "unsafe", "full"
            sess = self._get_sess(chat_id)
            sess["perm_level"] = level
            desc = {"safe": "只读+编辑", "unsafe": "允许 Bash", "full": "全部工具"}
            await _reply(msg_id,f"🔓 权限切换为 **{level}** ({desc.get(level, level)})")

        elif cmd in ("/status", "/session", "/ss"):
            sess = self.sessions.get(chat_id)
            if sess:
                # 从磁盘查找当前会话的标题
                title = ""
                for s in claude.list_sessions():
                    if s["sid"] == sess["session_id"]:
                        title = s["title"]
                        break

                state = "🟢 运行中" if sess.get("running") else "⏸ 空闲"
                lines = [
                    f"**{state}** | 🔒{sess['perm_level']} | #{sess['turn']}轮",
                    f"会话: `{sess['session_id'][:8]}...`",
                ]
                if title:
                    lines.append(f"标题: _{title}_")
                await _reply(msg_id, "\n".join(lines))
            else:
                await _reply(msg_id, "ℹ️ 无活跃会话")

        elif cmd in ("/sessions", "/s"):
            disk_sessions = claude.list_sessions()
            if not disk_sessions:
                await _reply(msg_id, "ℹ️ 磁盘上暂无 Claude Code 会话")
                return

            current_sid = self.sessions.get(chat_id, {}).get("session_id", "")
            tracked_sids = {s["session_id"] for s in self.sessions.values()}
            lines = [f"**📋 会话列表 ({len(disk_sessions)} 个)**\n"]
            for i, s in enumerate(disk_sessions, 1):
                if s["sid"] == current_sid:
                    marker = "🟢"
                elif s["sid"] in tracked_sids:
                    marker = "🔗"
                else:
                    marker = "  "
                lines.append(
                    f"**{i}** {marker} `{s['short_id']}` {s['age']} {s['size_kb']}KB "
                    f"#{s['turns']}轮 [{s['cwd']}]\n"
                    f"     _{s['title'][:60]}_"
                )
            lines.append(f"\n/s _    /sw #    /clr #")
            await _reply(msg_id, "\n".join(lines))

        elif cmd.startswith("/switch ") or cmd.startswith("/sw "):
            target = cmd.split(" ", 1)[1].strip()
            matched_sid, matched_cwd = self._resolve_sess(target)

            if matched_sid is None:
                await _reply(msg_id, f"❌ 未找到匹配 `{target}` 的会话。用 `/s` 查看列表。")
                return

            self._switch_sess(chat_id, matched_sid, matched_cwd)
            cwd_info = f"\n📁 `{matched_cwd}`" if matched_cwd else ""
            await _reply(msg_id,
                f"✅ 已切换到 `{matched_sid[:8]}...`{cwd_info}\n"
                f"下次消息将恢复该会话的上下文。")

        elif cmd.startswith("/clear ") or cmd.startswith("/clr "):
            target = cmd.split(" ", 1)[1].strip()
            matched_sid, _ = self._resolve_sess(target)
            if matched_sid is None:
                await _reply(msg_id, f"❌ 未找到匹配 `{target}` 的会话。用 `/s` 查看列表。")
                return

            ok, info = claude.delete_session(matched_sid)

            if ok:
                # 删的是当前 chat 的活跃会话 → 重置
                sess = self.sessions.get(chat_id)
                if sess and sess["session_id"] == info:
                    self.sessions.pop(chat_id, None)
                    await _reply(msg_id, f"🗑 已删除 `{info[:8]}...`（当前会话已重置）")
                else:
                    await _reply(msg_id, f"🗑 已删除 `{info[:8]}...`")
            else:
                await _reply(msg_id, f"❌ {info}")

        elif cmd in ("/cancel", "/c"):
            sess = self.sessions.get(chat_id)
            if not sess or not sess.get("running"):
                await _reply(msg_id, "ℹ️ 当前没有运行中的任务")
                return
            evt = sess.get("cancel_evt")
            if evt:
                evt.set()
                await _reply(msg_id, "⏹ 已发送取消信号...")
            else:
                await _reply(msg_id, "⚠️ 无法取消（缺少进程引用）")

        elif cmd in ("/help", "/h"):
            await _reply(msg_id,HELP_TEXT)

        else:
            await _reply(msg_id,f"未知命令 `{cmd}`\n\n{HELP_TEXT}")


# ---- 飞书 API（异步非阻塞） ----

def _reply_sync(msg_id: str, text: str):
    """同步发送飞书回复（在 executor 线程中调用）"""
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


async def _reply(msg_id: str, text: str):
    """异步发送飞书回复——HTTP 调用在 executor 线程执行，不阻塞 event loop"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _reply_sync, msg_id, text)


def _extract_text(content: str, msg_type: str) -> str:
    if not content:
        return ""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    return data.get("text", content)
