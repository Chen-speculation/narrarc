"""Layer 2 Semantic Threads - Embedding and thread pointer construction."""

import json
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Callable, Optional

import chromadb

from .models import TopicNode
from .db import get_nodes, get_all_messages, upsert_pointer, get_existing_pointer

if TYPE_CHECKING:
    from .llm import NonCoTLLM, CoTLLM, Reranker


def init_chroma(data_dir: str, talker_id: str) -> chromadb.Collection:
    """Initialize ChromaDB collection for a conversation.

    Args:
        data_dir: Path to the data directory.
        talker_id: The conversation's talker ID.

    Returns:
        A ChromaDB Collection object.
    """
    client = chromadb.PersistentClient(path=f"{data_dir}/chroma")

    # Collection name must be alphanumeric and underscores
    safe_name = f"narrative_mirror_{talker_id}".replace("-", "_")

    collection = client.get_or_create_collection(
        name=safe_name,
        metadata={"hnsw:space": "cosine"},
    )

    return collection


def _embed_one_node(
    node: TopicNode,
    text: str,
    llm: "NonCoTLLM",
) -> tuple[str, list[float], dict, str]:
    """Embed a single node. Returns (node_id, embedding, metadata, document)."""
    embedding = llm.embed(text)
    return (
        node.node_id,
        embedding,
        {
            "talker_id": node.talker_id,
            "topic_name": node.topic_name,
            "start_time": node.start_time,
        },
        text,
    )


def embed_nodes(
    nodes: list[TopicNode],
    messages_by_node: dict[str, list],
    llm: "NonCoTLLM",
    collection: chromadb.Collection,
) -> int:
    """Embed nodes and store in ChromaDB.

    Args:
        nodes: List of TopicNode objects to embed.
        messages_by_node: Dict mapping node_id to list of messages.
        llm: The NonCoTLLM to use for embedding.
        collection: ChromaDB collection.

    Returns:
        Number of nodes embedded.
    """
    existing_ids = set(collection.get()["ids"]) if collection.count() > 0 else set()

    # Build (node, text) for nodes that need embedding
    to_embed = []
    for node in nodes:
        if node.node_id in existing_ids:
            continue
        messages = messages_by_node.get(node.node_id, [])
        if not messages:
            continue

        content_parts = []
        total_chars = 0
        max_chars = 2000
        for msg in messages:
            content = msg.parsed_content or ""
            if total_chars + len(content) > max_chars:
                break
            content_parts.append(content)
            total_chars += len(content)

        text = f"{node.topic_name}: {' '.join(content_parts)}"
        to_embed.append((node, text))

    if not to_embed:
        return 0

    # Prefer batch embedding (single API call); fall back to parallel individual calls
    results = []
    if hasattr(llm, "embed_batch"):
        EMBED_BATCH_SIZE = 32
        for batch_start in range(0, len(to_embed), EMBED_BATCH_SIZE):
            batch = to_embed[batch_start : batch_start + EMBED_BATCH_SIZE]
            texts = [text for _, text in batch]
            embeddings = llm.embed_batch(texts)
            for (node, text), embedding in zip(batch, embeddings):
                results.append((
                    node.node_id,
                    embedding,
                    {
                        "talker_id": node.talker_id,
                        "topic_name": node.topic_name,
                        "start_time": node.start_time,
                    },
                    text,
                ))
    else:
        # Embed in parallel (I/O bound) - fallback when embed_batch not available
        _max_workers = min(getattr(llm, "max_workers", 8), len(to_embed))
        with ThreadPoolExecutor(max_workers=_max_workers) as executor:
            future_to_node = {
                executor.submit(_embed_one_node, node, text, llm): node
                for node, text in to_embed
            }
            for future in as_completed(future_to_node):
                try:
                    results.append(future.result())
                except Exception:
                    pass

    # Persist to ChromaDB (main thread)
    for node_id, embedding, metadata, document in results:
        collection.upsert(
            ids=[node_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[document],
        )

    return len(results)


def stage1_candidates(
    collection: chromadb.Collection,
    nodes: list[TopicNode],
    conn: sqlite3.Connection,
    threshold: float = 0.3,
    top_k: int = 10,
) -> list[tuple[TopicNode, TopicNode, float]]:
    """Find candidate node pairs based on embedding similarity.

    Args:
        collection: ChromaDB collection.
        nodes: List of TopicNode objects.
        conn: SQLite connection for checking existing pointers.
        threshold: Minimum similarity threshold.
        top_k: Number of similar nodes to consider per query.

    Returns:
        List of (node_a, node_b, similarity) tuples where node_a.start_time < node_b.start_time.
    """
    if collection.count() == 0:
        return []

    # Build node lookup
    node_by_id = {n.node_id: n for n in nodes}

    # Get all embeddings from the collection
    all_data = collection.get(include=["embeddings"])
    if not all_data or not all_data.get("ids"):
        return []

    embeddings = all_data.get("embeddings")
    if embeddings is None:
        return []

    # Build embedding lookup
    embedding_by_id = {}
    for i, node_id in enumerate(all_data["ids"]):
        if embeddings is not None and i < len(embeddings):
            embedding_by_id[node_id] = embeddings[i]

    candidates = []
    seen_pairs = set()

    for node in nodes:
        if node.node_id not in embedding_by_id:
            continue

        # Query using the node's embedding
        embedding = embedding_by_id[node.node_id]
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k + 1, len(nodes)),
        )

        if not results or not results.get("ids"):
            continue

        for i, other_id in enumerate(results["ids"][0]):
            if other_id == node.node_id:
                continue

            other_node = node_by_id.get(other_id)
            if not other_node:
                continue

            # Get similarity (distance is 1 - similarity for cosine)
            distances = results.get("distances")
            distance = distances[0][i] if distances else 0
            similarity = 1 - distance

            if similarity < threshold:
                continue

            # Form time-ordered pair
            if node.start_time < other_node.start_time:
                pair = (node, other_node, similarity)
            else:
                pair = (other_node, node, similarity)

            pair_key = (pair[0].node_id, pair[1].node_id)

            # Skip self-pairs and already seen
            if pair_key in seen_pairs:
                continue

            # Skip existing pointers
            if get_existing_pointer(conn, pair[0].node_id, pair[1].node_id):
                continue

            seen_pairs.add(pair_key)
            candidates.append(pair)

    # Sort by similarity descending
    candidates.sort(key=lambda x: x[2], reverse=True)

    return candidates


def stage1_5_rerank(
    pairs: list[tuple[TopicNode, TopicNode, float]],
    reranker: "Reranker",
    rerank_threshold: float = 0.5,
    top_m: int = 20,
) -> list[tuple[TopicNode, TopicNode, float]]:
    """Re-score candidate pairs using a cross-encoder reranker.

    This Stage 1.5 filters pairs by reranker score and returns top-M.
    (Reranker interface expects all pairs at once; kept serial.)
    """
    if not pairs:
        return []

    text_pairs = [
        (node_a.topic_name, node_b.topic_name)
        for node_a, node_b, _ in pairs
    ]

    scores = reranker.rerank(text_pairs)

    reranked_pairs = []
    for i, (node_a, node_b, _) in enumerate(pairs):
        score = scores[i] if i < len(scores) else 0.0
        if score >= rerank_threshold:
            reranked_pairs.append((node_a, node_b, score))

    reranked_pairs.sort(key=lambda x: x[2], reverse=True)
    return reranked_pairs[:top_m]


def _arbitrate_one_pair(
    node_a: TopicNode,
    node_b: TopicNode,
    similarity: float,
    llm: "CoTLLM",
) -> tuple[TopicNode, TopicNode, float, bool, str]:
    """Arbitrate one pair via LLM. Returns (node_a, node_b, similarity, linked, reason)."""
    prompt = f"""判断以下两个对话节点是否属于同一个演化故事（话题线程）。

节点A:
- 话题: {node_a.topic_name}
- 时间: {node_a.start_time}
- 消息ID范围: {node_a.start_local_id} - {node_a.end_local_id}

节点B:
- 话题: {node_b.topic_name}
- 时间: {node_b.start_time}
- 消息ID范围: {node_b.start_local_id} - {node_b.end_local_id}

相似度: {similarity:.2f}

请判断这两个节点是否描述了同一个话题或故事的演进过程。
返回JSON格式: {{"linked": true/false, "reason": "判断理由"}}

注意：
- linked为true表示两个节点有语义上的延续关系
- linked为false表示两个节点虽然相似但属于不同的话题线程
- 请根据话题内容、时间顺序和语义关系综合判断"""

    system_prompt = "你是一个语义分析助手，负责判断对话节点之间的话题关联性。"

    try:
        response = llm.think_and_complete(system_prompt, prompt, response_format="json_object")
        try:
            data = json.loads(response.strip())
        except json.JSONDecodeError:
            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            json_matches = list(re.finditer(json_pattern, response))
            if json_matches:
                data = json.loads(json_matches[-1].group(0))
            else:
                return (node_a, node_b, similarity, False, "")

        linked = data.get("linked", False)
        reason = data.get("reason", "")
        return (node_a, node_b, similarity, linked, reason)

    except (json.JSONDecodeError, ValueError, KeyError):
        return (node_a, node_b, similarity, False, "")


def stage2_arbitrate(
    pairs: list[tuple[TopicNode, TopicNode, float]],
    llm: "CoTLLM",
    conn: sqlite3.Connection,
    talker_id: str,
    debug: bool = False,
) -> list[tuple[str, str, str, float]]:
    """Use LLM to arbitrate candidate pairs and create thread pointers.

    LLM calls are parallelized (I/O bound). DB writes happen in main thread.
    """
    if not pairs:
        return []

    confirmed_links = []

    # Arbitrate in parallel (I/O bound)
    max_workers = min(getattr(llm, "max_workers", 8), len(pairs))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_pair = {
            executor.submit(_arbitrate_one_pair, node_a, node_b, sim, llm): (node_a, node_b)
            for node_a, node_b, sim in pairs
        }
        for future in as_completed(future_to_pair):
            try:
                node_a, node_b, similarity, linked, reason = future.result()
                if linked:
                    confirmed_links.append((node_a, node_b, similarity, reason))
                    if debug:
                        print(f"Linked: {node_a.topic_name} -> {node_b.topic_name} ({similarity:.2f})", file=sys.stderr)
            except Exception:
                pass

    # Persist pointers in main thread (SQLite)
    for node_a, node_b, similarity, reason in confirmed_links:
        upsert_pointer(
            conn,
            from_id=node_a.node_id,
            to_id=node_b.node_id,
            talker_id=talker_id,
            reason=reason,
            score=similarity,
        )

    return [
        (node_a.node_id, node_b.node_id, reason, similarity)
        for node_a, node_b, similarity, reason in confirmed_links
    ]


def get_thread(node_id: str, talker_id: str, conn: sqlite3.Connection) -> list[str]:
    """Follow thread pointers to get the complete thread for a node.

    Args:
        node_id: Starting node ID.
        talker_id: The conversation's talker ID.
        conn: SQLite connection.

    Returns:
        List of node_ids in the thread, including the starting node.
    """
    cursor = conn.cursor()

    # Collect all nodes in the thread (both forward and backward)
    thread_nodes = {node_id}

    # Follow forward pointers (from_node_id -> to_node_id)
    def follow_forward(current_id: str):
        cursor.execute("""
            SELECT to_node_id FROM semantic_thread_pointers
            WHERE from_node_id = ? AND talker_id = ?
        """, (current_id, talker_id))
        for row in cursor.fetchall():
            next_id = row[0]
            if next_id not in thread_nodes:
                thread_nodes.add(next_id)
                follow_forward(next_id)

    # Follow backward pointers (to_node_id <- from_node_id)
    def follow_backward(current_id: str):
        cursor.execute("""
            SELECT from_node_id FROM semantic_thread_pointers
            WHERE to_node_id = ? AND talker_id = ?
        """, (current_id, talker_id))
        for row in cursor.fetchall():
            prev_id = row[0]
            if prev_id not in thread_nodes:
                thread_nodes.add(prev_id)
                follow_backward(prev_id)

    follow_forward(node_id)
    follow_backward(node_id)

    return list(thread_nodes)


def build_layer2(
    talker_id: str,
    llm_noncot: "NonCoTLLM",
    reranker: "Reranker",
    llm_cot: "CoTLLM",
    conn: sqlite3.Connection,
    data_dir: str,
    sim_threshold: float = 0.3,
    top_k: int = 10,
    rerank_threshold: float = 0.5,
    top_m: int = 20,
    debug: bool = False,
    progress_callback: Optional[Callable[[str, str, str], None]] = None,
) -> tuple[int, int]:
    """Build Layer 2 semantic threads for a conversation.

    Three-stage pipeline:
    1. Stage 1 (embedding): Find candidate pairs by cosine similarity
    2. Stage 1.5 (reranker): Re-score pairs with cross-encoder
    3. Stage 2 (CoT LLM): Semantic arbitration

    Args:
        talker_id: The conversation's talker ID.
        llm_noncot: The NonCoTLLM for embedding.
        reranker: The Reranker for Stage 1.5.
        llm_cot: The CoTLLM for Stage 2 arbitration.
        conn: SQLite connection.
        data_dir: Path to data directory.
        sim_threshold: Similarity threshold for Stage 1 (default 0.3, relaxed for reranker).
        top_k: Number of similar nodes per query.
        rerank_threshold: Minimum reranker score to keep a pair (default 0.5).
        top_m: Maximum pairs to pass to Stage 2 (default 20).
        debug: If True, print debug information.
        progress_callback: Optional (stage, step, detail) callback for UI progress.

    Returns:
        Tuple of (nodes_embedded, pointers_created).
    """
    def _progress(stage: str, step: str, detail: str) -> None:
        if progress_callback:
            progress_callback(stage, step, detail)

    if debug:
        print(f"Building Layer 2 for {talker_id}...", file=sys.stderr)

    # Get all nodes
    nodes = get_nodes(conn, talker_id)
    if not nodes:
        return (0, 0)

    if debug:
        print(f"Found {len(nodes)} nodes", file=sys.stderr)

    # Get all messages
    all_messages = get_all_messages(conn, talker_id)
    msg_by_id = {m.local_id: m for m in all_messages}

    # Build messages_by_node mapping
    messages_by_node = {}
    for node in nodes:
        node_messages = [
            msg_by_id[lid]
            for lid in range(node.start_local_id, node.end_local_id + 1)
            if lid in msg_by_id
        ]
        messages_by_node[node.node_id] = node_messages

    # Initialize ChromaDB
    collection = init_chroma(data_dir, talker_id)

    # Embed nodes
    _progress("layer2", "embed", f"正在嵌入 {len(nodes)} 个节点")
    embedded = embed_nodes(nodes, messages_by_node, llm_noncot, collection)
    _progress("layer2", "embed", f"已嵌入 {embedded} 个节点")
    if debug:
        print(f"Embedded {embedded} nodes", file=sys.stderr)

    # Stage 1: Find candidates (relaxed threshold, reranker will filter)
    _progress("layer2", "stage1", "检索相似节点候选对")
    candidates = stage1_candidates(collection, nodes, conn, sim_threshold, top_k)
    _progress("layer2", "stage1", f"找到 {len(candidates)} 个候选对")
    if debug:
        print(f"Stage 1: Found {len(candidates)} candidate pairs", file=sys.stderr)

    # Stage 1.5: Rerank
    _progress("layer2", "stage1.5", "重排序候选对")
    reranked = stage1_5_rerank(candidates, reranker, rerank_threshold, top_m)
    _progress("layer2", "stage1.5", f"重排后保留 {len(reranked)} 对")
    if debug:
        print(f"Stage 1.5: {len(reranked)} pairs after reranking (threshold={rerank_threshold})", file=sys.stderr)

    # Stage 2: Arbitrate
    _progress("layer2", "stage2", "语义仲裁与链路写入")
    links = stage2_arbitrate(reranked, llm_cot, conn, talker_id, debug)
    _progress("layer2", "stage2", f"已创建 {len(links)} 条语义链路")
    if debug:
        print(f"Stage 2: Created {len(links)} thread pointers", file=sys.stderr)

    return (embedded, len(links))


def main():
    """CLI entry point for Layer 2 build."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Build Layer 2 semantic threads")
    parser.add_argument("--talker", required=True, help="Talker ID to process")
    parser.add_argument(
        "--sim-threshold",
        type=float,
        default=0.3,
        help="Similarity threshold for Stage 1 (default: 0.3)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of similar nodes per query (default: 10)",
    )
    parser.add_argument(
        "--rerank-threshold",
        type=float,
        default=0.5,
        help="Reranker score threshold for Stage 1.5 (default: 0.5)",
    )
    parser.add_argument(
        "--top-m",
        type=int,
        default=20,
        help="Maximum pairs to pass to Stage 2 (default: 20)",
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
        "--data-dir",
        default="data",
        help="Path to data directory (default: data)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yml for real LLM adapters (default: use stub)",
    )
    args = parser.parse_args()

    # Initialize database
    conn = sqlite3.connect(args.db)

    # Create LLMs (use real implementation if config provided, otherwise stub)
    if args.config:
        try:
            from .config import load_config
            from .llm import from_config
            config = load_config(args.config)
            llm_noncot, llm_cot, reranker = from_config(config)
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        from .llm import StubNonCoTLLM, StubCoTLLM, StubReranker
        llm_noncot = StubNonCoTLLM()
        llm_cot = StubCoTLLM()
        reranker = StubReranker()

    try:
        embedded, pointers = build_layer2(
            talker_id=args.talker,
            llm_noncot=llm_noncot,
            reranker=reranker,
            llm_cot=llm_cot,
            conn=conn,
            data_dir=args.data_dir,
            sim_threshold=args.sim_threshold,
            top_k=args.top_k,
            rerank_threshold=args.rerank_threshold,
            top_m=args.top_m,
            debug=args.debug,
        )

        print(f"\nLayer 2 build complete:")
        print(f"  Nodes embedded: {embedded}")
        print(f"  Thread pointers: {pointers}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
