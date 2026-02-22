"""Evidence reflection and verification for NarrativePhase objects."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from .models import NarrativePhase, TopicNode
from .db import get_messages_by_ids, get_nodes, get_messages_for_node

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# 6.1 Evidence existence verification
# ---------------------------------------------------------------------------

def _check_existence(
    phase: NarrativePhase,
    conn: sqlite3.Connection,
    talker_id: str,
) -> tuple[list[int], list[int]]:
    """Check which evidence message IDs actually exist in raw_messages.

    Args:
        phase: NarrativePhase whose evidence_msg_ids to verify.
        conn: SQLite connection.
        talker_id: The conversation's talker ID.

    Returns:
        Tuple of (valid_ids, invalid_ids).
    """
    if not phase.evidence_msg_ids:
        return [], []

    found_messages = get_messages_by_ids(conn, talker_id, phase.evidence_msg_ids)
    found_ids = {m.local_id for m in found_messages}

    valid_ids = [mid for mid in phase.evidence_msg_ids if mid in found_ids]
    invalid_ids = [mid for mid in phase.evidence_msg_ids if mid not in found_ids]

    return valid_ids, invalid_ids


# ---------------------------------------------------------------------------
# 6.2 Semantic relevance check
# ---------------------------------------------------------------------------

def _check_relevance(
    phase: NarrativePhase,
    valid_ids: list[int],
    conn: sqlite3.Connection,
    talker_id: str,
    llm,
) -> bool:
    """Check whether the evidence messages semantically support the conclusion.

    Args:
        phase: NarrativePhase to check.
        valid_ids: List of valid message IDs to retrieve.
        conn: SQLite connection.
        talker_id: The conversation's talker ID.
        llm: CoTLLM instance for semantic reasoning.

    Returns:
        True if evidence is relevant to the conclusion, False otherwise.
    """
    if not valid_ids:
        return False

    messages = get_messages_by_ids(conn, talker_id, valid_ids)
    if not messages:
        return False

    # Build message text for the prompt
    msg_lines = []
    for m in messages:
        sender = "我" if m.is_send else "TA"
        ts = datetime.fromtimestamp(m.create_time / 1000).strftime("%Y-%m-%d %H:%M")
        msg_lines.append(f"[{m.local_id}] {sender}({ts}): {m.parsed_content[:200]}")

    messages_text = "\n".join(msg_lines)

    system_prompt = (
        "你是一个证据相关性评估助手。判断给定的消息是否支撑给定的结论。"
        "返回JSON格式: {\"relevant\": true} 或 {\"relevant\": false, \"reason\": \"原因\"}"
    )
    prompt = (
        f"结论: {phase.core_conclusion}\n\n"
        f"阶段标题: {phase.phase_title}\n\n"
        f"证据消息:\n{messages_text}\n\n"
        "这些消息是否支撑上述结论？"
    )

    try:
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=256, response_format="json_object")
        data = json.loads(response)
        return bool(data.get("relevant", True))
    except Exception:
        # Fail safe: assume relevant if we can't determine
        return True


# ---------------------------------------------------------------------------
# 6.3 Evidence re-selection
# ---------------------------------------------------------------------------

def _reselect_evidence(
    phase: NarrativePhase,
    conn: sqlite3.Connection,
    talker_id: str,
    llm,
) -> list[int]:
    """Re-select evidence messages from nodes overlapping phase time range.

    Args:
        phase: NarrativePhase whose evidence needs re-selection.
        conn: SQLite connection.
        talker_id: The conversation's talker ID.
        llm: CoTLLM instance for selecting best messages.

    Returns:
        List of selected message local_ids.
    """
    all_nodes = get_nodes(conn, talker_id)

    # Parse phase time range to find overlapping nodes
    # The time_range is a free-form string like "2023年3月" or "2023-03"
    # We'll try to find nodes roughly in that period using simple string matching
    # against the formatted date
    candidate_nodes: list[TopicNode] = []

    time_range_lower = phase.time_range.lower()
    for node in all_nodes:
        node_date = datetime.fromtimestamp(node.start_time / 1000).strftime("%Y-%m-%d")
        node_date_cn = datetime.fromtimestamp(node.start_time / 1000).strftime("%Y年%m月")
        # Match if the phase time range appears in the node date string or vice versa
        if (
            time_range_lower in node_date.lower()
            or time_range_lower in node_date_cn.lower()
            or node_date[:7] in phase.time_range  # YYYY-MM prefix
        ):
            candidate_nodes.append(node)

    # If no nodes match by date, use uniformly-sampled nodes as fallback
    # (avoids early-period bias from all_nodes[:10])
    if not candidate_nodes:
        step = max(1, len(all_nodes) // 10)
        candidate_nodes = all_nodes[::step][:10]

    # Collect messages from candidate nodes
    all_messages = []
    for node in candidate_nodes:
        msgs = get_messages_for_node(conn, talker_id, node)
        all_messages.extend(msgs)

    if not all_messages:
        return []

    # Build message text for selection
    msg_lines = []
    for m in all_messages[:30]:  # limit to 30 messages to avoid token overflow
        sender = "我" if m.is_send else "TA"
        ts = datetime.fromtimestamp(m.create_time / 1000).strftime("%Y-%m-%d %H:%M")
        msg_lines.append(f"[{m.local_id}] {sender}({ts}): {m.parsed_content[:150]}")

    messages_text = "\n".join(msg_lines)

    system_prompt = (
        "你是一个证据选择助手。从给定消息列表中选择3-5条最能支撑给定结论的消息。"
        "只能选择列表中存在的消息ID。"
        "返回JSON格式: {\"selected_ids\": [id1, id2, ...]}"
    )
    prompt = (
        f"结论: {phase.core_conclusion}\n\n"
        f"阶段标题: {phase.phase_title}\n\n"
        f"可选消息:\n{messages_text}\n\n"
        "请选择3-5条最能支撑上述结论的消息ID。"
    )

    try:
        response = llm.think_and_complete(system_prompt, prompt, max_tokens=256, response_format="json_object")
        data = json.loads(response)
        raw_ids = data.get("selected_ids", [])
        selected_ids = []
        valid_set = {m.local_id for m in all_messages}
        for x in raw_ids:
            try:
                mid = int(x)
                if mid in valid_set:
                    selected_ids.append(mid)
            except (ValueError, TypeError):
                pass
        return selected_ids[:5]
    except Exception:
        # Return first few message IDs as fallback
        return [m.local_id for m in all_messages[:3]]


# ---------------------------------------------------------------------------
# 6.4 reflect_on_evidence orchestration
# ---------------------------------------------------------------------------

def reflect_on_evidence(
    phases: list[NarrativePhase],
    question: str,
    llm,
    conn: sqlite3.Connection,
    talker_id: str,
) -> list[NarrativePhase]:
    """Verify and correct evidence for each NarrativePhase.

    For each phase:
    1. Check existence: verify all evidence_msg_ids exist in raw_messages
    2. If all valid: check semantic relevance via LLM
    3. If existence or relevance fails: attempt one re-selection
    4. Set phase.verified based on final state

    Args:
        phases: List of NarrativePhase objects to verify.
        question: The user's original question (for context).
        llm: CoTLLM instance for semantic checks.
        conn: SQLite connection.
        talker_id: The conversation's talker ID.

    Returns:
        Updated list of NarrativePhase objects with verified flag set.
    """
    updated_phases = []

    for phase in phases:
        # Step 1: Check existence
        valid_ids, invalid_ids = _check_existence(phase, conn, talker_id)

        if invalid_ids:
            # Some IDs are invalid — try re-selection
            new_ids = _reselect_evidence(phase, conn, talker_id, llm)
            if new_ids:
                phase.evidence_msg_ids = new_ids
                phase.verified = True
            else:
                # Re-selection also failed
                phase.verified = False
            updated_phases.append(phase)
            continue

        # Step 2: All IDs valid — check semantic relevance
        is_relevant = _check_relevance(phase, valid_ids, conn, talker_id, llm)

        if is_relevant:
            phase.verified = True
        else:
            # Step 3: Relevance failed — try re-selection once
            new_ids = _reselect_evidence(phase, conn, talker_id, llm)
            if new_ids:
                phase.evidence_msg_ids = new_ids
                phase.verified = True
            else:
                phase.verified = False

        updated_phases.append(phase)

    return updated_phases
