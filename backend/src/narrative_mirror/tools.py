"""Narrative Mirror tool layer — 7 tools for the graph workflow."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import NonCoTLLM

from .models import RawMessage, TopicNode, AnomalyAnchor, MetadataSignals
from .db import (
    get_nodes,
    get_anchors,
    get_all_metadata,
    get_messages_for_node,
    get_nodes_by_time_range,
    get_time_range,
)


# ---------------------------------------------------------------------------
# Core abstractions
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """Result returned by any NarrativeTool.run() call.

    content: human-readable text for LLM consumption (appended to context)
    data:    structured Python data for code-level use
    """
    content: str
    data: Any = None


class NarrativeTool(Protocol):
    """Protocol that all 7 narrative tools must implement."""

    name: str
    description: str
    parameters: dict  # JSON Schema

    def run(self, conn: sqlite3.Connection, talker_id: str, **kwargs) -> ToolResult:
        ...


# ---------------------------------------------------------------------------
# Tool 1: search_semantic
# ---------------------------------------------------------------------------

class SearchSemanticTool:
    name = "search_semantic"
    description = "使用语义向量搜索，找出与 query 最相关的 TopicNode 列表。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"},
            "top_k": {"type": "integer", "default": 10, "description": "返回数量"},
        },
        "required": ["query"],
    }

    def __init__(self, chroma_dir: str, llm_noncot: "NonCoTLLM"):
        self._chroma_dir = chroma_dir
        self._llm = llm_noncot

    def run(self, conn: sqlite3.Connection, talker_id: str, query: str, top_k: int = 10) -> ToolResult:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=self._chroma_dir)
            collection_name = f"narrative_mirror_{talker_id}"
            try:
                collection = client.get_collection(collection_name)
            except Exception:
                return ToolResult(
                    content="未找到语义索引，请先运行 layer2 构建",
                    data=[],
                )

            embedding = self._llm.embed(query)
            results = collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k, collection.count()),
            )

            if not results or not results.get("ids") or not results["ids"][0]:
                return ToolResult(content="语义检索未找到相关节点", data=[])

            ids = results["ids"][0]
            distances = results.get("distances", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]

            lines = [f"语义检索结果 (query='{query}', top_k={top_k}):"]
            for node_id, dist, meta in zip(ids, distances, metadatas):
                topic = meta.get("topic_name", "?") if meta else "?"
                date = meta.get("date", "?") if meta else "?"
                lines.append(f"  [{node_id}] {topic} | {date} | distance={dist:.3f}")

            return ToolResult(content="\n".join(lines), data=ids)

        except Exception as e:
            return ToolResult(content=f"语义检索出错: {e}", data=[])


# ---------------------------------------------------------------------------
# Tool 2: lookup_anchors
# ---------------------------------------------------------------------------

class LookupAnchorsTool:
    name = "lookup_anchors"
    description = "按信号维度和时间范围查询异常锚点（anomaly anchors）。"
    parameters = {
        "type": "object",
        "properties": {
            "signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "信号维度列表，如 ['emotional_tone', 'conflict_intensity']",
            },
            "time_range": {
                "type": "string",
                "description": "时间范围前缀，如 '2024-01'",
            },
        },
    }

    def run(
        self,
        conn: sqlite3.Connection,
        talker_id: str,
        signals: Optional[list[str]] = None,
        time_range: Optional[str] = None,
    ) -> ToolResult:
        anchors = get_anchors(conn, talker_id, signals=signals, time_range=time_range)

        if not anchors:
            return ToolResult(content="未找到匹配的异常锚点", data=[])

        lines = [f"异常锚点列表 ({len(anchors)} 个):"]
        for a in anchors:
            lines.append(
                f"  [{a.node_id}] {a.signal_name}={a.signal_value:.3f} "
                f"(μ={a.baseline_mean:.3f} σ={a.baseline_std:.3f}) | {a.event_date}"
            )

        return ToolResult(content="\n".join(lines), data=[a.node_id for a in anchors])


# ---------------------------------------------------------------------------
# Tool 3: get_node_messages
# ---------------------------------------------------------------------------

class GetNodeMessagesTool:
    name = "get_node_messages"
    description = "获取指定 TopicNode 内的实际消息文本，用于选择证据 ID。"
    parameters = {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "TopicNode 的 node_id"},
            "max_msgs": {"type": "integer", "default": 20, "description": "最多返回消息数"},
        },
        "required": ["node_id"],
    }

    def run(
        self,
        conn: sqlite3.Connection,
        talker_id: str,
        node_id: str,
        max_msgs: int = 20,
    ) -> ToolResult:
        # Look up the node
        all_nodes = get_nodes(conn, talker_id)
        node = next((n for n in all_nodes if n.node_id == node_id), None)
        if node is None:
            return ToolResult(content=f"未找到节点: {node_id}", data=[])

        msgs = get_messages_for_node(conn, talker_id, node)

        if not msgs:
            return ToolResult(content=f"节点 {node_id} 内无消息", data=[])

        # Truncate: first half + last half
        if len(msgs) > max_msgs:
            half = max_msgs // 2
            msgs = msgs[:half] + msgs[-half:]

        lines = [f"节点 [{node_id}] {node.topic_name} 的消息 ({len(msgs)} 条):"]
        for m in msgs:
            sender = "我" if m.is_send else "TA"
            content_preview = m.parsed_content[:100]
            ts = datetime.fromtimestamp(m.create_time / 1000).strftime("%m-%d %H:%M")
            lines.append(f"  [{m.local_id}] {sender}({ts}): {content_preview}")

        return ToolResult(content="\n".join(lines), data=msgs)


# ---------------------------------------------------------------------------
# Tool 4: get_thread_neighbors
# ---------------------------------------------------------------------------

class GetThreadNeighborsTool:
    name = "get_thread_neighbors"
    description = "获取语义线程上与指定节点相关的所有邻居节点摘要。"
    parameters = {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "起始节点的 node_id"},
        },
        "required": ["node_id"],
    }

    def run(
        self,
        conn: sqlite3.Connection,
        talker_id: str,
        node_id: str,
    ) -> ToolResult:
        from .layer2 import get_thread

        thread_ids = get_thread(node_id, talker_id, conn)

        all_nodes = get_nodes(conn, talker_id)
        node_by_id = {n.node_id: n for n in all_nodes}

        if not thread_ids or thread_ids == [node_id]:
            return ToolResult(
                content=f"节点 [{node_id}] 无语义线程连接",
                data=[node_id],
            )

        lines = [f"节点 [{node_id}] 的语义线程邻居 ({len(thread_ids)} 个):"]
        for nid in sorted(thread_ids):
            n = node_by_id.get(nid)
            if n:
                date = datetime.fromtimestamp(n.start_time / 1000).strftime("%Y-%m-%d")
                lines.append(f"  [{nid}] {n.topic_name} | {date}")
            else:
                lines.append(f"  [{nid}] (节点不在数据库中)")

        return ToolResult(content="\n".join(lines), data=thread_ids)


# ---------------------------------------------------------------------------
# Tool 5: list_nodes_by_time
# ---------------------------------------------------------------------------

class ListNodesByTimeTool:
    name = "list_nodes_by_time"
    description = "按时间范围列出 TopicNode 摘要，用于探索特定时期的对话。"
    parameters = {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
        },
        "required": ["start_date", "end_date"],
    }

    def run(
        self,
        conn: sqlite3.Connection,
        talker_id: str,
        start_date: str,
        end_date: str,
    ) -> ToolResult:
        try:
            start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
            end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000) + 86400000  # include end day
        except ValueError:
            return ToolResult(content=f"日期格式错误，请使用 YYYY-MM-DD", data=[])

        all_nodes = get_nodes(conn, talker_id)
        filtered = [n for n in all_nodes if start_ts <= n.start_time <= end_ts]

        if not filtered:
            return ToolResult(content="该时间范围内未找到对话节点", data=[])

        lines = [f"时间范围 [{start_date} ~ {end_date}] 内的节点 ({len(filtered)} 个):"]
        for n in filtered:
            date = datetime.fromtimestamp(n.start_time / 1000).strftime("%Y-%m-%d")
            lines.append(f"  [{n.node_id}] {n.topic_name} | {date}")

        return ToolResult(content="\n".join(lines), data=[n.node_id for n in filtered])


# ---------------------------------------------------------------------------
# Tool 6: get_node_summary
# ---------------------------------------------------------------------------

class GetNodeSummaryTool:
    name = "get_node_summary"
    description = "获取单个节点的完整信息：话题名、7 维信号值和消息预览。"
    parameters = {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "TopicNode 的 node_id"},
        },
        "required": ["node_id"],
    }

    def run(
        self,
        conn: sqlite3.Connection,
        talker_id: str,
        node_id: str,
    ) -> ToolResult:
        from .db import get_metadata_by_node

        all_nodes = get_nodes(conn, talker_id)
        node = next((n for n in all_nodes if n.node_id == node_id), None)
        if node is None:
            return ToolResult(content=f"未找到节点: {node_id}", data=None)

        meta = get_metadata_by_node(conn, node_id)
        date = datetime.fromtimestamp(node.start_time / 1000).strftime("%Y-%m-%d")

        lines = [
            f"节点详情 [{node_id}]",
            f"  话题: {node.topic_name}",
            f"  日期: {date}",
            f"  消息范围: local_id {node.start_local_id} ~ {node.end_local_id}",
        ]

        if meta:
            lines += [
                f"  信号:",
                f"    reply_delay_avg={meta.reply_delay_avg_s:.1f}s",
                f"    emotional_tone={meta.emotional_tone:.3f}",
                f"    conflict_intensity={meta.conflict_intensity:.3f}",
                f"    silence_event={meta.silence_event}",
                f"    term_shift={meta.term_shift_score:.3f}",
                f"    initiator_ratio={meta.initiator_ratio:.3f}",
                f"    topic_frequency={meta.topic_frequency}",
            ]

        # Message preview: up to 5 messages
        msgs = get_messages_for_node(conn, talker_id, node)
        preview = msgs[:3] + msgs[-2:] if len(msgs) > 5 else msgs
        if preview:
            lines.append("  消息预览:")
            for m in preview:
                sender = "我" if m.is_send else "TA"
                lines.append(f"    [{m.local_id}] {sender}: {m.parsed_content[:80]}")

        return ToolResult(content="\n".join(lines), data=node)


# ---------------------------------------------------------------------------
# Stratified sampling and scope-driven retrieval
# ---------------------------------------------------------------------------


def stratified_sample(nodes: list, limit: int) -> list:
    """Sample nodes evenly across time buckets to avoid early bias."""
    if not nodes or len(nodes) <= limit:
        return nodes
    n_buckets = min(8, max(4, limit // 8))
    bucket_size = len(nodes) // n_buckets
    if bucket_size == 0:
        # Fewer nodes than buckets: take evenly from nodes
        step = len(nodes) / limit
        return [nodes[int(j * step)] for j in range(limit)]
    per_bucket = limit // n_buckets
    remainder = limit % n_buckets

    sampled = []
    for i in range(n_buckets):
        start_idx = i * bucket_size
        end_idx = start_idx + bucket_size if i < n_buckets - 1 else len(nodes)
        bucket = nodes[start_idx:end_idx]
        take = per_bucket + (1 if i < remainder else 0)

        if take <= 0:
            continue
        if len(bucket) <= take:
            sampled.extend(bucket)
        else:
            step = len(bucket) / take
            sampled.extend(bucket[int(j * step)] for j in range(take))

    return sampled


def _merge_and_dedup(
    overview: list[TopicNode],
    semantic_results: list,
    node_by_id: dict[str, TopicNode],
) -> list[TopicNode]:
    """Merge overview nodes with semantic results, deduplicate, preserve order."""
    seen = set()
    result = []
    for n in overview:
        if n.node_id not in seen:
            seen.add(n.node_id)
            result.append(n)
    for item in semantic_results:
        nid = item[0] if isinstance(item, (tuple, list)) else item
        if isinstance(nid, str) and nid in node_by_id and nid not in seen:
            seen.add(nid)
            result.append(node_by_id[nid])
    result.sort(key=lambda n: n.start_time)
    return result


def time_diversified_search(
    chroma_collection,
    queries: list[str],
    talker_id: str,
    conn: sqlite3.Connection,
    llm: "NonCoTLLM",
    top_k: int = 30,
) -> list[tuple[str, float, dict]]:
    """Semantic search with time diversification: split into 4 buckets, take top-k/4 per bucket."""
    min_ms, max_ms = get_time_range(conn, talker_id)
    if min_ms == 0 and max_ms == 0:
        return []

    raw_results = []
    for q in queries:
        try:
            embedding = llm.embed(q)
            results = chroma_collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k * 2, chroma_collection.count()),
            )
            if results and results.get("ids") and results["ids"][0]:
                ids = results["ids"][0]
                dists = results.get("distances", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                for i, nid in enumerate(ids):
                    meta = metas[i] if metas and i < len(metas) else {}
                    dist = dists[i] if dists and i < len(dists) else 0.0
                    raw_results.append((nid, dist, meta))
        except Exception:
            pass

    seen = set()
    unique = []
    for nid, dist, meta in raw_results:
        if nid not in seen:
            seen.add(nid)
            unique.append((nid, dist, meta))

    total_days = max(1, (max_ms - min_ms) / (1000 * 86400))
    n_buckets = 4
    bucket_days = total_days / n_buckets
    min_dt = datetime.fromtimestamp(min_ms / 1000)

    buckets: list[list[tuple]] = [[] for _ in range(n_buckets)]
    for nid, dist, meta in unique:
        st = meta.get("start_time", min_ms)
        if isinstance(st, (int, float)):
            node_dt = datetime.fromtimestamp(st / 1000)
        else:
            node_dt = min_dt
        days_offset = (node_dt - min_dt).days
        idx = min(n_buckets - 1, max(0, int(days_offset / bucket_days)))
        buckets[idx].append((nid, dist, meta))

    per_bucket = top_k // n_buckets
    final = []
    for bucket in buckets:
        bucket.sort(key=lambda x: x[1])
        final.extend(bucket[:per_bucket])
    return final


def search_semantic_in_range(
    chroma_collection,
    queries: list[str],
    start_ms: int,
    end_ms: int,
    llm: "NonCoTLLM",
    top_k: int = 20,
) -> list[tuple[str, float, dict]]:
    """Semantic search restricted to time range. ChromaDB metadata start_time is int ms."""
    raw = []
    for q in queries:
        try:
            embedding = llm.embed(q)
            results = chroma_collection.query(
                query_embeddings=[embedding],
                n_results=top_k * 2,
                where={
                    "$and": [
                        {"start_time": {"$gte": start_ms}},
                        {"start_time": {"$lte": end_ms}},
                    ]
                },
            )
            if results and results.get("ids") and results["ids"][0]:
                ids = results["ids"][0]
                dists = results.get("distances", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                for i, nid in enumerate(ids):
                    meta = metas[i] if metas and i < len(metas) else {}
                    dist = dists[i] if dists and i < len(dists) else 0.0
                    raw.append((nid, dist, meta))
        except Exception:
            pass

    seen = set()
    unique = []
    for nid, dist, meta in raw:
        if nid not in seen:
            seen.add(nid)
            unique.append((nid, dist, meta))
    unique.sort(key=lambda x: x[1])
    return unique[:top_k]


def retrieve_by_scope(
    conn: sqlite3.Connection,
    chroma_dir: str,
    talker_id: str,
    scope: dict,
    queries: list[str],
    llm: "NonCoTLLM",
    limit: int = 60,
    anchors: Optional[list] = None,
) -> list[TopicNode]:
    """Retrieve nodes by scope type: global (stratified + time-diversified semantic), time_bounded, topic_bounded."""
    from .time_utils import resolve_time_hint
    from .layer2 import get_thread

    scope_type = scope.get("type", "global")
    all_nodes = get_nodes(conn, talker_id)
    node_by_id = {n.node_id: n for n in all_nodes}

    try:
        import chromadb
        client = chromadb.PersistentClient(path=chroma_dir)
        coll_name = f"narrative_mirror_{talker_id}".replace("-", "_")
        collection = client.get_collection(coll_name)
    except Exception:
        collection = None

    if scope_type == "global":
        overview = stratified_sample(all_nodes, limit)
        semantic_tuples: list = []
        if collection and llm and queries:
            semantic_tuples = time_diversified_search(
                collection, queries, talker_id, conn, llm, top_k=30
            )
        merged = _merge_and_dedup(overview, [t[0] for t in semantic_tuples], node_by_id)
        # Add anchor + thread expansion
        if anchors:
            anchor_ids = {a.node_id for a in anchors}
            for a in anchors:
                anchor_ids.update(get_thread(a.node_id, talker_id, conn))
            prioritised = [n for n in merged if n.node_id in anchor_ids]
            rest = [n for n in merged if n.node_id not in anchor_ids]
            merged = prioritised + rest
        return merged[:limit]

    if scope_type == "time_bounded":
        time_hint = scope.get("time_hint", {})
        start_ms, end_ms = resolve_time_hint(conn, talker_id, time_hint)
        nodes = get_nodes_by_time_range(conn, talker_id, start_ms, end_ms)
        if collection and llm and queries:
            sem = search_semantic_in_range(
                collection, queries, start_ms, end_ms, llm, top_k=20
            )
            sem_ids = [t[0] for t in sem]
            merged = _merge_and_dedup(nodes, sem_ids, node_by_id)
        else:
            merged = nodes
        return merged[:limit]

    if scope_type == "topic_bounded":
        if not collection or not llm or not queries:
            return []
        semantic_tuples = []
        for q in queries:
            try:
                emb = llm.embed(q)
                res = collection.query(
                    query_embeddings=[emb],
                    n_results=limit,
                )
                if res and res.get("ids") and res["ids"][0]:
                    ids = res["ids"][0]
                    dists = res.get("distances", [[]])[0]
                    metas = res.get("metadatas", [[]])[0]
                    for i, nid in enumerate(ids):
                        meta = metas[i] if metas and i < len(metas) else {}
                        dist = dists[i] if dists and i < len(dists) else 0.0
                        semantic_tuples.append((nid, dist, meta))
            except Exception:
                pass
        seen = set()
        unique = []
        for nid, _, meta in sorted(semantic_tuples, key=lambda x: x[1]):
            if nid not in seen:
                seen.add(nid)
                if nid in node_by_id:
                    unique.append(node_by_id[nid])
        return unique[:limit]

    return get_all_nodes_overview(conn, talker_id, limit, scope)


def get_all_nodes_overview(
    conn: sqlite3.Connection,
    talker_id: str,
    limit: int = 60,
    scope: Optional[dict] = None,
) -> list[TopicNode]:
    """Get node overview with stratified sampling or scope-based filtering."""
    all_nodes = get_nodes(conn, talker_id)

    if len(all_nodes) <= limit:
        return all_nodes

    scope_type = (scope or {}).get("type", "global")

    if scope_type == "time_bounded" and scope:
        from .time_utils import resolve_time_hint

        time_hint = scope.get("time_hint", {})
        start_ms, end_ms = resolve_time_hint(conn, talker_id, time_hint)
        filtered = [
            n for n in all_nodes
            if start_ms <= n.start_time <= end_ms
        ]
        return filtered[:limit]

    if scope_type == "topic_bounded":
        return []

    return stratified_sample(all_nodes, limit)


# ---------------------------------------------------------------------------
# Tool 7: get_all_nodes_overview
# ---------------------------------------------------------------------------

class GetAllNodesOverviewTool:
    name = "get_all_nodes_overview"
    description = "获取所有 TopicNode 的简略列表，用于了解对话整体时间线。不含消息内容。支持 scope 分层采样。"
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 60, "description": "最多返回节点数"},
            "scope": {"type": "object", "description": "可选 scope 用于 time_bounded/topic_bounded 过滤"},
        },
    }

    def run(
        self,
        conn: sqlite3.Connection,
        talker_id: str,
        limit: int = 60,
        scope: Optional[dict] = None,
    ) -> ToolResult:
        all_nodes = get_all_nodes_overview(conn, talker_id, limit=limit, scope=scope)
        anchors = get_anchors(conn, talker_id)
        anchor_node_ids = {a.node_id for a in anchors}

        if not all_nodes:
            return ToolResult(content="未找到任何 TopicNode，请先运行 build 管道", data=[])

        total_count = len(get_nodes(conn, talker_id))
        lines = [f"全局节点概览 ({len(all_nodes)} 个节点，共 {total_count} 个):"]
        for n in all_nodes:
            date = datetime.fromtimestamp(n.start_time / 1000).strftime("%Y-%m-%d")
            anchor_mark = " [ANCHOR]" if n.node_id in anchor_node_ids else ""
            lines.append(f"  [{n.node_id}] {n.topic_name} | {date}{anchor_mark}")

        return ToolResult(content="\n".join(lines), data=[n.node_id for n in all_nodes])


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def get_all_tools(
    conn: sqlite3.Connection,
    talker_id: str,
    chroma_dir: str,
    llm_noncot: "NonCoTLLM",
) -> list:
    """Create and return all 7 NarrativeTool instances.

    Args:
        conn: SQLite connection (passed to each tool's run() call).
        talker_id: Conversation ID (passed to each tool's run() call).
        chroma_dir: ChromaDB persistence directory for search_semantic.
        llm_noncot: NonCoTLLM instance for embedding in search_semantic.

    Returns:
        List of 7 NarrativeTool instances.
    """
    return [
        SearchSemanticTool(chroma_dir=chroma_dir, llm_noncot=llm_noncot),
        LookupAnchorsTool(),
        GetNodeMessagesTool(),
        GetThreadNeighborsTool(),
        ListNodesByTimeTool(),
        GetNodeSummaryTool(),
        GetAllNodesOverviewTool(),
    ]
