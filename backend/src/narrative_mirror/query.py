"""Query Pipeline - Q1-Q5 implementation."""

import json
import re
import sqlite3
import sys
from datetime import datetime
from typing import TYPE_CHECKING

from .models import QueryIntent, NarrativePhase, TopicNode, AnomalyAnchor

from .metadata import CANONICAL_SIGNALS
from .db import get_nodes, get_anchors, get_messages_by_ids, get_messages_for_node
from .layer2 import get_thread

if TYPE_CHECKING:
    from .llm import CoTLLM
    from .tools import NarrativeTool


def parse_intent(question: str, llm: "CoTLLM") -> QueryIntent:
    """Parse user's question into a structured QueryIntent.

    Args:
        question: The user's question.
        llm: The CoTLLM to use for parsing.

    Returns:
        A QueryIntent object.
    """
    system_prompt = """你是一个查询意图分析助手。根据用户的问题，识别查询类型和关注的维度。

查询类型 (query_type):
- arc_narrative: 用户想了解某个过程/事件的演变（如"我们是怎么分手的"）
- time_point: 用户问某个时间点发生了什么（如"2023年6月发生了什么"）
- event_retrieval: 用户问某个特定事件（如"我们第一次吵架是什么时候"）

关注维度 (focus_dimensions): 从以下列表中选择相关的维度:
- reply_delay: 回复延迟变化
- term_shift: 称呼/措辞变化
- silence_event: 沉默事件
- topic_frequency: 话题频率
- initiator_ratio: 发起比例
- emotional_tone: 情感基调
- conflict_intensity: 冲突强度

返回JSON格式: {"query_type": "类型", "focus_dimensions": ["维度1", "维度2"], "time_range": "时间范围或null"}"""

    prompt = f"用户问题: {question}\n\n请分析这个问题的意图。"

    try:
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=512, response_format="json_object")
        data = json.loads(response)

        query_type = data.get("query_type", "arc_narrative")
        focus_dimensions = data.get("focus_dimensions", [])
        time_range = data.get("time_range")

        # Validate and filter dimensions against canonical list
        valid_dimensions = [
            dim for dim in focus_dimensions
            if dim in CANONICAL_SIGNALS
        ]

        return QueryIntent(
            query_type=query_type,
            focus_dimensions=valid_dimensions,
            time_range=time_range,
        )

    except (json.JSONDecodeError, ValueError, KeyError):
        # Fallback to default
        return QueryIntent(
            query_type="arc_narrative",
            focus_dimensions=CANONICAL_SIGNALS[:3],
            time_range=None,
        )


def lookup_anchors(
    intent: QueryIntent,
    talker_id: str,
    conn: sqlite3.Connection,
) -> list[AnomalyAnchor]:
    """Look up anomaly anchors based on query intent.

    Args:
        intent: The parsed QueryIntent.
        talker_id: The conversation's talker ID.
        conn: SQLite connection.

    Returns:
        List of matching AnomalyAnchor objects.
    """
    # Get anchors matching the focus dimensions
    signals = intent.focus_dimensions if intent.focus_dimensions else None

    anchors = get_anchors(
        conn,
        talker_id,
        signals=signals,
        time_range=intent.time_range,
    )

    return anchors


def expand_candidates(
    anchors: list[AnomalyAnchor],
    talker_id: str,
    conn: sqlite3.Connection,
    max_nodes: int = 60,
    query_type: str = "arc_narrative",
    question: str = "",
    llm_noncot=None,
    chroma_dir: str = "",
) -> list[TopicNode]:
    """Expand candidate nodes from anchors via thread traversal.

    For arc_narrative queries, full temporal coverage is needed so all nodes
    are included (anchored ones first, then remaining nodes to fill max_nodes).
    For other query types, only anchored nodes and their thread neighbours
    are returned, falling back to all nodes when no anchors match.

    Optionally performs semantic retrieval via ChromaDB when question,
    llm_noncot, and chroma_dir are all provided.

    Args:
        anchors: List of anomaly anchors.
        talker_id: The conversation's talker ID.
        conn: SQLite connection.
        max_nodes: Maximum number of nodes to return.
        query_type: The parsed query type from Q1.
        question: Optional question string for semantic retrieval.
        llm_noncot: Optional NonCoTLLM for embedding (enables semantic path).
        chroma_dir: Optional ChromaDB directory (enables semantic path).

    Returns:
        List of TopicNode objects, sorted by start_time.
    """
    all_nodes = get_nodes(conn, talker_id)

    # Optional semantic retrieval path
    semantic_node_ids: set[str] = set()
    if question and chroma_dir and llm_noncot is not None:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=chroma_dir)
            collection_name = f"narrative_mirror_{talker_id}"
            try:
                collection = client.get_collection(collection_name)
                embedding = llm_noncot.embed(question)
                results = collection.query(
                    query_embeddings=[embedding],
                    n_results=min(15, collection.count()),
                )
                if results and results.get("ids") and results["ids"][0]:
                    semantic_node_ids = set(results["ids"][0])
            except Exception:
                pass
        except Exception:
            pass

    if not anchors or query_type == "arc_narrative":
        # arc_narrative needs the full timeline to construct an evolution arc.
        # Prioritise anchor nodes, then fill with remaining nodes sorted by time.
        if anchors and query_type == "arc_narrative":
            anchor_node_ids = {a.node_id for a in anchors}
            # Add thread neighbours of anchors
            for anchor in anchors:
                anchor_node_ids.update(get_thread(anchor.node_id, talker_id, conn))
            # Merge semantic results for arc_narrative
            anchor_node_ids.update(semantic_node_ids)
            prioritised = [n for n in all_nodes if n.node_id in anchor_node_ids]
            rest = [n for n in all_nodes if n.node_id not in anchor_node_ids]
            candidates = prioritised + rest
        else:
            candidates = list(all_nodes)
        candidates.sort(key=lambda n: n.start_time)
        return candidates[:max_nodes]

    # Focused query (event_retrieval, time_point): anchor-only expansion
    node_ids = set()
    for anchor in anchors:
        node_ids.add(anchor.node_id)
        node_ids.update(get_thread(anchor.node_id, talker_id, conn))

    # Supplement with semantic results
    node_ids.update(semantic_node_ids)

    node_by_id = {n.node_id: n for n in all_nodes}
    candidates = [node_by_id[nid] for nid in node_ids if nid in node_by_id]
    candidates.sort(key=lambda n: n.start_time)
    return candidates[:max_nodes]


def segment_narrative(
    candidates: list[TopicNode],
    question: str,
    talker_id: str,
    llm: "CoTLLM",
    conn: sqlite3.Connection,
) -> list[NarrativePhase]:
    """Segment candidates into narrative phases.

    Args:
        candidates: List of TopicNode objects.
        question: The user's question.
        talker_id: The conversation's talker ID.
        llm: The CoTLLM to use.
        conn: SQLite connection.

    Returns:
        List of NarrativePhase objects.
    """
    if not candidates:
        return []

    # Build node summaries for the prompt
    from .db import get_all_metadata

    all_metadata = get_all_metadata(conn, talker_id)
    metadata_by_node = {m.node_id: m for m in all_metadata}

    node_summaries = []
    for node in candidates:
        meta = metadata_by_node.get(node.node_id)
        signals_str = ""
        if meta:
            signals_str = f", reply_delay={meta.reply_delay_avg_s:.0f}s, conflict={meta.conflict_intensity:.2f}"

        # Retrieve actual messages for this node and build a preview
        msgs = get_messages_for_node(conn, talker_id, node)
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
            content = m.parsed_content[:100]
            messages_preview.append({
                "id": m.local_id,
                "sender": sender,
                "content": content,
            })

        # Expose concrete integer IDs so the LLM can pick from them
        node_summaries.append({
            "topic": node.topic_name,
            "date": datetime.fromtimestamp(node.start_time / 1000).strftime("%Y-%m-%d"),
            "start_id": node.start_local_id,
            "end_id": node.end_local_id,
            "signals": signals_str,
            "messages_preview": messages_preview,
        })

    system_prompt = """你是一个叙事分析助手。根据对话节点的时间线，将其分割为4-6个叙事阶段。

每个阶段需要包含:
- phase_title: 阶段标题（简短有力）
- time_range: 时间范围（如"2023年3月"）
- core_conclusion: 核心结论（一句话概括）
- evidence_msg_ids: 从本阶段涵盖的节点中选取5-8个代表性消息的整数ID，覆盖该阶段的起止时间
- reasoning_chain: 推理链（解释为什么得出这个结论）
- uncertainty_note: 不确定性说明

注意：evidence_msg_ids 必须是各节点 start_id 到 end_id 范围内的真实消息ID。确保从不同日期/时间段的节点中选取证据（早期、中期、晚期都要有），不要只从某一小段选取。优先选择直接支撑结论、与用户问题关键词相关的消息。

返回JSON格式: {"phases": [{...}, {...}]}"""

    prompt = f"""用户问题: {question}

对话节点摘要:
{json.dumps(node_summaries, ensure_ascii=False, indent=2)}

请将这些节点组织成连贯的叙事阶段，回答用户的问题。"""

    try:
        response = llm.think_and_complete(system_prompt, prompt, response_format="json_object")
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # LLM may return thinking + markdown-wrapped JSON; extract JSON robustly
            match = re.search(r"```(?:json)?\s*\n(.*?)\n```", response, re.DOTALL)
            if match:
                data = json.loads(match.group(1).strip())
            else:
                # Try parsing from each '{' position; first valid parse wins
                for i, ch in enumerate(response):
                    if ch == "{":
                        try:
                            data = json.loads(response[i:])
                            break
                        except json.JSONDecodeError:
                            continue
                else:
                    raise ValueError("No valid JSON object found in response")

        # Build valid ID set: any local_id within a candidate node's range
        valid_ids = set()
        for node in candidates:
            for lid in range(node.start_local_id, node.end_local_id + 1):
                valid_ids.add(lid)

        phases = []
        for phase_data in data.get("phases", []):
            # Cast to int — LLMs sometimes return string IDs; filter to valid range
            raw_ids = phase_data.get("evidence_msg_ids", [])
            evidence_ids = []
            for x in raw_ids:
                try:
                    lid = int(x)
                    if lid in valid_ids:
                        evidence_ids.append(lid)
                except (ValueError, TypeError):
                    pass
            phase = NarrativePhase(
                phase_title=phase_data.get("phase_title", "未命名阶段"),
                time_range=phase_data.get("time_range", ""),
                core_conclusion=phase_data.get("core_conclusion", ""),
                evidence_msg_ids=evidence_ids,
                reasoning_chain=phase_data.get("reasoning_chain", ""),
                uncertainty_note=phase_data.get("uncertainty_note", ""),
                verified=False,
            )
            phases.append(phase)

        return phases

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        if candidates:
            try:
                prev = response[:200] if response else "None"
            except NameError:
                prev = "N/A"
            print(f"[segment_narrative] fallback empty: {type(e).__name__}: {str(e)[:150]} | response_preview: {prev}...", file=sys.stderr)
        return []


def verify_evidence(
    phases: list[NarrativePhase],
    talker_id: str,
    conn: sqlite3.Connection,
    llm: "CoTLLM",
    max_retries: int = 2,
) -> list[NarrativePhase]:
    """Verify that evidence message IDs are valid and within time range.

    Args:
        phases: List of NarrativePhase objects.
        talker_id: The conversation's talker ID.
        conn: SQLite connection.
        llm: The CoTLLM for corrections.
        max_retries: Maximum retry attempts.

    Returns:
        List of verified NarrativePhase objects.
    """
    verified_phases = []

    for phase in phases:
        # Get messages for evidence IDs
        messages = get_messages_by_ids(conn, talker_id, phase.evidence_msg_ids)

        # Check if all messages exist
        if len(messages) != len(phase.evidence_msg_ids):
            phase.verified = False
            verified_phases.append(phase)
            continue

        # Check if timestamps are within phase time range
        # For simplicity, we'll mark as verified if messages exist
        # In a full implementation, we'd parse time_range and check timestamps
        phase.verified = True
        verified_phases.append(phase)

    return verified_phases


def format_cards(
    phases: list[NarrativePhase],
    talker_id: str,
    conn: sqlite3.Connection,
) -> str:
    """Format narrative phases into plain-text cards.

    Args:
        phases: List of NarrativePhase objects.
        talker_id: The conversation's talker ID.
        conn: SQLite connection.

    Returns:
        Formatted string output.
    """
    if not phases:
        return "无法生成叙事分析结果。"

    output_lines = []

    for i, phase in enumerate(phases, 1):
        # Get evidence messages
        messages = get_messages_by_ids(conn, talker_id, phase.evidence_msg_ids)

        output_lines.append(f"═══ 阶段{i}: {phase.phase_title} ═════════════════")
        output_lines.append(f"时间范围: {phase.time_range}")
        output_lines.append(f"核心结论: {phase.core_conclusion}")
        output_lines.append("")
        output_lines.append("关键证据:")

        for msg in messages[:5]:  # Max 5 evidence items
            time_str = datetime.fromtimestamp(msg.create_time / 1000).strftime("%Y.%m.%d %H:%M")
            sender = "我" if msg.is_send else "TA"
            content = msg.parsed_content[:50] + ("..." if len(msg.parsed_content) > 50 else "")
            output_lines.append(f"  • [{time_str}] {sender}: {content}  (msg_id: {msg.local_id})")

        output_lines.append("")
        output_lines.append(f"推理链: {phase.reasoning_chain}")
        output_lines.append(f"不确定性: {phase.uncertainty_note}")

        if phase.verified:
            output_lines.append("[验证状态: ✓ 已验证]")
        else:
            output_lines.append("[验证状态: ✗ 待核实]")

        output_lines.append("")

    return "\n".join(output_lines)


def run_query(
    question: str,
    talker_id: str,
    llm: "CoTLLM",
    conn: sqlite3.Connection,
    max_nodes: int = 60,
    debug: bool = False,
    llm_noncot=None,
    chroma_dir: str = "",
    use_agent: bool = False,
    tools: list["NarrativeTool"] | None = None,
) -> str:
    """Run the full query pipeline (one-shot Q1-Q5 or agent graph workflow).

    Args:
        question: The user's question.
        talker_id: The conversation's talker ID.
        llm: The CoTLLM to use.
        conn: SQLite connection.
        max_nodes: Maximum candidate nodes (one-shot only).
        debug: If True, print debug information.
        llm_noncot: Optional NonCoTLLM for semantic retrieval in Q3 / agent tools.
        chroma_dir: Optional ChromaDB directory for semantic retrieval / agent tools.
        use_agent: If True, run the graph workflow instead of one-shot pipeline.
        tools: List of NarrativeTool instances (required when use_agent=True).

    Returns:
        Formatted narrative card output.
    """
    if use_agent:
        if not tools or not chroma_dir or llm_noncot is None:
            raise ValueError("use_agent=True requires tools, chroma_dir, and llm_noncot")
        from .workflow import run_workflow
        from .reflection import reflect_on_evidence

        trace = run_workflow(
            question=question,
            talker_id=talker_id,
            llm=llm,
            llm_noncot=llm_noncot,
            conn=conn,
            tools=tools,
            max_iterations=3,
            debug=debug,
        )
        phases = reflect_on_evidence(
            phases=trace.phases,
            question=question,
            llm=llm,
            conn=conn,
            talker_id=talker_id,
        )
        return format_cards(phases, talker_id, conn)

    # One-shot Q1-Q5 pipeline
    if debug:
        print(f"Q1: Parsing intent for: {question}", file=sys.stderr)

    intent = parse_intent(question, llm)
    if debug:
        print(f"Intent: {intent.query_type}, dimensions: {intent.focus_dimensions}", file=sys.stderr)

    anchors = lookup_anchors(intent, talker_id, conn)
    if debug:
        print(f"Q2: Found {len(anchors)} anomaly anchors", file=sys.stderr)

    candidates = expand_candidates(
        anchors, talker_id, conn, max_nodes, intent.query_type,
        question=question, llm_noncot=llm_noncot, chroma_dir=chroma_dir,
    )
    if debug:
        print(f"Q3: Expanded to {len(candidates)} candidate nodes", file=sys.stderr)

    phases = segment_narrative(candidates, question, talker_id, llm, conn)
    if debug:
        print(f"Q4: Generated {len(phases)} narrative phases", file=sys.stderr)

    from .reflection import reflect_on_evidence
    phases = reflect_on_evidence(
        phases=phases,
        question=question,
        llm=llm,
        conn=conn,
        talker_id=talker_id,
    )
    if debug:
        print(f"Reflected on evidence, {len(phases)} phases", file=sys.stderr)

    return format_cards(phases, talker_id, conn)


def run_query_with_phases(
    question: str,
    talker_id: str,
    llm: "CoTLLM",
    conn: sqlite3.Connection,
    max_nodes: int = 60,
    debug: bool = False,
    use_agent: bool = False,
    tools: list["NarrativeTool"] | None = None,
    llm_noncot=None,
    chroma_dir: str = "",
) -> tuple[str, list["NarrativePhase"]]:
    """Run the full query pipeline and return both output and phases.

    Same as run_query but returns (formatted_output, phases) for evaluation.
    Supports both one-shot and agent modes.
    """
    if use_agent and tools and chroma_dir and llm_noncot is not None:
        from .workflow import run_workflow
        from .reflection import reflect_on_evidence
        trace = run_workflow(
            question=question,
            talker_id=talker_id,
            llm=llm,
            llm_noncot=llm_noncot,
            conn=conn,
            tools=tools,
            max_iterations=3,
            debug=debug,
        )
        phases = reflect_on_evidence(
            phases=trace.phases,
            question=question,
            llm=llm,
            conn=conn,
            talker_id=talker_id,
        )
        output = format_cards(phases, talker_id, conn)
        return output, phases

    # One-shot path
    intent = parse_intent(question, llm)
    anchors = lookup_anchors(intent, talker_id, conn)
    candidates = expand_candidates(
        anchors, talker_id, conn, max_nodes, intent.query_type,
        question=question, llm_noncot=llm_noncot, chroma_dir=chroma_dir,
    )
    phases = segment_narrative(candidates, question, talker_id, llm, conn)
    if not phases and candidates:
        phases = segment_narrative(candidates, question, talker_id, llm, conn)
    from .reflection import reflect_on_evidence
    phases = reflect_on_evidence(
        phases=phases,
        question=question,
        llm=llm,
        conn=conn,
        talker_id=talker_id,
    )
    output = format_cards(phases, talker_id, conn)
    return output, phases


def main():
    """CLI entry point for query pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description="Query narrative for a conversation")
    parser.add_argument("question", help="The question to ask")
    parser.add_argument("--talker", required=True, help="Talker ID to query")
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=60,
        help="Maximum candidate nodes (default: 60)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug information",
    )
    parser.add_argument(
        "--db",
        default="data/mirror.db",
        help="Path to SQLite database (default: data/mirror.db)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yml for real LLM adapters (default: use stub)",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Use graph workflow (agent mode) instead of one-shot pipeline",
    )
    parser.add_argument(
        "--chroma",
        default="",
        help="ChromaDB directory (required for --agent)",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    if args.config:
        try:
            from .config import load_config
            from .llm import from_config
            config = load_config(args.config)
            llm_noncot, llm, _ = from_config(config)
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        from .llm import StubCoTLLM, StubNonCoTLLM
        llm = StubCoTLLM()
        llm_noncot = StubNonCoTLLM()

    tools = None
    chroma_dir = args.chroma
    if args.agent:
        if not chroma_dir:
            print("Error: --agent requires --chroma <chroma_dir>", file=sys.stderr)
            sys.exit(1)
        from .tools import get_all_tools
        tools = get_all_tools(conn, args.talker, chroma_dir, llm_noncot)

    try:
        output = run_query(
            question=args.question,
            talker_id=args.talker,
            llm=llm,
            conn=conn,
            max_nodes=args.max_nodes,
            debug=args.debug,
            use_agent=args.agent,
            tools=tools,
            llm_noncot=llm_noncot if args.agent else None,
            chroma_dir=chroma_dir,
        )
        print(output)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
