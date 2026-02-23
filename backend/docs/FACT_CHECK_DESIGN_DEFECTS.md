# 事实核查链路设计缺陷分析

## 问题现象

查询「Kate在第一次约会中去了哪个咖啡馆」时，系统返回「相关聊天记录为空」，但数据中 `localId: 292` 明确包含答案：**Central Perk**（Greenwich Village 区域）。

## 事实核查链路概览

```
用户问题 → parse_intent → [output_mode=fact 或 query_type=event_retrieval]
    → factual_retriever (语义检索 top_k=5 TopicNode)
    → factual_generator (从节点取消息 → 构建 preview → LLM 回答)
```

## 设计缺陷

### 1. 节点级检索 vs 消息级事实

**现状**：ChromaDB 索引的是 **TopicNode**（由 LLM 标注的 topic_name + 消息内容前 ~2000 字符），检索返回的是节点 ID，不是单条消息。

**问题**：
- 若包含答案的节点其 topic_name 与「咖啡馆」「第一次约会」语义不匹配，可能排不进 top 5
- 若该节点内容超过 2000 字符，message 292 可能不在嵌入文本中，检索时无法命中

### 2. top_k=5 过小

**现状**：`factual_retriever_node` 中 `top_k=5`，只取 5 个节点。

**问题**：476 条消息对应大量 TopicNode，若相关节点排名第 6 及以后，直接丢失。

### 3. 消息预览截断（核心缺陷）

**现状**：`factual_generator_node` 对每个节点的消息做「首 3 + 中 2 + 尾 3」预览：

```python
# workflow.py factual_generator_node
if len(msgs) > 8:
    mid = len(msgs) // 2
    preview_msgs = msgs[:3] + msgs[mid-1:mid+1] + msgs[-3:]
else:
    preview_msgs = msgs[:3] + msgs[-2:]
```

**问题**：若 message 292 所在节点有 20+ 条消息，且 292 位于「中间偏前」或「中间偏后」但不在那 2 条「中间样本」里，**LLM 根本看不到这条消息**，只能回答「无法确定」。

举例：节点有 31 条消息 (localId 280–310)，preview 取 index 0,1,2, 14,15, 27,28,29。若 292 对应 index 12，不在 preview 中 → 被截断。

### 4. 无消息级兜底检索

**现状**：事实核查完全依赖 TopicNode 语义检索，没有：
- 关键词/BM25 在原始消息上的检索
- 对「咖啡馆」「date」「first」等实体/事件词的显式匹配

**问题**：纯语义检索在长对话、多主题场景下容易漏掉具体事实。

### 5. GetNodeMessagesTool 的截断

**现状**：`GetNodeMessagesTool` 对单节点消息做「前一半 + 后一半」截断（`max_msgs=20` 时取前 10 + 后 10），且 content 只显示前 100 字符。

**问题**：若 292 在节点中间且节点消息数 > 20，可能被截断；即使未被截断，100 字符的 preview 也可能不足以包含「Central Perk」。

---

## 修复建议

| 缺陷 | 建议 |
|------|------|
| 节点级检索 | 对 fact 类查询增加**消息级**检索：按 localId 范围或关键词在原始消息上做 BM25/关键词匹配，与节点检索结果合并 |
| top_k 过小 | 将 factual 路径的 top_k 提高到 10–15，或根据问题复杂度动态调整 |
| 预览截断 | 对 fact 类查询：**不截断**，或至少对检索到的节点传完整消息；若必须截断，优先保留与问题关键词相关的消息 |
| 无消息级兜底 | 增加 hybrid 检索：语义 (TopicNode) + 关键词 (原始消息 content)，对 fact 查询做两路召回后合并 |
| GetNodeMessagesTool | 对 fact 场景放宽 max_msgs，或对匹配到问题关键词的消息优先完整展示 |

---

## 相关代码位置

- `workflow.py` L276–356: `factual_retriever_node`
- `workflow.py` L364–420: `factual_generator_node`（preview 逻辑）
- `tools.py` L156–198: `GetNodeMessagesTool`
- `layer2.py` L89–99: TopicNode 嵌入（max_chars=2000）
- `query.py` L40–120: `parse_intent`（output_mode / query_type）
