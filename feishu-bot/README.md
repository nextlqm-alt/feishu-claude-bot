# 飞书 Claude Code Bot

通过飞书消息控制本地 Claude Code 编写代码，支持流式思考过程查看。

## 架构

```
飞书群聊 ──WebSocket──▶ Python Bot ──subprocess──▶ Claude Code CLI
    ◀── 回复消息 ──              ◀── 流式输出 ──

本地浏览器 ──SSE──▶ http://localhost:8080    实时查看思考过程
```

## 快速开始

### 1. 飞书应用配置

1. 打开 [飞书开发者后台](https://open.feishu.cn/app)，创建**企业自建应用**
2. **添加能力** → 机器人
3. **权限管理** → 添加以下权限：
   - `im:message` — 接收和发送消息
   - `im:message:read` — 读取消息内容
   - `im:chat` — 获取群聊信息
4. **事件订阅** → 订阅 `im.message.receive_v1`（WebSocket 模式无需配置回调 URL）
5. **版本管理** → 创建版本并发布（仅应用管理员可见即可）
6. **凭证与基础信息** → 复制 App ID 和 App Secret

### 2. 安装启动

> **注意：** 当前版本仅在 Windows 下测试通过。

```powershell
cd feishu-bot
copy .env.example .env
# 编辑 .env，填入 FEISHU_APP_ID 和 FEISHU_APP_SECRET

python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

启动成功：
```
  本地监控 → http://localhost:8080
  [Lark] connected to wss://msg-frontier.feishu.cn/ws/v2?...
```

### 3. 使用

在飞书群聊中 **@机器人** 发送消息即可。

## 命令参考

| 命令 | 别名 | 作用 |
|------|------|------|
| 直接发消息 | — | 与 Claude Code 对话 |
| `/h` | `/help` | 显示帮助菜单 |
| `/s` | `/sessions` | 列出所有会话（带编号） |
| `/ss` | `/status` `/session` | 当前会话详情（含标题） |
| `/n` | `/new` | 重置会话，新建上下文 |
| `/sw #` | `/switch #` | 按编号切换会话（如 `/sw 2`） |
| `/sw <id>` | `/switch <id>` | 按 ID 前缀或 short_id 切换 |
| `/clr #` | `/clear #` | 按编号或 ID 删除会话 |
| `/c` | `/cancel` | 取消当前运行中的任务 |
| `/safe` | — | 安全模式：只读 + 编辑，禁止 Bash |
| `/unsafe` | — | 标准模式（**默认**）：允许 Bash |
| `/full` | — | 完整模式：允许所有工具 |

### 会话管理

新连接自动恢复磁盘上最近一次会话，无需手动切换。`/s` 列出带编号的会话列表：

```
📋 会话列表 (4 个)

**1** 🟢 6f56bf21  3m  12KB  #99轮  [D:/feishu]
     hello
**2** 🔗 88cd3a80  1h  45KB  #4轮   [D:/feishu/bot]
     修复 arp 检测

/s _    /sw #    /clr #
```

- `🟢` 当前会话，`🔗` 其他飞书聊天使用中
- `/sw 2` 即可切换到第 2 个会话，无需复制粘贴 UUID
- `/clr 3` 删除第 3 个会话
- `/c` 随时取消运行中的 Claude 任务（类似按 Esc）
- `/n` 强制创建全新会话

## 日志

日志同时输出到**终端**和**文件**：

```
feishu-bot/logs/bot.log
```

| 图标 | 含义 | 级别 |
|------|------|------|
| 👤 | 用户消息 | INFO |
| 🔧 | 工具调用及参数 | INFO |
| ❌ | 工具被阻止或失败 | WARNING |
| 💭 | Claude 思考过程 | DEBUG |
| 🤖 | Claude 回复 | INFO |

## 本地监控面板

浏览器打开 `http://localhost:8080`，实时查看完整的思考过程、工具调用和对话记录。

## 配置项（.env）

```bash
# 飞书应用凭证（必填）
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 飞书事件加密（可选，事件订阅页面可配）
FEISHU_ENCRYPT_KEY=
FEISHU_VERIFICATION_TOKEN=

# 日志级别
LOG_LEVEL=INFO

# Full 模式的权限模式（root 下只能用 acceptEdits）
CLAUDE_FULL_MODE=acceptEdits
```

## 文件说明

| 文件 | 行数 | 职责 |
|------|------|------|
| `main.py` | 73 | 入口：启动 WS 连接 + Web 面板 |
| `bot.py` | 310 | 飞书消息路由 + 会话管理 + 命令 |
| `claude.py` | 284 | Claude CLI 调用 + stream-json 解析 + 取消机制 |
| `webui.py` | 149 | 本地监控面板，SSE 实时推送 |
| `log.py` | 17 | 共享事件日志 |
| `config.py` | 13 | 环境变量读取 |
