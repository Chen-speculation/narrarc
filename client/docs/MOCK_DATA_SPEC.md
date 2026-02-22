# Narrative Mirror 客户端 Mock 数据规范

本文档说明 Narrative Mirror 桌面客户端当前 Mock 的数据结构与用途，供后端接口设计与联调参考。

---

## 1. Session（会话列表）

**数据源**：`src/mocks/data.ts` → `sessionsMock`

**用途**：侧边栏展示的会话列表，每个会话代表一个对话对象（如微信联系人）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `talker_id` | string | 会话唯一标识（如微信 talker_id） |
| `display_name` | string | 显示名称 |
| `last_timestamp` | number | 最后一条消息时间戳（毫秒） |
| `build_status` | `'pending' \| 'in_progress' \| 'complete'` | 索引构建状态 |
| `message_count` | number | 消息总数 |

**当前 Mock 数据**：4 条固定会话
- `mock_talker_002` - 张经理（唯一有聊天记录）
- `doctor_001` - 李医生
- `teacher_001` - 王老师
- `mock_talker_001` - TA

**后端需提供**：
- 会话列表 API（支持分页/筛选）
- 或与数据源同步的会话元数据

---

## 2. Message（聊天记录）

**数据源**：`src/mocks/data.ts` → `workMessages`（由 `generateWorkMessages()` 生成）

**用途**：聊天面板展示的原始消息流，以及 Query 结果中的证据引用。

| 字段 | 类型 | 说明 |
|------|------|------|
| `local_id` | number | 消息在会话内的本地 ID |
| `create_time` | number | 消息时间戳（毫秒） |
| `is_send` | boolean | 是否为自己发送 |
| `sender_username` | string? | 发送者用户名（可选） |
| `sender_display` | string | 发送者显示名 |
| `parsed_content` | string | 消息正文（纯文本） |
| `phase_index` | number? | 所属叙事阶段（仅证据消息有） |

**当前 Mock 逻辑**：
- 125 条消息，基于随机 filler 文本生成
- 其中 9 条为「证据消息」，注入到固定 `local_id` 位置，用于叙事弧展示
- 仅 `talker_id === 'mock_talker_002'` 时展示聊天记录；其他会话无消息

**后端需提供**：
- 按 `talker_id` 查询消息列表 API
- 支持按时间范围、分页
- 消息格式与上述结构兼容

---

## 3. Agent（查询 / 叙事生成）

### 3.1 Query 请求

**触发**：用户在输入框输入问题并提交（如「我们这个工作进展怎么样了？」）

**当前 Mock**：`App.tsx` 中 `handleQuery` 直接返回 `queryWorkMock`，无真实 API 调用。

**预期请求**（需后端实现）：
- 方法：`POST`
- 参数：`talker_id`、`question`
- 返回：`QueryResponse`（见下）

### 3.2 QueryResponse（查询结果）

**数据源**：`src/mocks/data.ts` → `queryWorkMock`

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | string | 会话/对话 ID |
| `question` | string | 用户问题 |
| `phases` | Phase[] | 叙事阶段列表 |
| `agent_trace` | AgentTrace | Agent 执行轨迹 |
| `all_messages` | Message[] | 该会话全部消息（用于右侧聊天面板） |

### 3.3 Phase（叙事阶段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `phase_index` | number | 阶段序号 |
| `phase_title` | string | 阶段标题 |
| `time_range` | string | 时间范围描述 |
| `core_conclusion` | string | 核心结论 |
| `evidence` | Message[] | 证据消息列表 |
| `reasoning_chain` | string | 推理链简述 |
| `uncertainty_note` | string \| null | 不确定性说明 |
| `verified` | boolean | 是否已验证 |

### 3.4 AgentTrace（Agent 执行轨迹）

| 字段 | 类型 | 说明 |
|------|------|------|
| `steps` | AgentStep[] | 执行步骤列表 |
| `total_llm_calls` | number | LLM 调用总次数 |
| `total_duration_ms` | number | 总耗时（毫秒） |

### 3.5 AgentStep（单步）

| 字段 | 类型 | 说明 |
|------|------|------|
| `node_name` | string | 节点标识（如 `planner`、`retriever`） |
| `node_name_display` | string | 显示名称（如「意图解析」） |
| `input_summary` | string | 输入摘要 |
| `output_summary` | string | 输出摘要 |
| `llm_calls` | number | 本步 LLM 调用次数 |
| `timestamp_ms` | number | 时间戳 |

**当前 Mock 的 Agent 步骤**：
1. `planner` - 意图解析
2. `retriever` - 检索锚点与节点
3. `grader` - 证据评估
4. `generator` - 叙事生成

---

## 4. Import（导入）

**数据源**：`src/components/ImportModal.tsx`

**当前 Mock 逻辑**：
- 支持 JSON 文件上传或粘贴文本
- 解析 JSON 时尝试读取 `name`、`messages`
- 创建新 Session：`talker_id: imported_${Date.now()}`，`build_status: 'pending'`
- **不调用后端**：无真实导入、索引构建、持久化

**后端需提供**：
- 导入 API：接收聊天记录（JSON/文件），返回 `talker_id` 或 Session
- 索引构建状态查询（`build_status` 轮询或 WebSocket）

---

## 5. AgentProgress 动画日志（纯前端）

**数据源**：`src/components/AgentProgress.tsx` → `stepLogs`

在「分析中」阶段展示的终端风格日志为**硬编码**，与真实 Agent 无关：

```ts
[
  ["[SYS] INITIALIZING PLANNER...", "PARSING USER INTENT", ...],
  ["[SYS] SCANNING LOCAL DB...", "MATCH FOUND: local_id 15", ...],
  ["[SYS] EVALUATING EVIDENCE", "EVIDENCE VALIDATED"],
  ["[SYS] GENERATING NARRATIVE", "COMPLETE"]
]
```

可保留为 UI 动画，或后续改为消费真实 Agent 的流式/增量日志。

---

## 6. 类型定义位置

所有类型定义在 `src/types.ts`：

- `Session`
- `Message`
- `Phase`
- `AgentStep`
- `AgentTrace`
- `QueryResponse`
- `BuildStatus`

---

## 7. 后端接口清单（待实现）

| 接口 | 方法 | 说明 |
|------|------|------|
| 会话列表 | GET | 返回 `Session[]` |
| 消息列表 | GET | 按 `talker_id` 返回 `Message[]` |
| 查询/叙事 | POST | `{ talker_id, question }` → `QueryResponse` |
| 导入 | POST | 上传聊天记录 → 返回 `Session` 或 `talker_id` |
| 构建状态 | GET/WS | 按 `talker_id` 查询 `build_status` |

具体路径、鉴权、错误码等需结合 narrarc 后端工程另行约定。
