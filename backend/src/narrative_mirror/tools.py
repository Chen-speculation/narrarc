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
# Tool 7: get_all_nodes_overview
# ---------------------------------------------------------------------------

class GetAllNodesOverviewTool:
    name = "get_all_nodes_overview"
    description = "获取所有 TopicNode 的简略列表，用于了解对话整体时间线。不含消息内容。"
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 60, "description": "最多返回节点数"},
        },
    }

    def run(
        self,
        conn: sqlite3.Connection,
        talker_id: str,
        limit: int = 60,
    ) -> ToolResult:
        all_nodes = get_nodes(conn, talker_id)[:limit]
        anchors = get_anchors(conn, talker_id)
        anchor_node_ids = {a.node_id for a in anchors}

        if not all_nodes:
            return ToolResult(content="未找到任何 TopicNode，请先运行 build 管道", data=[])

        lines = [f"全局节点概览 ({len(all_nodes)} 个节点，共 {len(get_nodes(conn, talker_id))} 个):"]
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
