# Narrative Mirror 证据召回准确率提升任务

本文档面向负责提升系统准确率的同学，说明当前问题、测试方式及预期工作内容。若你此前未接触本项目，请按顺序阅读。

---

## 一、项目背景：Narrative Mirror 是什么

**Narrative Mirror** 是一个将聊天历史转化为「有证据支持的叙事」的系统。用户用自然语言提问（如「他什么时候去晨跑的？」），系统从聊天记录中检索相关证据，并生成带引用、可追溯的回答。

### 核心流程

```
原始消息 → L1 话题聚合 → L1.5 元数据信号 → L2 语义线程 → 查询管道 → 带证据的回答
```

- **L1**：按 30 分钟间隔把消息聚成 Burst，再用 LLM 分类为 TopicNode（如「日常闲聊」「电影讨论」）
- **L1.5**：为每个 TopicNode 计算 7 维信号（回复延迟、沉默事件等），检测异常锚点
- **L2**：用 ChromaDB 向量检索 + Reranker + LLM 仲裁，建立语义线程
- **查询**：解析问题意图 → 查锚点 → 扩展候选节点 → LLM 生成叙事并标注证据 ID

### 两种查询模式

| 模式 | 说明 | 代码入口 |
|------|------|----------|
| **oneshot** 【已废弃】| 传统 Q1–Q5 管道，一次走完 | `query.run_query_with_phases(use_agent=False)` |
| **agent** | LangGraph 工作流：Planner → Retriever → Grader → Generator | `workflow.run_workflow()` |

---

## 二、当前问题：证据召回率极低

### 2.1 现象

在 RealTalk 数据集上评估时，**Evidence Recall (exact) 为 0%**，即系统返回的证据消息中，没有任何一条与人工标注的 ground truth 完全一致。

### 2.2 典型失败案例

| 问题 | 预期证据 (localId) | 系统返回 | 结果 |
|------|-------------------|----------|------|
| When did Fahim Khan go for a morning run after the rain? | [4] | [1, 3, 9, 13, 28] (oneshot) / [28] (agent) | 0% exact recall |
| When did Muhammad cancel plans with friends due to illness? | [14] | [52, 53, 61, 63, 201] (oneshot) / [1, 4, 13, 23, 28] (agent) | 0% exact recall |

**预期证据对应的真实内容**（来自 Chat_10_Fahim_Muhhamed.json）：

- localId 4 (D1:4)：*"Earlier in the day I was going out running and took some photos on the scenic route I took."*（晨跑证据）
- localId 14 (D1:15)：*"But being sick isn't all bad. I work in a downtown Chicago office..."*（因病相关）

系统既没有精确命中这些消息，生成的答案也与 ground truth 矛盾（如回答「聊天记录中没有相关信息」）。

### 2.3 指标说明

| 指标 | 含义 | 当前值 |
|------|------|--------|
| **Evidence Recall (exact)** | 返回证据与预期证据的精确重叠率，`\|返回 ∩ 预期\| / \|预期\|` | **0%**（核心问题） |
| **Fuzzy Recall (±3)** | 允许 ±3 条消息容差的召回，可能产生误导 | 0% (oneshot) / 100% (agent) |
| **Precision** | 返回证据中有效比例 | 0% |
| **Timeline Coverage** | 生成叙事覆盖的时间线比例 | 100% |
| **Groundedness** | 无幻觉（证据 ID 均在有效范围内） | 100% |

**结论**：Fuzzy Recall 可能因「附近消息」被算作命中而虚高；**Exact Recall 0% 才是真实问题**，说明检索/排序没有把正确消息排到前面。

---

## 三、数据集划分：训练集 vs 测试集

**重要**：必须将 RealTalk 划分为两部分，避免在开发阶段「偷看」测试数据，导致高估效果。

### 3.1 划分原则

| 用途 | 说明 | 使用时机 |
|------|------|----------|
| **训练集 / 开发集** | 用于迭代调参、改 prompt、调模型等，反复跑评估、分析失败 case | 日常开发、调优 |
| **测试集** | 完全留出，仅在最终验收时跑一次，用于报告真实提升水平 | 所有改动完成后，做最终评估 |

**规则**：开发过程中**不得**根据测试集结果做任何决策（包括调参、改 prompt、选模型）。否则测试集指标会虚高，无法反映真实泛化能力。

### 3.2 划分方案

RealTalk 根目录 `REALTALK/data/` 下有多组对话文件，建议**按文件划分**（不同对话彼此独立，避免泄漏）：

| 划分 | 文件 | 用途 |
|------|------|------|
| **训练/开发集** | `Chat_1_Emi_Elise.json` ~ `Chat_7_Nebraas_Vanessa.json`（或自选 6–7 个） | 调参、改 prompt、分析失败 case、快速迭代 |
| **测试集** | `Chat_8_Akib_Muhhamed.json`、`Chat_9_Fahim_Akib.json`、`Chat_10_Fahim_Muhhamed.json`（或自选 2–3 个留出） | 仅用于最终验收，报告 Evidence Recall 等指标 |

**示例**：开发时只在 `Chat_1` ~ `Chat_7` 上跑 `run_realtalk_eval.py`；全部改动完成后，再在 `Chat_8` ~ `Chat_10` 上跑一次，得到的 Exact Recall 才是可信的「提升水平」。

### 3.3 可选：按 QA 划分（单文件内）

若某文件 QA 较多（如 85 个），也可在**同一对话内**按 QA 划分：

- 训练集：约 70% 的 qa（如前 60 个）
- 测试集：约 30% 的 qa（如后 25 个）

注意：同一对话的消息会被两边共用，仅 QA 不同。适合单文件规模大、需要更多测试 case 时使用。**按文件划分仍是首选**，语义更清晰。

---

## 四、RealTalk 数据结构

### 4.1 数据来源

- **路径**：`REALTALK/data/`（与 chat-mirror 同级的 REALTALK 仓库）
- **可用文件**：`Chat_1_Emi_Elise.json` ~ `Chat_10_Fahim_Muhhamed.json`（10 个 RealTalk 格式）
- **已测示例**：`Chat_10_Fahim_Muhhamed.json`（662 条消息，85 个 QA）

### 4.2 数据结构

RealTalk JSON 包含：

| 结构 | 说明 |
|------|------|
| `name.speaker_1/2` | 对话双方姓名 |
| `session_N` | 消息数组，每条含 `clean_text`, `speaker`, `date_time`, `dia_id` (如 D1:4) |
| `events_session_N` | 事件标注（当前未用于评估） |
| `session_N_date_time` | 会话时间 |
| `qa` | 问答对：`question`, `answer`, `evidence` (dia_ids), `category` (1=fact, 2=date, 3=inference) |

### 4.3 转换流程

所有 session 会被**合并为一条按时间排序的对话**，再灌入 backend：

1. `convert_realtalk.py`：session_1..N → `messages.json` + `sessions.json` + `mapping.json`（dia_id ↔ localId）
2. `generate_arc_cases_from_qa.py`：qa → `arc_cases.json`（评估用例）
3. 输出目录：`backend/tests/data/realtalk_eval/`

---

## 五、验证方式

### 5.1 一键运行

**在训练集上迭代**（示例：Chat_1_Emi_Elise）：

```bash
cd chat-mirror/backend

uv run python scripts/run_realtalk_eval.py \
  --input /path/to/REALTALK/data/Chat_1_Emi_Elise.json \
  --self-id "Emi" \
  --talker-id realtalk_emi_elise \
  --limit-cases 5 \
  --mode agent
```

**在测试集上最终验收**（示例：Chat_10_Fahim_Muhhamed，仅在所有改动完成后跑一次）：

```bash
uv run python scripts/run_realtalk_eval.py \
  --input /path/to/REALTALK/data/Chat_10_Fahim_Muhhamed.json \
  --self-id "Fahim Khan" \
  --talker-id realtalk_fahim_muhhamed \
  --mode agent
# 不加 --limit-cases，跑全量 QA
```

该脚本依次执行：转换 → 生成 arc_cases → 运行评估。每个 Chat 文件需对应正确的 `--self-id`（`name.speaker_1` 或 `speaker_2` 之一）。

### 5.2 评估流程

1. **构建阶段**：L1 → L1.5 → L2，写入临时 SQLite + ChromaDB
2. **查询阶段**：对每个 arc case 的 `question` 跑查询管道，得到 `phases`（含 `evidence_msg_ids`）
3. **指标计算**：
   - 用 `mapping.json` 将预期的 `evidence_dia_ids` 转为 `expected_local_ids`
   - Exact Recall = `|returned ∩ expected| / |expected|`
   - Fuzzy Recall = 对每个 expected_id，若存在 returned_id 满足 `|r - e| ≤ 3` 则计为命中

### 5.3 输出解读

```
Case 1/2 [oneshot]: When did Fahim Khan go for a morning run after the rain?
  Recall: 0.0% | Fuzzy: 0.0% | Phases: 1
  [debug] expected=[4] | returned=[28] | overlap=set()
```

- `expected`：ground truth 的 localId
- `returned`：系统返回的 localId
- `overlap`：交集，为空则 exact recall = 0%

---

## 六、预期工作内容

### 6.1 核心目标

**提升 Evidence Recall (exact)**，使系统能稳定命中 ground truth 标注的证据消息。

### 6.2 建议排查方向

1. **L1 话题划分**
   - 30 分钟 burst 是否把相关消息拆到不同 TopicNode？
   - Topic 分类为中文（如「文学阅读」「电影讨论」），而 RealTalk 为英文，是否存在语言/语义 gap？

2. **L2 语义检索**
   - ChromaDB 向量检索的 top_k、sim_threshold 是否合适？
   - Reranker 重排序是否把正确节点排到前面？
   - Embedding 模型（BAAI/bge-m3）对英文对话的适配性

3. **Q3 候选扩展**
   - 锚点 + 线程遍历得到的候选集是否覆盖预期证据？
   - 评估报告中的「Q2 Anomaly Anchor Coverage」可作参考（当前约 50%）

4. **Q4 / Generator**
   - 即使候选集中包含正确消息，LLM 是否选对了 evidence_msg_ids？
   - 可抽查：候选节点内容 vs 最终返回的 evidence_msg_ids

### 6.3 调试建议

- 先用 `--limit-cases 2` 快速迭代，确认改动有效后再跑全量
- 对失败 case，可查 `realtalk_fahim_muhhamed_messages.json` 中对应 localId 的 `content`，对比预期与返回
- 可加日志：在 Q3 输出候选节点列表，检查预期 localId 是否在候选中

### 6.4 相关代码位置

| 模块 | 路径 | 职责 |
|------|------|------|
| L1 构建 | `src/narrative_mirror/build.py` | Burst 聚合、TopicNode 分类 |
| L1.5 | `src/narrative_mirror/metadata.py` | 信号计算、异常锚点 |
| L2 | `src/narrative_mirror/layer2.py` | 向量检索、Reranker、线程构建 |
| 查询 (oneshot) | `src/narrative_mirror/query.py` | Q1–Q5 管道 |
| 查询 (agent) | `src/narrative_mirror/workflow.py` | LangGraph 工作流 |
| 评估脚本 | `scripts/eval_realtalk_accuracy.py` | 指标计算、报告输出 |

### 6.5 参考文档

- `backend/CLAUDE.md`：架构与数据流
- `backend/docs/REALTALK_EVAL_GUIDE.md`：RealTalk 转换与测评操作说明

---

## 七、成功标准（建议）

- **短期**：在**训练集**上，Evidence Recall (exact) 从 0% 提升至 ≥ 30%
- **中期**：训练集 Exact Recall ≥ 50%，且 Fuzzy 与 Exact 差距缩小
- **验收**：在**测试集**上跑最终评估，报告 Exact Recall 等指标，作为真实提升水平的依据

**注意**：训练集指标用于指导迭代；**测试集指标**才是对外报告、验收的权威结果。

---

## 八、快速上手检查清单

- [ ] 克隆/拉取 chat-mirror 与 REALTALK 仓库
- [ ] 确认 `backend/config.yml` 中 LLM/embedding/reranker 配置正确
- [ ] **确定训练集 / 测试集划分**（见第三节），并记录在案
- [ ] 在**训练集**某文件上运行 `run_realtalk_eval.py --limit-cases 2` 复现 0% exact recall
- [ ] 阅读 `CLAUDE.md` 理解 L1/L1.5/L2 与查询管道
- [ ] 选一个失败 case，手动查看 expected localId 对应的消息内容
- [ ] 在 Q3 或 Retriever 中加日志，确认预期证据是否进入候选集
- [ ] 全部改动完成后，在**测试集**上跑一次最终评估，记录 Exact Recall
