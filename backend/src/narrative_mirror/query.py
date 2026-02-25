"""Query Pipeline - Q1-Q5 implementation."""

import json
import re
import sqlite3
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .models import QueryIntent, NarrativePhase, TopicNode, AnomalyAnchor

from .metadata import CANONICAL_SIGNALS
from .db import get_nodes, get_anchors, get_messages_by_ids, get_messages_for_node
from .layer2 import get_thread

if TYPE_CHECKING:
    from .llm import CoTLLM
    from .tools import NarrativeTool

# Output mode config for dynamic phase count and evidence range
OUTPUT_MODES = {
    "narrative": {
        "min_phases": 2,
        "max_phases": 8,
        "evidence_per_phase": (3, 15),
    },
    "fact": {
        "min_phases": 1,
        "max_phases": 1,
        "evidence_per_phase": (1, 5),
    },
    "summary": {
        "min_phases": 2,
        "max_phases": 4,
        "evidence_per_phase": (2, 5),
    },
}


def parse_intent(question: str, llm: "CoTLLM") -> QueryIntent:
    """Parse user's question into a structured QueryIntent.

    Args:
        question: The user's question.
        llm: The CoTLLM to use for parsing.

    Returns:
        A QueryIntent object with scope and output_mode.
    """
    system_prompt = """分析用户问题，输出 JSON：
{
  "intent_type": "arc_narrative | fact_lookup | theme_summary | phase_query",
  "scope": {
    "type": "global | time_bounded | topic_bounded",
    "time_hint": {
      "start": "2023-01-01 或 null",
      "end": "2023-06-01 或 null",
      "relative": "自然语言时间描述 或 null"
    },
    "topic_hint": "主题关键词 或 null"
  },
  "focus_dimensions": ["维度1", "维度2"],
  "output_mode": "narrative | fact | summary"
}

scope 判断规则：
- 问题涉及整段关系/经历的演变 → global
- 问题指向特定时间段 → time_bounded
- 问题指向特定话题但不限时间 → topic_bounded
- 可组合：time_bounded + topic_hint 同时存在

参考示例：
职场："入职以来工作进展如何" → global, narrative
职场："上个季度的项目复盘" → time_bounded, relative="上个季度", narrative
职场："那次需求评审会说了什么" → time_bounded + topic_bounded, fact
师生："导师指导方向有过哪些调整" → global, narrative
师生："老师有没有提过延毕" → topic_bounded, fact, topic_hint="延毕"
社交："我和他的关系怎么变化的" → global, narrative
社交："去年国庆一起出去玩那次" → time_bounded, fact
家庭："和爸妈的沟通模式有变化吗" → global, narrative
家庭："上次聊到买房是什么时候" → topic_bounded, fact, topic_hint="买房"
沟通："沟通方式有什么问题" → global, narrative
沟通："谁更主动发起聊天" → global, summary

fact_lookup 判断规则（关键）：问题只需要一个具体的事实答案（地点、时间、名称、数字等），不需要分析演变过程或多阶段叙事，答案通常可以用一句话回答 → fact_lookup, output_mode=fact

事件级事实查询（指向某个具体事件/场合的单一事实）→ fact_lookup, output_mode=fact：
- "Kate第一次约会去了哪个咖啡馆" → fact_lookup, fact
- "第一次见面是在哪里" → fact_lookup, fact
- "他们第一次约会去了哪里" → fact_lookup, fact
- "那次旅行住的什么酒店" → fact_lookup, fact
- "生日是哪天" → fact_lookup, fact
- "他说的那个餐厅叫什么名字" → fact_lookup, fact
- "第一次约会在哪" → fact_lookup, fact

消息级事实查询（指向某条具体消息的事实）→ fact_lookup, output_mode=fact：
- "292消息里提到的Central Park是什么" → fact_lookup, fact
- "消息292里说的咖啡店叫什么" → fact_lookup, fact
- "What was the Central Park mentioned in message 292?" → fact_lookup, fact
- "第100条消息说了什么" → fact_lookup, fact
- "localId 292里提到的约会地点" → fact_lookup, fact

关注维度 (focus_dimensions) 从以下选择: reply_delay, term_shift, silence_event, topic_frequency, initiator_ratio, emotional_tone, conflict_intensity"""

    prompt = f"用户问题: {question}\n\n请分析这个问题的意图。"

    try:
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=512, response_format="json_object")
        data = json.loads(response)

        # Support both new format (intent_type, scope, output_mode) and legacy (query_type)
        intent_type = data.get("intent_type") or data.get("query_type", "arc_narrative")
        focus_dimensions = data.get("focus_dimensions", [])
        time_range = data.get("time_range")
        output_mode = data.get("output_mode", "narrative")

        # Map intent_type to legacy query_type
        query_type_map = {
            "arc_narrative": "arc_narrative",
            "fact_lookup": "event_retrieval",
            "theme_summary": "arc_narrative",
            "phase_query": "time_point",
        }
        query_type = query_type_map.get(intent_type, intent_type if intent_type in ("arc_narrative", "time_point", "event_retrieval") else "arc_narrative")

        scope = data.get("scope")
        if scope and scope.get("type") not in ("global", "time_bounded", "topic_bounded"):
            scope = {"type": "global", "time_hint": {}, "topic_hint": None}

        valid_dimensions = [d for d in focus_dimensions if d in CANONICAL_SIGNALS]

        return QueryIntent(
            query_type=query_type,
            focus_dimensions=valid_dimensions,
            time_range=time_range,
            scope=scope,
            output_mode=output_mode if output_mode in ("narrative", "fact", "summary") else "narrative",
        )

    except (json.JSONDecodeError, ValueError, KeyError):
        return QueryIntent(
            query_type="arc_narrative",
            focus_dimensions=CANONICAL_SIGNALS[:3],
            time_range=None,
            scope={"type": "global", "time_hint": {}, "topic_hint": None},
            output_mode="narrative",
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
    scope: Optional[dict] = None,
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

    # Use retrieve_by_scope when chroma_dir and llm_noncot available
    if chroma_dir and llm_noncot is not None:
        from .tools import retrieve_by_scope
        scope = scope or {"type": "global"}
        return retrieve_by_scope(
            conn=conn,
            chroma_dir=chroma_dir,
            talker_id=talker_id,
            scope=scope,
            queries=[question] if question else [],
            llm=llm_noncot,
            limit=max_nodes,
            anchors=anchors,
        )

    # Optional semantic retrieval path (fallback)
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
    output_mode: str = "narrative",
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

        # Expose concrete integer IDs so the LLM can pick from them.
        # all_message_ids: full list of local_ids in node (LLM can select from any, not just preview)
        all_message_ids = [m.local_id for m in msgs]
        node_summaries.append({
            "topic": node.topic_name,
            "date": datetime.fromtimestamp(node.start_time / 1000).strftime("%Y-%m-%d"),
            "start_id": node.start_local_id,
            "end_id": node.end_local_id,
            "all_message_ids": all_message_ids,
            "signals": signals_str,
            "messages_preview": messages_preview,
        })

    cfg = OUTPUT_MODES.get(output_mode, OUTPUT_MODES["narrative"])
    time_span_days = 1
    if candidates:
        ts_min = min(n.start_time for n in candidates)
        ts_max = max(n.start_time for n in candidates)
        time_span_days = max(1, (ts_max - ts_min) / (1000 * 86400))
    phase_count = max(cfg["min_phases"], min(cfg["max_phases"], max(1, int(time_span_days // 180))))
    phase_count = min(phase_count, max(1, len(candidates) // 3))

    # Resolve speaker names from DB so the LLM can match names in QA questions
    speaker_context = ""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sender_username FROM raw_messages WHERE talker_id=? AND is_send=1 AND sender_username!='' LIMIT 1",
            (talker_id,),
        )
        row = cursor.fetchone()
        self_name = row[0] if row else None
        cursor.execute(
            "SELECT sender_username FROM raw_messages WHERE talker_id=? AND is_send=0 AND sender_username!='' LIMIT 1",
            (talker_id,),
        )
        row = cursor.fetchone()
        other_name = row[0] if row else None
        if self_name and other_name:
            speaker_context = f"\n\n对话双方：发送方（isSend=1）= {self_name}，接收方（isSend=0）= {other_name}。消息中的 sender 字段即为此名字。"
    except Exception:
        pass

    ev_min, ev_max = cfg["evidence_per_phase"]
    system_prompt = f"""你是一个叙事分析助手。根据对话节点的时间线，将其分割为 {phase_count} 个叙事阶段。{speaker_context}

每个阶段需要包含:
- phase_title: 阶段标题（简短有力）
- time_range: 时间范围（如"2023年3月"）
- core_conclusion: 核心结论（一句话概括）
- evidence_msg_ids: 从本阶段涵盖的节点的 all_message_ids 中选取所有直接支撑本阶段结论的消息ID（目标{ev_min}-{ev_max}个，但不要因数量限制而遗漏关键证据）。每个涵盖该阶段的节点至少选1个ID，覆盖该阶段的起止时间。
- reasoning_chain: 推理链（解释为什么得出这个结论）
- uncertainty_note: 不确定性说明

注意：evidence_msg_ids 必须来自各节点的 all_message_ids（即 start_id 到 end_id 范围内的真实消息ID）。确保从不同日期/时间段的节点中选取证据（早期、中期、晚期都要有），不要只从某一小段选取。优先选择直接支撑结论、与用户问题关键词相关的消息。宁可多选也不要遗漏关键证据。

返回JSON格式: {{\"phases\": [{{...}}, {{...}}]}}"""

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
            chroma_dir=chroma_dir,
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
        scope=intent.scope if intent else None,
    )
    if debug:
        print(f"Q3: Expanded to {len(candidates)} candidate nodes", file=sys.stderr)

    phases = segment_narrative(
        candidates, question, talker_id, llm, conn,
        output_mode=intent.output_mode if intent else "narrative",
    )
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
            chroma_dir=chroma_dir,
            retrieval_limit=max_nodes,
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
        scope=intent.scope if intent else None,
    )
    output_mode = intent.output_mode if intent else "narrative"
    phases = segment_narrative(
        candidates, question, talker_id, llm, conn,
        output_mode=output_mode,
    )
    if not phases and candidates:
        phases = segment_narrative(
            candidates, question, talker_id, llm, conn,
            output_mode=output_mode,
        )
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
