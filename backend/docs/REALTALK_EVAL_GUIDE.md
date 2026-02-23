# RealTalk 数据集测评指南

本文档说明如何利用 RealTalk 数据集测试、测评 Narrative Mirror 后端系统。

## RealTalk JSON 结构

RealTalk 数据集 JSON 包含四类核心结构：

| 结构 | 说明 | 用途 |
|------|------|------|
| **session_N** | 消息数组 | 每条消息：`clean_text`, `speaker`, `date_time`, `dia_id` (D{session}:{idx}) |
| **events_session_N** | 事件标注 | `agent_a`/`agent_b` 的 sub-event 列表，含 date、caused_by |
| **session_N_date_time** | 会话时间 | 格式 `DD.MM.YYYY, HH:MM:SS` |
| **qa** | 问答对 | `question`, `answer`, `evidence` (dia_ids), `category` (1=fact, 2=date, 3=inference) |

示例：

```json
{
  "name": { "speaker_1": "Fahim Khan", "speaker_2": "Muhhamed" },
  "session_1": [
    { "clean_text": "Hey good afternoon", "speaker": "Fahim Khan", "date_time": "29.12.2023, 00:51:12", "dia_id": "D1:1" }
  ],
  "events_session_1": { "agent_a": [...], "agent_b": [...] },
  "session_1_date_time": "29.12.2023, 00:51:12",
  "qa": [
    { "question": "When did Fahim Khan go for a morning run?", "answer": "...", "evidence": ["D1:4"], "category": 2 }
  ]
}
```

## 转换与测评流程

### 方式一：一键流水线（推荐）

```bash
cd backend
uv run python scripts/run_realtalk_eval.py \
  --input /path/to/REALTALK/data/Chat_10_Fahim_Muhhamed.json \
  --self-id "Fahim Khan" \
  --talker-id realtalk_fahim_muhhamed \
  [--limit-cases 3]   # 调试时只跑前 N 个 case
  --mode agent
```

该脚本依次执行：
1. **convert_realtalk.py**：session_N → messages.json + sessions.json + mapping.json
2. **generate_arc_cases_from_qa.py**：qa → arc_cases.json
3. **eval_realtalk_accuracy.py**：L1→L1.5→L2 构建 + 查询评估

### 方式二：分步执行

```bash
# 1. 转换消息
uv run python scripts/convert_realtalk.py \
  --input /path/to/Chat_10_Fahim_Muhhamed.json \
  --self-id "Fahim Khan" \
  --talker-id realtalk_fahim_muhhamed \
  --output tests/data/realtalk_eval/realtalk_fahim_muhhamed_messages.json \
  --sessions-output tests/data/realtalk_eval/realtalk_fahim_muhhamed_sessions.json \
  --mapping-output tests/data/realtalk_eval/realtalk_fahim_muhhamed_mapping.json

# 2. 从 qa 生成 arc_cases
uv run python scripts/generate_arc_cases_from_qa.py \
  --input /path/to/Chat_10_Fahim_Muhhamed.json \
  --output tests/data/realtalk_eval/realtalk_fahim_muhhamed_arc_cases.json

# 3. 运行评估
uv run python scripts/eval_realtalk_accuracy.py \
  --chat-id realtalk_fahim_muhhamed \
  [--mode oneshot]
```

## 输出文件

转换后生成于 `tests/data/realtalk_eval/`：

| 文件 | 说明 |
|------|------|
| `{chat_id}_messages.json` | WeFlow 格式消息（JsonFileDataSource 输入） |
| `{chat_id}_sessions.json` | 会话列表 |
| `{chat_id}_mapping.json` | dia_id ↔ localId 映射 |
| `{chat_id}_arc_cases.json` | 评估用 arc 用例（question + expected_phases） |

## 评估指标

- **Evidence Recall**：返回证据与预期证据的重叠率
- **Fuzzy Recall**：±3 条消息容差的召回
- **Precision**：返回证据中有效比例
- **Hallucination Rate**：超出有效范围的证据比例
- **Per-phase Recall**：按 phase 分别计算召回

## 注意事项

1. **config.yml**：评估需配置 LLM、embedding、reranker，确保 `config.yml` 存在且 API 可用
2. **耗时**：L1/L1.5/L2 构建 + 每个 arc case 的 LLM 查询较慢，建议先用 `--limit-cases 2` 验证
3. **self-id**：需与 `name.speaker_1` 或 `speaker_2` 之一完全匹配（用于 isSend 判定）
4. **events_session**：当前仅使用 session 与 qa；events_session 可用于未来更细粒度的 phase 标注

## 已测试文件

- `Chat_10_Fahim_Muhhamed.json`：662 条消息，85 个 arc cases，转换与流水线已跑通
