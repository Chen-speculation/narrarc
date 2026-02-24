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

RealTalk 根目录 `REALTALK/data/` 下有多组对话文件，建议**按文件划分**（不同对话彼此独立，避免泄漏）。**ARC case 文件与对话文件一一对应**，划分时须同步处理：

| 划分 | 原始 QA 文件 | 对应 ARC 文件 | 用途 |
|------|------------|--------------|------|
| **训练/开发集** | `Chat_1` ~ `Chat_7` | `realtalk_emi_elise_arc_cases.json` 等 6 个 | 调参、改 prompt、分析失败 case、快速迭代 |
| **测试集** | `Chat_8_Akib_Muhhamed.json`、`Chat_9_Fahim_Akib.json`、`Chat_10_Fahim_Muhhamed.json` | `realtalk_akib_muhhamed_arc_cases.json`、`realtalk_fahim_akib_arc_cases.json`、`realtalk_fahim_muhhamed_arc_cases.json` | 仅用于最终验收 |

**示例**：开发时只在 `Chat_1` ~ `Chat_7` 及其对应 ARC 文件上迭代；全部改动完成后，在 `Chat_8` ~ `Chat_10` 及其对应 ARC 文件上各跑一次，得到的指标才是可信的「提升水平」。

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

### 4.2 原始 QA 数据结构

RealTalk JSON 包含：

| 结构 | 说明 |
|------|------|
| `name.speaker_1/2` | 对话双方姓名 |
| `session_N` | 消息数组，每条含 `clean_text`, `speaker`, `date_time`, `dia_id` (如 D1:4) |
| `events_session_N` | 事件标注（当前未用于评估） |
| `session_N_date_time` | 会话时间 |
| `qa` | 问答对：`question`, `answer`, `evidence` (dia_ids), `category` (1=fact, 2=date, 3=inference) |

原始 QA 是**单点事实型**问题（when/what/who），每个 case 只有一个扁平证据列表。

### 4.3 转换流程

所有 session 会被**合并为一条按时间排序的对话**，再灌入 backend：

1. `convert_realtalk.py`：session_1..N → `messages.json` + `sessions.json` + `mapping.json`（dia_id ↔ localId）
2. `generate_arc_cases_from_qa.py`：qa → `arc_cases.json`（评估用例）
3. 输出目录：`backend/tests/data/realtalk_eval/`

### 4.4 ARC 叙事弧 Cases（新增）

除原始 QA 外，还构造了一批 **ARC 叙事弧 case**，测试系统对跨时间线演变的多阶段叙事能力。

**路径**：`REALTALK/arc_data/`，共 9 个文件，覆盖所有对话对：

| 文件 | 对应对话 |
|------|----------|
| `realtalk_emi_elise_arc_cases.json` | Chat_1_Emi_Elise |
| `realtalk_emi_paola_arc_cases.json` | Chat_2_Emi_Paola |
| `realtalk_kevin_elise_arc_cases.json` | Chat_3_Kevin_Elise |
| `realtalk_kevin_paola_arc_cases.json` | Chat_4_Kevin_Paola |
| `realtalk_nebraas_vanessa_arc_cases.json` | Chat_5/6 Nebraas_Vanessa |
| `realtalk_vanessa_nicolas_arc_cases.json` | Chat_7_Vanessa_Nicolas |
| `realtalk_akib_muhhamed_arc_cases.json` | Chat_8_Akib_Muhhamed |
| `realtalk_fahim_akib_arc_cases.json` | Chat_9_Fahim_Akib |
| `realtalk_fahim_muhhamed_arc_cases.json` | Chat_10_Fahim_Muhhamed |

**ARC case 格式**（与原始 QA 的核心差异）：

```json
{
  "question": "How did Fahim's outdoor activities and health status change over the conversations?",
  "query_type": "arc_narrative",
  "expected_phases": [
    {
      "title": "Active enjoyment of nature and running",
      "time_range": "Dec 29",
      "evidence_dia_ids": ["D1:4", "D1:29"]
    },
    {
      "title": "Falling sick with a cold",
      "time_range": "Jan 01",
      "evidence_dia_ids": ["D4:2", "D4:3"]
    },
    {
      "title": "Recovery and resuming outdoor visits",
      "time_range": "Jan 10-21",
      "evidence_dia_ids": ["D13:8", "D20:1", "D20:53"]
    }
  ]
}
```

**关键特征**：

| 维度 | 原始 QA | ARC Case |
|------|---------|----------|
| 问题类型 | 单点事实（when/what/who） | 跨时间演变弧（how did X evolve） |
| 证据结构 | 扁平列表 | 多个阶段，每阶段独立证据 |
| 预期答案 | 固定文本 `answer` 字段 | 无固定文本，仅 `expected_phases` 中的证据 |
| Phase 标题 | N/A | LLM 生成的描述性标题，不可做精确匹配 |

**重要**：ARC case 的 `title` 字段是人工构造时由 LLM 生成的描述性标签，不是精确字符串。系统生成的 phase 标题与之不同是**预期现象**，评估时**不得**将标题用于匹配或打分（见第五节）。

---

## 五、验证方式

### 5.1 一键运行

评估脚本同时支持原始 QA cases 和 ARC cases，通过 `--arc-cases` 参数传入 ARC 文件：

**在训练集上迭代**（示例：Chat_1_Emi_Elise）：

```bash
cd backend

uv run python scripts/run_realtalk_eval.py \
  --input /path/to/REALTALK/data/Chat_1_Emi_Elise.json \
  --arc-cases /path/to/REALTALK/arc_data/realtalk_emi_elise_arc_cases.json \
  --self-id "Emi" \
  --talker-id realtalk_emi_elise \
  --limit-cases 5 \
  --mode agent
```

**在测试集上最终验收**（示例：Chat_10_Fahim_Muhhamed，仅在所有改动完成后跑一次）：

```bash
uv run python scripts/run_realtalk_eval.py \
  --input /path/to/REALTALK/data/Chat_10_Fahim_Muhhamed.json \
  --arc-cases /path/to/REALTALK/arc_data/realtalk_fahim_muhhamed_arc_cases.json \
  --self-id "Fahim Khan" \
  --talker-id realtalk_fahim_muhhamed \
  --mode agent
# 不加 --limit-cases，跑全量 QA + 全量 ARC
```

若暂不传 `--arc-cases`，则只评估原始 QA；两种 case 互不干扰，可独立运行。

### 5.2 原始 QA 评估流程

1. **构建阶段**：L1 → L1.5 → L2，写入临时 SQLite + ChromaDB
2. **查询阶段**：对每个 QA case 的 `question` 跑查询管道，得到 `phases`（含 `evidence_msg_ids`）
3. **指标计算**：
   - 用 `mapping.json` 将预期的 `evidence_dia_ids` 转为 `expected_local_ids`
   - Exact Recall = `|returned ∩ expected| / |expected|`
   - Fuzzy Recall = 对每个 expected_id，若存在 returned_id 满足 `|r - e| ≤ 3` 则计为命中

### 5.3 原始 QA 输出解读

```
Case 1/2 [agent]: When did Fahim Khan go for a morning run after the rain?
  Recall: 0.0% | Fuzzy: 0.0% | Phases: 1
  [debug] expected=[4] | returned=[28] | overlap=set()
```

- `expected`：ground truth 的 localId
- `returned`：系统返回的 localId
- `overlap`：交集，为空则 exact recall = 0%

### 5.4 ARC Case 评估方法（重要）

ARC case 的评估与原始 QA **有本质差异**，需单独处理。

#### 核心原则：**只评证据，不评标题**

ARC case 的 `expected_phases[i].title` 是构造时由 LLM 生成的描述性标签（如 "Active enjoyment of nature and running"）。系统运行时也会用 LLM 自行生成 phase 标题，两者措辞天然不同。**任何基于标题字符串的匹配（精确或模糊）都是无效的**，评估中完全忽略标题字段。

#### 指标一：全局证据召回（Global Evidence Recall）

将 `expected_phases` 中所有 `evidence_dia_ids` 合并为一个扁平集合，视作该 case 的全量预期证据，然后与系统所有 phases 返回的全量证据取交集：

```
Global Expected = ∪ expected_phases[i].evidence_dia_ids
Global Returned = ∪ system_phases[j].evidence_msg_ids
Global Exact Recall = |Global Returned ∩ Global Expected| / |Global Expected|
Global Fuzzy Recall = 同原始 QA，±3 容差
```

这是**最重要的指标**，与原始 QA 的 exact recall 概念一致，便于横向对比。

#### 指标二：Phase-level Recall（分阶段召回）

衡量系统是否把正确证据分配到了对应的「演变阶段」。由于标题不可比较，**以证据重叠度作为阶段匹配依据**：

1. 对每个 `expected_phase[i]`，找系统返回的所有 phases 中，与该期望阶段证据重叠度最高的 `best_match_phase`
2. 计算该 expected phase 的 per-phase recall = `|best_match.evidence ∩ expected_phase[i].evidence| / |expected_phase[i].evidence|`
3. 报告各阶段召回均值（Mean Phase Recall）

```
Mean Phase Recall = mean(per_phase_recall[i] for all i)
```

#### 指标三：Phase Coverage（阶段覆盖率）

衡量系统输出是否覆盖了各个预期演变阶段（即是否遗漏某个阶段）：

```
Phase Coverage = fraction of expected phases where per_phase_recall[i] > 0
```

若系统完全没有返回某个预期阶段的任何证据，该阶段计为「未覆盖」。

#### ARC 评估输出格式（建议）

```
[ARC] Case 1/3: How did Fahim's outdoor activities and health status change?
  Global Recall: 33.3% | Global Fuzzy: 50.0% | Phases returned: 3
  Phase Coverage: 2/3 (66.7%)
  Mean Phase Recall: 40.0%
  [debug] phase_0 expected=[localId_A, localId_B] best_match_recall=100% (phase 1)
  [debug] phase_1 expected=[localId_C, localId_D] best_match_recall=0%   (no match)
  [debug] phase_2 expected=[localId_E, localId_F, localId_G] best_match_recall=33.3% (phase 2)
```

#### 实现提示

ARC case 的评估逻辑建议在 `eval_realtalk_accuracy.py` 中增加独立分支，检测 case 是否含 `query_type: arc_narrative` 字段来区分两种评估路径。`generate_arc_cases_from_qa.py` 生成的 cases 与 `arc_data/` 中手工构造的 cases 格式不同（前者是 QA → 单阶段转换），注意区分。

### 5.5 汇总报告

两类 case 的指标分开汇总，最终报告格式建议：

```
=== QA Cases (N=85) ===
  Mean Exact Recall:  X%
  Mean Fuzzy Recall:  Y%
  Precision:          Z%

=== ARC Cases (N=4) ===
  Global Exact Recall:  A%
  Global Fuzzy Recall:  B%
  Mean Phase Recall:    C%
  Phase Coverage:       D%
```

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

### 6.3 ARC Case 专项排查方向

ARC case 的核心特征是问题类型为 `arc_narrative`，在系统内部走不同的检索路径（Q3/Retriever 返回**全量节点**而非仅锚点相关）。因此除通用方向外，还需关注：

1. **arc_narrative 路径覆盖全局时间线的能力**
   - Q3 的全量节点返回是否真的包含所有 session 的 TopicNode？
   - 若对话跨越多个 session（如 D1 到 D23），确认 L1 建库时所有 session 的节点都写入了 SQLite 和 ChromaDB

2. **Generator 的多阶段切分质量**
   - Generator（Q4/LLM）能否把全量候选节点正确切分为时间顺序的多个 phase？
   - 当候选节点覆盖了预期证据，但 LLM 仍合并到单一 phase 或遗漏某阶段时，是 prompt 问题
   - 可对比：`expected_phases` 的数量 vs 系统返回 phases 数量

3. **Phase 标题差异属于预期，不需要修复**
   - 系统生成 phase 标题（如 "Active running and nature"）和 ground truth 标题（如 "Active enjoyment of nature and running"）措辞不同是**正常现象**，不需要通过任何方式对齐标题字符串
   - 评估只看 `evidence_msg_ids` 是否命中，标题仅供人工阅读参考

4. **per-phase 证据分配错误**
   - 即使 Global Recall 较高，若证据被错误地集中在某一个 phase 而另几个 phase 为空，Mean Phase Recall 和 Phase Coverage 会揭示这一问题
   - 例如：系统把跨越 3 个月的证据全塞进一个 phase，Global Recall = 100% 但 Phase Coverage = 33%

### 6.4 调试建议

- 先用 `--limit-cases 2` 快速迭代，确认改动有效后再跑全量
- 对失败 case，可查 `realtalk_fahim_muhhamed_messages.json` 中对应 localId 的 `content`，对比预期与返回
- 可加日志：在 Q3 输出候选节点列表，检查预期 localId 是否在候选中
- ARC case 调试时，重点看 `[debug] phase_X expected=... best_match_recall=0%` 的行，找出系统完全未覆盖的预期阶段

### 6.5 相关代码位置

| 模块 | 路径 | 职责 |
|------|------|------|
| L1 构建 | `src/narrative_mirror/build.py` | Burst 聚合、TopicNode 分类 |
| L1.5 | `src/narrative_mirror/metadata.py` | 信号计算、异常锚点 |
| L2 | `src/narrative_mirror/layer2.py` | 向量检索、Reranker、线程构建 |
| 查询 (oneshot) | `src/narrative_mirror/query.py` | Q1–Q5 管道 |
| 查询 (agent) | `src/narrative_mirror/workflow.py` | LangGraph 工作流 |
| 评估脚本 | `scripts/eval_realtalk_accuracy.py` | 指标计算、报告输出 |

### 6.6 参考文档

- `backend/CLAUDE.md`：架构与数据流
- `backend/docs/REALTALK_EVAL_GUIDE.md`：RealTalk 转换与测评操作说明

---

## 七、成功标准（建议）

两类 case 分别设定目标，各自独立衡量进展。

### 7.1 原始 QA Cases

| 阶段 | 指标 | 目标 |
|------|------|------|
| 短期 | 训练集 Exact Recall | ≥ 30% |
| 中期 | 训练集 Exact Recall | ≥ 50%，且 Fuzzy–Exact 差距 < 20% |
| 验收 | **测试集** Exact Recall | 报告实测值，作为权威结果 |

### 7.2 ARC Cases

| 阶段 | 指标 | 目标 |
|------|------|------|
| 短期 | 训练集 Global Exact Recall | ≥ 30% |
| 中期 | 训练集 Global Exact Recall | ≥ 50%，Phase Coverage ≥ 60% |
| 中期 | 训练集 Mean Phase Recall | ≥ 40% |
| 验收 | **测试集** Global Exact Recall + Phase Coverage | 报告实测值 |

**说明**：
- ARC case 总数较少（每个对话约 4–6 个），单 case 的方差较大，需结合多个对话文件的聚合结果来判断趋势
- Phase Coverage 比 Mean Phase Recall 更能反映「是否遗漏演变阶段」，是 ARC 评估的核心诊断指标
- 标题质量（phase 标题是否优美、准确）**不在量化评估范围内**，但可供人工 review 参考

**注意**：训练集指标用于指导迭代；**测试集指标**才是对外报告、验收的权威结果。

---

## 八、快速上手检查清单

**基础准备**
- [ ] 克隆/拉取 narrarc（backend）与 REALTALK 仓库
- [ ] 确认 `backend/config.yml` 中 LLM/embedding/reranker 配置正确
- [ ] **确定训练集 / 测试集划分**（见第三节），QA 文件和 ARC 文件同步划分，记录在案

**原始 QA 评估**
- [ ] 在**训练集**某文件上运行 `run_realtalk_eval.py --limit-cases 2` 复现 0% exact recall
- [ ] 阅读 `CLAUDE.md` 理解 L1/L1.5/L2 与查询管道
- [ ] 选一个失败 QA case，手动查看 expected localId 对应的消息内容
- [ ] 在 Q3 或 Retriever 中加日志，确认预期证据是否进入候选集

**ARC Case 评估**
- [ ] 确认 `REALTALK/arc_data/` 下 9 个 `*_arc_cases.json` 文件存在且可读
- [ ] 在训练集某文件上用 `--arc-cases` 参数运行，查看 Global Recall 与 Phase Coverage 基准值
- [ ] 检查评估脚本是否已实现 ARC 评估分支（`query_type: arc_narrative` 路径）；若未实现，需先实现（见 5.4 节）
- [ ] 对失败 ARC case，查看 `[debug] phase_X ... best_match_recall=0%` 行，定位未覆盖的演变阶段
- [ ] 确认 arc_narrative 查询路径（Q3 全量返回）确实覆盖跨 session 的所有节点

**最终验收**
- [ ] 全部改动完成后，在**测试集**（Chat_8/9/10）上各跑一次完整评估（含 QA + ARC）
- [ ] 记录 QA Exact Recall、ARC Global Recall、ARC Phase Coverage 三个核心指标
