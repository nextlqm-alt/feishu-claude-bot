"""
Claude Code CLI

使用 stream-json 模式捕获思考过程、工具调用和最终回复。
"""

import asyncio
import json
import logging
import os
import uuid

import log

logger = logging.getLogger(__name__)

PERM_PRESETS = {
    "safe": {
        "mode": "acceptEdits",
        "tools": "Read(*),Write(*),Edit(*),Glob(*),Grep(*),WebFetch(*),WebSearch(*)"
    },
    "unsafe": {
        "mode": "acceptEdits",
        "tools": "Bash(*),Read(*),Write(*),Edit(*),Glob(*),Grep(*),WebFetch(*),WebSearch(*)"
    },
    "full": {
        "mode": os.getenv("CLAUDE_FULL_MODE", "acceptEdits"),
        "tools": "Bash(*),Read(*),Write(*),Edit(*),Glob(*),Grep(*),WebFetch(*),WebSearch(*),Task(*),Skill(*)"
    },
}


async def run(message: str, session_id: str, is_new: bool,
             perm_level: str = "unsafe", chat_id: str = "") -> tuple[str, str]:
    """执行 Claude Code，返回 (响应文本, session_id)。"""
    sid = session_id or str(uuid.uuid4())
    preset = PERM_PRESETS.get(perm_level, PERM_PRESETS["unsafe"])

    cmd = [
        "claude", "-p",
        "--session-id" if is_new else "--resume", sid,
        "--permission-mode", preset["mode"],
        "--allowedTools", preset["tools"],
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        message,
    ]

    logger.info(f"claude [{perm_level}] {sid[:8]}... \"{message[:60]}...\"")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    text_parts = []
    async for line in proc.stdout:
        try:
            ev = json.loads(line.decode().strip())
        except json.JSONDecodeError:
            continue

        t = ev.get("type", "")

        if t == "assistant":
            for c in ev.get("message", {}).get("content", []):
                ct = c.get("type", "")
                if ct == "thinking":
                    thinking = c.get("thinking", "")[:200]
                    if thinking.strip():
                        log.add(chat_id, "💭", thinking)
                elif ct == "tool_use":
                    name = c.get("name", "?")
                    inp = json.dumps(c.get("input", {}), ensure_ascii=False)[:300]
                    log.add(chat_id, "🔧", f"{name}: {inp}", {"tool": name, "input": c.get("input", {})})
                elif ct == "text":
                    text_parts.append(c.get("text", ""))

        elif t == "user":
            for c in ev.get("message", {}).get("content", []):
                result = str(c.get("content", ""))[:500]
                is_err = c.get("is_error", False)
                tag = "❌" if is_err else "✅"
                log.add(chat_id, tag, result)

        elif t == "result":
            final = ev.get("result", "")
            if final:
                text_parts.append(final)

    await proc.wait()
    stderr = (await proc.stderr.read()).decode("utf-8", errors="replace")

    if proc.returncode != 0:
        err = stderr[:300] or "unknown error"
        logger.error(f"Claude exited {proc.returncode}: {err}")
        return f"❌ 执行失败: {err}", sid

    return "".join(text_parts), sid
