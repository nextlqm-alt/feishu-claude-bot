# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# Feishu Claude Code Bot — 项目开发指南

## 架构概览

```
main.py ──启动──▶ WS Client (飞书长连接)  +  WebUI (http.server:8080)
  │                    │
  └── bot.py ◀────────┘  SDK 同步回调 → loop.create_task() 异步调度
        │
        ├── claude.py    subprocess: claude -p --output-format stream-json
        ├── log.py       deque(maxlen=500) 事件日志（内存）
        └── config.py    os.getenv()
```

## 关键约束

1. **事件处理器必须同步**：`lark_oapi` 的 `EventDispatcherHandler` 同步调用回调。`handle_message` 内部用 `loop.create_task()` 调度异步任务。
2. **单线程单 loop**：没有 FastAPI/uvicorn。`WsClient.start()` 是同步阻塞方法，内部管理自己的 event loop。WebUI 在独立线程运行。
3. **飞书 API 是同步的**：`LarkClient` 底层用 `requests` 库，线程安全，async 函数中直接调用即可。
4. **root 限制**：`--permission-mode bypassPermissions` 在 root 下被禁止，只能用 `acceptEdits`。

## 开发规范

### 加新功能
1. `bot.py` 是唯一消息入口，新功能加在 `_chat()` 或 `_command()` 中
2. 如需新的飞书 API，查 `lark_oapi.api.im.v1` 的 model 和 request builder
3. 飞书消息类型说明：text 消息 content 是 `{"text":"..."}` 的 JSON 字符串

### 加新飞书事件
1. 在 `main.py` 的 `EventDispatcherHandler.builder()` 链中注册
2. 在 `bot.py` 加对应 handler 方法（必须是同步函数）
3. 不关心的事件统一绑到 `handle_noop`

### 调试
- 终端日志：`LOG_LEVEL=DEBUG` 在 `.env` 中设置
- Web 面板：`http://localhost:8080` 实时查看所有事件流
- Claude 原始输出：`claude.py` 的 stream-json 解析循环

### 不要做的事
- 不要加 FastAPI/Flask——WebUI 用 stdlib 足够
- 不要在 bot.py 的 handler 方法中写 async——SDK 同步调用
- 不要加 session_manager 类——一个 `dict[str,dict]` 足够
