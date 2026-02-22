# WeFlow vs Narrarc 前端对比与改进计划

## 一、技术栈对比

| 维度 | WeFlow | Narrarc |
|------|--------|---------|
| **桌面壳** | Electron 39 + Vite 6 | Tauri 2 + Vite 6 |
| **前端框架** | React 19 + TypeScript | React 19 + TypeScript |
| **样式** | SCSS + CSS 变量（设计系统） | Tailwind CSS 4 |
| **状态** | Zustand | 本地 useState |
| **动效** | CSS keyframes + transition | motion (ex-framer-motion) |
| **长列表** | react-virtuoso | 无虚拟列表 |
| **图表** | echarts + echarts-for-react | 无 |
| **路由** | react-router-dom v7 | 无（单页） |

**结论**：  
- **(a)** WeFlow 确认为 **Electron + React + Vite**；Narrarc 为 **Tauri + React + Vite**。  
- **(b)** 语言上：前端都是 TS/React；差异在「壳」：Electron 用 Node/Chromium，Tauri 用 Rust + 系统 WebView。  
- **丝滑感差异**主要来自：**窗口与标题栏设计**、**动效与过渡**、**设计系统统一度**、以及**列表与交互细节**，而非单纯 Electron vs Tauri。

---

## 二、差距具体在哪里

### 2.1 窗口与标题栏（影响最大）

**WeFlow：**

- `electron/main.ts` 使用：
  - `titleBarStyle: 'hidden'`
  - `titleBarOverlay: { color: '#00000000', symbolColor: '#1a1a1a', height: 40 }`
- 即：**无系统标题栏**，窗口顶部交给前端。
- 前端实现：
  - 固定高度 **TitleBar**（logo + 标题），整条 `-webkit-app-region: drag`，可拖拽窗口。
  - 顶部一条 **window-drag-region**（`right: 150px` 预留右侧按钮区），同样 `drag`。
  - 系统最小化/最大化/关闭由 **系统 overlay 按钮** 渲染（symbolColor 随主题切换），与内容区视觉统一。

**Narrarc：**

- `tauri.conf.json` 未改 `decorations`，即使用 **系统默认标题栏**。
- 无自定义标题栏、无拖拽区、无自定义关闭/最小化样式。
- 表现：标准 Windows 标题栏，与 App 内风格割裂，也无法做「关闭 hover 变红」等细节。

**差距总结：**  
WeFlow 的「丝滑」很大程度来自：**一体化的窗口外观 + 自定义标题栏 + 拖拽区**。Narrarc 目前是系统标题栏，观感和交互都更「传统」。

---

### 2.2 关闭 / 最小化 / 最大化交互

**WeFlow：**

- 独立窗口（如欢迎页、引导页）在页面内做 **自定义窗口按钮**：
  - 圆形按钮：最小化、关闭（`WelcomePage.scss`）。
  - `.window-btn`：圆角、半透明背景、`backdrop-filter`。
  - **关闭按钮**：`.is-close:hover` → `background: #ff5f57; color: white`（类似 macOS 红点）。
- 主窗口则用系统 overlay 按钮，与主题色同步（`setTitleBarOverlay({ symbolColor })`）。

**Narrarc：**

- 完全依赖系统标题栏按钮，无自定义样式、无 hover 反馈。

**可借鉴：**  
- 若采用无边框 + 自定义标题栏，关闭按钮应带 **hover 变红** 的语义化设计。  
- 最小化/最大化可用图标 + 统一圆角与过渡。

---

### 2.3 动效与入场

**WeFlow：**

- `App.scss`：`.app-container` 使用 `animation: appFadeIn 0.35s ease-out`（opacity + translateY）。
- `WelcomePage.scss`：欢迎卡片 `animation: scaleIn 0.5s cubic-bezier(0.16, 1, 0.3, 1)`。
- 全局统一 `transition`（如 0.2s ease）在按钮、导航等控件上。

**Narrarc：**

- 已引入 `motion`，在 MainArea 等有 `AnimatePresence` 等。
- 缺少「整窗」级别的入场动画，也缺少类似 WeFlow 的**统一过渡时长与曲线**。

**差距：**  
WeFlow 有明确的**应用级入场 + 卡片级动效**；Narrarc 可补「整窗淡入/微位移」和全局 transition 规范。

---

### 2.4 主题与设计系统

**WeFlow：**

- `themeStore` 多主题（云上舞白、刚玉蓝等），每个主题有 `primaryColor`、`bgColor`。
- 全局 CSS 变量：`--bg-primary`、`--bg-secondary`、`--text-primary`、`--border-color`、`--primary` 等。
- 亮/暗/跟随系统，且与 `setTitleBarOverlay(symbolColor)` 联动。

**Narrarc：**

- 深/浅色切换 + Tailwind（如 `dark:bg-[#050505]`）。
- 没有统一的 design tokens（如 spacing、radius、duration），也没有多套主题色。

**差距：**  
WeFlow 的「丝滑」一部分来自**颜色与间距的一致性和可预测性**。Narrarc 可逐步引入少量 CSS 变量或 Tailwind 扩展，统一圆角、过渡时间、主题色。

---

### 2.5 侧栏与布局

**WeFlow：**

- 侧栏可**折叠**（`collapsed`），宽度 220px → 64px，带 `transition: width 0.25s ease`。
- 导航项圆角胶囊形、active 态明显（背景主色）。

**Narrarc：**

- 侧栏固定宽度，无折叠；功能上已具备会话列表、主题切换、导入等。
- 若会话数量增多，可考虑虚拟列表（见下）。

---

### 2.6 长列表与性能

**WeFlow：**

- 依赖中有 **react-virtuoso**（聊天等长列表场景会用到虚拟滚动），减少 DOM 与重排。

**Narrarc：**

- 会话列表、消息列表若数据量大，目前未做虚拟化，可能在大数据量下出现滚动或渲染不够顺滑。

**差距：**  
在「大量会话/消息」场景，引入虚拟列表可明显提升丝滑感。

---

## 三、可借鉴的界面设计（可直接参照或借鉴）

1. **关闭窗口的方式**
   - **无边框窗口 + 自定义标题栏**：顶部一条为拖拽区，右侧为最小化/最大化/关闭。
   - **关闭按钮**：圆形或圆角矩形，hover 时变为红色（#ff5f57 或相近），与 WeFlow/部分 macOS 习惯一致。
   - **原因**：语义清晰、视觉反馈明确，且与内容区风格统一。

2. **窗口拖拽**
   - 标题栏区域（或整条顶部区域）设为可拖拽（Tauri 用 `data-tauri-drag-region`），避免与按钮、输入框抢事件。

3. **应用入场动画**
   - 整窗淡入 + 轻微 translateY（如 8px → 0），时长约 0.3–0.35s，ease-out。

4. **统一过渡**
   - 按钮、导航、卡片等使用统一 duration（如 0.2s）和 ease，避免有的地方「很快」、有的「很慢」。

5. **侧栏折叠（可选）**
   - 侧栏支持收起/展开，并带宽度 transition，便于在窄屏或需要更大内容区时使用。

---

## 四、改进计划（按优先级）

### P0：自定义标题栏 + 窗口控制（对齐 WeFlow 的「关闭方式」与一体感）

- **Tauri 配置**
  - 在 `tauri.conf.json` 的主窗口配置中设置 `decorations: false`。
  - 在 `capabilities/default.json` 中增加窗口相关权限（见下）。
- **前端**
  - 新增 **TitleBar** 组件：
    - 左侧：Logo + 应用名（可带 `data-tauri-drag-region`）。
    - 右侧：最小化、最大化、关闭三个按钮；关闭按钮 hover 时背景变为红色。
  - 在 `App.tsx` 顶层放入 TitleBar，并保证拖拽区覆盖标题栏区域（右侧留出按钮区）。
- **权限示例**（Tauri 2）：
  ```json
  "core:window:default",
  "core:window:allow-start-dragging",
  "core:window:allow-close",
  "core:window:allow-minimize",
  "core:window:allow-toggle-maximize"
  ```
- **调用**：使用 `@tauri-apps/api/window` 的 `getCurrent()` 得到当前窗口，调用 `minimize()`、`toggleMaximize()`、`close()`。

**产出**：无边框窗口 + 自定义标题栏 + 拖拽 + 关闭/最小化/最大化，关闭按钮 hover 变红。

---

### P1：应用级入场动效

- 在根布局容器上增加入场动画（如 opacity 0→1，translateY 8px→0），时长约 0.3s，ease-out。
- 可与现有 `motion` 或纯 CSS keyframes 二选一，保持与其它动效风格一致。

---

### P2：统一过渡与设计 token

- 定义少量 CSS 变量或 Tailwind 扩展：如 `--transition-duration: 0.2s`、`--radius-md`、主色等。
- 为按钮、导航、卡片等统一使用同一 transition duration/ease，避免参差不齐。

---

### P3：侧栏可折叠（可选）

- 侧栏增加折叠状态，宽度从当前值过渡到约 64px（仅图标），带 `transition: width 0.25s ease`。
- 折叠时仅显示图标，展开显示文案，交互可参考 WeFlow Sidebar。

---

### P4：长列表虚拟化（有大量数据时）

- 若会话列表或消息列表条目很多，引入 **react-virtuoso**（或类似）做虚拟滚动，减少 DOM 与重绘，提升滚动流畅度。

---

## 五、总结

| 差距点 | 原因简述 | 改进方向 |
|--------|----------|----------|
| 窗口与标题栏 | WeFlow 无边框 + 自定义 TitleBar + 拖拽区；Narrarc 用系统标题栏 | P0：Tauri 无边框 + 自定义 TitleBar + 关闭 hover 变红 |
| 关闭/最小化交互 | WeFlow 有自定义按钮与 hover 语义 | P0：自定义三个窗口按钮 + 统一样式 |
| 动效 | WeFlow 有 app 入场 + 统一 transition | P1 入场 + P2 统一过渡 |
| 主题与设计系统 | WeFlow 多主题 + CSS 变量 | P2 设计 token，可选多主题 |
| 侧栏 | WeFlow 可折叠 | P3 侧栏折叠 |
| 长列表 | WeFlow 用 react-virtuoso | P4 按需虚拟列表 |

**技术栈差异**（Electron vs Tauri）会带来打包体积与运行时的不同，但「丝滑」更多来自：**统一的窗口与标题栏设计、明确的动效与过渡、以及列表与交互细节**。优先做 P0（自定义标题栏与窗口控制），再补 P1/P2，能最快缩小与 WeFlow 在前端体验上的差距，并直接借鉴其「关闭窗口的方式」与整体一体感。
