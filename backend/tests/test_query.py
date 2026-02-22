"""Unit tests for Query Pipeline module."""

import pytest
import tempfile
import os
from datetime import datetime

from narrative_mirror.models import QueryIntent, NarrativePhase, TopicNode, AnomalyAnchor
from narrative_mirror.query import (
    parse_intent,
    lookup_anchors,
    expand_candidates,
    segment_narrative,
    verify_evidence,
    format_cards,
)
from narrative_mirror.llm import StubCoTLLM


class TestParseIntent:
    """Tests for intent parsing."""

    def test_breakup_question(self):
        """Breakup question should return arc_narrative."""
        llm = StubCoTLLM()
        intent = parse_intent("我们是怎么一步步分手的？", llm)

        # StubCoTLLM returns hardcoded response with query_type=arc_narrative
        assert intent.query_type == "arc_narrative"

    def test_validates_dimensions(self):
        """Invalid dimensions should be filtered out."""
        # This is tested via the actual implementation
        llm = StubCoTLLM()
        intent = parse_intent("test question", llm)

        # All returned dimensions should be valid
        from narrative_mirror.metadata import CANONICAL_SIGNALS
        for dim in intent.focus_dimensions:
            assert dim in CANONICAL_SIGNALS


class TestLookupAnchors:
    """Tests for anchor lookup."""

    def test_empty_anchors(self):
        """Empty intent should return empty list if no data."""
        import sqlite3
        from narrative_mirror.db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            intent = QueryIntent(
                query_type="arc_narrative",
                focus_dimensions=["reply_delay"],
                time_range=None,
            )

            anchors = lookup_anchors(intent, "test", conn)
            assert anchors == []

            conn.close()


class TestExpandCandidates:
    """Tests for candidate expansion."""

    def test_no_anchors_returns_all_nodes(self):
        """No anchors should return all nodes (up to max_nodes)."""
        import sqlite3
        from narrative_mirror.db import init_db, upsert_node
        from narrative_mirror.models import TopicNode

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            # Add some nodes
            base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
            for i in range(3):
                node = TopicNode(
                    node_id=f"n{i}",
                    talker_id="test",
                    burst_id=f"b{i}",
                    topic_name=f"topic{i}",
                    start_local_id=i * 5,
                    end_local_id=i * 5 + 4,
                    start_time=base_ts + i * 3600000,
                    end_time=base_ts + i * 3600000 + 600000,
                )
                upsert_node(conn, node)

            candidates = expand_candidates([], "test", conn, max_nodes=60)
            assert len(candidates) == 3

            conn.close()

    def test_no_semantic_params_falls_back_to_original_behavior(self):
        """Without question/llm_noncot/chroma_dir, expand_candidates uses anchor+thread only."""
        from narrative_mirror.db import init_db, upsert_node, upsert_anchors

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
            for i in range(4):
                node = TopicNode(
                    node_id=f"n{i}",
                    talker_id="test",
                    burst_id=f"b{i}",
                    topic_name=f"topic{i}",
                    start_local_id=i * 5,
                    end_local_id=i * 5 + 4,
                    start_time=base_ts + i * 3600000,
                    end_time=base_ts + i * 3600000 + 600000,
                )
                upsert_node(conn, node)

            anchor = AnomalyAnchor(
                anchor_id="a1", talker_id="test", node_id="n1",
                signal_name="conflict_intensity", signal_value=0.8,
                baseline_mean=0.2, baseline_std=0.1,
                event_date="2023-01-01",
            )
            upsert_anchors(conn, [anchor])

            intent = QueryIntent(
                query_type="event_retrieval",
                focus_dimensions=["conflict_intensity"],
                time_range=None,
            )
            anchors = lookup_anchors(intent, "test", conn)

            # Without semantic params - only anchor expansion
            candidates_no_sem = expand_candidates(
                anchors, "test", conn, max_nodes=60, query_type="event_retrieval",
            )
            # With empty semantic params - should behave same (no chroma, no embed)
            candidates_with_empty = expand_candidates(
                anchors, "test", conn, max_nodes=60, query_type="event_retrieval",
                question="", llm_noncot=None, chroma_dir="",
            )
            assert len(candidates_no_sem) == len(candidates_with_empty)
            assert {n.node_id for n in candidates_no_sem} == {n.node_id for n in candidates_with_empty}

            conn.close()


class TestSegmentNarrative:
    """Tests for Q4 segment_narrative with message preview injection."""

    def test_messages_preview_injected_and_evidence_from_preview(self):
        """segment_narrative injects messages_preview; evidence IDs come from visible messages."""
        import sqlite3
        from narrative_mirror.db import init_db, upsert_messages, upsert_node
        from narrative_mirror.models import RawMessage, TopicNode

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            # Messages 1-10 for node
            msgs = [
                RawMessage(
                    local_id=i, talker_id="test", create_time=i * 1000,
                    is_send=(i % 2 == 0), sender_username="u",
                    parsed_content=f"content {i}", local_type=1,
                )
                for i in range(1, 11)
            ]
            upsert_messages(conn, msgs)

            node = TopicNode(
                node_id="n1", talker_id="test", burst_id="b1",
                topic_name="测试话题", start_local_id=1, end_local_id=10,
                start_time=1000, end_time=10000,
            )
            upsert_node(conn, node)

            llm = StubCoTLLM()
            phases = segment_narrative(
                candidates=[node],
                question="测试问题",
                talker_id="test",
                llm=llm,
                conn=conn,
            )

            assert len(phases) >= 1
            # StubCoTLLM returns evidence_msg_ids [1, 2, 3] - must be in messages_preview range
            for p in phases:
                for eid in p.evidence_msg_ids:
                    assert 1 <= eid <= 10, f"evidence {eid} should be in node range 1-10"

            conn.close()


class TestVerifyEvidence:
    """Tests for evidence verification."""

    def test_valid_evidence(self):
        """Valid evidence should be marked as verified."""
        import sqlite3
        from narrative_mirror.db import init_db, upsert_messages
        from narrative_mirror.models import RawMessage

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            # Add messages
            messages = [
                RawMessage(1, "test", 1000, True, "user", "msg1", 1, False),
                RawMessage(2, "test", 2000, False, "ta", "msg2", 1, False),
            ]
            upsert_messages(conn, messages)

            phase = NarrativePhase(
                phase_title="Test Phase",
                time_range="2023-01",
                core_conclusion="Test conclusion",
                evidence_msg_ids=[1, 2],
                reasoning_chain="Test reasoning",
                uncertainty_note="None",
                verified=False,
            )

            llm = StubCoTLLM()
            verified = verify_evidence([phase], "test", conn, llm)

            assert len(verified) == 1
            assert verified[0].verified is True

            conn.close()

    def test_missing_evidence(self):
        """Missing evidence should not be verified."""
        import sqlite3
        from narrative_mirror.db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            phase = NarrativePhase(
                phase_title="Test Phase",
                time_range="2023-01",
                core_conclusion="Test conclusion",
                evidence_msg_ids=[999],  # Non-existent
                reasoning_chain="Test reasoning",
                uncertainty_note="None",
                verified=False,
            )

            llm = StubCoTLLM()
            verified = verify_evidence([phase], "test", conn, llm)

            assert len(verified) == 1
            assert verified[0].verified is False

            conn.close()


class TestFormatCards:
    """Tests for output formatting."""

    def test_empty_phases(self):
        """Empty phases should return helpful message."""
        import sqlite3
        from narrative_mirror.db import init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            output = format_cards([], "test", conn)
            assert "无法生成" in output

            conn.close()

    def test_formats_single_phase(self):
        """Single phase should be formatted correctly."""
        import sqlite3
        from narrative_mirror.db import init_db, upsert_messages
        from narrative_mirror.models import RawMessage

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = init_db(db_path)

            # Add messages
            messages = [
                RawMessage(1, "test", 1000, True, "user", "Hello world", 1, False),
            ]
            upsert_messages(conn, messages)

            phase = NarrativePhase(
                phase_title="测试阶段",
                time_range="2023-01",
                core_conclusion="这是测试结论",
                evidence_msg_ids=[1],
                reasoning_chain="这是推理过程",
                uncertainty_note="样本较小",
                verified=True,
            )

            output = format_cards([phase], "test", conn)

            assert "测试阶段" in output
            assert "2023-01" in output
            assert "这是测试结论" in output
            assert "Hello world" in output
            assert "已验证" in output

            conn.close()
