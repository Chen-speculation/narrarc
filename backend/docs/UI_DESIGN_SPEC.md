# 叙事镜（Narrative Mirror）前端 UI 设计规范

**版本**：V1.0  
**目标读者**：前端 UI 设计师  
**更新日期**：2026年2月

---

## 一、产品核心与设计原则

### 1.1 一句话定义

叙事镜在用户本地设备上运行，**AI 全面接管用户的聊天记录**。用户随手问任意问题——如「我们这个工作进展怎么样了？」「我和医生上一次讲到的我母亲的身体情况，具体是什么样的？」「我和老师上次讲到的数学成绩是什么样的？」——系统都能在聊天记录中找到**佐证和关键证据**，输出清晰的阶段、核心结论、多条原始消息铁证、推理链、不确定性说明。用户可编辑，最终导出「我的最终版本」。

**核心能力**：不是预设某类问题（如恋爱关系），而是**任意问题 + 任意对话对象**，系统都能从对应聊天中精准抓取证据。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **证据可追溯** | 每个叙事阶段的结论必须可点击跳转到原始聊天记录，用户可验证 |
| **AI 透明** | 展示 Agent 的思考与检索过程，让用户理解系统如何得出结论 |
| **用户是作者** | 提供编辑、删减、排序、标「不认同」等控件，AI 只提供建议骨架 |
| **不阻塞用户** | 导入后秒级展示时间线，后台构建不阻塞主流程 |
| **本地优先** | 数据 100% 不离开设备，UI 需传达安全感 |

---

## 二、完整用户流程与页面结构

### 2.1 流程总览

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  1. 导入聊天    │ →  │  2. 选择对话    │ →  │  3. 提问        │ →  │  4. 叙事弧展示  │
│  上传/连接      │    │  查看构建状态   │    │  输入问题       │    │  阶段卡片+证据  │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
                                                                              │
                                                                              ▼
┌─────────────────┐    ┌─────────────────┐
│  6. 导出/分享   │ ←  │  5. 追问/编辑   │
│  我的最终版本   │    │  继续提问/修改  │
└─────────────────┘    └─────────────────┘
```

### 2.2 各阶段 UI 要点

| 阶段 | 核心任务 | UI 要点 |
|------|----------|---------|
| **1. 导入** | 用户上传 JSON 文件或连接 WeFlow | 拖拽上传区、进度条、导入完成提示 |
| **2. 选择对话** | 展示会话列表，显示构建状态 | 会话卡片、「✓ 可深度查询」标记、后台构建进度 |
| **3. 提问** | 用户输入自然语言问题 | 输入框、建议问题模板、历史问题 |
| **4. 叙事弧展示** | 展示 4–8 个阶段卡片，每张卡片可展开证据 | 时间轴/阶段卡片、证据消息可点击、推理链折叠 |
| **5. 追问/编辑** | 用户可追问、编辑卡片、标不认同 | 追问输入、编辑控件、证据增删 |
| **6. Agent 轨迹** | 展示系统检索与推理过程 | 可折叠的「系统如何找到答案」面板 |

---

## 三、API 响应结构与 MOCK 数据约定

> **重要**：后端接口尚未实现。设计师需基于以下 RESPONSE 结构进行 MOCK，确保 UI 与未来 API 一致。

### 3.1 会话列表 API

**请求**：`GET /api/sessions`

**响应结构**：

```json
{
  "sessions": [
    {
      "talker_id": "string",
      "display_name": "string",
      "last_timestamp": 1234567890000,
      "build_status": "pending" | "in_progress" | "complete",
      "message_count": 120
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `build_status` | enum | `pending`=未开始构建，`in_progress`=后台构建中，`complete`=可查询 |
| `message_count` | int | 该对话的消息总数 |

---

### 3.2 查询 API（核心）

**请求**：`POST /api/query`

```json
{
  "talker_id": "string",
  "question": "string",
  "conversation_id": "string | null"
}
```

| 字段 | 说明 |
|------|------|
| `conversation_id` | 可选，用于追问时关联上一轮对话 |

**响应结构**：

```json
{
  "conversation_id": "string",
  "question": "string",
  "phases": [
    {
      "phase_index": 1,
      "phase_title": "string",
      "time_range": "string",
      "core_conclusion": "string",
      "evidence": [
        {
          "local_id": 1,
          "create_time": 1678457400000,
          "is_send": true,
          "sender_display": "我",
          "parsed_content": "string",
          "phase_index": 1
        }
      ],
      "reasoning_chain": "string",
      "uncertainty_note": "string",
      "verified": true
    }
  ],
  "agent_trace": {
    "steps": [
      {
        "node_name": "planner" | "retriever" | "grader" | "explorer" | "generator",
        "node_name_display": "string",
        "input_summary": "string",
        "output_summary": "string",
        "llm_calls": 1,
        "timestamp_ms": 1234567890000
      }
    ],
    "total_llm_calls": 5,
    "total_duration_ms": 12000
  },
  "all_messages": [
    {
      "local_id": 1,
      "create_time": 1678457400000,
      "is_send": true,
      "sender_username": "string",
      "sender_display": "我",
      "parsed_content": "string"
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `phases` | 叙事阶段列表，每个阶段含证据消息 |
| `evidence` | 该阶段引用的 3–5 条消息，需与 `all_messages` 中的 `local_id` 对应 |
| `agent_trace` | Agent 执行轨迹，用于「系统如何找到答案」面板 |
| `all_messages` | 该对话的完整消息列表，用于证据点击跳转 |

---

### 3.3 消息按 ID 查询（证据跳转用）

**请求**：`GET /api/messages?talker_id=xxx&local_ids=1,2,3,5,8`

**响应**：返回 `all_messages` 中对应 `local_id` 的子集。若前端已缓存 `all_messages`，可无需此接口，直接在前端过滤。

---

## 四、MOCK 数据要求与合成指引

### 4.0 核心要求：100+ 条消息 + 多场景覆盖

**MOCK 数据必须至少包含 100 条以上聊天记录**，才能充分体现叙事镜的优越性：

- 短对话（如 20 条）难以展示系统从长程、散乱记录中**准确抓取证据**的能力
- 100+ 条消息让 UI 设计有足够的滚动、筛选、证据高亮等交互空间
- **叙事镜不是预设某类问题**（如恋爱关系），而是**任意问题都能从对应聊天中找证据**

### 4.0.1 必须覆盖的四种 Case（每个都要有 MOCK）

设计师需为以下**四类典型问题**分别准备 MOCK 数据，体现「随手问、AI 都能找到佐证」：

| Case | 用户问题 | 对话对象 | 数据要求 |
|------|----------|----------|----------|
| **Case 1** | 我们这个工作进展怎么样了？ | 老板/同事 | 100+ 条工作相关聊天（任务、汇报、进度、反馈） |
| **Case 2** | 我和医生上一次讲到的我母亲的身体情况，具体是什么样的？ | 医生 | 100+ 条就医/咨询聊天（检查结果、用药、复查、母亲病情） |
| **Case 3** | 我和老师上次讲到的数学成绩是什么样的？ | 老师 | 100+ 条家校沟通（成绩、作业、考试、进步/退步） |
| **Case 4** | 我们是怎么一步步分手的？ | 恋人/TA | 100+ 条情感聊天（关系演进、冲突、仪式变化等） |

**每个 Case 对应一个会话（talker_id）**，每个会话至少 100 条消息。`sessions.json` 中应包含 4 个会话；`query_response` 需为每种问题各准备一份，结构相同、内容不同。

### 4.0.2 合成指引（给懂数据合成的设计师）

若你自行合成 MOCK 数据，请满足：

1. **数量**：每个会话的 `all_messages` 至少 100 条，建议 120–150 条
2. **场景覆盖**：必须包含上述四种 Case（工作、医生、老师、恋爱关系演进），**尽可能兼顾全部**
3. **内容可检索**：在合成时有意植入可被检索的「关键证据」，例如：
   - 工作：具体任务名、进度、老板反馈、时间节点
   - 医生：母亲具体检查项目、指标、用药、复查时间
   - 老师：数学成绩、分数、排名、进步/退步描述
   - 恋爱：回复延迟变化、称呼变化、冲突事件、仪式消失等
4. **时间跨度**：建议覆盖数月，便于形成阶段划分

---

### 4.1 会话列表 MOCK（参考）

需包含至少 4 个会话，对应四种 Case：

```json
{
  "sessions": [
    {
      "talker_id": "boss_001",
      "display_name": "张经理",
      "last_timestamp": 1707922800000,
      "build_status": "complete",
      "message_count": 125
    },
    {
      "talker_id": "doctor_001",
      "display_name": "李医生",
      "last_timestamp": 1707800000000,
      "build_status": "complete",
      "message_count": 118
    },
    {
      "talker_id": "teacher_001",
      "display_name": "王老师",
      "last_timestamp": 1707500000000,
      "build_status": "complete",
      "message_count": 132
    },
    {
      "talker_id": "mock_talker_001",
      "display_name": "TA",
      "last_timestamp": 1707922800000,
      "build_status": "complete",
      "message_count": 129
    }
  ]
}
```

### 4.2 查询响应 MOCK（四种 Case 各需一份）

以下为**两种响应结构示例**，分别对应 Case 1（工作进展）与 Case 4（恋爱关系演进）。设计师需为四种问题各准备一份完整 MOCK，结构相同、`question` / `phases` / `all_messages` 内容适配各场景。

#### 4.2.1 示例一：Case 1 工作进展（我们这个工作进展怎么样了？）

```json
{
  "conversation_id": "conv_mock_work",
  "question": "我们这个工作进展怎么样了？",
  "phases": [
    {
      "phase_index": 1,
      "phase_title": "项目启动与任务分配",
      "time_range": "2024年1月",
      "core_conclusion": "张经理明确了 Q1 目标：完成 A 模块开发、B 接口联调。你承诺 1 月底前交付初版。",
      "evidence": [
        {
          "local_id": 2,
          "create_time": 1704067200000,
          "is_send": false,
          "sender_display": "张经理",
          "parsed_content": "小陈，Q1 重点是把 A 模块做出来，B 接口和下游联调也要跟上",
          "phase_index": 1
        },
        {
          "local_id": 5,
          "create_time": 1704153600000,
          "is_send": true,
          "sender_display": "我",
          "parsed_content": "好的，A 模块我计划 1 月底前出初版",
          "phase_index": 1
        },
        {
          "local_id": 7,
          "create_time": 1704240000000,
          "is_send": false,
          "sender_display": "张经理",
          "parsed_content": "行，有进展随时同步",
          "phase_index": 1
        }
      ],
      "reasoning_chain": "任务分配 + 时间承诺 + 确认 → 项目启动阶段，目标清晰。",
      "uncertainty_note": null,
      "verified": true
    },
    {
      "phase_index": 2,
      "phase_title": "中期推进与阻塞",
      "time_range": "2024年2月",
      "core_conclusion": "A 模块开发完成 70%，但 B 接口联调因下游延期受阻。张经理要求先内部自测，等下游就绪再联调。",
      "evidence": [
        {
          "local_id": 9,
          "create_time": 1706745600000,
          "is_send": true,
          "sender_display": "我",
          "parsed_content": "张经理，A 模块大概完成 70% 了，但 B 接口那边说他们还没准备好",
          "phase_index": 2
        },
        {
          "local_id": 10,
          "create_time": 1706832000000,
          "is_send": false,
          "sender_display": "张经理",
          "parsed_content": "你先内部自测，B 接口等下游好了再说，别卡在这",
          "phase_index": 2
        },
        {
          "local_id": 12,
          "create_time": 1706918400000,
          "is_send": false,
          "sender_display": "张经理",
          "parsed_content": "周五前把自测报告发我",
          "phase_index": 2
        }
      ],
      "reasoning_chain": "进度汇报 + 阻塞说明 + 经理调整策略 → 中期推进，有依赖但已明确应对。",
      "uncertainty_note": "下游具体何时就绪未在对话中明确。",
      "verified": true
    },
    {
      "phase_index": 3,
      "phase_title": "当前状态与下一步",
      "time_range": "2024年2月中",
      "core_conclusion": "自测已完成，张经理反馈「整体不错，有几处小问题」。要求下周修复后提测，预计 2 月底可上线。",
      "evidence": [
        {
          "local_id": 15,
          "create_time": 1707922800000,
          "is_send": true,
          "sender_display": "我",
          "parsed_content": "自测报告已发，您看下",
          "phase_index": 3
        },
        {
          "local_id": 16,
          "create_time": 1707926400000,
          "is_send": false,
          "sender_display": "张经理",
          "parsed_content": "整体不错，有几处小问题我标红了，你下周修一下",
          "phase_index": 3
        },
        {
          "local_id": 18,
          "create_time": 1707930000000,
          "is_send": false,
          "sender_display": "张经理",
          "parsed_content": "修完提测，顺利的话 2 月底能上",
          "phase_index": 3
        }
      ],
      "reasoning_chain": "自测完成 + 经理反馈 + 时间节点 → 当前状态清晰，下一步明确。",
      "uncertainty_note": null,
      "verified": true
    }
  ],
  "agent_trace": {
    "steps": [
      {
        "node_name": "planner",
        "node_name_display": "意图解析",
        "input_summary": "用户问题：我们这个工作进展怎么样了？",
        "output_summary": "解析为 progress_summary，关注：任务、进度、反馈、时间节点",
        "llm_calls": 1,
        "timestamp_ms": 1707922810000
      },
      {
        "node_name": "retriever",
        "node_name_display": "检索锚点与节点",
        "input_summary": "按任务/进度/反馈查询相关消息",
        "output_summary": "命中任务分配、进度汇报、经理反馈等关键节点",
        "llm_calls": 0,
        "timestamp_ms": 1707922812000
      },
      {
        "node_name": "grader",
        "node_name_display": "证据评估",
        "input_summary": "已收集节点，覆盖 2024.01 - 2024.02",
        "output_summary": "信息充足，可生成进展摘要",
        "llm_calls": 1,
        "timestamp_ms": 1707922815000
      },
      {
        "node_name": "generator",
        "node_name_display": "叙事生成",
        "input_summary": "节点摘要 + 消息预览",
        "output_summary": "生成 3 个阶段（启动、中期、当前），证据验证通过",
        "llm_calls": 1,
        "timestamp_ms": 1707922820000
      }
    ],
    "total_llm_calls": 3,
    "total_duration_ms": 10000
  },
  "all_messages": [
    {"local_id": 1, "create_time": 1704067200000, "is_send": false, "sender_display": "张经理", "parsed_content": "小陈，Q1 重点是把 A 模块做出来，B 接口和下游联调也要跟上"},
    {"local_id": 2, "create_time": 1704153600000, "is_send": true, "sender_display": "我", "parsed_content": "好的，A 模块我计划 1 月底前出初版"},
    {"local_id": 3, "create_time": 1704240000000, "is_send": false, "sender_display": "张经理", "parsed_content": "行，有进展随时同步"},
    {"local_id": 4, "create_time": 1706745600000, "is_send": true, "sender_display": "我", "parsed_content": "张经理，A 模块大概完成 70% 了，但 B 接口那边说他们还没准备好"},
    {"local_id": 5, "create_time": 1706832000000, "is_send": false, "sender_display": "张经理", "parsed_content": "你先内部自测，B 接口等下游好了再说，别卡在这"},
    {"local_id": 6, "create_time": 1706918400000, "is_send": false, "sender_display": "张经理", "parsed_content": "周五前把自测报告发我"},
    {"local_id": 7, "create_time": 1707922800000, "is_send": true, "sender_display": "我", "parsed_content": "自测报告已发，您看下"},
    {"local_id": 8, "create_time": 1707926400000, "is_send": false, "sender_display": "张经理", "parsed_content": "整体不错，有几处小问题我标红了，你下周修一下"},
    {"local_id": 9, "create_time": 1707930000000, "is_send": false, "sender_display": "张经理", "parsed_content": "修完提测，顺利的话 2 月底能上"}
  ]
}
```

**说明**：上述 `all_messages` 为简化示例（9 条）。实际 MOCK 每个会话需 100+ 条，便于体现从长程记录中抓取证据的能力。

#### 4.2.2 示例二：Case 4 恋爱关系演进（我们是怎么一步步分手的？）

**推荐使用**：`docs/mock/query_response_120.json`（129 条消息，4 阶段叙事弧）

结构同上，`question` 为「我们是怎么一步步分手的？」，`phases` 示例：热恋期 → 第一道裂痕 → 冲突激化 → 仪式消失与终点。`evidence` 中体现回复延迟、称呼变化、冲突事件等关键证据。详见 `query_response_120.json`。

### 4.3 追问场景 MOCK（简化）

用户追问「B 接口具体什么时候能联调？」「张经理标红的是哪几处？」或「第一道裂痕具体是哪天开始的？」时，响应结构相同，`phases` 可能更聚焦于单阶段，`agent_trace.steps` 可能包含 `explorer` 节点（深度探索）。

---

## 五、新颖 UI 设计思路

### 5.1 叙事弧可视化：时间轴 + 阶段卡片

**创意点**：将叙事阶段呈现为**可交互的时间轴**，每个阶段是一个「节点」，节点之间用线连接，形成视觉上的「弧线」。点击节点展开该阶段的卡片。

- **时间轴**：横向或纵向，按 `time_range` 排布
- **节点样式**：可用颜色/大小暗示 `conflict_intensity` 或 `emotional_tone`（若后端提供）
- **证据高亮**：在时间轴下方的聊天记录流中，用不同颜色高亮各阶段引用的消息

### 5.2 证据与聊天记录的双向联动

**创意点**：阶段卡片中的每条证据可点击，点击后：

1. **右侧/下方聊天记录面板**自动滚动到对应 `local_id` 的消息位置
2. 该消息**高亮**（如边框、背景色）
3. 可选：在聊天记录中，被引用的消息旁显示小标签「阶段2·第一道裂痕」

反之，在聊天记录中点击某条消息，可显示「该消息被哪些阶段引用」。

### 5.3 Agent 轨迹的「侦探日志」风格

**创意点**：将 `agent_trace.steps` 设计成**可折叠的「侦探工作日志」**：

- 每个 step 是一个时间戳 + 节点名称 + 简短摘要的条目
- 默认折叠，展开后显示 `input_summary` 和 `output_summary`
- 视觉上像调查笔记：左侧时间线，右侧内容
- 文案示例：「意图解析 → 识别为关系演变类问题，关注回复延迟与冲突强度」

### 5.4 不确定性声明的前置展示

**创意点**：每个阶段卡片中，`uncertainty_note` 不应藏在底部，而应**与核心结论并置**：

- 用弱对比色或小字展示「不确定性：……」
- 传达「AI 承认局限」的透明感，符合产品调性

### 5.5 构建状态的「相册式」隐喻

**创意点**：参考 init.md 中的手机相册类比：

- 导入完成 → 显示「原始时间线」缩略图（按日期分组的消息预览）
- 构建中 → 显示进度条 + 「正在分析对话结构，请稍候」
- 构建完成 → 会话卡片出现「✓ 可深度查询」徽章，可点击进入提问

### 5.6 追问的对话式布局

**创意点**：追问时采用**对话式布局**：

- 用户问题 + 系统回答（叙事弧）为一组
- 追问时，新问题追加在下方，新回答可**对比展示**（如并排或折叠切换）
- 保留 `conversation_id`，便于后端关联多轮

### 5.7 编辑控件的轻量化

**创意点**：每张阶段卡片提供：

- **编辑**：修改 `phase_title`、`core_conclusion`（内联编辑或弹窗）
- **证据**：删/加证据（从 `all_messages` 中勾选）
- **不认同**：标记「我不认同此解读」，该阶段卡片灰显或折叠，导出时可选排除

---

## 六、页面与组件清单

| 页面/组件 | 职责 | 依赖 MOCK |
|-----------|------|-----------|
| 导入页 | 上传 JSON / 连接 WeFlow，展示导入进度 | 无（本地操作） |
| 会话列表 | 展示 sessions，构建状态，点击进入对话 | `GET /api/sessions` |
| 对话主视图 | 左侧/上方：提问区 + 叙事弧；右侧/下方：聊天记录 | `POST /api/query` 完整响应 |
| 阶段卡片 | 展示单阶段：标题、结论、证据、推理链、不确定性、编辑控件 | `phases[]` |
| 证据消息条 | 单条证据，可点击跳转 | `evidence[]` |
| 聊天记录流 | 按时间展示 all_messages，支持高亮被引用消息 | `all_messages` |
| Agent 轨迹面板 | 可折叠，展示 agent_trace.steps | `agent_trace` |
| 追问输入 | 输入框 + 发送，关联 conversation_id | `POST /api/query` |

---

## 七、文案与术语

| 术语 | 推荐文案 | 说明 |
|------|----------|------|
| 叙事弧 | 叙事弧 / 故事线 | 4–8 个阶段的整体 |
| 阶段 | 阶段 N：xxx | 如「阶段1：热恋期」 |
| 证据 | 关键证据 | 3–5 条原始消息 |
| 推理链 | 推理链 | AI 如何得出结论 |
| 不确定性 | 不确定性 | AI 承认的局限 |
| 验证状态 | ✓ 已验证 / ✗ 待核实 | 证据是否通过校验 |
| Agent 轨迹 | 系统如何找到答案 | 面向用户的友好表述 |

---

## 八、参考资料

- **产品与技术文档**：`init.md`（含完整 Demo Case）
- **Agentic 改造设计**：`REALTALK/improve`（多节点工作流、Agent 轨迹）
- **OpenSpec 规范**：`openspec/specs/query-pipeline/spec.md`、`openspec/changes/agentic-query-reform/specs/graph-workflow/spec.md`

---

## 九、MOCK 数据文件

项目已提供以下 MOCK 文件，可直接用于前端开发：

| 文件 | 路径 | 说明 |
|------|------|------|
| 会话列表 | `docs/mock/sessions.json` | 含 4 个会话（工作/医生/老师/恋爱，各 100+ 条消息） |
| 查询响应-工作 | `docs/mock/query_response_work.json` | Case 1：工作进展，3 阶段 |
| 查询响应-医生 | `docs/mock/query_response_doctor.json` | Case 2：母亲身体情况 |
| 查询响应-老师 | `docs/mock/query_response_teacher.json` | Case 3：数学成绩 |
| 查询响应-恋爱 | `docs/mock/query_response_120.json` | Case 4：关系演进，129 条消息、4 阶段叙事弧 |
| 查询响应-简化 | `docs/mock/query_response.json` | 20 条消息的通用结构参考 |

前端开发时可：
- 直接 `import` 或 `fetch` 上述 JSON
- 使用 Mock Service Worker (MSW) 拦截 `GET /api/sessions` 和 `POST /api/query` 返回对应 JSON
- 按用户选中的会话/问题类型，切换返回不同的 `query_response_*.json`，以展示四种 Case 的完整能力
