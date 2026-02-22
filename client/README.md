<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Narrative Mirror - Tauri + React 客户端

基于 Tauri 2 + React + Vite 的桌面应用，将微信聊天历史转化为有证据支持的叙事弧。

## 环境要求

- **Node.js** 18+
- **Rust** (Tauri 2 需要，首次构建会自动下载)
- **macOS**: Xcode Command Line Tools
- **Windows**: Visual Studio Build Tools
- **Linux**: `webkit2gtk`, `libappindicator` 等

## 快速开始

1. 安装依赖：
   ```bash
   npm install
   ```

2. 配置环境变量（可选，如需 Gemini API）：
   - 复制 `.env.example` 为 `.env.local`
   - 设置 `GEMINI_API_KEY`

3. 开发模式（桌面应用）：
   ```bash
   npm run tauri:dev
   ```
   会启动 Vite 开发服务器并打开 Tauri 窗口，支持 HMR。

4. 仅 Web 开发（浏览器预览）：
   ```bash
   npm run dev
   ```

5. 构建桌面应用：
   ```bash
   npm run tauri:build
   ```
   产物在 `src-tauri/target/release/` 下。

## Mock 数据说明

当前客户端使用本地 Mock 数据，未连接后端。详见 [docs/MOCK_DATA_SPEC.md](docs/MOCK_DATA_SPEC.md)，包含：

- **Session**：会话列表
- **Message**：聊天记录
- **Agent / QueryResponse**：查询结果、叙事阶段、Agent 轨迹
- **Import**：导入流程

可根据该文档与 narrarc 后端工程对接接口。

## 项目结构

```
narrative-mirror/
├── src/                 # React 前端
├── src-tauri/           # Tauri Rust 后端
│   ├── src/
│   ├── Cargo.toml
│   └── tauri.conf.json
├── index.html
├── vite.config.ts
└── package.json
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `npm run tauri:dev` | 开发模式（Tauri 窗口 + HMR） |
| `npm run tauri:build` | 构建桌面应用 |
| `npm run dev` | 仅 Web 开发服务器 |
| `npm run build` | 仅构建前端静态资源 |
| `npm run lint` | TypeScript 检查 |
