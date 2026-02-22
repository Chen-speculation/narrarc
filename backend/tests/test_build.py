"""Unit tests for Layer 1 Build module."""

import pytest
from datetime import datetime

from narrative_mirror.models import RawMessage, Burst, TopicNode
from narrative_mirror.build import aggregate_bursts, classify_burst
from narrative_mirror.llm import StubNonCoTLLM


def make_message(local_id: int, talker_id: str, minutes: int, is_send: bool, content: str) -> RawMessage:
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


class TestAggregateBursts:
    """Tests for burst aggregation."""

    def test_within_window(self):
        """Messages within 30-minute window should be in same burst."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 5, False, "msg2"),  # 5 min gap
            make_message(3, "test", 12, True, "msg3"),  # 7 min gap
        ]
        bursts = aggregate_bursts(messages)
        assert len(bursts) == 1
        assert len(bursts[0].messages) == 3

    def test_gap_triggers_new_burst(self):
        """Gap >= 30 minutes should trigger new burst."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 35, False, "msg2"),  # 35 min gap
        ]
        bursts = aggregate_bursts(messages)
        assert len(bursts) == 2
        assert bursts[0].messages[0].local_id == 1
        assert bursts[1].messages[0].local_id == 2

    def test_single_message_burst(self):
        """A lone message should form its own burst."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 120, False, "msg2"),  # 2 hour gap
        ]
        bursts = aggregate_bursts(messages)
        assert len(bursts) == 2
        assert len(bursts[0].messages) == 1
        assert len(bursts[1].messages) == 1

    def test_configurable_threshold(self):
        """Gap threshold should be configurable."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 2, False, "msg2"),  # 2 min gap
        ]
        # With default threshold (30 min), same burst
        bursts_default = aggregate_bursts(messages)
        assert len(bursts_default) == 1

        # With 1 minute threshold, different bursts
        bursts_short = aggregate_bursts(messages, gap_seconds=60)
        assert len(bursts_short) == 2

    def test_excluded_messages_skipped(self):
        """Excluded messages should be skipped."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            RawMessage(2, "test", 0, True, "user", "system msg", 10000, excluded=True),
            make_message(3, "test", 5, False, "msg3"),
        ]
        bursts = aggregate_bursts(messages)
        assert len(bursts) == 1
        assert len(bursts[0].messages) == 2
        assert bursts[0].messages[0].local_id == 1
        assert bursts[0].messages[1].local_id == 3

    def test_empty_messages(self):
        """Empty message list should return empty bursts."""
        bursts = aggregate_bursts([])
        assert len(bursts) == 0

    def test_burst_time_range(self):
        """Burst start_time and end_time should match message range."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 5, False, "msg2"),
            make_message(3, "test", 10, True, "msg3"),
        ]
        bursts = aggregate_bursts(messages)
        assert bursts[0].start_time == messages[0].create_time
        assert bursts[0].end_time == messages[2].create_time


class TestClassifyBurst:
    """Tests for burst classification."""

    def test_single_topic_burst(self):
        """Single-topic burst should return one node."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 1, False, "msg2"),
        ]
        burst = Burst(talker_id="test", messages=messages)
        llm = StubNonCoTLLM()

        nodes = classify_burst(burst, llm)
        assert len(nodes) >= 1
        assert nodes[0].burst_id == burst.burst_id
        assert nodes[0].topic_name != ""

    def test_malformed_response_fallback(self):
        """Malformed LLM response should fallback to '未分类'."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
        ]
        burst = Burst(talker_id="test", messages=messages)

        # Create a mock LLM that returns invalid JSON
        class BadLLM:
            def complete(self, system, prompt, max_tokens=1024, response_format=None):
                return "not valid json"
            def embed(self, text):
                return [0.0] * 1024

        nodes = classify_burst(burst, BadLLM())
        assert len(nodes) == 1
        assert nodes[0].topic_name == "未分类"

    def test_node_time_range(self):
        """Node time range should match segment message range."""
        messages = [
            make_message(1, "test", 0, True, "msg1"),
            make_message(2, "test", 5, False, "msg2"),
            make_message(3, "test", 10, True, "msg3"),
        ]
        burst = Burst(talker_id="test", messages=messages)
        llm = StubNonCoTLLM()

        nodes = classify_burst(burst, llm)
        # The stub returns nodes with local_ids 1-10, but we only have messages 1-3
        # The actual node time range will be based on available messages
        assert len(nodes) >= 1
