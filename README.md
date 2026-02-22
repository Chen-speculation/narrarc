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

**前置要求**：
- **uv**（Python 包管理）在 PATH 中。若未安装：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`，安装后把 `%USERPROFILE%\.local\bin` 加入 PATH。
- **Node.js 18+**（客户端构建与 Tauri 需要）。
- **Rust**（Tauri 2 首次构建时会提示安装）。

**一键本地运行**（自动安装 uv、Node.js、Rust、MSVC Build Tools，然后启动桌面客户端）：
```cmd
run-local.cmd
```
或（若遇「禁止运行脚本」则用）：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-local.ps1
```
- 首次运行若缺少 **Visual Studio Build Tools**，会自动通过 winget 安装（体积较大，约 10–20 分钟），完成后请再执行一次上述命令即可打开 Tauri 窗口。
- Node.js 若未安装会下载便携版到项目目录 `.node/`，无需全局安装。

## 导入示例数据

客户端内置示例：`client/data/samples/realtalk_emi_elise.json`。在「导入数据」中选择该文件即可快速体验。

## 配置

- 后端 LLM：`backend/config.yml`（参考 `backend/config.yml.example`）
- 数据库：`backend/data/mirror.db`（自动创建）

## 更多文档

- 后端架构：`backend/CLAUDE.md`
- 客户端适配：`backend/docs/CLIENT_ADAPTATION_PLAN.md`
