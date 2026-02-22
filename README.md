# narrarc

将微信聊天历史转化为有证据支持的叙事弧的系统。采用双层索引架构，支持自然语言查询关系动态变化。

## 项目结构

```
narrarc/
├── backend/      # Python 后端（narrative_mirror）
├── client/       # Tauri 桌面客户端（叙事镜鉴）
└── README.md
```

## 快速开始

### 后端

```bash
cd backend
uv sync
uv run python -m narrative_mirror.build --talker mock_talker_001 --debug
uv run python -m narrative_mirror.metadata --talker mock_talker_001 --debug
uv run python -m narrative_mirror.layer2 --talker mock_talker_001 --debug
uv run python -m narrative_mirror.query --talker mock_talker_001 "我们是怎么一步步分手的？"
```

### 客户端

```bash
cd client
npm install
npm run tauri:dev
```

**前置要求**：本机安装 `uv`（Python 包管理）、`uv` 在 PATH 中。客户端会通过 `backend/` 目录运行 Python 子进程。

## 导入示例数据

客户端内置示例：`client/data/samples/realtalk_emi_elise.json`。在「导入数据」中选择该文件即可快速体验。

## 配置

- 后端 LLM：`backend/config.yml`（参考 `backend/config.yml.example`）
- 数据库：`backend/data/mirror.db`（自动创建）

## 更多文档

- 后端架构：`backend/CLAUDE.md`
- 客户端适配：`backend/docs/CLIENT_ADAPTATION_PLAN.md`
