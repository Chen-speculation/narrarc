# Narrative Mirror 客户端适配计划（完整版）

本文档对两个项目的现状进行全面对比，识别后端无法满足的功能，并给出可直接实施的完整方案。

---

## 一、双端现状对比总览

### 1.1 客户端（narrative-mirror）实际状态

**架构**：React 19 + TypeScript + Tauri 2，共 10 个组件文件。

**Tauri Rust 侧**（`src-tauri/src/lib.rs`）：**完全未实现**，仅有 6 行默认模板，没有注册任何 Command，没有引入 shell 插件，Python 子进程调用完全不存在。

**当前 Mock 状态**：

| 功能点 | 文件位置 | Mock 方式 |
|--------|----------|-----------|
| 会话列表 | `App.tsx` | 硬编码 `sessionsMock`（4条固定数据）|
| 消息列表 | `App.tsx` | 只有 `mock_talker_002` 有 `workMessages`（125条），其他3个会话无消息 |
| 查询结果 | `App.tsx` | 始终返回 `queryWorkMock`，与问题和会话无关 |
| AgentProgress 步骤 | `MainArea.tsx:141` | 硬编码 `steps={queryWorkMock.agent_trace.steps}` |
| 导入 | `ImportModal.tsx` | 前端纯本地创建 Session，数据从未到达后端 |
| Build 触发 | 无 | 不存在，导入后 `build_status` 永远是 `pending` |

**查询执行顺序（当前 Bug）**：
```
用户提交 → queryState='analyzing' → 播放10秒动画 → 动画结束后才调用 onQuery()
```
这意味着真实后端调用发生在动画之后，而非并发，必须修改。

### 1.2 后端（narrarc）实际状态

| 能力 | 实现状态 | 说明 |
|------|----------|------|
| 从 SQLite 聚合 Session 列表 | ❌ 不存在 | `db.py` 无此函数，需新增 |
| 获取消息列表 | ✅ 已有 | `db.get_all_messages()` |
| 运行查询（含 AgentTrace）| ✅ 已有 | `workflow.run_workflow()` 返回 `AgentTrace` |
| 转换为客户端 JSON 格式 | ❌ 不存在 | `cli_json.py` 模块不存在 |
| 解析并导入外部数据 | ⚠️ 部分 | `JsonFileDataSource` 需要两个文件；无单文件导入 |
| 触发完整构建流水线 | ⚠️ 仅 CLI | 手动运行 build/metadata/layer2，无统一入口 |
| `AgentStep.timestamp_ms` | ❌ 不存在 | `AgentStep` 数据类无时间戳字段 |
| `AgentTrace.total_duration_ms` | ❌ 不存在 | `AgentTrace` 数据类无计时字段 |
| `NarrativePhase.phase_index` | ❌ 不存在 | 需在转换层枚举生成 |

---

## 二、功能缺口详细分析

### 2.1 缺口一：Tauri 侧没有 Python 调用桥（最严重，阻塞所有功能）

**现状**：`lib.rs` 是空壳，Cargo.toml 没有 `tauri-plugin-shell`，无法从 TypeScript 调用任何外部进程。

**需要做的事**：
1. 安装 `tauri-plugin-shell`
2. 在 lib.rs 注册插件
3. 在 capabilities 中声明权限
4. 在前端安装 npm 包

### 2.2 缺口二：查询是串行而非并发

**现状**：`MainArea.tsx` 的流程是：
```typescript
handleSubmit → setQueryState('analyzing')  // 开始10s动画
// ... 10s后 ...
handleAnalysisComplete → onQuery(query)    // 才调用后端
```

**问题**：真实 LLM 查询需要 30-60 秒，而客户端只播放了 10 秒动画就期待结果，会导致动画结束后界面卡死等待。

**需要做的事**：重构为并发模式——用户提交时立即调用后端，同时播放动画；后端响应到达时无论动画是否完成都渲染结果。

### 2.3 缺口三：Import 从未调用后端

**现状**：`ImportModal.tsx` 的 `handleSubmit`：
```typescript
// 伪造1.5秒处理
await sleep(1500)
// 纯前端创建 Session 对象
onImport({ talker_id: `imported_${Date.now()}`, build_status: 'pending', ... })
// 数据从未写入 SQLite，从未触发构建
```

**需要做的事**：
1. 后端新增 `import` 命令，解析 JSON，写入 SQLite
2. 后端新增 `build` 命令，触发构建流水线
3. ImportModal 调用真实后端，轮询 build_status

### 2.4 缺口四：JsonFileDataSource 需要两个文件，但客户端只能上传一个

**现状**：`JsonFileDataSource` 接受 `messages_path` 和 `sessions_path` 两个独立文件。

**需要做的事**：在 `cli_json.py` 定义并解析一种单文件导入格式（详见第四节）。

### 2.5 缺口五：build_status 无法区分 `in_progress`

**现状**：后端无法知道构建是否正在进行（无进程锁，无状态写入）。

**可行方案**：通过检查各表的数据完整性推断状态：
- `pending`：有 `raw_messages`，无 `topic_nodes`
- `in_progress`：有 `topic_nodes`，无 `node_metadata`（Layer 1 完成但 1.5 未完成）
- `complete`：有 `topic_nodes` 且有 `node_metadata`

---

## 三、后端改动清单（narrarc）

### 3.1 `db.py` — 新增 2 个函数

```python
def get_talkers_with_stats(conn: sqlite3.Connection) -> list[dict]:
    """从 raw_messages / topic_nodes / node_metadata 聚合 Session 信息。"""
    # SQL:
    # SELECT
    #   talker_id,
    #   COUNT(*) as message_count,
    #   MAX(create_time) as last_timestamp,
    #   MIN(CASE WHEN is_send=0 THEN sender_username END) as display_name_candidate
    # FROM raw_messages
    # GROUP BY talker_id
    # 然后逐个查询 build_status
```

```python
def get_build_status(conn: sqlite3.Connection, talker_id: str) -> str:
    """推断构建状态。
    Returns: 'pending' | 'in_progress' | 'complete'
    """
    # has topic_nodes? → if no: 'pending'
    # has node_metadata for those nodes? → if yes: 'complete', else: 'in_progress'
```

### 3.2 `cli_json.py` — 新模块（完整实现）

位置：`src/narrative_mirror/cli_json.py`

**五个子命令**：

#### `list_sessions --db <path>`

```bash
uv run python -m narrative_mirror.cli_json list_sessions --db data/mirror.db
```

输出：`Session[]` JSON
```json
[
  {
    "talker_id": "wxid_xxx",
    "display_name": "张经理",
    "last_timestamp": 1707922800000,
    "build_status": "complete",
    "message_count": 125
  }
]
```

#### `get_messages --db <path> --talker <id>`

```bash
uv run python -m narrative_mirror.cli_json get_messages --db data/mirror.db --talker wxid_xxx
```

输出：`Message[]` JSON，`sender_display` 规则：
- `is_send=True` → `"我"`
- `is_send=False` → `sender_username`（无联系人数据库时 fallback）

```json
[
  {
    "local_id": 1,
    "create_time": 1704000000000,
    "is_send": false,
    "sender_display": "张经理",
    "parsed_content": "消息内容"
  }
]
```

#### `query --db <path> --talker <id> --question "..." [--config config.yml] [--chroma-dir dir]`

```bash
uv run python -m narrative_mirror.cli_json query \
  --db data/mirror.db \
  --talker wxid_xxx \
  --question "我们是怎么走到这一步的" \
  --config config.yml
```

**核心实现逻辑**：
```python
import time

start_ms = int(time.time() * 1000)
trace = run_workflow(question, talker_id, llm, conn, tools, ...)
end_ms = int(time.time() * 1000)

# 为每个 AgentStep 生成递增时间戳（均匀分配总时长）
step_count = len(trace.steps)
for i, step in enumerate(trace.steps):
    step_ts = start_ms + int((end_ms - start_ms) * i / step_count)
    # 转换时附加 step_ts

output = build_query_response(trace, talker_id, start_ms, end_ms, conn)
print(json.dumps(output, ensure_ascii=False))
```

**`build_query_response` 转换细节**（完整字段映射）：

```python
NODE_NAME_DISPLAY = {
    "planner":   "意图解析",
    "retriever": "检索锚点与节点",
    "grader":    "证据评估",
    "explorer":  "深度探查",
    "generator": "叙事生成",
}

def build_query_response(trace, talker_id, start_ms, end_ms, conn) -> dict:
    step_count = len(trace.steps)

    # 1. 转换 AgentStep
    client_steps = []
    for i, step in enumerate(trace.steps):
        ts = start_ms + int((end_ms - start_ms) * i / max(step_count, 1))
        client_steps.append({
            "node_name": step.node_name,
            "node_name_display": NODE_NAME_DISPLAY.get(step.node_name, step.node_name),
            "input_summary": step.input_summary,
            "output_summary": step.output_summary,
            "llm_calls": step.llm_calls,
            "timestamp_ms": ts,
        })

    # 2. 转换 NarrativePhase → Phase（含 evidence 查询）
    evidence_index: dict[int, int] = {}  # local_id → phase_index
    client_phases = []
    for idx, phase in enumerate(trace.phases, 1):
        msgs = db.get_messages_by_ids(conn, talker_id, phase.evidence_msg_ids)
        evidence_msgs = [msg_to_client(m, phase_index=idx) for m in msgs]
        for m in evidence_msgs:
            evidence_index[m["local_id"]] = idx
        client_phases.append({
            "phase_index": idx,                              # NarrativePhase 无此字段，枚举生成
            "phase_title": phase.phase_title,
            "time_range": phase.time_range,
            "core_conclusion": phase.core_conclusion,
            "evidence": evidence_msgs,                       # list[Message]，非 list[int]
            "reasoning_chain": phase.reasoning_chain,
            "uncertainty_note": phase.uncertainty_note or None,  # "" → null
            "verified": phase.verified,
        })

    # 3. 构建 all_messages（全量，证据消息带 phase_index）
    all_raw = db.get_all_messages(conn, talker_id)
    all_messages = [
        msg_to_client(m, phase_index=evidence_index.get(m.local_id))
        for m in all_raw
    ]

    return {
        "conversation_id": talker_id,                        # 客户端期望此字段
        "question": trace.question,
        "phases": client_phases,
        "agent_trace": {
            "steps": client_steps,
            "total_llm_calls": trace.total_llm_calls,
            "total_duration_ms": end_ms - start_ms,          # 客户端期望此字段
        },
        "all_messages": all_messages,
    }

def msg_to_client(msg: RawMessage, phase_index: int | None = None) -> dict:
    result = {
        "local_id": msg.local_id,
        "create_time": msg.create_time,
        "is_send": msg.is_send,
        "sender_display": "我" if msg.is_send else msg.sender_username,
        "parsed_content": msg.parsed_content,
    }
    if phase_index is not None:
        result["phase_index"] = phase_index
    return result
```

#### `import --db <path> --file <json_path>`

```bash
uv run python -m narrative_mirror.cli_json import \
  --db data/mirror.db \
  --file /path/to/chat_export.json
```

**单文件导入格式**（详见第四节）

输出：导入后的 Session JSON（含 `build_status: "pending"`）

#### `build --db <path> --talker <id> --config config.yml [--chroma-dir dir]`

```bash
uv run python -m narrative_mirror.cli_json build \
  --db data/mirror.db \
  --talker wxid_xxx \
  --config config.yml
```

运行完整流水线：`build_layer1()` → `compute_all_metadata()` → `detect_anomalies()` → （可选）`build_layer2()`

输出：`{"status": "complete", "talker_id": "wxid_xxx"}`

---

## 四、导入文件格式规范（单文件）

### 4.1 格式定义

客户端上传的 JSON 文件，格式如下：

```json
{
  "display_name": "张经理",
  "talker_id": "wxid_xxx",
  "messages": [
    {
      "localId": 1,
      "createTime": 1704000000000,
      "isSend": 1,
      "senderUsername": "user_self",
      "parsedContent": "消息内容",
      "localType": 1
    }
  ]
}
```

**字段说明**：
- `display_name`：必填，显示名称
- `talker_id`：选填；若无，则 `md5(display_name + messages[0].createTime)[:8]` 生成
- `messages[].localId`：必填，会话内唯一整数
- `messages[].createTime`：必填；若值 < 10^10，视为秒单位自动乘以 1000
- `messages[].isSend`：必填，1=自己发送，0=对方发送
- `messages[].senderUsername`：选填，发送者用户名
- `messages[].parsedContent`：必填，消息文本
- `messages[].localType`：选填，默认 1；10000/10002 为系统消息（自动标记 excluded=True）

### 4.2 WeFlow 格式兼容（可选）

如果用户直接提供 WeFlow 导出的两个文件，也可通过以下方式合并调用：
```bash
# 不通过 ImportModal，直接运行已有的 build.py
uv run python -m narrative_mirror.build --talker <id> --source file \
  --messages-path messages.json --sessions-path sessions.json
```

---

## 五、客户端改动清单（narrative-mirror）

### 5.1 Tauri 侧 — Shell 插件集成

**`src-tauri/Cargo.toml`** — 新增依赖：
```toml
tauri-plugin-shell = "2"
tauri-plugin-dialog = "2"  # 用于文件选择对话框（导入功能）
```

**`src-tauri/src/lib.rs`** — 注册插件：
```rust
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_dialog::init())  // 可选，用于文件对话框
    .setup(|app| { ... })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
```

**`src-tauri/capabilities/default.json`** — 声明权限：
```json
{
  "identifier": "default",
  "description": "Default capabilities",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "shell:allow-execute",
    "shell:allow-spawn",
    "dialog:allow-open"
  ]
}
```

**`package.json`** — 新增 npm 包：
```bash
npm install @tauri-apps/plugin-shell @tauri-apps/plugin-dialog
```

### 5.2 `src/api.ts` — 新文件（完整实现）

```typescript
import { Command } from '@tauri-apps/plugin-shell';
import { Session, Message, QueryResponse } from './types';

// 配置路径（可由用户设置，先用固定值）
const DB_PATH = 'data/mirror.db';
const CONFIG_PATH = 'config.yml';
const UV_CMD = 'uv';  // 需在 Tauri 权限中声明

async function runCli<T>(args: string[]): Promise<T> {
  const cmd = Command.create(UV_CMD, [
    'run', 'python', '-m', 'narrative_mirror.cli_json',
    ...args
  ]);
  const output = await cmd.execute();
  if (output.code !== 0) {
    throw new Error(`CLI error: ${output.stderr}`);
  }
  return JSON.parse(output.stdout) as T;
}

export async function listSessions(): Promise<Session[]> {
  return runCli<Session[]>(['list_sessions', '--db', DB_PATH]);
}

export async function getMessages(talkerId: string): Promise<Message[]> {
  return runCli<Message[]>(['get_messages', '--db', DB_PATH, '--talker', talkerId]);
}

export async function queryNarrative(
  talkerId: string,
  question: string
): Promise<QueryResponse> {
  return runCli<QueryResponse>([
    'query',
    '--db', DB_PATH,
    '--talker', talkerId,
    '--question', question,
    '--config', CONFIG_PATH,
  ]);
}

export async function importData(filePath: string): Promise<Session> {
  return runCli<Session>(['import', '--db', DB_PATH, '--file', filePath]);
}

// build 以 spawn（非阻塞）方式执行，立即返回，后台运行
export async function triggerBuild(talkerId: string): Promise<void> {
  const cmd = Command.create(UV_CMD, [
    'run', 'python', '-m', 'narrative_mirror.cli_json',
    'build', '--db', DB_PATH, '--talker', talkerId, '--config', CONFIG_PATH,
  ]);
  await cmd.spawn();  // 非阻塞，后台运行
}
```

### 5.3 `src/App.tsx` — 替换所有 Mock 数据

**需要修改的部分**：

**① 初始化会话列表**：
```typescript
// 旧
const [sessions, setSessions] = useState<Session[]>(sessionsMock);

// 新
const [sessions, setSessions] = useState<Session[]>([]);
useEffect(() => {
  api.listSessions().then(setSessions).catch(console.error);
}, []);
```

**② 选中会话时加载消息**：
```typescript
// 旧（在 App.tsx 或 MainArea.tsx）
// workMessages 只在 mock_talker_002 有数据

// 新
const [sessionMessages, setSessionMessages] = useState<Message[]>([]);
const handleSelectSession = (session: Session) => {
  setActiveSession(session);
  setQueryResult(null);
  setSessionMessages([]);
  api.getMessages(session.talker_id).then(setSessionMessages).catch(console.error);
};
```

**③ 查询**：
```typescript
// 旧（在 handleQuery 中，由 MainArea 的 handleAnalysisComplete 调用）
setQueryResult(queryWorkMock);

// 新（改为在 MainArea 中直接调用 api，详见 5.4）
```

**④ Build status 轮询**：
```typescript
// 导入后，后台监听 build_status 变化
const pollBuildStatus = (talkerId: string) => {
  const interval = setInterval(async () => {
    const updated = await api.listSessions();
    const session = updated.find(s => s.talker_id === talkerId);
    if (session) {
      setSessions(updated);
      if (session.build_status === 'complete') {
        clearInterval(interval);
        // 自动加载消息
        setSessionMessages(await api.getMessages(talkerId));
      }
    }
  }, 3000); // 每3秒轮询
};
```

### 5.4 `src/components/MainArea.tsx` — 修复异步查询顺序

**最重要的修改**：将串行查询改为并发查询。

**修改前（有问题）**：
```typescript
const handleSubmit = (e: React.FormEvent) => {
  e.preventDefault();
  setQueryState('analyzing');
  // 动画播10s后才调用后端
};

const handleAnalysisComplete = () => {
  onQuery(query);  // 这里才调用
  setQueryState('complete');
};
```

**修改后（正确）**：
```typescript
// 1. 移除 onQuery prop，改为直接接收 queryNarrative 函数
// 2. handleSubmit 立即发起 API 调用

const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();
  if (!query.trim() || !activeSession) return;

  setQueryState('analyzing');
  setIsReviewMode(true);

  try {
    // 并发：动画 + 真实 API 调用同时进行
    const result = await api.queryNarrative(activeSession.talker_id, query);
    // API 返回后，如果动画还在播，等动画结束才能 setQueryState('complete')
    // 可通过 ref 标记 result 已就绪，让 handleAnalysisComplete 消费
    pendingResult.current = result;
  } catch (err) {
    setQueryState('idle');
    // 显示错误提示
  }
};

const handleAnalysisComplete = () => {
  if (pendingResult.current) {
    // 动画结束时 API 已返回
    onResultReady(pendingResult.current);
    setQueryState('complete');
  } else {
    // 动画结束但 API 还未返回：继续等
    setQueryState('waiting');  // 可选中间状态，或保持 analyzing
  }
};
```

**同时需要修改第 141 行**，移除对 mock 的硬编码：
```typescript
// 旧
<AgentProgress steps={queryWorkMock.agent_trace.steps} onComplete={handleAnalysisComplete} />

// 新（使用固定的节点名称，不依赖 mock）
const DEFAULT_STEPS = [
  { node_name: 'planner',   node_name_display: '意图解析', ... },
  { node_name: 'retriever', node_name_display: '检索锚点与节点', ... },
  { node_name: 'grader',    node_name_display: '证据评估', ... },
  { node_name: 'generator', node_name_display: '叙事生成', ... },
];
<AgentProgress steps={DEFAULT_STEPS} onComplete={handleAnalysisComplete} />
```

### 5.5 `src/components/ImportModal.tsx` — 调用真实后端

**当前逻辑（纯前端 mock）**：
```typescript
handleSubmit → sleep(1500) → onImport(fake_session)
```

**修改后逻辑**：
```typescript
handleSubmit = async () => {
  setIsProcessing(true);

  try {
    // 1. 获取文件路径（使用 Tauri 文件对话框，或从已上传的文件读取路径）
    const filePath = selectedFilePath;  // 通过 tauri-plugin-dialog 获取

    // 2. 调用后端 import（快速，只写 SQLite）
    const session = await api.importData(filePath);

    // 3. 通知父组件（添加到列表）
    onImport(session);

    // 4. 触发后台构建（非阻塞）
    await api.triggerBuild(session.talker_id);

    // 5. 关闭 Modal，父组件开始轮询 build_status
    onClose();

  } catch (err) {
    setError('导入失败：' + err.message);
  } finally {
    setIsProcessing(false);
  }
};
```

**ImportModal 的文件选择改造**：

当前 ImportModal 使用 HTML drag-and-drop/input，读取文件内容到内存。但 `cli_json import` 需要的是文件路径而非内容。

**两个选项**：
- **选项 A（推荐）**：用 `tauri-plugin-dialog` 的 `open()` 返回文件路径，直接传给后端。优点：简单，不需要写临时文件。
- **选项 B**：保留前端文件读取，后端 `import` 命令支持从 stdin 读取（`--file -`）。稍复杂但更灵活。

建议先实现选项 A，用 `@tauri-apps/plugin-dialog` 弹出原生文件选择框替换现有 drag-and-drop。

---

## 六、功能实现优先级

### Phase 1 — 核心连通（会话列表 + 消息 + 查询）

| 步骤 | 文件 | 改动说明 |
|------|------|----------|
| 1 | `narrarc/src/narrative_mirror/db.py` | 新增 `get_talkers_with_stats()`、`get_build_status()` |
| 2 | `narrarc/src/narrative_mirror/cli_json.py` | 新建，实现 `list_sessions`、`get_messages`、`query` 三个命令 |
| 3 | `narrative-mirror/src-tauri/Cargo.toml` | 添加 `tauri-plugin-shell = "2"` |
| 4 | `narrative-mirror/src-tauri/src/lib.rs` | 注册 shell plugin |
| 5 | `narrative-mirror/src-tauri/capabilities/default.json` | 声明 shell 权限 |
| 6 | `narrative-mirror/package.json` | `npm install @tauri-apps/plugin-shell` |
| 7 | `narrative-mirror/src/api.ts` | 新建，实现 `listSessions`、`getMessages`、`queryNarrative` |
| 8 | `narrative-mirror/src/App.tsx` | 替换 sessions、messages、query 的 Mock 数据源 |
| 9 | `narrative-mirror/src/components/MainArea.tsx` | 修复异步查询顺序；移除 `queryWorkMock` 硬编码 |

### Phase 2 — 导入与构建

| 步骤 | 文件 | 改动说明 |
|------|------|----------|
| 10 | `narrarc/src/narrative_mirror/cli_json.py` | 新增 `import`、`build` 子命令 |
| 11 | `narrative-mirror/src-tauri/Cargo.toml` | 添加 `tauri-plugin-dialog = "2"` |
| 12 | `narrative-mirror/src/api.ts` | 新增 `importData()`、`triggerBuild()` |
| 13 | `narrative-mirror/src/App.tsx` | 新增 build_status 轮询逻辑 |
| 14 | `narrative-mirror/src/components/ImportModal.tsx` | 替换为真实后端调用 + 文件对话框 |

### Phase 3 — 完善（可选）

| 步骤 | 说明 |
|------|------|
| 错误处理 | API 失败时显示错误提示 |
| 配置界面 | 让用户设置 DB 路径、config.yml 路径 |
| Build 进度流 | 实时显示构建进度（需要 stdout 流式读取）|

---

## 七、格式速查（types.ts 完整对应）

### 后端输出 → 客户端接收，字段映射对照表

| 客户端字段 | 来源 | 转换说明 |
|-----------|------|----------|
| `Session.talker_id` | `raw_messages.talker_id` | 直接 |
| `Session.display_name` | `raw_messages` 中 `is_send=0` 的首个 `sender_username` | fallback 为 talker_id |
| `Session.last_timestamp` | `MAX(raw_messages.create_time)` | 直接（已是 ms）|
| `Session.message_count` | `COUNT(*)` by talker_id | 直接 |
| `Session.build_status` | `get_build_status()` 推断 | pending/in_progress/complete |
| `Message.local_id` | `raw_messages.local_id` | 直接 |
| `Message.sender_display` | `raw_messages.is_send` + `sender_username` | `is_send=True` → `"我"` |
| `Message.phase_index` | 来自 Phase.evidence 倒推 | 仅证据消息有此字段 |
| `QueryResponse.conversation_id` | `talker_id` | 直接 |
| `QueryResponse.agent_trace.total_duration_ms` | cli_json 计时 | `end_ms - start_ms` |
| `Phase.phase_index` | 枚举 | `NarrativePhase` 无此字段，enumerate(phases, 1) |
| `Phase.evidence` | `get_messages_by_ids(evidence_msg_ids)` | list[RawMessage] → list[Message] |
| `Phase.uncertainty_note` | `NarrativePhase.uncertainty_note` | `""` → `null` |
| `AgentStep.node_name_display` | 静态映射表 | `NODE_NAME_DISPLAY[node_name]` |
| `AgentStep.timestamp_ms` | cli_json 计时 | 按步骤均匀分配总时长 |
