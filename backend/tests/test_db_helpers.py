"""Tests for db helper functions."""
import sqlite3
import pytest
from narrative_mirror.db import (
    init_db,
    upsert_messages,
    upsert_node,
    upsert_metadata,
    get_messages_for_node,
    get_talkers_with_stats,
    get_build_status,
)
from narrative_mirror.models import RawMessage, TopicNode, MetadataSignals


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return init_db(":memory:")


@pytest.fixture
def db_with_messages():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from narrative_mirror.db import init_db
    conn = init_db(":memory:")

    talker_id = "test_talker"
    messages = [
        RawMessage(local_id=i, talker_id=talker_id, create_time=i * 1000,
                   is_send=(i % 2 == 0), sender_username="user",
                   parsed_content=f"Message {i}", local_type=1)
        for i in range(1, 11)  # local_ids 1-10
    ]
    upsert_messages(conn, messages)

    node = TopicNode(
        node_id="node_a", talker_id=talker_id, burst_id="burst_1",
        topic_name="Test Topic", start_local_id=3, end_local_id=7,
        start_time=3000, end_time=7000,
    )
    upsert_node(conn, node)

    return conn, talker_id, node


def test_get_messages_for_node_normal(db_with_messages):
    conn, talker_id, node = db_with_messages
    msgs = get_messages_for_node(conn, talker_id, node)
    assert len(msgs) == 5  # local_ids 3, 4, 5, 6, 7
    assert [m.local_id for m in msgs] == [3, 4, 5, 6, 7]


def test_get_messages_for_node_empty(db_with_messages):
    conn, talker_id, _ = db_with_messages
    empty_node = TopicNode(
        node_id="node_b", talker_id=talker_id, burst_id="burst_2",
        topic_name="Empty", start_local_id=100, end_local_id=200,
        start_time=100000, end_time=200000,
    )
    msgs = get_messages_for_node(conn, talker_id, empty_node)
    assert msgs == []


def test_get_messages_for_node_boundary_ids(db_with_messages):
    conn, talker_id, _ = db_with_messages
    boundary_node = TopicNode(
        node_id="node_c", talker_id=talker_id, burst_id="burst_3",
        topic_name="Boundary", start_local_id=1, end_local_id=1,
        start_time=1000, end_time=1000,
    )
    msgs = get_messages_for_node(conn, talker_id, boundary_node)
    assert len(msgs) == 1
    assert msgs[0].local_id == 1


def test_get_messages_for_node_content(db_with_messages):
    conn, talker_id, node = db_with_messages
    msgs = get_messages_for_node(conn, talker_id, node)
    contents = [m.parsed_content for m in msgs]
    assert "Message 3" in contents
    assert "Message 7" in contents
    # Messages outside range not included
    assert "Message 1" not in contents
    assert "Message 10" not in contents


# ---------------------------------------------------------------------------
# get_talkers_with_stats
# ---------------------------------------------------------------------------


def test_get_talkers_with_stats_multiple_talkers():
    conn = init_db(":memory:")
    upsert_messages(conn, [
        RawMessage(1, "t1", 1000, True, "u1", "a", 1),
        RawMessage(2, "t1", 2000, False, "partner1", "b", 1),
        RawMessage(3, "t2", 3000, False, "partner2", "c", 1),
        RawMessage(4, "t2", 4000, True, "u2", "d", 1),
    ])
    stats = get_talkers_with_stats(conn)
    assert len(stats) == 2
    t1 = next(s for s in stats if s["talker_id"] == "t1")
    t2 = next(s for s in stats if s["talker_id"] == "t2")
    assert t1["message_count"] == 2
    assert t1["last_timestamp"] == 2000
    assert t1["display_name"] == "partner1"
    assert t2["message_count"] == 2
    assert t2["last_timestamp"] == 4000
    assert t2["display_name"] == "partner2"


def test_get_talkers_with_stats_display_name_fallback():
    """When all messages are is_send=1, display_name falls back to talker_id."""
    conn = init_db(":memory:")
    upsert_messages(conn, [
        RawMessage(1, "self_only", 1000, True, "me", "hi", 1),
        RawMessage(2, "self_only", 2000, True, "me", "bye", 1),
    ])
    stats = get_talkers_with_stats(conn)
    assert len(stats) == 1
    assert stats[0]["display_name"] == "self_only"


def test_get_talkers_with_stats_empty():
    conn = init_db(":memory:")
    stats = get_talkers_with_stats(conn)
    assert stats == []


# ---------------------------------------------------------------------------
# get_build_status
# ---------------------------------------------------------------------------


def test_get_build_status_pending_no_nodes():
    conn = init_db(":memory:")
    upsert_messages(conn, [
        RawMessage(1, "t1", 1000, True, "u", "a", 1),
    ])
    assert get_build_status(conn, "t1") == "pending"


def test_get_build_status_pending_no_data():
    conn = init_db(":memory:")
    assert get_build_status(conn, "nonexistent") == "pending"


def test_get_build_status_in_progress():
    conn = init_db(":memory:")
    upsert_messages(conn, [
        RawMessage(1, "t1", 1000, True, "u", "a", 1),
    ])
    node = TopicNode(
        node_id="n1", talker_id="t1", burst_id="b1",
        topic_name="T", start_local_id=1, end_local_id=1,
        start_time=1000, end_time=1000,
    )
    upsert_node(conn, node)
    assert get_build_status(conn, "t1") == "in_progress"


def test_get_build_status_complete():
    conn = init_db(":memory:")
    upsert_messages(conn, [
        RawMessage(1, "t1", 1000, True, "u", "a", 1),
    ])
    node = TopicNode(
        node_id="n1", talker_id="t1", burst_id="b1",
        topic_name="T", start_local_id=1, end_local_id=1,
        start_time=1000, end_time=1000,
    )
    upsert_node(conn, node)
    meta = MetadataSignals(
        node_id="n1", talker_id="t1",
        reply_delay_avg_s=0.0, reply_delay_max_s=0.0,
        term_shift_score=0.0, silence_event=False,
        topic_frequency=0, initiator_ratio=0.0,
        emotional_tone=0.0, conflict_intensity=0.0,
    )
    upsert_metadata(conn, meta)
    assert get_build_status(conn, "t1") == "complete"
