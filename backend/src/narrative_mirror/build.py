"""Layer 1 Build - Burst aggregation and TopicNode construction."""

import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Callable, Optional

from .models import RawMessage, Burst, TopicNode
from .datasource import ChatDataSource, get_data_source
from .db import (
    init_db,
    upsert_messages,
    upsert_burst,
    upsert_node,
    get_node_by_burst,
    get_all_messages,
)

if TYPE_CHECKING:
    from .llm import NonCoTLLM


def aggregate_bursts(
    messages: list[RawMessage],
    gap_seconds: int = 1800,
) -> list[Burst]:
    """Aggregate messages into bursts based on time gaps.

    A new Burst starts whenever the gap between consecutive messages exceeds
    the threshold. System messages (local_type 10000/10002) are excluded.

    Args:
        messages: List of RawMessage objects, sorted by create_time.
        gap_seconds: Gap threshold in seconds (default: 1800 = 30 minutes).

    Returns:
        List of Burst objects.
    """
    if not messages:
        return []

    # Filter out excluded messages (system/forwarded)
    valid_messages = [m for m in messages if not m.excluded]
    if not valid_messages:
        return []

    bursts = []
    current_messages = [valid_messages[0]]
    gap_ms = gap_seconds * 1000

    for i in range(1, len(valid_messages)):
        prev_msg = valid_messages[i - 1]
        curr_msg = valid_messages[i]

        # Check if gap exceeds threshold
        time_gap = curr_msg.create_time - prev_msg.create_time

        if time_gap >= gap_ms:
            # Start a new burst
            bursts.append(Burst(
                talker_id=current_messages[0].talker_id,
                messages=current_messages,
            ))
            current_messages = [curr_msg]
        else:
            # Continue current burst
            current_messages.append(curr_msg)

    # Don't forget the last burst
    if current_messages:
        bursts.append(Burst(
            talker_id=current_messages[0].talker_id,
            messages=current_messages,
        ))

    return bursts


def classify_burst(
    burst: Burst,
    llm: "NonCoTLLM",
    max_retries: int = 2,
) -> list[TopicNode]:
    """Classify a burst into one or more TopicNodes using LLM.

    Args:
        burst: The Burst to classify.
        llm: The NonCoTLLM to use for classification.
        max_retries: Maximum number of retries on malformed response.

    Returns:
        List of TopicNode objects (at least one with topic "未分类" on failure).
    """
    # Build the prompt with message content
    msg_lines = []
    for msg in burst.messages:
        sender = "我" if msg.is_send else "TA"
        msg_lines.append(f"[{msg.local_id}] {sender}: {msg.parsed_content}")

    prompt = f"""分析以下对话片段，识别话题。请返回JSON格式：
{{"topic_name": "主话题名称", "segments": [{{"topic_name": "话题名称", "start_local_id": 起始消息ID, "end_local_id": 结束消息ID}}]}}

如果话题有变化，在segments中按顺序列出每个话题片段。话题名称应为2-5个字的中文描述。

对话内容：
{chr(10).join(msg_lines)}"""

    system_prompt = "你是一个对话分析助手，负责识别和分类对话中的话题。"

    # Try classification with retries
    for attempt in range(max_retries + 1):
        try:
            response = llm.complete(system_prompt, prompt, response_format="json_object")
            data = json.loads(response)

            # Validate response structure
            if "segments" not in data or not isinstance(data["segments"], list):
                raise ValueError("Missing or invalid 'segments' field")

            nodes = []
            for seg in data["segments"]:
                if "topic_name" not in seg or "start_local_id" not in seg or "end_local_id" not in seg:
                    raise ValueError("Invalid segment structure")

                # Find the time range for this segment
                start_msg = next(
                    (m for m in burst.messages if m.local_id == seg["start_local_id"]),
                    burst.messages[0]
                )
                end_msg = next(
                    (m for m in burst.messages if m.local_id == seg["end_local_id"]),
                    burst.messages[-1]
                )

                nodes.append(TopicNode(
                    talker_id=burst.talker_id,
                    burst_id=burst.burst_id,
                    topic_name=seg["topic_name"],
                    start_local_id=seg["start_local_id"],
                    end_local_id=seg["end_local_id"],
                    start_time=start_msg.create_time,
                    end_time=end_msg.create_time,
                ))

            if not nodes:
                raise ValueError("No segments in response")

            return nodes

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if attempt == max_retries:
                # Fallback: treat entire burst as one unclassified node
                return [TopicNode(
                    talker_id=burst.talker_id,
                    burst_id=burst.burst_id,
                    topic_name="未分类",
                    start_local_id=burst.messages[0].local_id,
                    end_local_id=burst.messages[-1].local_id,
                    start_time=burst.start_time,
                    end_time=burst.end_time,
                )]

    # Should not reach here, but just in case
    return [TopicNode(
        talker_id=burst.talker_id,
        burst_id=burst.burst_id,
        topic_name="未分类",
        start_local_id=burst.messages[0].local_id,
        end_local_id=burst.messages[-1].local_id,
        start_time=burst.start_time,
        end_time=burst.end_time,
    )]


def classify_bursts_batch(
    bursts: list[Burst],
    llm: "NonCoTLLM",
    max_retries: int = 1,
) -> list[list[TopicNode]]:
    """Classify multiple bursts in a single LLM call.

    Sends all bursts as one prompt and parses a JSON array response.
    Falls back to "未分类" for any burst whose segments fail to parse.

    Args:
        bursts: List of Burst objects to classify.
        llm: The NonCoTLLM to use.
        max_retries: Retry attempts on parse failure (retries entire batch).

    Returns:
        List of list[TopicNode] in the same order as input bursts.
    """
    if not bursts:
        return []

    # Build combined prompt
    burst_sections = []
    for idx, burst in enumerate(bursts):
        msg_lines = []
        for msg in burst.messages:
            sender = "我" if msg.is_send else "TA"
            msg_lines.append(f"[{msg.local_id}] {sender}: {msg.parsed_content}")
        burst_sections.append(f"片段{idx}:\n" + "\n".join(msg_lines))

    n = len(bursts)
    prompt = f"""分析以下 {n} 个对话片段，分别识别每个片段的话题。
返回JSON格式：{{"bursts": [{{"segments": [{{"topic_name": "话题名称", "start_local_id": 起始消息ID, "end_local_id": 结束消息ID}}]}}]}}
数组长度必须等于 {n}，顺序与输入一致。话题名称应为2-5个中文字。

{chr(10).join(burst_sections)}"""

    system_prompt = "你是一个对话分析助手，负责识别和分类对话中的话题。"

    def _make_fallback(burst: Burst) -> list[TopicNode]:
        return [TopicNode(
            talker_id=burst.talker_id,
            burst_id=burst.burst_id,
            topic_name="未分类",
            start_local_id=burst.messages[0].local_id,
            end_local_id=burst.messages[-1].local_id,
            start_time=burst.start_time,
            end_time=burst.end_time,
        )]

    for attempt in range(max_retries + 1):
        try:
            response = llm.complete(system_prompt, prompt, max_tokens=3000, response_format="json_object")
            data = json.loads(response)
            raw_bursts = data.get("bursts", [])

            if not isinstance(raw_bursts, list) or len(raw_bursts) != n:
                raise ValueError(f"Expected {n} burst entries, got {len(raw_bursts)}")

            results: list[list[TopicNode]] = []
            for burst, burst_data in zip(bursts, raw_bursts):
                try:
                    segments = burst_data.get("segments", [])
                    if not segments:
                        raise ValueError("No segments")
                    nodes = []
                    for seg in segments:
                        start_msg = next(
                            (m for m in burst.messages if m.local_id == seg["start_local_id"]),
                            burst.messages[0],
                        )
                        end_msg = next(
                            (m for m in burst.messages if m.local_id == seg["end_local_id"]),
                            burst.messages[-1],
                        )
                        nodes.append(TopicNode(
                            talker_id=burst.talker_id,
                            burst_id=burst.burst_id,
                            topic_name=seg["topic_name"],
                            start_local_id=seg["start_local_id"],
                            end_local_id=seg["end_local_id"],
                            start_time=start_msg.create_time,
                            end_time=end_msg.create_time,
                        ))
                    results.append(nodes)
                except (KeyError, ValueError):
                    results.append(_make_fallback(burst))

            return results

        except (json.JSONDecodeError, ValueError) as e:
            if attempt == max_retries:
                return [_make_fallback(b) for b in bursts]

    return [_make_fallback(b) for b in bursts]


def build_layer1(
    talker_id: str,
    source: ChatDataSource,
    llm: "NonCoTLLM",
    conn: sqlite3.Connection,
    gap_seconds: int = 1800,
    debug: bool = False,
    progress_callback: Optional[Callable[[str, str, str], None]] = None,
) -> list[TopicNode]:
    """Build Layer 1 topic nodes for a conversation.

    This function:
    1. Fetches messages from the data source
    2. Persists messages to the database
    3. Aggregates messages into bursts
    4. Classifies each burst (skipping already-classified ones)
    5. Persists topic nodes to the database

    Args:
        talker_id: The conversation's talker ID.
        source: The data source to fetch messages from.
        llm: The NonCoTLLM to use for classification.
        conn: SQLite connection.
        gap_seconds: Gap threshold for burst aggregation.
        debug: If True, print debug information.
        progress_callback: Optional (stage, step, detail) callback for UI progress.

    Returns:
        List of all TopicNode objects for the conversation.
    """
    def _progress(stage: str, step: str, detail: str) -> None:
        if progress_callback:
            progress_callback(stage, step, detail)

    # Fetch all messages (batch fetch to avoid truncation; datasource supports offset)
    if debug:
        print(f"Fetching messages for {talker_id}...", file=sys.stderr)

    BATCH_SIZE = 10000
    messages = []
    offset = 0
    while True:
        batch = source.get_messages(talker_id, limit=BATCH_SIZE, offset=offset)
        if not batch:
            break
        messages.extend(batch)
        offset += BATCH_SIZE
        _progress("layer1", "fetch", f"已获取 {len(messages)} 条消息")
        if len(batch) < BATCH_SIZE:
            break

    _progress("layer1", "fetch", f"已获取 {len(messages)} 条消息")

    if debug:
        print(f"Fetched {len(messages)} messages", file=sys.stderr)

    # Persist messages
    inserted = upsert_messages(conn, messages)
    if debug:
        print(f"Inserted {inserted} new messages", file=sys.stderr)

    # Aggregate into bursts
    bursts = aggregate_bursts(messages, gap_seconds)
    _progress("layer1", "aggregate", f"已聚合为 {len(bursts)} 个 burst")
    if debug:
        print(f"Aggregated into {len(bursts)} bursts", file=sys.stderr)

    # Process each burst
    all_nodes = []
    bursts_to_classify = []  # (index, burst)

    for i, burst in enumerate(bursts):
        existing_nodes = get_node_by_burst(conn, burst.burst_id)
        if existing_nodes:
            if debug:
                print(f"Burst {i+1}/{len(bursts)}: already classified, skipping", file=sys.stderr)
            all_nodes.extend(existing_nodes)
            continue

        upsert_burst(conn, burst)
        bursts_to_classify.append((i, burst))

    # Classify bursts in parallel batches.
    # Each batch call handles BATCH_SIZE bursts in one LLM request, reducing
    # total request count (important for rate-limited providers). Batch calls
    # themselves run concurrently up to llm.max_workers (configurable).
    if bursts_to_classify:
        _progress("layer1", "classify", f"正在分类 {len(bursts_to_classify)} 个 burst")
        BATCH_SIZE = 8
        max_workers: int = getattr(llm, "max_workers", 8)

        # Group into batches
        batches: list[list[tuple[int, "Burst"]]] = []
        for start in range(0, len(bursts_to_classify), BATCH_SIZE):
            batches.append(bursts_to_classify[start : start + BATCH_SIZE])

        batch_output: dict[int, list[TopicNode]] = {}

        with ThreadPoolExecutor(max_workers=min(max_workers, len(batches))) as executor:
            future_to_batch = {
                executor.submit(classify_bursts_batch, [b for _, b in batch], llm): (bi, batch)
                for bi, batch in enumerate(batches)
            }
            for future in as_completed(future_to_batch):
                bi, batch = future_to_batch[future]
                try:
                    batch_output[bi] = future.result()
                except Exception:
                    batch_output[bi] = [None] * len(batch)
                done = sum(len(batches[bbi]) for bbi in batch_output)
                _progress("layer1", "classify", f"已分类 {done}/{len(bursts)} 个 burst")

        for bi, batch in enumerate(batches):
            results = batch_output.get(bi, [None] * len(batch))
            for (i, burst), nodes in zip(batch, results):
                if not nodes:
                    nodes = [TopicNode(
                        talker_id=burst.talker_id,
                        burst_id=burst.burst_id,
                        topic_name="未分类",
                        start_local_id=burst.messages[0].local_id,
                        end_local_id=burst.messages[-1].local_id,
                        start_time=burst.start_time,
                        end_time=burst.end_time,
                    )]
                for node in nodes:
                    upsert_node(conn, node)
                    all_nodes.append(node)
                if debug:
                    topics = ", ".join(n.topic_name for n in nodes)
                    print(f"Burst {i+1}/{len(bursts)}: {topics}", file=sys.stderr)

    return all_nodes


def main():
    """CLI entry point for Layer 1 build."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Build Layer 1 topic nodes")
    parser.add_argument("--talker", required=True, help="Talker ID to process")
    parser.add_argument(
        "--source",
        choices=["mock", "weflow", "file"],
        default="mock",
        help="Data source to use (default: mock)",
    )
    parser.add_argument(
        "--messages-path",
        default=None,
        help="Path to messages JSON file (required when source=file)",
    )
    parser.add_argument(
        "--sessions-path",
        default=None,
        help="Path to sessions JSON file (required when source=file)",
    )
    parser.add_argument(
        "--burst-gap-seconds",
        type=int,
        default=1800,
        help="Gap threshold for burst aggregation in seconds (default: 1800)",
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
        "--weflow-url",
        default="http://localhost:5031",
        help="WeFlow base URL (default: http://localhost:5031)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yml for real LLM adapters (default: use stub)",
    )
    args = parser.parse_args()

    # Initialize database
    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    conn = init_db(args.db)

    # Get data source
    try:
        source = get_data_source(
            args.source,
            args.weflow_url,
            args.messages_path,
            args.sessions_path,
        )
    except Exception as e:
        print(f"Error connecting to data source: {e}", file=sys.stderr)
        sys.exit(1)

    # Create LLM (use real implementation if config provided, otherwise stub)
    if args.config:
        try:
            from .config import load_config
            from .llm import from_config
            config = load_config(args.config)
            llm, _, _ = from_config(config)
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        from .llm import StubNonCoTLLM
        llm = StubNonCoTLLM()

    # Build Layer 1
    try:
        nodes = build_layer1(
            talker_id=args.talker,
            source=source,
            llm=llm,
            conn=conn,
            gap_seconds=args.burst_gap_seconds,
            debug=args.debug,
        )
        print(f"\nCreated {len(nodes)} topic nodes", file=sys.stderr)
    except Exception as e:
        print(f"Error during build: {e}", file=sys.stderr)
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
