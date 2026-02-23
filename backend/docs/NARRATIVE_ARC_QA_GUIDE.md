# 叙事弧 QA 对生成指南

本文档面向负责根据 RealTalk 数据生成**叙事弧（Narrative Arc）QA 对**的同学。若你此前未接触本项目，请按顺序阅读。

---

## 一、什么是叙事弧 QA

### 1.1 与简单 QA 的区别

RealTalk 自带的 `qa` 多为**单点事实**或**扁平列举**：

| 类型 | 示例问题 | 特点 |
|------|----------|------|
| 简单 QA | "When did Fahim go for a morning run?" | 单一时间点，1–2 条证据 |
| 简单 QA | "What are Fahim's hobbies?" | 列举型，多条证据但无时间顺序 |
| **叙事弧 QA** | "How did Muhammad's work situation evolve over these sessions?" | **跨时间演变**，分阶段、有起承转合 |

**叙事弧 QA** 关注的是：某条「故事线」在对话中**如何随时间推进**，需要拆成多个阶段（phase），每个阶段有对应证据。

### 1.2 典型叙事弧问题句式

- "How did **X** evolve over these sessions?"
- "How did **X's relationship with Y** develop over time?"
- "How did **X's interest in Z** change across the conversation?"
- "What was the progression of **X** (e.g., health, job, hobby)?"

---

## 二、输出格式

每个叙事弧 QA 对是一个 JSON 对象，结构如下：

```json
{
  "question": "How did Muhammad's work situation evolve over these sessions?",
  "query_type": "arc_narrative",
  "expected_phases": [
    {
      "title": "Initial frustration with boss and workplace",
      "time_range": "Dec 29-30",
      "evidence_dia_ids": ["D1:15", "D1:16"]
    },
    {
      "title": "Considering job change and reporting",
      "time_range": "Jan 01-05",
      "evidence_dia_ids": ["D4:8", "D5:2"]
    },
    {
      "title": "Finding positives and adjusting",
      "time_range": "Jan 07-14",
      "evidence_dia_ids": ["D10:3", "D12:1"]
    }
  ]
}
```

### 2.1 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `question` | ✓ | 英文问题，需体现「演变/发展」 |
| `query_type` | ✓ | 固定为 `"arc_narrative"` |
| `expected_phases` | ✓ | 阶段数组，至少 2 个，按时间顺序 |
| `expected_phases[].title` | ✓ | 该阶段简短标题（英文） |
| `expected_phases[].time_range` | 建议 | 时间范围，如 "Dec 29-30"、"Jan 01-05" |
| `expected_phases[].evidence_dia_ids` | ✓ | 支持该阶段的证据消息 ID 列表 |

### 2.2 evidence_dia_ids 规则

- **格式**：`D{session}:{message_index}`，如 `D1:4`、`D3:15`
- **含义**：`D1:4` = session_1 中某条消息的 ID（编号可能不连续，如 D1:5 可能缺失）
- **来源**：**必须**从 `session_N` 中每条消息的 `dia_id` 字段直接复制，不得臆造
- **要求**：每个 ID 都必须在 RealTalk JSON 里真实存在，否则评估会报错

---

## 三、RealTalk 数据结构速览

### 3.1 需要阅读的部分

```
REALTALK/data/Chat_X_*.json
├── name.speaker_1, speaker_2     # 对话双方
├── session_1, session_2, ...    # 消息数组，每条有 clean_text, speaker, date_time, dia_id
├── events_session_1, ...        # 事件摘要（agent_a/agent_b），可辅助找故事线
└── session_1_date_time, ...     # 各 session 时间，用于填 time_range
```

### 3.2 消息与 dia_id 示例

```json
{
  "clean_text": "Earlier in the day I was going out running and took some photos.",
  "speaker": "Fahim Khan",
  "date_time": "29.12.2023, 01:06:31",
  "dia_id": "D1:4"
}
```

→ 这条消息的 evidence 应写为 `"D1:4"`。

### 3.3 events_session 的用途

`events_session_N` 提供每 session 的**事件摘要**，便于发现故事线，但**没有 dia_id**，需要你回到 `session_N` 找到对应消息：

```json
"events_session_1": {
  "agent_a": [
    { "sub-event": "Fahim Khan is going for a morning run after the rain.", "date": "", "id": "E" }
  ],
  "agent_b": [
    { "sub-event": "Muhammad became sick, thus he called off his plans with friends.", "date": "", "id": "E" }
  ]
}
```

→ 根据 "morning run" 去 session_1 找含 running 的 clean_text，得到 dia_id（如 D1:4）。

---

## 四、生成流程（建议步骤）

### Step 1：通读对话，标记故事线

- 顺序阅读 `session_1` ~ `session_N` 的 `clean_text`
- 参考 `events_session_N` 的 sub-event
- 列出可写成叙事弧的主题，例如：
  - 某人健康/病情变化
  - 某人工作/职场态度变化
  - 两人共同兴趣的发展
  - 某人感情/追求进展

### Step 2：为每条故事线划分阶段

- 按时间顺序拆成 2–4 个阶段
- 每个阶段有清晰转折或进展
- 参考 `session_N_date_time` 确定 time_range

### Step 3：为每个阶段找证据

- 回到 `session_N`，找到支持该阶段的 `clean_text`
- 记录对应 `dia_id`，填入 `evidence_dia_ids`
- 每阶段至少 1 条证据，建议 2–3 条

### Step 4：写成问题 + 输出 JSON

- 问题要明确体现「演变/发展」
- 按模板组装 JSON，检查 dia_id 拼写与存在性

---

## 五、示例

### 5.1 完整示例（参考 realtalk_nicolas_nebraas_arc_cases.json）

```json
{
  "question": "How did Nicolas's pursuit of his crush evolve over these sessions?",
  "query_type": "arc_narrative",
  "expected_phases": [
    {
      "title": "Initial interest and planning to ask her out",
      "time_range": "Dec 29-30",
      "evidence_dia_ids": ["D2:3", "D3:3"]
    },
    {
      "title": "Asking her out and uncertain waiting",
      "time_range": "Dec 31-Jan 02",
      "evidence_dia_ids": ["D7:1", "D8:1", "D8:2"]
    },
    {
      "title": "Positive interaction and shared activities",
      "time_range": "Jan 03-14",
      "evidence_dia_ids": ["D7:3", "D9:1"]
    }
  ]
}
```

### 5.2 针对 Chat_10_Fahim_Muhhamed 的示例思路

基于对话内容，可考虑的故事线（需你核实具体 dia_id）：

| 故事线 | 问题示例 | 阶段思路 |
|--------|----------|----------|
| Muhammad 工作/老板 | How did Muhammad's work situation evolve? | 初期不满 → 考虑举报 → 调整心态 |
| 两人游戏兴趣 | How did Fahim and Muhammad's gaming activities develop? | 提及 Fortnite → 一起打联赛 → 讨论电竞 |
| Fahim 户外/健康 | How did Fahim's outdoor activities and health change? | 晨跑、自然 → 感冒 → 恢复、博物馆 |

---

## 六、质量要求

### 6.1 必须满足

- [ ] `evidence_dia_ids` 中的每个 ID 在 RealTalk JSON 中存在
- [ ] 阶段按时间顺序排列
- [ ] 每阶段至少 1 条证据
- [ ] 问题与阶段内容一致，能由证据支撑

### 6.2 建议做到

- [ ] 每阶段 2–3 条证据，提高评估稳定性
- [ ] `time_range` 与 `session_N_date_time` 一致
- [ ] 阶段之间有清晰进展或转折
- [ ] 问题用英文，与 RealTalk 对话语言一致

### 6.3 避免

- [ ] 单点事实问题（如 "When did X happen?"）—— 用原有 qa 即可
- [ ] 证据与阶段内容不符
- [ ] 编造或不存在的 dia_id
- [ ] 阶段过多（建议 2–4 个），导致过细难评估

---

## 七、输出与交付

### 7.1 文件格式

- 单个 JSON 文件，内容为 **数组**，每个元素是一个 arc case
- 文件命名建议：`{chat_id}_arc_cases.json`，如 `realtalk_fahim_muhhamed_arc_cases.json`

### 7.2 示例文件结构

```json
[
  {
    "question": "How did ... evolve?",
    "query_type": "arc_narrative",
    "expected_phases": [...]
  },
  {
    "question": "How did ... develop?",
    "query_type": "arc_narrative",
    "expected_phases": [...]
  }
]
```

### 7.3 放置位置

- 产出文件放在：`chat-mirror/backend/tests/data/realtalk_eval/`
- 与同 chat 的 `*_messages.json`、`*_sessions.json`、`*_mapping.json` 配套使用

### 7.4 验证方式

你产出的是**手写**的 arc_cases，不要用 `run_realtalk_eval.py`（它会用 qa 自动生成并覆盖你的文件）。按下面步骤验证：

**Step 1：转换消息**（若尚未转换）

```bash
cd chat-mirror/backend
uv run python scripts/convert_realtalk.py \
  --input /path/to/REALTALK/data/Chat_10_Fahim_Muhhamed.json \
  --self-id "Fahim Khan" \
  --talker-id realtalk_fahim_muhhamed \
  --output tests/data/realtalk_eval/realtalk_fahim_muhhamed_messages.json \
  --sessions-output tests/data/realtalk_eval/realtalk_fahim_muhhamed_sessions.json \
  --mapping-output tests/data/realtalk_eval/realtalk_fahim_muhhamed_mapping.json
```

**Step 2：放置你的 arc_cases.json**

将你生成的 `realtalk_fahim_muhhamed_arc_cases.json` 放到 `tests/data/realtalk_eval/`。

**Step 3：跑评估**

```bash
uv run python scripts/eval_realtalk_accuracy.py \
  --chat-id realtalk_fahim_muhhamed \
  --mode agent
```

若无 dia_id 不存在等报错，且能输出 Recall 等指标，即说明格式正确。

---

## 八、参考文件

| 文件 | 说明 |
|------|------|
| `backend/tests/data/realtalk_eval/realtalk_nicolas_nebraas_arc_cases.json` | 多阶段叙事弧示例 |
| `backend/tests/data/realtalk_eval/realtalk_emi_elise_arc_cases.json` | 单阶段示例（简单弧） |
| `backend/docs/REALTALK_EVAL_GUIDE.md` | RealTalk 转换与测评流程 |
| `backend/docs/ACCURACY_IMPROVEMENT_TASK.md` | 准确率提升任务说明（含训练/测试集划分） |
