"""LangGraph-based graph workflow for agentic narrative query."""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Optional, TYPE_CHECKING

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from .models import (
    QueryIntent,
    TopicNode,
    RawMessage,
    NarrativePhase,
    AgentStep,
    AgentTrace,
)
from .db import get_nodes, get_messages_for_node, get_all_metadata, get_time_range
from .query import parse_intent
from .time_utils import resolve_time_hint

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# WorkflowState
# ---------------------------------------------------------------------------

class WorkflowState(TypedDict):
    question: str
    intent: Optional[QueryIntent]
    search_queries: list[str]
    collected_nodes: list[TopicNode]
    collected_messages: dict[str, list[RawMessage]]  # node_id -> messages
    evaluation: str  # "sufficient" or "insufficient: <reason>" or raw JSON
    iterations: int
    phases: list[NarrativePhase]
    trace_steps: list[AgentStep]
    answer_mode: str  # "full_narrative" or "factual_rag"
    factual_answer: Optional[dict]  # {"answer": str, "evidence_msg_ids": list[int]}
    # injected dependencies (not serialized by LangGraph in a meaningful way)
    llm: Any  # CoTLLM
    llm_noncot: Any  # Optional[NonCoTLLM]
    conn: Any  # sqlite3.Connection
    talker_id: str
    tools: list  # list[NarrativeTool]
    chroma_dir: str  # ChromaDB path for retrieve_by_scope
    max_iterations: int
    debug: bool
    retrieval_limit: int  # Max candidate nodes (from config, default 60)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_tool(tools: list, name: str):
    """Find a tool by name from a list of NarrativeTool instances."""
    return next((t for t in tools if t.name == name), None)


# Message-ID pattern: "292消息", "消息292", "message 292", "第292条", "localId 292"
_MSG_ID_PATTERN = re.compile(
    r"(?:消息|message|msg|条|localId|local_id)\s*\d+|\d+\s*(?:消息|message|msg|条)",
    re.IGNORECASE,
)


def _is_message_specific_factual(question: str) -> bool:
    """Heuristic: question references a specific message ID → factual lookup, not multi-phase narrative."""
    return bool(_MSG_ID_PATTERN.search(question))


# ---------------------------------------------------------------------------
# 5.2 planner_node
# ---------------------------------------------------------------------------

def planner_node(state: WorkflowState) -> dict:
    """Parse intent and generate semantic search queries."""
    question = state["question"]
    llm = state["llm"]
    debug = state.get("debug", False)

    if debug:
        print(f"[planner] entry: question='{question[:80]}'", file=sys.stderr)

    # Parse intent using Q1 logic from query.py
    intent = parse_intent(question, llm)

    # Generate 1-3 semantic search queries
    search_queries = [question]
    try:
        system_prompt = (
            "你是一个搜索查询生成助手。根据用户问题，生成1-3个用于ChromaDB语义检索的搜索查询。"
            "查询应覆盖不同角度，帮助检索相关的对话节点。"
            "返回JSON格式: {\"queries\": [\"查询1\", \"查询2\", ...]}"
        )
        prompt = f"用户问题: {question}\n\n请生成1-3个语义检索查询。"
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=256, response_format="json_object")
        data = json.loads(response)
        queries = data.get("queries", [])
        if isinstance(queries, list) and len(queries) > 0:
            search_queries = [q for q in queries if isinstance(q, str) and q.strip()]
            if not search_queries:
                search_queries = [question]
    except Exception:
        search_queries = [question]

    step = AgentStep(
        node_name="planner",
        input_summary=f"question='{question[:50]}'",
        output_summary=f"intent={intent.query_type}, queries={search_queries}",
        llm_calls=2,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(
            f"[planner] exit: intent={intent.query_type}, "
            f"focus_dimensions={intent.focus_dimensions}, "
            f"search_queries={search_queries}",
            file=sys.stderr,
        )

    # Map output_mode and query_type to answer_mode
    output_mode = getattr(intent, "output_mode", None) or "narrative"
    answer_mode = (
        "factual_rag"
        if output_mode == "fact" or intent.query_type in ("time_point", "event_retrieval")
        else "full_narrative"
    )
    # Heuristic fallback: question references specific message ID (e.g. "292消息", "message 292")
    # → force factual_rag so we get direct answer, not multi-phase narrative
    if answer_mode == "full_narrative" and _is_message_specific_factual(question):
        answer_mode = "factual_rag"

    return {
        "intent": intent,
        "search_queries": search_queries,
        "answer_mode": answer_mode,
        "trace_steps": existing_steps,
    }


# ---------------------------------------------------------------------------
# 5.3 retriever_node
# ---------------------------------------------------------------------------

def retriever_node(state: WorkflowState) -> dict:
    """Retrieve relevant nodes via scope-driven retrieval or fallback to anchors/semantic/overview."""
    intent = state["intent"]
    search_queries = state["search_queries"]
    tools = state["tools"]
    conn = state["conn"]
    talker_id = state["talker_id"]
    chroma_dir = state.get("chroma_dir", "")
    llm_noncot = state.get("llm_noncot")
    debug = state.get("debug", False)

    if debug:
        print(
            f"[retriever] entry: intent={intent.query_type if intent else 'None'}, "
            f"queries={search_queries}, scope={intent.scope.get('type') if intent and intent.scope else None}",
            file=sys.stderr,
        )

    scope = (intent.scope or {"type": "global"}) if intent else {"type": "global"}
    get_node_messages_tool = _get_tool(tools, "get_node_messages")

    # Use retrieve_by_scope when chroma_dir and llm_noncot available
    if chroma_dir and llm_noncot is not None:
        from .tools import retrieve_by_scope
        from .query import lookup_anchors

        anchors = lookup_anchors(intent, talker_id, conn) if intent else []
        anchor_node_ids = {a.node_id for a in anchors}
        retrieval_limit = state.get("retrieval_limit", 60)
        merged_nodes = retrieve_by_scope(
            conn=conn,
            chroma_dir=chroma_dir,
            talker_id=talker_id,
            scope=scope,
            queries=search_queries,
            llm=llm_noncot,
            limit=retrieval_limit,
            anchors=anchors,
        )
    else:
        # Fallback: original tool-based retrieval
        lookup_anchors_tool = _get_tool(tools, "lookup_anchors")
        search_semantic_tool = _get_tool(tools, "search_semantic")
        get_thread_neighbors_tool = _get_tool(tools, "get_thread_neighbors")
        get_all_nodes_overview_tool = _get_tool(tools, "get_all_nodes_overview")
        get_node_messages_tool = _get_tool(tools, "get_node_messages")

        collected_node_ids: set[str] = set()
        anchor_node_ids: set[str] = set()

        if lookup_anchors_tool and intent:
            signals = intent.focus_dimensions if intent.focus_dimensions else None
            time_range = intent.time_range if intent.time_range else None
            result = lookup_anchors_tool.run(conn, talker_id, signals=signals, time_range=time_range)
            if isinstance(result.data, list):
                for nid in result.data:
                    if isinstance(nid, str):
                        collected_node_ids.add(nid)
                        anchor_node_ids.add(nid)

        if search_semantic_tool:
            for query in search_queries:
                result = search_semantic_tool.run(conn, talker_id, query=query, top_k=10)
                if isinstance(result.data, list):
                    for nid in result.data:
                        if isinstance(nid, str):
                            collected_node_ids.add(nid)

        if get_thread_neighbors_tool:
            for anchor_nid in list(anchor_node_ids):
                result = get_thread_neighbors_tool.run(conn, talker_id, node_id=anchor_nid)
                if isinstance(result.data, list):
                    for nid in result.data:
                        if isinstance(nid, str):
                            collected_node_ids.add(nid)

        if intent and intent.query_type == "arc_narrative" and get_all_nodes_overview_tool:
            retrieval_limit = state.get("retrieval_limit", 60)
            result = get_all_nodes_overview_tool.run(conn, talker_id, limit=retrieval_limit, scope=scope)
            if isinstance(result.data, list):
                for nid in result.data:
                    if isinstance(nid, str):
                        collected_node_ids.add(nid)

        all_nodes = get_nodes(conn, talker_id)
        node_by_id = {n.node_id: n for n in all_nodes}
        merged_nodes = [node_by_id[nid] for nid in collected_node_ids if nid in node_by_id]
        merged_nodes.sort(key=lambda n: n.start_time)

    # Load messages for anchor nodes
    collected_messages: dict[str, list[RawMessage]] = dict(state.get("collected_messages", {}))
    if get_node_messages_tool:
        for anchor_nid in anchor_node_ids:
            if anchor_nid not in collected_messages:
                result = get_node_messages_tool.run(conn, talker_id, node_id=anchor_nid)
                if isinstance(result.data, list) and result.data:
                    collected_messages[anchor_nid] = result.data

    step = AgentStep(
        node_name="retriever",
        input_summary=f"queries={search_queries[:2]}, scope={scope.get('type')}",
        output_summary=f"collected_nodes={len(merged_nodes)}, messages_loaded={len(collected_messages)}",
        llm_calls=0,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(
            f"[retriever] exit: collected_nodes={len(merged_nodes)}",
            file=sys.stderr,
        )

    return {
        "collected_nodes": merged_nodes,
        "collected_messages": collected_messages,
        "trace_steps": existing_steps,
    }


# ---------------------------------------------------------------------------
# 5.3b route_after_planning
# ---------------------------------------------------------------------------

def route_after_planning(state: WorkflowState) -> str:
    """Route to agentic path (retrieve) for all queries. Factual and narrative both go through Retriever -> Grader -> Explorer -> Generator."""
    return "retrieve"


# ---------------------------------------------------------------------------
# 5.3c factual_retriever_node
# ---------------------------------------------------------------------------

def factual_retriever_node(state: WorkflowState) -> dict:
    """Lightweight retrieval for factual queries: semantic search + optional time filter."""
    intent = state["intent"]
    question = state["question"]
    tools = state["tools"]
    conn = state["conn"]
    talker_id = state["talker_id"]
    debug = state.get("debug", False)

    if debug:
        print(
            f"[factual_retriever] entry: question='{question[:50]}', "
            f"time_range={intent.time_range if intent else None}",
            file=sys.stderr,
        )

    search_semantic_tool = _get_tool(tools, "search_semantic")
    list_nodes_by_time_tool = _get_tool(tools, "list_nodes_by_time")
    get_node_messages_tool = _get_tool(tools, "get_node_messages")

    collected_node_ids: set[str] = set()

    # 1. Single semantic search with the question (top_k=15 for better recall)
    if search_semantic_tool:
        result = search_semantic_tool.run(conn, talker_id, query=question, top_k=15)
        if isinstance(result.data, list):
            for nid in result.data:
                if isinstance(nid, str):
                    collected_node_ids.add(nid)

    # 2. If time_range present, also do time-based retrieval
    if intent and intent.time_range and list_nodes_by_time_tool:
        time_range = intent.time_range
        if len(time_range) == 7:  # "YYYY-MM"
            year, month = int(time_range[:4]), int(time_range[5:7])
            start_date = f"{time_range}-01"
            if month == 12:
                end_date = f"{year + 1}-01-01"
            else:
                end_date = f"{year}-{month + 1:02d}-01"
        else:
            start_date = time_range
            end_date = time_range
        result = list_nodes_by_time_tool.run(conn, talker_id, start_date=start_date, end_date=end_date)
        if isinstance(result.data, list):
            for nid in result.data:
                if isinstance(nid, str):
                    collected_node_ids.add(nid)

    # Load and sort nodes
    all_nodes = get_nodes(conn, talker_id)
    node_by_id = {n.node_id: n for n in all_nodes}
    merged_nodes = [node_by_id[nid] for nid in collected_node_ids if nid in node_by_id]
    merged_nodes.sort(key=lambda n: n.start_time)

    # Load messages for all retrieved nodes
    collected_messages: dict[str, list[RawMessage]] = {}
    if get_node_messages_tool:
        for node in merged_nodes:
            result = get_node_messages_tool.run(conn, talker_id, node_id=node.node_id)
            if isinstance(result.data, list) and result.data:
                collected_messages[node.node_id] = result.data

    step = AgentStep(
        node_name="factual_retriever",
        input_summary=f"question='{question[:50]}', time_range={intent.time_range if intent else None}",
        output_summary=f"collected_nodes={len(merged_nodes)}",
        llm_calls=0,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(f"[factual_retriever] exit: collected_nodes={len(merged_nodes)}", file=sys.stderr)

    return {
        "collected_nodes": merged_nodes,
        "collected_messages": collected_messages,
        "trace_steps": existing_steps,
    }


# ---------------------------------------------------------------------------
# 5.3d factual_generator_node
# ---------------------------------------------------------------------------

def factual_generator_node(state: WorkflowState) -> dict:
    """Generate a direct factual answer from retrieved nodes."""
    collected_nodes = state["collected_nodes"]
    collected_messages = state.get("collected_messages", {})
    question = state["question"]
    llm = state["llm"]
    conn = state["conn"]
    talker_id = state["talker_id"]
    debug = state.get("debug", False)

    if debug:
        print(f"[factual_generator] entry: nodes={len(collected_nodes)}", file=sys.stderr)

    # Build message context with previews
    all_msg_entries = []
    valid_ids: set[int] = set()
    for node in collected_nodes:
        msgs = collected_messages.get(node.node_id)
        if msgs is None:
            msgs = get_messages_for_node(conn, talker_id, node)
        # For factual queries, use all messages to avoid missing specific facts
        preview_msgs = msgs
        for m in preview_msgs:
            valid_ids.add(m.local_id)
            sender = "我" if m.is_send else "TA"
            date_str = datetime.fromtimestamp(m.create_time / 1000).strftime("%Y-%m-%d %H:%M")
            all_msg_entries.append({
                "id": m.local_id,
                "date": date_str,
                "sender": sender,
                "content": m.parsed_content[:200],
            })

    system_prompt = (
        "你是一个聊天记录查询助手。根据提供的聊天消息，直接回答用户的问题。\n"
        "回答要简洁直接，包含具体事实。\n"
        "返回JSON格式: {\"answer\": \"直接回答\", \"evidence_msg_ids\": [3-5个最相关的消息ID整数]}"
    )
    prompt = (
        f"用户问题: {question}\n\n"
        f"相关聊天记录:\n"
        f"{json.dumps(all_msg_entries, ensure_ascii=False, indent=2)}\n\n"
        "请直接回答用户的问题，并列出支撑答案的消息ID。"
    )

    factual_answer: dict = {"answer": "未找到相关记录。", "evidence_msg_ids": []}
    try:
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=1024, response_format="json_object")
        data = json.loads(response)
        answer_text = data.get("answer", "未找到相关记录。")
        raw_ids = data.get("evidence_msg_ids", [])
        evidence_ids: list[int] = []
        for x in raw_ids:
            try:
                mid = int(x)
                if mid in valid_ids:
                    evidence_ids.append(mid)
            except (ValueError, TypeError):
                pass
        factual_answer = {"answer": answer_text, "evidence_msg_ids": evidence_ids}
    except Exception:
        pass

    # Create a NarrativePhase for backward compatibility
    phase = NarrativePhase(
        phase_title="事实查证",
        time_range="",
        core_conclusion=factual_answer["answer"],
        evidence_msg_ids=factual_answer["evidence_msg_ids"],
        evidence_segments=[],
        reasoning_chain="",
        uncertainty_note="",
        verified=False,
    )

    step = AgentStep(
        node_name="factual_generator",
        input_summary=f"nodes={len(collected_nodes)}, messages={len(all_msg_entries)}",
        output_summary=f"answer='{factual_answer['answer'][:60]}'",
        llm_calls=1,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(f"[factual_generator] exit: answer='{factual_answer['answer'][:60]}'", file=sys.stderr)

    return {
        "phases": [phase],
        "factual_answer": factual_answer,
        "trace_steps": existing_steps,
    }


# ---------------------------------------------------------------------------
# 5.4 grader_node
# ---------------------------------------------------------------------------

def _grade_coverage_by_scope(
    collected_nodes: list,
    scope: dict,
    conn,
    talker_id: str,
) -> Optional[str]:
    """Programmatic scope-based coverage check. Returns evaluation JSON or None to fall back to LLM."""
    scope_type = scope.get("type", "global")

    if scope_type == "global":
        min_ms, max_ms = get_time_range(conn, talker_id)
        if min_ms == 0 and max_ms == 0:
            return None
        min_dt = datetime.fromtimestamp(min_ms / 1000)
        max_dt = datetime.fromtimestamp(max_ms / 1000)
        total_days = max(1, (max_dt - min_dt).days)
        quarter_days = total_days / 4
        gaps = []
        for i in range(4):
            q_start_ms = int((min_dt + timedelta(days=i * quarter_days)).timestamp() * 1000)
            q_end_ms = int((min_dt + timedelta(days=(i + 1) * quarter_days)).timestamp() * 1000)
            count = sum(1 for n in collected_nodes if q_start_ms <= n.start_time <= q_end_ms)
            if count < 2:
                gaps.append({
                    "type": "time_search",
                    "quarter": f"Q{i + 1}",
                    "start_date": datetime.fromtimestamp(q_start_ms / 1000).strftime("%Y-%m-%d"),
                    "end_date": datetime.fromtimestamp(q_end_ms / 1000).strftime("%Y-%m-%d"),
                    "current_count": count,
                })
        if gaps:
            return json.dumps({"evaluation": "insufficient", "reason": "时间覆盖不足", "gaps": gaps})
        return '{"evaluation": "sufficient"}'

    if scope_type == "time_bounded":
        time_hint = scope.get("time_hint", {})
        start_ms, end_ms = resolve_time_hint(conn, talker_id, time_hint)
        in_range = [n for n in collected_nodes if start_ms <= n.start_time <= end_ms]
        if len(in_range) >= 5:
            return '{"evaluation": "sufficient"}'
        return json.dumps({
            "evaluation": "insufficient",
            "reason": "目标时间段内节点不足",
            "gaps": [{
                "type": "time_search",
                "start_date": datetime.fromtimestamp(start_ms / 1000).strftime("%Y-%m-%d"),
                "end_date": datetime.fromtimestamp(end_ms / 1000).strftime("%Y-%m-%d"),
                "current_count": len(in_range),
            }],
        })

    if scope_type == "topic_bounded":
        if len(collected_nodes) >= 3:
            return '{"evaluation": "sufficient"}'
        return json.dumps({
            "evaluation": "insufficient",
            "reason": "主题相关节点不足",
            "gaps": [{"type": "semantic_expand", "suggestion": "用同义词或相关表述扩展语义搜索"}],
        })

    return None


def grader_node(state: WorkflowState) -> dict:
    """Evaluate whether collected nodes are sufficient to answer the question."""
    collected_nodes = state["collected_nodes"]
    question = state["question"]
    intent = state.get("intent")
    conn = state["conn"]
    talker_id = state["talker_id"]
    llm = state["llm"]
    debug = state.get("debug", False)

    if debug:
        print(
            f"[grader] entry: collected_nodes={len(collected_nodes)}, "
            f"iterations={state.get('iterations', 0)}",
            file=sys.stderr,
        )

    # Factual queries: skip exploration, go straight to generator
    answer_mode = state.get("answer_mode", "full_narrative")
    if answer_mode == "factual_rag":
        step = AgentStep(
            node_name="grader",
            input_summary=f"nodes={len(collected_nodes)}, factual_rag=True",
            output_summary="evaluation=sufficient (factual fast-path)",
            llm_calls=0,
            timestamp_ms=int(time.time() * 1000),
        )
        return {
            "evaluation": '{"evaluation": "sufficient"}',
            "trace_steps": list(state.get("trace_steps", [])) + [step],
        }

    # Scope-based programmatic check first
    scope = (intent.scope or {}) if intent else {}
    if scope.get("type"):
        prog_eval = _grade_coverage_by_scope(collected_nodes, scope, conn, talker_id)
        if prog_eval is not None:
            step = AgentStep(
                node_name="grader",
                input_summary=f"nodes={len(collected_nodes)}, scope={scope.get('type')}",
                output_summary=f"evaluation={prog_eval[:80]}",
                llm_calls=0,
                timestamp_ms=int(time.time() * 1000),
            )
            return {
                "evaluation": prog_eval,
                "trace_steps": list(state.get("trace_steps", [])) + [step],
            }

    # Build prompt summarizing collected nodes
    node_count = len(collected_nodes)
    if node_count > 0:
        start_ts = collected_nodes[0].start_time
        end_ts = collected_nodes[-1].start_time
        start_date = datetime.fromtimestamp(start_ts / 1000).strftime("%Y-%m-%d")
        end_date = datetime.fromtimestamp(end_ts / 1000).strftime("%Y-%m-%d")
        topics = [n.topic_name for n in collected_nodes[:5]]
        date_range = f"{start_date} ~ {end_date}"
    else:
        date_range = "无数据"
        topics = []

    temporal_dist_text = ""
    if intent and getattr(intent, "query_type", None) == "arc_narrative" and collected_nodes:
        ts_list = [n.start_time for n in collected_nodes]
        ts_min, ts_max = min(ts_list), max(ts_list)
        ts_span = ts_max - ts_min
        q_counts = [0, 0, 0, 0]
        for n in collected_nodes:
            if ts_span <= 0:
                q_counts[0] += 1
            else:
                ratio = (n.start_time - ts_min) / ts_span
                qi = min(3, int(ratio * 4))
                q_counts[qi] += 1
        temporal_dist_text = (
            f"\n- 时间分布: Q1={q_counts[0]}, Q2={q_counts[1]}, Q3={q_counts[2]}, Q4={q_counts[3]}"
        )

    system_prompt = (
        "你是一个信息充足性评估助手。评估当前收集的节点是否足够回答用户的问题。\n"
        "对于 arc_narrative（完整叙事弧）类型的查询，如果时间分布中任何时段（Q1/Q2/Q3/Q4）的节点数为0，"
        "则必须返回 insufficient 并建议 time_search，在 params 或 gaps 中指定该缺失时段对应的日期范围。\n"
        "返回JSON格式: "
        '{"evaluation": "sufficient"} 或 '
        '{"evaluation": "insufficient", "reason": "原因", '
        '"suggested_action": "time_search/topic_search/thread_expand", '
        '"params": {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}}'
    )
    prompt = (
        f"用户问题: {question}\n\n"
        f"当前收集到的节点信息:\n"
        f"- 节点数量: {node_count}\n"
        f"- 日期范围: {date_range}\n"
        f"- 代表话题: {topics}"
        f"{temporal_dist_text}\n\n"
        "请评估当前信息是否足够回答用户问题。"
    )

    evaluation = '{"evaluation": "sufficient"}'
    try:
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=512, response_format="json_object")
        data = json.loads(response)
        if "evaluation" in data:
            evaluation = response
        else:
            evaluation = '{"evaluation": "sufficient"}'
    except Exception:
        evaluation = '{"evaluation": "sufficient"}'

    step = AgentStep(
        node_name="grader",
        input_summary=f"nodes={node_count}, date_range={date_range}",
        output_summary=f"evaluation={evaluation[:80]}",
        llm_calls=1,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(f"[grader] exit: evaluation={evaluation[:100]}", file=sys.stderr)

    return {
        "evaluation": evaluation,
        "trace_steps": existing_steps,
    }


# ---------------------------------------------------------------------------
# 5.5 route_after_grading
# ---------------------------------------------------------------------------

def route_after_grading(state: WorkflowState) -> str:
    """Route to 'generate' or 'explore' based on grader evaluation."""
    evaluation = state.get("evaluation", "sufficient")
    iterations = state.get("iterations", 0)
    max_iterations = state.get("max_iterations", 3)

    # Force generate if max iterations reached
    if iterations >= max_iterations:
        return "generate"

    # Parse JSON evaluation
    try:
        data = json.loads(evaluation)
        eval_value = data.get("evaluation", "sufficient")
        if eval_value == "sufficient":
            return "generate"
        else:
            return "explore"
    except (json.JSONDecodeError, AttributeError):
        # Fall back to string check
        if evaluation.startswith("sufficient"):
            return "generate"
        return "explore"


# ---------------------------------------------------------------------------
# 5.6 explorer_node
# ---------------------------------------------------------------------------

def explorer_node(state: WorkflowState) -> dict:
    """Explore additional nodes based on grader's suggested action."""
    evaluation = state.get("evaluation", '{"evaluation": "sufficient"}')
    collected_nodes = list(state["collected_nodes"])
    collected_messages = dict(state.get("collected_messages", {}))
    tools = state["tools"]
    conn = state["conn"]
    talker_id = state["talker_id"]
    iterations = state.get("iterations", 0)
    debug = state.get("debug", False)

    if debug:
        print(
            f"[explorer] entry: iterations={iterations}, "
            f"evaluation={evaluation[:80]}",
            file=sys.stderr,
        )

    # Parse evaluation to get gaps or suggested_action/params
    suggested_action = "topic_search"
    params = {}
    evaluation_reason = ""
    gaps = []
    try:
        data = json.loads(evaluation)
        gaps = data.get("gaps", [])
        suggested_action = data.get("suggested_action", "topic_search")
        params = data.get("params", {})
        evaluation_reason = data.get("reason", "")
    except (json.JSONDecodeError, AttributeError):
        evaluation_reason = evaluation

    list_nodes_by_time_tool = _get_tool(tools, "list_nodes_by_time")
    search_semantic_tool = _get_tool(tools, "search_semantic")
    get_thread_neighbors_tool = _get_tool(tools, "get_thread_neighbors")
    get_node_messages_tool = _get_tool(tools, "get_node_messages")

    from .db import get_nodes_by_time_range

    existing_node_ids = {n.node_id for n in collected_nodes}
    new_node_ids: set[str] = set()

    # Execute action based on gaps (P1-2) or suggested_action
    if gaps:
        for gap in gaps:
            gap_type = gap.get("type", "")
            if gap_type == "time_search":
                start_date = gap.get("start_date", "2020-01-01")
                end_date = gap.get("end_date", "2030-12-31")
                start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
                end_ts = int((datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp() * 1000) - 1
                nodes = get_nodes_by_time_range(conn, talker_id, start_ts, end_ts)
                for n in nodes[:15]:
                    if n.node_id not in existing_node_ids:
                        new_node_ids.add(n.node_id)
            elif gap_type == "semantic_expand" and search_semantic_tool:
                query = gap.get("suggestion", evaluation_reason) or evaluation_reason or "对话"
                result = search_semantic_tool.run(conn, talker_id, query=query, top_k=15)
                if isinstance(result.data, list):
                    for nid in result.data:
                        if isinstance(nid, str) and nid not in existing_node_ids:
                            new_node_ids.add(nid)
    elif suggested_action == "time_search" and list_nodes_by_time_tool:
        start_date = params.get("start_date", "2020-01-01")
        end_date = params.get("end_date", "2030-12-31")
        result = list_nodes_by_time_tool.run(conn, talker_id, start_date=start_date, end_date=end_date)
        if isinstance(result.data, list):
            for nid in result.data:
                if isinstance(nid, str) and nid not in existing_node_ids:
                    new_node_ids.add(nid)

    elif suggested_action == "topic_search" and search_semantic_tool:
        query = params.get("query", evaluation_reason) or evaluation_reason or "对话"
        result = search_semantic_tool.run(conn, talker_id, query=query, top_k=10)
        if isinstance(result.data, list):
            for nid in result.data:
                if isinstance(nid, str) and nid not in existing_node_ids:
                    new_node_ids.add(nid)

    elif suggested_action == "thread_expand" and get_thread_neighbors_tool:
        node_id = params.get("node_id", "")
        if not node_id and collected_nodes:
            node_id = collected_nodes[0].node_id
        if node_id:
            result = get_thread_neighbors_tool.run(conn, talker_id, node_id=node_id)
            if isinstance(result.data, list):
                for nid in result.data:
                    if isinstance(nid, str) and nid not in existing_node_ids:
                        new_node_ids.add(nid)

    else:
        # Default: semantic search with reason text
        if search_semantic_tool:
            query = evaluation_reason or "对话"
            result = search_semantic_tool.run(conn, talker_id, query=query, top_k=10)
            if isinstance(result.data, list):
                for nid in result.data:
                    if isinstance(nid, str) and nid not in existing_node_ids:
                        new_node_ids.add(nid)

    # Load new nodes
    all_nodes = get_nodes(conn, talker_id)
    node_by_id = {n.node_id: n for n in all_nodes}
    new_nodes = [node_by_id[nid] for nid in new_node_ids if nid in node_by_id]

    # Load messages for new nodes
    if get_node_messages_tool:
        for node in new_nodes:
            if node.node_id not in collected_messages:
                result = get_node_messages_tool.run(conn, talker_id, node_id=node.node_id)
                if isinstance(result.data, list) and result.data:
                    collected_messages[node.node_id] = result.data

    # Merge and sort
    merged = collected_nodes + new_nodes
    merged.sort(key=lambda n: n.start_time)

    # If no new nodes found, force sufficient to avoid infinite loop
    new_evaluation = evaluation
    if not new_nodes:
        new_evaluation = '{"evaluation": "sufficient"}'

    step = AgentStep(
        node_name="explorer",
        input_summary=f"suggested_action={suggested_action}, reason='{evaluation_reason[:40]}'",
        output_summary=f"new_nodes={len(new_nodes)}, total_nodes={len(merged)}",
        llm_calls=0,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(
            f"[explorer] exit: new_nodes={len(new_nodes)}, "
            f"total_nodes={len(merged)}, iterations={iterations + 1}",
            file=sys.stderr,
        )

    return {
        "collected_nodes": merged,
        "collected_messages": collected_messages,
        "iterations": iterations + 1,
        "evaluation": new_evaluation,
        "trace_steps": existing_steps,
    }


# ---------------------------------------------------------------------------
# 5.7 generator_node
# ---------------------------------------------------------------------------

def _generator_factual_branch(
    state: WorkflowState,
    collected_nodes: list,
    collected_messages: dict,
    question: str,
    llm,
    conn,
    talker_id: str,
    debug: bool,
) -> dict:
    """Factual query branch: direct answer + evidence, no multi-stage narrative, no uncertainty_note."""
    all_msg_entries = []
    valid_ids: set[int] = set()
    for node in collected_nodes:
        msgs = collected_messages.get(node.node_id)
        if msgs is None:
            msgs = get_messages_for_node(conn, talker_id, node)
        for m in msgs:
            valid_ids.add(m.local_id)
            sender = "我" if m.is_send else "TA"
            date_str = datetime.fromtimestamp(m.create_time / 1000).strftime("%Y-%m-%d %H:%M")
            all_msg_entries.append({
                "id": m.local_id,
                "date": date_str,
                "sender": sender,
                "content": m.parsed_content[:200],
            })

    system_prompt = (
        "你是一个聊天记录查询助手。根据提供的聊天消息，直接回答用户的问题。\n"
        "回答要简洁直接，包含具体事实。不要输出多阶段叙事或不确定性说明。\n"
        "返回JSON格式: {\"answer\": \"直接回答\", \"evidence_msg_ids\": [3-5个最相关的消息ID整数]}"
    )
    prompt = (
        f"用户问题: {question}\n\n"
        f"相关聊天记录:\n"
        f"{json.dumps(all_msg_entries, ensure_ascii=False, indent=2)}\n\n"
        "请直接回答用户的问题，并列出支撑答案的消息ID。"
    )

    factual_answer: dict = {"answer": "未找到相关记录。", "evidence_msg_ids": []}
    try:
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=1024, response_format="json_object")
        data = json.loads(response)
        answer_text = data.get("answer", "未找到相关记录。")
        raw_ids = data.get("evidence_msg_ids", [])
        evidence_ids: list[int] = []
        for x in raw_ids:
            try:
                mid = int(x)
                if mid in valid_ids:
                    evidence_ids.append(mid)
            except (ValueError, TypeError):
                pass
        factual_answer = {"answer": answer_text, "evidence_msg_ids": evidence_ids}
    except Exception:
        pass

    phase = NarrativePhase(
        phase_title="事实回答",
        time_range="",
        core_conclusion=factual_answer["answer"],
        evidence_msg_ids=factual_answer["evidence_msg_ids"],
        evidence_segments=[],
        reasoning_chain="",
        uncertainty_note="",
        verified=False,
    )

    step = AgentStep(
        node_name="generator",
        input_summary=f"factual: nodes={len(collected_nodes)}, messages={len(all_msg_entries)}",
        output_summary=f"answer='{factual_answer['answer'][:60]}'",
        llm_calls=1,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(f"[generator] factual exit: answer='{factual_answer['answer'][:60]}'", file=sys.stderr)

    return {
        "phases": [phase],
        "factual_answer": factual_answer,
        "trace_steps": existing_steps,
    }


def generator_node(state: WorkflowState) -> dict:
    """Generate NarrativePhase objects from collected nodes. Supports narrative/summary/factual output_mode."""
    collected_nodes = state["collected_nodes"]
    collected_messages = state.get("collected_messages", {})
    question = state["question"]
    intent = state.get("intent")
    llm = state["llm"]
    conn = state["conn"]
    talker_id = state["talker_id"]
    debug = state.get("debug", False)
    answer_mode = state.get("answer_mode", "full_narrative")

    output_mode = getattr(intent, "output_mode", None) if intent else "narrative"
    if output_mode not in ("narrative", "summary", "fact"):
        output_mode = "narrative"

    if debug:
        print(
            f"[generator] entry: collected_nodes={len(collected_nodes)}, "
            f"output_mode={output_mode}, answer_mode={answer_mode}, question='{question[:50]}'",
            file=sys.stderr,
        )

    # Factual queries: direct answer format, no multi-stage narrative, no uncertainty_note
    if answer_mode == "factual_rag":
        return _generator_factual_branch(
            state=state,
            collected_nodes=collected_nodes,
            collected_messages=collected_messages,
            question=question,
            llm=llm,
            conn=conn,
            talker_id=talker_id,
            debug=debug,
        )

    # Task 1.1: Compute Q1-Q4 temporal boundaries from all collected nodes
    if collected_nodes:
        ts_list = [n.start_time for n in collected_nodes]
        ts_min, ts_max = min(ts_list), max(ts_list)
        ts_span = ts_max - ts_min

        def _get_temporal_position(start_time: int) -> str:
            if ts_span <= 0:
                return "Q1"
            ratio = (start_time - ts_min) / ts_span
            if ratio < 0.25:
                return "Q1"
            elif ratio < 0.50:
                return "Q2"
            elif ratio < 0.75:
                return "Q3"
            else:
                return "Q4"
    else:
        def _get_temporal_position(start_time: int) -> str:  # type: ignore[misc]
            return "Q1"

    # Task 1.3: Load all metadata signals for temporal/emotional enrichment
    all_metadata = get_all_metadata(conn, talker_id)
    meta_by_node_id = {m.node_id: m for m in all_metadata}

    # Build node summaries with message previews
    node_summaries = []
    for node in collected_nodes:
        # Get messages: from collected_messages or load from DB
        msgs = collected_messages.get(node.node_id)
        if msgs is None:
            msgs = get_messages_for_node(conn, talker_id, node)

        # Build messages_preview: first 3 + middle 2 + last 3 for large nodes
        if len(msgs) > 8:
            mid = len(msgs) // 2
            preview_msgs = msgs[:3] + msgs[mid - 1 : mid + 1] + msgs[-3:]
        elif len(msgs) > 5:
            preview_msgs = msgs[:3] + msgs[-2:]
        else:
            preview_msgs = msgs

        messages_preview = []
        for m in preview_msgs:
            sender = "我" if m.is_send else "TA"
            messages_preview.append({
                "id": m.local_id,
                "sender": sender,
                "content": m.parsed_content[:100],
            })

        all_message_ids = [m.local_id for m in msgs]
        date_str = datetime.fromtimestamp(node.start_time / 1000).strftime("%Y-%m-%d")
        # Task 1.2: Add temporal_position field
        entry: dict = {
            "node_id": node.node_id,
            "topic": node.topic_name,
            "date": date_str,
            "start_id": node.start_local_id,
            "end_id": node.end_local_id,
            "all_message_ids": all_message_ids,
            "temporal_position": _get_temporal_position(node.start_time),
            "messages_preview": messages_preview,
        }
        # Task 1.3: Add emotional_tone and conflict_intensity if metadata available
        meta = meta_by_node_id.get(node.node_id)
        if meta is not None:
            entry["emotional_tone"] = meta.emotional_tone
            entry["conflict_intensity"] = meta.conflict_intensity
        node_summaries.append(entry)

    # P2-1: Dynamic prompt by output_mode
    from .query import OUTPUT_MODES

    cfg = OUTPUT_MODES.get(output_mode, OUTPUT_MODES["narrative"])
    time_span_days = 1
    if collected_nodes:
        ts_min = min(n.start_time for n in collected_nodes)
        ts_max = max(n.start_time for n in collected_nodes)
        time_span_days = max(1, (ts_max - ts_min) / (1000 * 86400))
    phase_count = max(cfg["min_phases"], min(cfg["max_phases"], max(1, int(time_span_days // 180))))
    phase_count = min(phase_count, max(1, len(collected_nodes) // 3))

    if output_mode == "summary":
        system_prompt = (
            f"围绕用户问题做主题汇总。输出 JSON：\n"
            f'{{"summary": "整体概括，2-3句话", "themes": ['
            f'{{"theme_title": "主题标题", "description": "描述", "evidence_msg_ids": [2-5条], "time_range": "涉及的时间范围"}}'
            f"]}}\n"
            f"主题数量 {cfg['min_phases']}-{cfg['max_phases']} 个，根据实际内容决定。"
        )
    else:
        ev_min, ev_max = cfg["evidence_per_phase"]
        system_prompt = (
            f"你是一个叙事分析助手。根据对话节点的时间线，将其分割为 {phase_count} 个叙事阶段。\n\n"
            "每个阶段需要包含:\n"
            "- phase_title: 阶段标题（简短有力）\n"
            "- time_range: 时间范围（如\"2023年3月\"）\n"
            "- core_conclusion: 核心结论（一句话概括）\n"
            f"- evidence_msg_ids: 从本阶段涵盖的节点的 all_message_ids 中选取所有直接支撑本阶段结论的消息ID（目标{ev_min}-{ev_max}个，但不要因数量限制而遗漏关键证据）。每个涵盖该阶段的节点至少选1个ID。必须是具体整数ID的列表。\n"
            "- reasoning_chain: 推理链（解释为什么得出这个结论）\n"
            "- uncertainty_note: 不确定性说明\n\n"
            "时序覆盖约束：叙事的早期阶段（第1、2阶段）的证据应优先来自 temporal_position 为 Q1/Q2 的节点；"
            "后期阶段（最后1、2阶段）的证据应优先来自 Q3/Q4 的节点。"
            "每个阶段的 evidence_msg_ids 应尽量覆盖至少两个不同的 temporal_position。宁可多选也不要遗漏关键证据。\n\n"
            "返回JSON格式: {\"phases\": [{\"phase_title\": \"...\", \"evidence_msg_ids\": [57, 59, 103], ...}, ...]}"
        )

    # Task 1.8: User prompt explains how to select IDs
    if output_mode == "summary":
        prompt = (
            f"用户问题: {question}\n\n"
            f"对话节点摘要:\n"
            f"{json.dumps(node_summaries, ensure_ascii=False, indent=2)}\n\n"
            "请做主题汇总，输出 summary 和 themes。每个 theme 需包含 evidence_msg_ids（从 messages_preview 的 id 选取）。"
        )
    else:
        prompt = (
            f"用户问题: {question}\n\n"
            f"对话节点摘要（每个节点含 all_message_ids 和 temporal_position）:\n"
            f"{json.dumps(node_summaries, ensure_ascii=False, indent=2)}\n\n"
            "请将这些节点组织成连贯的叙事阶段，回答用户的问题。"
            "为每个阶段选择具体的消息ID作为证据，请从每个节点的 all_message_ids 中选取（不要局限于 messages_preview）。"
        )

    valid_ids = set()
    for node in collected_nodes:
        for lid in range(node.start_local_id, node.end_local_id + 1):
            valid_ids.add(lid)

    phases: list[NarrativePhase] = []
    max_attempts = 2 if collected_nodes else 1
    for attempt in range(max_attempts):
        try:
            response = llm.think_and_complete(system_prompt, prompt, max_tokens=4096, response_format="json_object")
            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                match = re.search(r"```(?:json)?\s*\n(.*?)\n```", response, re.DOTALL)
                if match:
                    data = json.loads(match.group(1).strip())
                else:
                    data = None
                    for i, ch in enumerate(response):
                        if ch == "{":
                            try:
                                data = json.loads(response[i:])
                                break
                            except json.JSONDecodeError:
                                continue
                    if data is None:
                        raise ValueError("No valid JSON in response")
            # Handle summary format: themes -> phases
            raw_phases = data.get("phases", [])
            if not raw_phases and output_mode == "summary":
                for theme in data.get("themes", []):
                    raw_ids = theme.get("evidence_msg_ids", [])
                    evidence_ids = []
                    for x in raw_ids:
                        try:
                            mid = int(x)
                            if mid in valid_ids:
                                evidence_ids.append(mid)
                        except (ValueError, TypeError):
                            pass
                    raw_phases.append({
                        "phase_title": theme.get("theme_title", "主题"),
                        "time_range": theme.get("time_range", ""),
                        "core_conclusion": theme.get("description", ""),
                        "evidence_msg_ids": evidence_ids,
                        "reasoning_chain": "",
                        "uncertainty_note": "",
                    })
            # Task 1.6: Read evidence_msg_ids directly
            for phase_data in raw_phases:
                raw_ids = phase_data.get("evidence_msg_ids", [])
                evidence_ids: list[int] = []
                for x in raw_ids:
                    try:
                        mid = int(x)
                        if mid in valid_ids:
                            evidence_ids.append(mid)
                    except (ValueError, TypeError):
                        pass
                # Task 1.7: evidence_segments kept as empty list (backward compat)
                phase = NarrativePhase(
                    phase_title=phase_data.get("phase_title", "未命名阶段"),
                    time_range=phase_data.get("time_range", ""),
                    core_conclusion=phase_data.get("core_conclusion", ""),
                    evidence_msg_ids=evidence_ids,
                    evidence_segments=[],
                    reasoning_chain=phase_data.get("reasoning_chain", ""),
                    uncertainty_note=phase_data.get("uncertainty_note", ""),
                    verified=False,
                )
                phases.append(phase)
            if phases:
                break
        except Exception:
            phases = []

    step = AgentStep(
        node_name="generator",
        input_summary=f"nodes={len(collected_nodes)}, question='{question[:40]}'",
        output_summary=f"phases={len(phases)}",
        llm_calls=1,
        timestamp_ms=int(time.time() * 1000),
    )

    existing_steps = list(state.get("trace_steps", []))
    existing_steps.append(step)

    if debug:
        print(f"[generator] exit: phases={len(phases)}", file=sys.stderr)

    return {
        "phases": phases,
        "trace_steps": existing_steps,
    }


# ---------------------------------------------------------------------------
# 5.8 Assemble StateGraph
# ---------------------------------------------------------------------------

_graph_builder = StateGraph(WorkflowState)
_graph_builder.add_node("planner", planner_node)
_graph_builder.add_node("retriever", retriever_node)
_graph_builder.add_node("grader", grader_node)
_graph_builder.add_node("explorer", explorer_node)
_graph_builder.add_node("generator", generator_node)
_graph_builder.add_node("factual_retriever", factual_retriever_node)
_graph_builder.add_node("factual_generator", factual_generator_node)

_graph_builder.add_conditional_edges(
    "planner",
    route_after_planning,
    {"factual_retrieve": "factual_retriever", "retrieve": "retriever"},
)
_graph_builder.add_edge("retriever", "grader")
_graph_builder.add_conditional_edges(
    "grader",
    route_after_grading,
    {"generate": "generator", "explore": "explorer"},
)
_graph_builder.add_edge("explorer", "grader")
_graph_builder.add_edge("factual_retriever", "factual_generator")
_graph_builder.set_entry_point("planner")
_graph_builder.add_edge("generator", END)
_graph_builder.add_edge("factual_generator", END)

compiled_graph = _graph_builder.compile()


# ---------------------------------------------------------------------------
# 5.9 run_workflow entry point
# ---------------------------------------------------------------------------

def run_workflow(
    question: str,
    talker_id: str,
    llm,
    conn,
    tools: list,
    max_iterations: int = 3,
    debug: bool = False,
    llm_noncot=None,
    chroma_dir: str = "",
    retrieval_limit: int = 60,
) -> AgentTrace:
    """Run the LangGraph-based agentic narrative workflow.

    Args:
        question: The user's question.
        talker_id: Conversation ID to query.
        llm: CoTLLM instance for reasoning.
        conn: sqlite3.Connection for DB access.
        tools: List of NarrativeTool instances.
        max_iterations: Maximum exploration iterations before forcing generation.
        debug: If True, print node entry/exit summaries to stderr.
        llm_noncot: Optional NonCoTLLM instance (for semantic tools).

    Returns:
        AgentTrace with steps, phases, and totals.
    """
    initial_state: WorkflowState = {
        "question": question,
        "intent": None,
        "search_queries": [],
        "collected_nodes": [],
        "collected_messages": {},
        "evaluation": '{"evaluation": "sufficient"}',
        "iterations": 0,
        "phases": [],
        "trace_steps": [],
        "answer_mode": "full_narrative",
        "factual_answer": None,
        "llm": llm,
        "llm_noncot": llm_noncot,
        "conn": conn,
        "talker_id": talker_id,
        "tools": tools,
        "chroma_dir": chroma_dir,
        "max_iterations": max_iterations,
        "debug": debug,
        "retrieval_limit": retrieval_limit,
    }

    final_state = compiled_graph.invoke(initial_state)

    steps: list[AgentStep] = final_state.get("trace_steps", [])
    phases: list[NarrativePhase] = final_state.get("phases", [])
    answer_mode: str = final_state.get("answer_mode", "full_narrative")
    factual_answer = final_state.get("factual_answer")
    # When all queries go agentic path, factual_rag gets phases from generator; derive factual_answer for client compat
    if answer_mode == "factual_rag" and factual_answer is None and phases:
        first = phases[0]
        factual_answer = {"answer": first.core_conclusion, "evidence_msg_ids": first.evidence_msg_ids}
    elif answer_mode == "factual_rag" and factual_answer is None:
        factual_answer = {"answer": "未找到相关记录。", "evidence_msg_ids": []}
    total_llm_calls = sum(s.llm_calls for s in steps)
    collected_nodes = final_state.get("collected_nodes", [])

    trace = AgentTrace(
        question=question,
        steps=steps,
        final_answer="",
        phases=phases,
        total_llm_calls=total_llm_calls,
        answer_mode=answer_mode,
        factual_answer=factual_answer,
        collected_nodes=collected_nodes,
    )

    return trace


def run_workflow_stream_values(
    question: str,
    talker_id: str,
    llm,
    conn,
    tools: list,
    max_iterations: int = 3,
    debug: bool = False,
    llm_noncot=None,
    chroma_dir: str = "",
    retrieval_limit: int = 60,
):
    """Stream workflow execution with full state after each node.

    Yields (trace_steps, full_state) after each node.
    The last yield has the complete final_state.
    """
    initial_state: WorkflowState = {
        "question": question,
        "intent": None,
        "search_queries": [],
        "collected_nodes": [],
        "collected_messages": {},
        "evaluation": '{"evaluation": "sufficient"}',
        "iterations": 0,
        "phases": [],
        "trace_steps": [],
        "answer_mode": "full_narrative",
        "factual_answer": None,
        "llm": llm,
        "llm_noncot": llm_noncot,
        "conn": conn,
        "talker_id": talker_id,
        "tools": tools,
        "chroma_dir": chroma_dir,
        "max_iterations": max_iterations,
        "debug": debug,
        "retrieval_limit": retrieval_limit,
    }

    for full_state in compiled_graph.stream(
        initial_state,
        stream_mode="values",
    ):
        steps: list[AgentStep] = full_state.get("trace_steps", [])
        yield (steps, full_state)
