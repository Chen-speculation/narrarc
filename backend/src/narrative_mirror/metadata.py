"""Layer 1.5 Metadata - Signal computation and anomaly detection."""

import json
import sqlite3
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import TYPE_CHECKING

from .models import TopicNode, MetadataSignals, AnomalyAnchor, RawMessage
from .db import (
    get_nodes,
    get_all_messages,
    upsert_metadata,
    upsert_anchors,
    get_all_metadata,
)

if TYPE_CHECKING:
    from .llm import NonCoTLLM


# Canonical list of signal names for focus dimensions
CANONICAL_SIGNALS = [
    "reply_delay",
    "term_shift",
    "silence_event",
    "topic_frequency",
    "initiator_ratio",
    "emotional_tone",
    "conflict_intensity",
]


def compute_reply_delay(messages: list[RawMessage]) -> tuple[float, float]:
    """Compute reply delay statistics for alternating sender exchanges.

    Args:
        messages: List of RawMessage objects.

    Returns:
        Tuple of (mean_delay_seconds, max_delay_seconds).
        Returns (0.0, 0.0) if no alternating exchanges exist.
    """
    if len(messages) < 2:
        return (0.0, 0.0)

    delays = []
    for i in range(1, len(messages)):
        prev_msg = messages[i - 1]
        curr_msg = messages[i]

        # Only count delays where sender alternates
        if prev_msg.is_send != curr_msg.is_send:
            delay_ms = curr_msg.create_time - prev_msg.create_time
            delay_seconds = delay_ms / 1000.0
            delays.append(delay_seconds)

    if not delays:
        return (0.0, 0.0)

    return (statistics.mean(delays), max(delays))


def compute_term_shift(
    messages: list[RawMessage],
    baseline_terms: set[str],
) -> float:
    """Compute the fraction of TA messages using non-baseline address terms.

    Args:
        messages: List of RawMessage objects.
        baseline_terms: Set of baseline address terms.

    Returns:
        Fraction of TA messages using non-baseline terms (0.0 to 1.0).
    """
    ta_messages = [m for m in messages if not m.is_send]
    if not ta_messages:
        return 0.0

    non_baseline_count = 0
    for msg in ta_messages:
        content = msg.parsed_content
        # Check if content contains any baseline term
        has_baseline = any(term in content for term in baseline_terms)
        if not has_baseline and content.strip():
            non_baseline_count += 1

    return non_baseline_count / len(ta_messages)


def compute_silence_event(
    node: TopicNode,
    all_nodes: list[TopicNode],
) -> bool:
    """Check if the gap after this node exceeds 3× median inter-burst gap.

    Args:
        node: The TopicNode to check.
        all_nodes: All TopicNodes in the conversation.

    Returns:
        True if silence event detected, False otherwise.
    """
    if len(all_nodes) < 2:
        return False

    # Calculate inter-burst gaps
    gaps = []
    sorted_nodes = sorted(all_nodes, key=lambda n: n.end_time)

    for i in range(1, len(sorted_nodes)):
        gap = sorted_nodes[i].start_time - sorted_nodes[i - 1].end_time
        if gap > 0:
            gaps.append(gap)

    if not gaps:
        return False

    median_gap = statistics.median(gaps)
    threshold = 3 * median_gap

    # Find the gap after this node
    node_idx = next(
        (i for i, n in enumerate(sorted_nodes) if n.node_id == node.node_id),
        None
    )
    if node_idx is None or node_idx >= len(sorted_nodes) - 1:
        # Last node - check if gap to "now" or next conversation
        return False

    gap_after = sorted_nodes[node_idx + 1].start_time - node.end_time
    return gap_after > threshold


def compute_topic_frequency(node: TopicNode, all_nodes: list[TopicNode]) -> int:
    """Count prior nodes with the same topic_name (case-insensitive).

    Args:
        node: The TopicNode to check.
        all_nodes: All TopicNodes in the conversation.

    Returns:
        Count of prior nodes with same topic.
    """
    count = 0
    node_topic = node.topic_name.lower()

    for other in all_nodes:
        if other.node_id == node.node_id:
            continue
        if other.end_time < node.start_time:  # Prior node
            if other.topic_name.lower() == node_topic:
                count += 1

    return count


def compute_initiator_ratio(messages: list[RawMessage]) -> float:
    """Compute fraction of exchanges where user sent the opening message.

    An "exchange" is a pair of consecutive messages where sender alternates.
    The "opening message" is the first message of the pair.

    Args:
        messages: List of RawMessage objects.

    Returns:
        Fraction of exchanges opened by user (0.0 to 1.0).
    """
    if len(messages) < 2:
        return 0.0

    # Find alternating message pairs
    user_initiated = 0
    total_pairs = 0

    i = 0
    while i < len(messages) - 1:
        # A pair is two consecutive messages from different senders
        if messages[i].is_send != messages[i + 1].is_send:
            total_pairs += 1
            if messages[i].is_send:  # User sent first
                user_initiated += 1
            i += 2  # Skip to next potential pair
        else:
            i += 1

    if total_pairs == 0:
        return 0.0

    return user_initiated / total_pairs


def extract_llm_signals(
    node: TopicNode,
    messages: list[RawMessage],
    llm: "NonCoTLLM",
) -> tuple[float, float]:
    """Extract emotional_tone and conflict_intensity using LLM.

    Args:
        node: The TopicNode to analyze.
        messages: Messages in this node.
        llm: The NonCoTLLM to use.

    Returns:
        Tuple of (emotional_tone, conflict_intensity).
    """
    if not messages:
        return (0.0, 0.0)

    # Build prompt with message content
    msg_lines = []
    for msg in messages:
        sender = "我" if msg.is_send else "TA"
        msg_lines.append(f"{sender}: {msg.parsed_content}")

    prompt = f"""分析以下对话片段的情感基调(-1到1)和冲突强度(0到1)。
返回JSON格式: {{"emotional_tone": 数值, "conflict_intensity": 数值}}

emotional_tone: -1表示非常负面(愤怒/悲伤/沮丧), 0表示中性, 1表示非常正面(开心/温暖/亲密)
conflict_intensity: 0表示无冲突, 1表示激烈冲突/争吵

对话内容:
{chr(10).join(msg_lines)}"""

    system_prompt = "你是一个情感分析助手，负责分析对话的情感和冲突程度。"

    try:
        response = llm.complete(system_prompt, prompt, response_format="json_object")
        data = json.loads(response)

        emotional_tone = float(data.get("emotional_tone", 0.0))
        conflict_intensity = float(data.get("conflict_intensity", 0.0))

        # Clamp to valid ranges
        emotional_tone = max(-1.0, min(1.0, emotional_tone))
        conflict_intensity = max(0.0, min(1.0, conflict_intensity))

        return (emotional_tone, conflict_intensity)

    except (json.JSONDecodeError, ValueError, KeyError):
        return (0.0, 0.0)


def extract_llm_signals_batch(
    nodes_with_messages: list[tuple[TopicNode, list[RawMessage]]],
    llm: "NonCoTLLM",
) -> dict[str, tuple[float, float]]:
    """Extract emotional_tone and conflict_intensity for multiple nodes in one LLM call.

    Args:
        nodes_with_messages: List of (TopicNode, messages) tuples.
        llm: The NonCoTLLM to use.

    Returns:
        Dict mapping node_id -> (emotional_tone, conflict_intensity).
        Falls back to (0.0, 0.0) for any node that fails to parse.
    """
    if not nodes_with_messages:
        return {}

    node_sections = []
    for node, messages in nodes_with_messages:
        if not messages:
            node_sections.append(f'节点"{node.node_id}"（话题：{node.topic_name}）:\n（无消息）')
            continue
        msg_lines = []
        for msg in messages:
            sender = "我" if msg.is_send else "TA"
            msg_lines.append(f"{sender}: {msg.parsed_content}")
        node_sections.append(f'节点"{node.node_id}"（话题：{node.topic_name}）:\n' + "\n".join(msg_lines))

    n = len(nodes_with_messages)
    prompt = f"""分析以下 {n} 个对话节点，分别给出情感基调(-1到1)和冲突强度(0到1)。
返回JSON格式：{{"nodes": [{{"node_id": "节点ID", "emotional_tone": 数值, "conflict_intensity": 数值}}]}}
数组长度必须等于 {n}，顺序与输入一致。

{chr(10).join(node_sections)}"""

    system_prompt = "你是一个情感分析助手，负责分析对话的情感和冲突程度。"

    results: dict[str, tuple[float, float]] = {}

    try:
        response = llm.complete(system_prompt, prompt, max_tokens=1000, response_format="json_object")
        data = json.loads(response)
        for item in data.get("nodes", []):
            node_id = str(item.get("node_id", ""))
            if not node_id:
                continue
            tone = max(-1.0, min(1.0, float(item.get("emotional_tone", 0.0))))
            intensity = max(0.0, min(1.0, float(item.get("conflict_intensity", 0.0))))
            results[node_id] = (tone, intensity)
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    # Fill in fallback for any missing node
    for node, _ in nodes_with_messages:
        if node.node_id not in results:
            results[node.node_id] = (0.0, 0.0)

    return results


def compute_all_metadata(
    talker_id: str,
    llm: "NonCoTLLM",
    conn: sqlite3.Connection,
    baseline_terms: set[str] | None = None,
    debug: bool = False,
    force_recompute: bool = False,
) -> list[MetadataSignals]:
    """Compute metadata signals for all nodes in a conversation.

    Skips nodes that already have metadata in the database unless force_recompute
    is True. This reduces LLM calls and algorithmic computation on re-runs.

    Args:
        talker_id: The conversation's talker ID.
        llm: The NonCoTLLM to use.
        conn: SQLite connection.
        baseline_terms: Set of baseline address terms (optional).
        debug: If True, print debug information.
        force_recompute: If True, recompute all nodes and ignore existing metadata.

    Returns:
        List of MetadataSignals objects, ordered by node start_time.
    """
    if baseline_terms is None:
        baseline_terms = {"宝贝", "亲爱的", "宝宝", "亲"}

    # Get all nodes
    nodes = get_nodes(conn, talker_id)
    if not nodes:
        return []

    node_ids = {n.node_id for n in nodes}

    # Load existing metadata and determine which nodes to skip
    existing_by_node_id: dict[str, MetadataSignals] = {}
    if not force_recompute:
        existing = get_all_metadata(conn, talker_id)
        existing_by_node_id = {
            s.node_id: s for s in existing if s.node_id in node_ids
        }
        if debug and existing_by_node_id:
            print(
                f"Skipping {len(existing_by_node_id)} nodes with existing metadata",
                file=sys.stderr,
            )

    nodes_to_compute = [n for n in nodes if n.node_id not in existing_by_node_id]

    # Get all messages for term shift baseline
    all_messages = get_all_messages(conn, talker_id)

    # Build a mapping from local_id to message
    msg_by_id = {m.local_id: m for m in all_messages}

    # Build per-node data only for nodes that need computation
    node_data = []
    for node in nodes_to_compute:
        node_messages = [
            msg_by_id[lid]
            for lid in range(node.start_local_id, node.end_local_id + 1)
            if lid in msg_by_id
        ]
        reply_delay_avg, reply_delay_max = compute_reply_delay(node_messages)
        term_shift = compute_term_shift(node_messages, baseline_terms)
        silence_event = compute_silence_event(node, nodes)
        topic_freq = compute_topic_frequency(node, nodes)
        initiator_ratio = compute_initiator_ratio(node_messages)

        node_data.append((node, node_messages, {
            "reply_delay_avg": reply_delay_avg,
            "reply_delay_max": reply_delay_max,
            "term_shift": term_shift,
            "silence_event": silence_event,
            "topic_freq": topic_freq,
            "initiator_ratio": initiator_ratio,
        }))

    # Compute LLM signals in parallel batches (only for nodes_to_compute)
    BATCH_SIZE = 8
    max_workers: int = getattr(llm, "max_workers", 8)
    llm_results: dict[str, tuple[float, float]] = {}

    if node_data:
        batches = [node_data[s : s + BATCH_SIZE] for s in range(0, len(node_data), BATCH_SIZE)]

        with ThreadPoolExecutor(max_workers=min(max_workers, len(batches))) as executor:
            future_to_batch = {
                executor.submit(
                    extract_llm_signals_batch,
                    [(node, msgs) for node, msgs, _ in batch],
                    llm,
                ): batch
                for batch in batches
            }
            for future in as_completed(future_to_batch):
                try:
                    llm_results.update(future.result())
                except Exception:
                    for node, _, _ in future_to_batch[future]:
                        llm_results[node.node_id] = (0.0, 0.0)

    # Build signals for computed nodes and persist
    new_signals_by_node: dict[str, MetadataSignals] = {}
    for node, node_messages, algo in node_data:
        emotional_tone, conflict_intensity = llm_results.get(node.node_id, (0.0, 0.0))

        signals = MetadataSignals(
            node_id=node.node_id,
            talker_id=talker_id,
            reply_delay_avg_s=algo["reply_delay_avg"],
            reply_delay_max_s=algo["reply_delay_max"],
            term_shift_score=algo["term_shift"],
            silence_event=algo["silence_event"],
            topic_frequency=algo["topic_freq"],
            initiator_ratio=algo["initiator_ratio"],
            emotional_tone=emotional_tone,
            conflict_intensity=conflict_intensity,
        )

        upsert_metadata(conn, signals)
        new_signals_by_node[node.node_id] = signals

        if debug:
            print(
                f"Node {node.topic_name}: reply_delay={algo['reply_delay_avg']:.1f}s, "
                f"emotional_tone={emotional_tone:.2f}, conflict={conflict_intensity:.2f}",
                file=sys.stderr,
            )

    # Assemble final list in node order (by start_time)
    all_signals = []
    for node in nodes:
        if node.node_id in existing_by_node_id:
            all_signals.append(existing_by_node_id[node.node_id])
        else:
            all_signals.append(new_signals_by_node[node.node_id])

    return all_signals


def detect_anomalies(
    signals: list[MetadataSignals],
    talker_id: str,
) -> list[AnomalyAnchor]:
    """Detect anomaly anchors where signals exceed 2σ from baseline.

    Args:
        signals: List of MetadataSignals for all nodes.
        talker_id: The conversation's talker ID.

    Returns:
        List of AnomalyAnchor objects.
    """
    if len(signals) < 2:
        # Need at least 2 points for std calculation
        return []

    anchors = []

    # Signal fields to check (excluding node_id and talker_id)
    signal_fields = [
        ("reply_delay_avg_s", "reply_delay"),
        ("reply_delay_max_s", "reply_delay"),
        ("term_shift_score", "term_shift"),
        ("topic_frequency", "topic_frequency"),
        ("initiator_ratio", "initiator_ratio"),
        ("emotional_tone", "emotional_tone"),
        ("conflict_intensity", "conflict_intensity"),
    ]

    for field_name, signal_name in signal_fields:
        # Extract values for this signal
        values = [getattr(s, field_name) for s in signals]

        try:
            mean = statistics.mean(values)
            std = statistics.stdev(values)
        except statistics.StatisticsError:
            continue

        if std == 0:
            continue

        threshold = mean + 2 * std

        # Find anomalies (values above threshold)
        for s in signals:
            value = getattr(s, field_name)
            if value > threshold:
                # Find the node to get event_date
                # We need to look up the node's start_time
                # For now, we'll store the node_id and compute date later
                anchors.append(AnomalyAnchor(
                    talker_id=talker_id,
                    node_id=s.node_id,
                    signal_name=signal_name,
                    signal_value=value,
                    baseline_mean=mean,
                    baseline_std=std,
                    event_date="",  # Will be filled in by caller
                ))

    # Also check silence_event (boolean, not numeric)
    for s in signals:
        if s.silence_event:
            anchors.append(AnomalyAnchor(
                talker_id=talker_id,
                node_id=s.node_id,
                signal_name="silence_event",
                signal_value=1.0,
                baseline_mean=0.0,
                baseline_std=0.0,
                event_date="",
            ))

    return anchors


def build_layer15(
    talker_id: str,
    llm: "NonCoTLLM",
    conn: sqlite3.Connection,
    debug: bool = False,
    force_recompute: bool = False,
) -> tuple[list[MetadataSignals], list[AnomalyAnchor]]:
    """Build Layer 1.5 metadata for a conversation.

    Args:
        talker_id: The conversation's talker ID.
        llm: The NonCoTLLM to use.
        conn: SQLite connection.
        debug: If True, print debug information.
        force_recompute: If True, recompute all metadata and ignore existing.

    Returns:
        Tuple of (metadata signals, anomaly anchors).
    """
    if debug:
        print(f"Computing metadata for {talker_id}...", file=sys.stderr)

    # Compute metadata
    signals = compute_all_metadata(
        talker_id, llm, conn, debug=debug, force_recompute=force_recompute
    )

    if debug:
        print(f"Computed {len(signals)} metadata entries", file=sys.stderr)

    # Detect anomalies
    anchors = detect_anomalies(signals, talker_id)

    # Update anchors with event dates
    nodes = get_nodes(conn, talker_id)
    node_by_id = {n.node_id: n for n in nodes}

    for anchor in anchors:
        if anchor.node_id in node_by_id:
            node = node_by_id[anchor.node_id]
            anchor.event_date = datetime.fromtimestamp(
                node.start_time / 1000
            ).strftime("%Y-%m-%d")

    # Persist anchors
    upsert_anchors(conn, anchors)

    if debug:
        print(f"Detected {len(anchors)} anomaly anchors", file=sys.stderr)

    return (signals, anchors)


def main():
    """CLI entry point for Layer 1.5 metadata."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Build Layer 1.5 metadata")
    parser.add_argument("--talker", required=True, help="Talker ID to process")
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
        "--force",
        action="store_true",
        help="Force recompute all metadata, ignore existing",
    )
    args = parser.parse_args()

    # Initialize database
    conn = sqlite3.connect(args.db)

    # Create stub LLM for testing
    from .llm import StubNonCoTLLM
    llm = StubNonCoTLLM()

    try:
        signals, anchors = build_layer15(
            talker_id=args.talker,
            llm=llm,
            conn=conn,
            debug=args.debug,
            force_recompute=args.force,
        )

        # Print anomaly summary table
        print("\n=== Anomaly Anchors ===")
        print(f"{'Date':<12} {'Signal':<20} {'Value':>12} {'Baseline':>12}")
        print("-" * 58)

        for anchor in sorted(anchors, key=lambda a: a.event_date):
            print(
                f"{anchor.event_date:<12} "
                f"{anchor.signal_name:<20} "
                f"{anchor.signal_value:>12.2f} "
                f"{anchor.baseline_mean:>8.2f} ± {anchor.baseline_std:.2f}"
            )

        print(f"\nTotal: {len(anchors)} anomalies")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
