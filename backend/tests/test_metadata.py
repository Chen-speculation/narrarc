"""Unit tests for Layer 1.5 Metadata module."""

import pytest
import tempfile
from datetime import datetime

from narrative_mirror.models import RawMessage, TopicNode, MetadataSignals
from narrative_mirror.metadata import (
    compute_reply_delay,
    compute_term_shift,
    compute_silence_event,
    compute_topic_frequency,
    compute_initiator_ratio,
    detect_anomalies,
    compute_all_metadata,
)


def make_message(
    local_id: int,
    talker_id: str,
    minutes: int,
    is_send: bool,
    content: str,
) -> RawMessage:
    """Helper to create a test message."""
    base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
    return RawMessage(
        local_id=local_id,
        talker_id=talker_id,
        create_time=base_ts + minutes * 60 * 1000,
        is_send=is_send,
        sender_username="user" if is_send else "ta",
        parsed_content=content,
        local_type=1,
        excluded=False,
    )


class TestComputeReplyDelay:
    """Tests for reply delay computation."""

    def test_alternating_exchange(self):
        """Reply delay should be computed for alternating sender exchanges."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),    # User at 0 min
            make_message(2, "test", 3, False, "msg2"),   # TA at 3 min (180s delay)
            make_message(3, "test", 5, True, "msg3"),    # User at 5 min (120s delay)
        ]
        avg, max_delay = compute_reply_delay(messages)
        # Average of 180s and 120s = 150s
        assert avg == pytest.approx(150.0, rel=0.01)
        assert max_delay == pytest.approx(180.0, rel=0.01)

    def test_no_alternation(self):
        """No alternation should return 0.0, 0.0."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 5, True, "msg2"),
            make_message(3, "test", 10, True, "msg3"),
        ]
        avg, max_delay = compute_reply_delay(messages)
        assert avg == 0.0
        assert max_delay == 0.0

    def test_empty_messages(self):
        """Empty message list should return 0.0, 0.0."""
        avg, max_delay = compute_reply_delay([])
        assert avg == 0.0
        assert max_delay == 0.0

    def test_single_message(self):
        """Single message should return 0.0, 0.0."""
        messages = [make_message(1, "test", 0, True, "msg1")]
        avg, max_delay = compute_reply_delay(messages)
        assert avg == 0.0
        assert max_delay == 0.0


class TestComputeTermShift:
    """Tests for term shift computation."""

    def test_all_baseline_terms(self):
        """All TA messages with baseline terms should return 0.0."""
        messages = [
            make_message(1, "test", 0, True, "hi"),
            make_message(2, "test", 1, False, "宝贝你好"),
            make_message(3, "test", 2, True, "hello"),
            make_message(4, "test", 3, False, "宝宝晚安"),
        ]
        baseline = {"宝贝", "宝宝"}
        score = compute_term_shift(messages, baseline)
        assert score == 0.0

    def test_no_baseline_terms(self):
        """No TA messages with baseline terms should return 1.0."""
        messages = [
            make_message(1, "test", 0, True, "hi"),
            make_message(2, "test", 1, False, "哦"),
            make_message(3, "test", 2, True, "hello"),
            make_message(4, "test", 3, False, "嗯"),
        ]
        baseline = {"宝贝", "宝宝"}
        score = compute_term_shift(messages, baseline)
        assert score == 1.0

    def test_mixed_terms(self):
        """Mixed baseline and non-baseline should return appropriate fraction."""
        messages = [
            make_message(1, "test", 0, True, "hi"),
            make_message(2, "test", 1, False, "宝贝你好"),  # baseline
            make_message(3, "test", 2, True, "hello"),
            make_message(4, "test", 3, False, "哦"),        # non-baseline
        ]
        baseline = {"宝贝", "宝宝"}
        score = compute_term_shift(messages, baseline)
        # 1 non-baseline out of 2 TA messages
        assert score == pytest.approx(0.5, rel=0.01)

    def test_no_ta_messages(self):
        """No TA messages should return 0.0."""
        messages = [
            make_message(1, "test", 0, True, "hi"),
            make_message(2, "test", 1, True, "hello"),
        ]
        baseline = {"宝贝", "宝宝"}
        score = compute_term_shift(messages, baseline)
        assert score == 0.0


class TestComputeSilenceEvent:
    """Tests for silence event detection."""

    def test_silence_event_detected(self):
        """Gap > 3x median should be detected as silence event."""
        # Create nodes with many small gaps and one large gap
        # Small gaps: 10 min each, then one large gap
        # Median should be around 10 min, threshold = 30 min
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        nodes = [
            TopicNode(
                node_id="n1",
                talker_id="test",
                burst_id="b1",
                topic_name="topic1",
                start_local_id=1,
                end_local_id=2,
                start_time=base_ts,
                end_time=base_ts + 10 * 60 * 1000,  # ends at 10 min
            ),
            TopicNode(
                node_id="n2",
                talker_id="test",
                burst_id="b2",
                topic_name="topic2",
                start_local_id=3,
                end_local_id=4,
                start_time=base_ts + 20 * 60 * 1000,  # starts at 20 min (10 min gap)
                end_time=base_ts + 30 * 60 * 1000,    # ends at 30 min
            ),
            TopicNode(
                node_id="n3",
                talker_id="test",
                burst_id="b3",
                topic_name="topic3",
                start_local_id=5,
                end_local_id=6,
                start_time=base_ts + 40 * 60 * 1000,  # starts at 40 min (10 min gap)
                end_time=base_ts + 50 * 60 * 1000,    # ends at 50 min
            ),
            TopicNode(
                node_id="n4",
                talker_id="test",
                burst_id="b4",
                topic_name="topic4",
                start_local_id=7,
                end_local_id=8,
                start_time=base_ts + 100 * 60 * 1000,  # starts at 100 min (50 min gap > 3x 10)
                end_time=base_ts + 110 * 60 * 1000,
            ),
        ]

        # Gaps: 10, 10, 50 min -> median = 10 min, threshold = 30 min
        # n3 should have silence event (gap after is 50 min, threshold is 30 min)
        result = compute_silence_event(nodes[2], nodes)
        assert result is True

    def test_no_silence_event(self):
        """Normal gap should not trigger silence event."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        nodes = [
            TopicNode(
                node_id="n1",
                talker_id="test",
                burst_id="b1",
                topic_name="topic1",
                start_local_id=1,
                end_local_id=2,
                start_time=base_ts,
                end_time=base_ts + 10 * 60 * 1000,
            ),
            TopicNode(
                node_id="n2",
                talker_id="test",
                burst_id="b2",
                topic_name="topic2",
                start_local_id=3,
                end_local_id=4,
                start_time=base_ts + 15 * 60 * 1000,  # 5 min gap
                end_time=base_ts + 25 * 60 * 1000,
            ),
        ]

        # n1 should not have silence event (gap is 5 min, median would be similar)
        result = compute_silence_event(nodes[0], nodes)
        assert result is False

    def test_single_node(self):
        """Single node should not have silence event."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        nodes = [
            TopicNode(
                node_id="n1",
                talker_id="test",
                burst_id="b1",
                topic_name="topic1",
                start_local_id=1,
                end_local_id=2,
                start_time=base_ts,
                end_time=base_ts + 10 * 60 * 1000,
            ),
        ]
        result = compute_silence_event(nodes[0], nodes)
        assert result is False


class TestComputeTopicFrequency:
    """Tests for topic frequency computation."""

    def test_topic_frequency(self):
        """Should count prior nodes with same topic."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        nodes = [
            TopicNode(
                node_id="n1",
                talker_id="test",
                burst_id="b1",
                topic_name="工作压力",
                start_local_id=1,
                end_local_id=2,
                start_time=base_ts,
                end_time=base_ts + 10 * 60 * 1000,
            ),
            TopicNode(
                node_id="n2",
                talker_id="test",
                burst_id="b2",
                topic_name="日常生活",
                start_local_id=3,
                end_local_id=4,
                start_time=base_ts + 20 * 60 * 1000,
                end_time=base_ts + 30 * 60 * 1000,
            ),
            TopicNode(
                node_id="n3",
                talker_id="test",
                burst_id="b3",
                topic_name="工作压力",  # Same as n1
                start_local_id=5,
                end_local_id=6,
                start_time=base_ts + 60 * 60 * 1000,
                end_time=base_ts + 70 * 60 * 1000,
            ),
        ]

        # n3 should have frequency 1 (n1 is prior with same topic)
        freq = compute_topic_frequency(nodes[2], nodes)
        assert freq == 1

    def test_case_insensitive(self):
        """Topic comparison should be case-insensitive."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        nodes = [
            TopicNode(
                node_id="n1",
                talker_id="test",
                burst_id="b1",
                topic_name="工作压力",
                start_local_id=1,
                end_local_id=2,
                start_time=base_ts,
                end_time=base_ts + 10 * 60 * 1000,
            ),
            TopicNode(
                node_id="n2",
                talker_id="test",
                burst_id="b2",
                topic_name="工作压力",  # Same topic
                start_local_id=3,
                end_local_id=4,
                start_time=base_ts + 60 * 60 * 1000,
                end_time=base_ts + 70 * 60 * 1000,
            ),
        ]

        freq = compute_topic_frequency(nodes[1], nodes)
        assert freq == 1


class TestComputeInitiatorRatio:
    """Tests for initiator ratio computation."""

    def test_user_initiated(self):
        """User initiating all alternating pairs should return 1.0."""
        # Pairs: (msg1, msg2) - user starts, (msg3, msg4) - user starts
        messages = [
            make_message(1, "test", 0, True, "msg1"),   # User starts pair 1
            make_message(2, "test", 1, False, "msg2"),  # TA responds
            make_message(3, "test", 5, True, "msg3"),   # User starts pair 2
            make_message(4, "test", 6, False, "msg4"),  # TA responds
        ]
        ratio = compute_initiator_ratio(messages)
        assert ratio == 1.0

    def test_ta_initiated(self):
        """TA initiating all alternating pairs should return 0.0."""
        # Pairs: (msg1, msg2) - TA starts, (msg3, msg4) - TA starts
        messages = [
            make_message(1, "test", 0, False, "msg1"),  # TA starts pair 1
            make_message(2, "test", 1, True, "msg2"),   # User responds
            make_message(3, "test", 5, False, "msg3"),  # TA starts pair 2
            make_message(4, "test", 6, True, "msg4"),   # User responds
        ]
        ratio = compute_initiator_ratio(messages)
        assert ratio == 0.0

    def test_mixed_initiators(self):
        """Mixed initiators should return appropriate ratio."""
        # Pairs: (msg1, msg2) - user starts, (msg3, msg4) - TA starts
        messages = [
            make_message(1, "test", 0, True, "msg1"),   # User starts pair 1
            make_message(2, "test", 1, False, "msg2"),  # TA responds
            make_message(3, "test", 5, False, "msg3"),  # TA (but this creates a pair: msg3, msg4)
            make_message(4, "test", 6, True, "msg4"),   # User responds
        ]
        ratio = compute_initiator_ratio(messages)
        # Pair 1: user starts, Pair 2: TA starts
        # So 1 out of 2 pairs started by user
        assert ratio == pytest.approx(0.5, rel=0.01)

    def test_empty_messages(self):
        """Empty messages should return 0.0."""
        ratio = compute_initiator_ratio([])
        assert ratio == 0.0


class TestDetectAnomalies:
    """Tests for anomaly detection."""

    def test_reply_delay_anomaly(self):
        """High reply delay should be detected as anomaly when there are enough data points."""
        # With many clustered values and one outlier,
        # the outlier detection should work
        # Values clustered around 100-120, with one at 10000
        signals = [
            MetadataSignals(node_id="n1", talker_id="test", reply_delay_avg_s=100.0),
            MetadataSignals(node_id="n2", talker_id="test", reply_delay_avg_s=105.0),
            MetadataSignals(node_id="n3", talker_id="test", reply_delay_avg_s=110.0),
            MetadataSignals(node_id="n4", talker_id="test", reply_delay_avg_s=115.0),
            MetadataSignals(node_id="n5", talker_id="test", reply_delay_avg_s=120.0),
            MetadataSignals(node_id="n6", talker_id="test", reply_delay_avg_s=10000.0),  # outlier
        ]

        anchors = detect_anomalies(signals, "test")

        # n6 should be flagged for reply_delay
        reply_anchors = [a for a in anchors if a.signal_name == "reply_delay"]
        assert len(reply_anchors) >= 1
        assert any(a.node_id == "n6" for a in reply_anchors)

    def test_insufficient_data(self):
        """Less than 2 nodes should return no anomalies."""
        signals = [
            MetadataSignals(node_id="n1", talker_id="test", reply_delay_avg_s=100.0),
        ]
        anchors = detect_anomalies(signals, "test")
        assert len(anchors) == 0

    def test_no_anomalies(self):
        """Normal values should not trigger anomalies."""
        signals = [
            MetadataSignals(node_id="n1", talker_id="test", reply_delay_avg_s=100.0),
            MetadataSignals(node_id="n2", talker_id="test", reply_delay_avg_s=110.0),
            MetadataSignals(node_id="n3", talker_id="test", reply_delay_avg_s=105.0),
        ]
        anchors = detect_anomalies(signals, "test")

        # All values are close to mean, no anomalies expected
        reply_anchors = [a for a in anchors if a.signal_name == "reply_delay"]
        assert len(reply_anchors) == 0

    def test_silence_event_flagged(self):
        """Silence events should always be flagged."""
        signals = [
            MetadataSignals(node_id="n1", talker_id="test", silence_event=False),
            MetadataSignals(node_id="n2", talker_id="test", silence_event=True),
            MetadataSignals(node_id="n3", talker_id="test", silence_event=False),
        ]
        anchors = detect_anomalies(signals, "test")

        silence_anchors = [a for a in anchors if a.signal_name == "silence_event"]
        assert len(silence_anchors) == 1
        assert silence_anchors[0].node_id == "n2"


class TestComputeAllMetadataSkipIfExists:
    """Tests for compute_all_metadata skip-if-exists behavior."""

    def test_skips_nodes_with_existing_metadata(self):
        """When metadata already exists for all nodes, no LLM calls are made."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        talker_id = "skip_test"

        messages = [
            make_message(1, talker_id, 0, True, "hi"),
            make_message(2, talker_id, 1, False, "hello"),
            make_message(3, talker_id, 2, True, "how are you"),
            make_message(4, talker_id, 3, False, "fine"),
        ]

        nodes = [
            TopicNode(
                node_id="n1",
                talker_id=talker_id,
                burst_id="b1",
                topic_name="问候",
                start_local_id=1,
                end_local_id=2,
                start_time=base_ts,
                end_time=base_ts + 60 * 60 * 1000,
            ),
            TopicNode(
                node_id="n2",
                talker_id=talker_id,
                burst_id="b1",
                topic_name="寒暄",
                start_local_id=3,
                end_local_id=4,
                start_time=base_ts + 2 * 60 * 60 * 1000,
                end_time=base_ts + 3 * 60 * 60 * 1000,
            ),
        ]

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            from narrative_mirror.db import init_db, upsert_messages, upsert_node, upsert_metadata

            conn = init_db(db_path)
            upsert_messages(conn, messages)
            for node in nodes:
                upsert_node(conn, node)

            # Pre-insert metadata for all nodes
            for node in nodes:
                signals = MetadataSignals(
                    node_id=node.node_id,
                    talker_id=talker_id,
                    reply_delay_avg_s=10.0,
                    reply_delay_max_s=30.0,
                    term_shift_score=0.0,
                    silence_event=False,
                    topic_frequency=0,
                    initiator_ratio=0.5,
                    emotional_tone=0.2,
                    conflict_intensity=0.1,
                )
                upsert_metadata(conn, signals)

            from narrative_mirror.llm import StubNonCoTLLM

            stub_llm = StubNonCoTLLM()
            signals = compute_all_metadata(talker_id, stub_llm, conn)

            # All nodes should be in result (from existing metadata)
            assert len(signals) == 2
            assert {s.node_id for s in signals} == {"n1", "n2"}
            # No LLM calls because all nodes were skipped
            assert stub_llm._call_count == 0
        finally:
            import os

            os.unlink(db_path)

    def test_force_recompute_ignores_existing(self):
        """When force_recompute=True, recomputes even when metadata exists."""
        base_ts = int(datetime(2023, 1, 1, 12, 0).timestamp() * 1000)
        talker_id = "force_test"

        messages = [
            make_message(1, talker_id, 0, True, "hi"),
            make_message(2, talker_id, 1, False, "hello"),
        ]

        node = TopicNode(
            node_id="n1",
            talker_id=talker_id,
            burst_id="b1",
            topic_name="问候",
            start_local_id=1,
            end_local_id=2,
            start_time=base_ts,
            end_time=base_ts + 60 * 60 * 1000,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            from narrative_mirror.db import init_db, upsert_messages, upsert_node, upsert_metadata

            conn = init_db(db_path)
            upsert_messages(conn, messages)
            upsert_node(conn, node)
            upsert_metadata(
                conn,
                MetadataSignals(
                    node_id="n1",
                    talker_id=talker_id,
                    reply_delay_avg_s=99.0,  # Distinct value to detect recompute
                ),
            )

            from narrative_mirror.llm import StubNonCoTLLM

            stub_llm = StubNonCoTLLM()
            signals = compute_all_metadata(
                talker_id, stub_llm, conn, force_recompute=True
            )

            assert len(signals) == 1
            # LLM was called (recomputed)
            assert stub_llm._call_count > 0
        finally:
            import os

            os.unlink(db_path)
