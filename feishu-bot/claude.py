"""
Claude Code CLI

- claude -p --session-id <UUID> msg  → 新会话
- claude -p --resume <UUID> msg      → 继续会话
- list_sessions()                    → 读取磁盘上的所有会话
"""

import asyncio
import glob
import json
import logging
import os
import sys
import time
import uuid

import log

logger = logging.getLogger(__name__)

# Windows: Python's CreateProcess doesn't resolve .cmd files, need explicit extension
_CLAUDE_EXE = "claude.cmd" if sys.platform == "win32" else "claude"

SESSION_DIR = os.path.expanduser("~/.claude/projects")

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
             perm_level: str = "unsafe", chat_id: str = "",
             cwd: str = None) -> tuple[str, str]:
    """执行 Claude Code，返回 (响应文本, session_id)。

    cwd: 会话所属的工作目录。None 表示使用当前目录。
    """
    sid = session_id or str(uuid.uuid4())
    preset = PERM_PRESETS.get(perm_level, PERM_PRESETS["unsafe"])

    # 跨项目目录的会话需要 --resume 在正确的 cwd 下运行
    # 但 subprocess 的 cwd 参数可以指定
    work_dir = cwd if cwd and os.path.isdir(cwd) else None
    if work_dir:
        logger.info(f"Using session cwd: {work_dir}")

    cmd = [
        _CLAUDE_EXE, "-p",
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
        cwd=work_dir,
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
                    thinking = c.get("thinking", "")[:120]
                    if thinking.strip():
                        log.add(chat_id, "💭", thinking)
                        logger.debug(f"[{chat_id[-8:]}] 💭 {thinking}")
                elif ct == "tool_use":
                    name = c.get("name", "?")
                    inp = json.dumps(c.get("input", {}), ensure_ascii=False)[:200]
                    log.add(chat_id, "🔧", f"{name}: {inp}", {"tool": name, "input": c.get("input", {})})
                    logger.info(f"[{chat_id[-8:]}] 🔧 {name}: {inp}")
                elif ct == "text":
                    text_parts.append(c.get("text", ""))

        elif t == "user":
            for c in ev.get("message", {}).get("content", []):
                result = str(c.get("content", ""))[:300]
                is_err = c.get("is_error", False)
                tag = "❌" if is_err else "✅"
                log.add(chat_id, tag, result)
                if is_err:
                    logger.warning(f"[{chat_id[-8:]}] ❌ {result}")

        elif t == "result":
            final = ev.get("result", "")
            if final:
                text_parts.append(final)
                log.add(chat_id, "🤖", final[:500])

    await proc.wait()
    stderr = (await proc.stderr.read()).decode("utf-8", errors="replace")

    if proc.returncode != 0:
        err = stderr[:300] or "unknown error"
        logger.error(f"Claude exited {proc.returncode}: {err}")
        return f"❌ 执行失败: {err}", sid

    return "".join(text_parts), sid


def list_sessions() -> list[dict]:
    """扫描磁盘上所有 Claude Code 会话，返回 [{
        sid, short_id, title, mtime, size_kb, turns, project, cwd
    }]"""
    results = []
    now = time.time()

    for proj_dir in glob.glob(os.path.join(SESSION_DIR, "*")):
        project = os.path.basename(proj_dir)

        for f in sorted(glob.glob(os.path.join(proj_dir, "*.jsonl"))):
            sid = os.path.basename(f)[:-6]
            stat = os.stat(f)
            title, turns, parsed_cwd = _parse_session_meta(f)
            # 优先用 JSONL 里的 cwd，回退到 project 目录名解码
            real_cwd = parsed_cwd or project

            results.append({
                "sid": sid,
                "short_id": sid[:8],
                "title": title,
                "mtime": stat.st_mtime,
                "age": _format_age(now - stat.st_mtime),
                "size_kb": int(stat.st_size / 1024),
                "turns": turns,
                "project": project,
                "cwd": real_cwd,
            })

    results.sort(key=lambda r: r["mtime"], reverse=True)
    return results


def _parse_session_meta(filepath: str) -> tuple[str, int, str]:
    """解析 session JSONL，返回 (首条用户消息, 对话轮次, 工作目录)"""
    title = ""
    turns = 0
    cwd = ""
    try:
        with open(filepath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 从任意行提取 cwd
                if not cwd and d.get("cwd"):
                    cwd = d["cwd"]

                t = d.get("type", "")
                if t == "user":
                    turns += 1
                    if not title:
                        msg = d.get("message", {})
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            parts = []
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    text = c.get("text", "").strip()
                                    if text and not text.startswith(("/", "<")):
                                        parts.append(text)
                            title = " ".join(parts)
                        elif isinstance(content, str) and not content.startswith(("/", "<")):
                            title = content.strip()
                elif t == "assistant":
                    turns += 1
    except Exception:
        pass

    title = title[:80] or "(无文本消息)"
    title = title.replace("\n", " ").replace("\r", "")
    return title, turns // 2, cwd


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h"
    else:
        return f"{int(seconds / 86400)}d"
