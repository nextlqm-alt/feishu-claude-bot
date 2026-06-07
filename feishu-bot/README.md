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

```bash
cd feishu-bot
cp .env.example .env
# 编辑 .env，填入 FEISHU_APP_ID 和 FEISHU_APP_SECRET

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
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

| 命令 | 作用 |
|------|------|
| 直接发消息 | 与 Claude Code 对话 |
| `/safe` | 安全模式：只读 + 文件编辑，禁止 Bash |
| `/unsafe` | 标准模式（**默认**）：允许 Bash |
| `/full` | 完整模式：允许所有工具 |
| `/new` | 重置当前会话，清空上下文 |
| `/sessions` | 列出本机**所有** Claude Code 会话（磁盘扫描） |
| `/switch <id>` | 切换到指定会话（支持跨项目目录） |
| `/status` | 查看当前会话状态 |
| `/help` | 显示帮助 |

### 会话管理

`/sessions` 扫描 `~/.claude/projects/` 下所有 Claude Code 会话，显示：

```
📋 所有 Claude Code 会话 (20 个)

   cf5bb7a7 5m 1923KB #408轮 [/root/桌面/feishu]
      # 基础开发 /plugin install code-review@claude-plugins-official
🔗 5afae8e9 31m 126KB #32轮 [/root/桌面/feishu/feishu-bot]
     列出之前的会话
  f85117c7 2d 256KB #50轮 [/root/桌面]
     帮我写一个 Nginx 配置
```

- `🔗` 表示已关联到当前飞书群聊
- `/switch f85117c7` 可以恢复 2 天前在 `/root/桌面` 目录下的会话
- 切换后自动定位到原会话的工作目录，保证 `--resume` 正确

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
| `main.py` | 65 | 入口：启动 WS 连接 + Web 面板 |
| `bot.py` | 165 | 飞书消息路由 + 会话管理 + 命令 |
| `claude.py` | 90 | Claude CLI 调用，stream-json 解析 |
| `webui.py` | 105 | 本地监控面板，SSE 实时推送 |
| `log.py` | 15 | 共享事件日志 |
| `config.py` | 10 | 环境变量读取 |
