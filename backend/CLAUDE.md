# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Narrative Mirror 是一个将微信聊天历史转化为有证据支持的叙事弧的系统。采用双层索引架构，支持自然语言查询关系动态变化。

## 核心架构设计

### 分层索引（Three-Layer Index）

```
Raw Messages → Burst → TopicNode → MetadataSignals → AnomalyAnchor
                           ↓
                    ChromaDB Embeddings
                           ↓
                    SemanticThreadPointers
```

**Layer 1 - TopicNode 构建** (`build.py`)
- 消息按30分钟间隔聚合成 Burst
- 每个 Burst 通过 LLM 分类为1~N个 TopicNode
- TopicNode = (topic_name, start_local_id, end_local_id, start_time, end_time)

**Layer 1.5 - 元数据信号** (`metadata.py`)
- 每个 TopicNode 计算 7 维信号：
  - `reply_delay_avg/max_s`: 交替回复延迟
  - `term_shift_score`: 称呼变化比例
  - `silence_event`: 是否超过3×中位间隔
  - `topic_frequency`: 话题历史出现次数
  - `initiator_ratio`: 用户发起对话比例
  - `emotional_tone`: 情感基调 (-1~1)
  - `conflict_intensity`: 冲突强度 (0~1)
- 异常锚点检测：信号值超过 μ+2σ

**Layer 2 - 语义线程** (`layer2.py`)
- 三阶段流水线：
  1. Stage 1: ChromaDB 向量相似度召回候选对
  2. Stage 1.5: Cross-encoder Reranker 重排序
  3. Stage 2: CoT LLM 语义仲裁，创建 thread pointer

### Protocol-based 抽象

所有外部依赖通过 Protocol 定义接口：

```python
class NonCoTLLM(Protocol):
    def complete(system, prompt, max_tokens, response_format) -> str
    def embed(text) -> list[float]
    def embed_batch(texts) -> list[list[float]]

class CoTLLM(Protocol):
    def think_and_complete(system, prompt, max_tokens) -> str

class Reranker(Protocol):
    def rerank(pairs: list[tuple[str, str]]) -> list[float]
```

**设计意图**：支持测试替身（Stub）和真实实现的切换，便于单元测试和集成测试分离。

### 数据流

```
ChatDataSource → RawMessage → SQLite
                      ↓
              aggregate_bursts() → Burst
                      ↓
              classify_bursts_batch() → TopicNode → SQLite
                      ↓
              compute_all_metadata() → MetadataSignals → SQLite
                      ↓
              detect_anomalies() → AnomalyAnchor → SQLite
                      ↓
              embed_nodes() → ChromaDB
                      ↓
              stage1/1.5/2 → SemanticThreadPointer → SQLite
```

### 查询管道（Q1-Q5）

`query.py` 实现运行时查询：

1. **Q1** `parse_intent()`: CoT LLM 解析意图 → QueryIntent
2. **Q2** `lookup_anchors()`: 按维度查询 AnomalyAnchor
3. **Q3** `expand_candidates()`: 锚点 + 线程遍历扩展候选节点
4. **Q4** `segment_narrative()`: CoT LLM 生成分段叙事 + 证据ID
5. **Q5** `format_cards()`: 格式化为纯文本卡片

**关键设计**：`arc_narrative` 查询需要完整时间线，因此 Q3 会返回所有节点（优先排序锚点节点）；其他查询类型仅返回锚点相关节点。

## 并发模型

LLM 调用是 I/O 密集型，采用批处理 + 并行策略：

```python
# 批处理：多请求合并为单个 LLM 调用
classify_bursts_batch(bursts, llm)  # 8 bursts per call
extract_llm_signals_batch(nodes, llm)  # 8 nodes per call

# 并行：批调用通过 ThreadPoolExecutor 并发执行
max_workers = min(llm.max_workers, len(batches))
```

**原则**：批处理减少 API 请求次数，并行减少总延迟。

## 存储层

**SQLite** (`db.py`)：
- `raw_messages`: 原始消息，PK=(talker_id, local_id)
- `bursts`: 聚合后的消息组
- `topic_nodes`: Layer 1 话题节点
- `node_metadata`: Layer 1.5 信号
- `anomaly_anchors`: 异常锚点
- `semantic_thread_pointers`: Layer 2 线程指针

**ChromaDB** (`layer2.py`)：
- Collection: `narrative_mirror_{talker_id}`
- 存储 TopicNode 的 embedding + metadata
- 距离度量：cosine

## 数据源扩展

`datasource.py` 定义 `ChatDataSource` Protocol：

- `MockDataSource`: 硬编码的20条测试对话
- `WeFlowDataSource`: 连接本地 WeFlow HTTP API (port 5031)
- `JsonFileDataSource`: 从 JSON 文件加载

新增数据源只需实现 Protocol 接口。

## CLI 入口

每个模块都是可独立执行的 CLI：

```bash
uv run python -m narrative_mirror.build --talker <id> --debug
uv run python -m narrative_mirror.metadata --talker <id> --debug
uv run python -m narrative_mirror.layer2 --talker <id> --debug
uv run python -m narrative_mirror.query --talker <id> "问题"
```

通过 `--config config.yml` 切换真实 LLM 实现。

## 信号维度常量

`metadata.CANONICAL_SIGNALS` 定义查询可用的维度列表：

```python
CANONICAL_SIGNALS = [
    "reply_delay", "term_shift", "silence_event",
    "topic_frequency", "initiator_ratio",
    "emotional_tone", "conflict_intensity"
]
```

Q1 解析的 `focus_dimensions` 必须是此列表的子集。
