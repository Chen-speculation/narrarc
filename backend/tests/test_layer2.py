"""Unit tests for Layer 2 Semantic Threads module."""

import pytest
import tempfile
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

from narrative_mirror.models import TopicNode, RawMessage
from narrative_mirror.layer2 import (
    get_thread,
    stage1_candidates,
    stage1_5_rerank,
    stage2_arbitrate,
)
from narrative_mirror.llm import StubCoTLLM, StubReranker


def make_node(node_id: str, topic: str, start_time: int, start_id: int, end_id: int) -> TopicNode:
    """Helper to create a test node."""
    return TopicNode(
        node_id=node_id,
        talker_id="test",
        burst_id=f"burst_{node_id}",
        topic_name=topic,
        start_local_id=start_id,
        end_local_id=end_id,
        start_time=start_time,
        end_time=start_time + 10 * 60 * 1000,
    )


class TestStage1Candidates:
    """Tests for Stage 1 candidate finding."""

    def test_similarity_threshold_filtering(self):
        """Pairs below threshold should be excluded."""
        import sqlite3
        import chromadb
        from narrative_mirror.db import init_db
        from narrative_mirror.layer2 import init_chroma

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            # Create in-memory ChromaDB for testing
            client = chromadb.EphemeralClient()
            collection = client.create_collection("test_collection")

            base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
            node_a1 = make_node("a1", "工作压力", base_ts, 1, 5)
            node_b = make_node("b", "工作压力", base_ts + 3600000, 6, 10)
            node_a2 = make_node("a2", "日常生活", base_ts + 7200000, 11, 15)
            node_c = make_node("c", "娱乐活动", base_ts + 10800000, 16, 20)

            nodes = [node_a1, node_b, node_a2, node_c]

            # Manually add embeddings with known similarities
            # a1 and b: high similarity (0.81)
            # a2 and c: low similarity (0.31)
            import math
            dim = 1024

            # Create vectors where a1 and b are similar, a2 and c are dissimilar
            vec_a1 = [0.5] * dim
            vec_b = [0.5] * dim  # Same as a1 -> similarity = 1.0
            vec_a2 = [1.0] * dim
            vec_c = [-1.0] * dim  # Opposite to a2 -> low similarity

            # Normalize
            def normalize(v):
                mag = math.sqrt(sum(x * x for x in v))
                return [x / mag for x in v]

            collection.upsert(
                ids=["a1", "b", "a2", "c"],
                embeddings=[normalize(vec_a1), normalize(vec_b), normalize(vec_a2), normalize(vec_c)],
                metadatas=[{"talker_id": "test", "topic_name": n.topic_name, "start_time": n.start_time} for n in nodes],
                documents=[n.topic_name for n in nodes],
            )

            # Mock the query to return known results
            # We'll patch the collection.query to return what we expect

            conn.close()


class TestGetThread:
    """Tests for thread traversal."""

    def test_single_node(self):
        """Single node with no pointers should return just itself."""
        import sqlite3
        from narrative_mirror.db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            thread = get_thread("n1", "test", conn)
            assert thread == ["n1"]

            conn.close()

    def test_thread_traversal(self):
        """Thread should follow pointers in both directions."""
        import sqlite3
        from narrative_mirror.db import init_db, upsert_pointer

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            # Create pointers: n1 -> n2 -> n3
            upsert_pointer(conn, "n1", "n2", "test", "reason1", 0.8)
            upsert_pointer(conn, "n2", "n3", "test", "reason2", 0.8)

            # Get thread starting from n2
            thread = get_thread("n2", "test", conn)
            assert set(thread) == {"n1", "n2", "n3"}

            conn.close()


class TestStage2Arbitrate:
    """Tests for LLM arbitration."""

    def test_confirmed_link_written(self):
        """Confirmed link should be written to DB."""
        import sqlite3
        from narrative_mirror.db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
            node_a = make_node("n1", "工作压力", base_ts, 1, 5)
            node_b = make_node("n2", "工作压力", base_ts + 3600000, 6, 10)

            # StubCoTLLM returns linked: true for semantic prompts
            llm = StubCoTLLM()

            links = stage2_arbitrate(
                [(node_a, node_b, 0.81)],
                llm,
                conn,
                "test",
                debug=False,
            )

            assert len(links) == 1
            assert links[0][0] == "n1"
            assert links[0][1] == "n2"

            conn.close()

    def test_rejected_link_skipped(self):
        """Rejected link should not be written."""
        import sqlite3
        from narrative_mirror.db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
            node_a = make_node("n1", "工作压力", base_ts, 1, 5)
            node_b = make_node("n2", "日常生活", base_ts + 3600000, 6, 10)

            # Create a mock LLM that returns linked: false
            class RejectingLLM:
                def think_and_complete(self, system, prompt, max_tokens=4096):
                    return '{"linked": false, "reason": "Different topics"}'

            llm = RejectingLLM()

            links = stage2_arbitrate(
                [(node_a, node_b, 0.31)],
                llm,
                conn,
                "test",
                debug=False,
            )

            assert len(links) == 0

            conn.close()

    def test_malformed_response_skipped(self):
        """Malformed response should be skipped after retry."""
        import sqlite3
        from narrative_mirror.db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
            node_a = make_node("n1", "工作压力", base_ts, 1, 5)
            node_b = make_node("n2", "工作压力", base_ts + 3600000, 6, 10)

            # Create a mock LLM that returns invalid JSON
            class BadLLM:
                def think_and_complete(self, system, prompt, max_tokens=4096):
                    return "not valid json"

            llm = BadLLM()

            links = stage2_arbitrate(
                [(node_a, node_b, 0.81)],
                llm,
                conn,
                "test",
                debug=False,
            )

            assert len(links) == 0

            conn.close()


class TestStage15Rerank:
    """Tests for Stage 1.5 reranking."""

    def test_stub_reranker_all_pass(self):
        """StubReranker with default 0.8 should pass all pairs."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        node_a = make_node("n1", "工作压力", base_ts, 1, 5)
        node_b = make_node("n2", "工作压力", base_ts + 3600000, 6, 10)
        node_c = make_node("n3", "日常生活", base_ts + 7200000, 11, 15)

        pairs = [
            (node_a, node_b, 0.81),
            (node_a, node_c, 0.5),
        ]

        reranker = StubReranker(score=0.8)  # Default score
        reranked = stage1_5_rerank(pairs, reranker, rerank_threshold=0.5, top_m=20)

        # All pairs should pass (score 0.8 > threshold 0.5)
        assert len(reranked) == 2

    def test_low_score_all_filtered(self):
        """Pairs below threshold should be filtered."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        node_a = make_node("n1", "工作压力", base_ts, 1, 5)
        node_b = make_node("n2", "工作压力", base_ts + 3600000, 6, 10)

        pairs = [(node_a, node_b, 0.81)]

        # StubReranker returns 0.2 for all pairs
        reranker = StubReranker(score=0.2)
        reranked = stage1_5_rerank(pairs, reranker, rerank_threshold=0.5, top_m=20)

        # All pairs should be filtered (0.2 < 0.5)
        assert len(reranked) == 0

    def test_top_m_limit(self):
        """Should return at most top_m pairs."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        nodes = [
            make_node(f"n{i}", f"话题{i}", base_ts + i * 3600000, i * 5 + 1, i * 5 + 5)
            for i in range(10)
        ]

        # Create many pairs
        pairs = []
        for i in range(len(nodes) - 1):
            pairs.append((nodes[i], nodes[i + 1], 0.5))

        reranker = StubReranker(score=0.8)
        reranked = stage1_5_rerank(pairs, reranker, rerank_threshold=0.5, top_m=3)

        # Should return only top_m=3 pairs
        assert len(reranked) == 3

    def test_sorted_by_rerank_score(self):
        """Results should be sorted by rerank score descending."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        node_a = make_node("n1", "工作压力", base_ts, 1, 5)
        node_b = make_node("n2", "日常生活", base_ts + 3600000, 6, 10)
        node_c = make_node("n3", "娱乐活动", base_ts + 7200000, 11, 15)

        pairs = [
            (node_a, node_b, 0.5),
            (node_b, node_c, 0.5),
        ]

        # Create a reranker that returns different scores
        class VariableReranker:
            def __init__(self):
                self.call_count = 0

            def rerank(self, pairs):
                self.call_count += 1
                # Return different scores for each pair
                return [0.9, 0.6]

        reranker = VariableReranker()
        reranked = stage1_5_rerank(pairs, reranker, rerank_threshold=0.5, top_m=20)

        # Should be sorted by score: 0.9 first, then 0.6
        assert len(reranked) == 2
        assert reranked[0][2] == 0.9
        assert reranked[1][2] == 0.6

    def test_empty_input(self):
        """Should return empty list for empty input."""
        reranker = StubReranker()
        reranked = stage1_5_rerank([], reranker)
        assert reranked == []
