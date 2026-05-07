# NJU QQ helper

Docker 运行结构：
- `web`：前端页面 + `POST /api/activities/extract`（读取 `data/activities.json`）
- `bridge`：连接 NapCat WebSocket，调用 AI 提取活动并写入 `data/activities.json`

## 1) 配置环境变量（不要明写密钥）

```bash
cp .env.example .env
```

编辑 `.env`：

```env
AI_API_KEY=你的真实密钥
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
PORT=8000
NAPCAT_WS_URL=ws://127.0.0.1:3001
TARGET_GROUP_ID=685245727
TARGET_USERS=123456789,987654321
SYSTEM_PROMPT=
```

说明：
- `AI_API_KEY` 只在桥接容器内读取，不出现在前端。
- `TARGET_USERS` 为空时表示监听目标群所有成员；不为空则按逗号分隔白名单过滤。
- `SYSTEM_PROMPT` 可留空（使用内置提示词），也可自定义。

## 2) Docker 启动

```bash
docker compose up -d --build
```

打开：`http://<你的服务器IP>:8000`

NapCat 端口参考（按你当前配置）：
- WebUI: `6099`
- HTTP: `3002`（当前 bridge 未使用）
- WebSocket: `3001`（bridge 使用这个）

## 3) 工作流程

1. NapCat 推送群消息到 `NAPCAT_WS_URL`
2. `bridge` 过滤目标群/成员后调用 AI
3. 提取结果自动去重更新并写入 `data/activities.json`
4. 前端点“同步活动”时从 `/api/activities/extract` 拉取并展示

## 4) 你给的示例代码问题

你那段代码的整体思路是对的，但有几个风险点：
- 把 `AI_API_KEY` 写死在代码里（不安全）
- 只提取 `task + ddl`，不符合你当前页面字段
- 使用 sqlite 会增加前端对接复杂度（你现在页面更适合直接读活动 JSON）
- 缺少“同名活动更新、无变化忽略”的逻辑

本项目里我已实现这些能力（环境变量、活动结构化、去重更新、Docker化）。
