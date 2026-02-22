"""Unit tests for the narrative tools layer."""
import sqlite3
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from narrative_mirror.db import init_db, upsert_messages, upsert_node, upsert_anchors, upsert_pointer
from narrative_mirror.models import RawMessage, TopicNode, AnomalyAnchor
from narrative_mirror.tools import (
    ToolResult,
    get_all_tools,
    LookupAnchorsTool,
    GetNodeMessagesTool,
    GetThreadNeighborsTool,
    ListNodesByTimeTool,
    GetNodeSummaryTool,
    GetAllNodesOverviewTool,
)


TALKER = "test_talker"


@pytest.fixture
def populated_db():
    conn = init_db(":memory:")

    # Insert messages local_id 1-20
    msgs = [
        RawMessage(
            local_id=i, talker_id=TALKER, create_time=i * 100_000,
            is_send=(i % 2 == 0), sender_username="u",
            parsed_content=f"msg content {i}", local_type=1,
        )
        for i in range(1, 21)
    ]
    upsert_messages(conn, msgs)

    # Insert 3 nodes
    node_a = TopicNode(
        node_id="node_a", talker_id=TALKER, burst_id="b1",
        topic_name="日常聊天", start_local_id=1, end_local_id=5,
        start_time=100_000, end_time=500_000,
    )
    node_b = TopicNode(
        node_id="node_b", talker_id=TALKER, burst_id="b2",
        topic_name="工作讨论", start_local_id=6, end_local_id=12,
        start_time=600_000, end_time=1_200_000,
    )
    node_c = TopicNode(
        node_id="node_c", talker_id=TALKER, burst_id="b3",
        topic_name="感情问题", start_local_id=13, end_local_id=20,
        start_time=1_300_000, end_time=2_000_000,
    )
    for n in [node_a, node_b, node_c]:
        upsert_node(conn, n)

    # Insert anchor for node_b
    anchor = AnomalyAnchor(
        anchor_id="anc_1", talker_id=TALKER, node_id="node_b",
        signal_name="conflict_intensity", signal_value=0.9,
        baseline_mean=0.2, baseline_std=0.1,
        event_date="1970-01-01",
    )
    upsert_anchors(conn, [anchor])

    # Insert thread pointer node_a -> node_c
    upsert_pointer(conn, "node_a", "node_c", TALKER, "related topic", 0.85)

    return conn


def test_tool_factory_returns_7_tools():
    mock_llm = MagicMock()
    mock_llm.embed.return_value = [0.1] * 10
    conn = init_db(":memory:")
    tools = get_all_tools(conn, TALKER, "/tmp/chroma", mock_llm)
    assert len(tools) == 7
    names = {t.name for t in tools}
    expected = {
        "search_semantic", "lookup_anchors", "get_node_messages",
        "get_thread_neighbors", "list_nodes_by_time",
        "get_node_summary", "get_all_nodes_overview",
    }
    assert names == expected


def test_lookup_anchors_all(populated_db):
    tool = LookupAnchorsTool()
    result = tool.run(populated_db, TALKER)
    assert isinstance(result, ToolResult)
    assert "node_b" in result.content
    assert "conflict_intensity" in result.content
    assert "node_b" in result.data


def test_lookup_anchors_by_signal(populated_db):
    tool = LookupAnchorsTool()
    result = tool.run(populated_db, TALKER, signals=["conflict_intensity"])
    assert "node_b" in result.data

    result_miss = tool.run(populated_db, TALKER, signals=["emotional_tone"])
    assert result_miss.data == []
    assert "未找到" in result_miss.content


def test_get_node_messages_normal(populated_db):
    tool = GetNodeMessagesTool()
    result = tool.run(populated_db, TALKER, node_id="node_b")
    assert isinstance(result, ToolResult)
    # node_b covers local_ids 6-12 = 7 messages
    msgs = result.data
    assert len(msgs) == 7
    assert all(6 <= m.local_id <= 12 for m in msgs)


def test_get_node_messages_invalid_node(populated_db):
    tool = GetNodeMessagesTool()
    result = tool.run(populated_db, TALKER, node_id="nonexistent")
    assert result.data == []
    assert "未找到节点" in result.content


def test_get_node_messages_max_msgs(populated_db):
    tool = GetNodeMessagesTool()
    result = tool.run(populated_db, TALKER, node_id="node_c", max_msgs=4)
    # node_c has 8 messages (13-20), max_msgs=4 → first 2 + last 2
    assert len(result.data) == 4


def test_get_thread_neighbors_with_connection(populated_db):
    tool = GetThreadNeighborsTool()
    # node_a has a thread pointer to node_c
    result = tool.run(populated_db, TALKER, node_id="node_a")
    assert isinstance(result, ToolResult)
    assert "node_a" in result.data
    assert "node_c" in result.data


def test_get_thread_neighbors_isolated(populated_db):
    tool = GetThreadNeighborsTool()
    result = tool.run(populated_db, TALKER, node_id="node_b")
    # node_b has no thread connections
    assert "无语义线程" in result.content


def test_list_nodes_by_time(populated_db):
    tool = ListNodesByTimeTool()
    # node_a starts at 100_000 ms = 1970-01-01 UTC
    # Use a broad range that definitely includes it
    result = tool.run(populated_db, TALKER, start_date="1970-01-01", end_date="1970-01-02")
    assert isinstance(result, ToolResult)
    assert len(result.data) > 0


def test_list_nodes_by_time_empty(populated_db):
    tool = ListNodesByTimeTool()
    result = tool.run(populated_db, TALKER, start_date="2099-01-01", end_date="2099-12-31")
    assert result.data == []
    assert "未找到" in result.content


def test_get_node_summary(populated_db):
    tool = GetNodeSummaryTool()
    result = tool.run(populated_db, TALKER, node_id="node_a")
    assert isinstance(result, ToolResult)
    assert "日常聊天" in result.content
    assert "node_a" in result.content


def test_get_node_summary_invalid(populated_db):
    tool = GetNodeSummaryTool()
    result = tool.run(populated_db, TALKER, node_id="bad_id")
    assert result.data is None
    assert "未找到节点" in result.content


def test_get_all_nodes_overview(populated_db):
    tool = GetAllNodesOverviewTool()
    result = tool.run(populated_db, TALKER, limit=60)
    assert isinstance(result, ToolResult)
    assert len(result.data) == 3
    assert "node_b" in result.content
    assert "[ANCHOR]" in result.content  # node_b is an anchor


def test_get_all_nodes_overview_limit(populated_db):
    tool = GetAllNodesOverviewTool()
    result = tool.run(populated_db, TALKER, limit=2)
    assert len(result.data) == 2
