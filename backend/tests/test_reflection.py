"""Unit tests for evidence reflection module."""

import sqlite3
import tempfile
import os
from datetime import datetime

import pytest

from narrative_mirror.db import init_db, upsert_messages, upsert_node
from narrative_mirror.models import RawMessage, TopicNode, NarrativePhase
from narrative_mirror.reflection import reflect_on_evidence
from narrative_mirror.llm import StubCoTLLM


TALKER = "test_reflection"


@pytest.fixture
def conn_with_messages():
    """DB with messages 1-10 and a node covering them."""
    conn = init_db(":memory:")
    msgs = [
        RawMessage(
            local_id=i, talker_id=TALKER, create_time=i * 100_000,
            is_send=(i % 2 == 0), sender_username="u",
            parsed_content=f"msg {i} content", local_type=1,
        )
        for i in range(1, 11)
    ]
    upsert_messages(conn, msgs)
    node = TopicNode(
        node_id="n1", talker_id=TALKER, burst_id="b1",
        topic_name="测试", start_local_id=1, end_local_id=10,
        start_time=100_000, end_time=1_000_000,
    )
    upsert_node(conn, node)
    return conn


def test_reflect_all_pass(conn_with_messages):
    """All evidence valid and relevant - phases marked verified."""
    conn = conn_with_messages
    phases = [
        NarrativePhase(
            phase_title="阶段1",
            time_range="2023-01",
            core_conclusion="测试结论",
            evidence_msg_ids=[1, 2, 3],
            reasoning_chain="推理",
            uncertainty_note="无",
            verified=False,
        ),
    ]
    llm = StubCoTLLM()
    result = reflect_on_evidence(phases, "问题", llm, conn, TALKER)
    assert len(result) == 1
    assert result[0].verified is True
    assert result[0].evidence_msg_ids == [1, 2, 3]
    conn.close()


def test_reflect_invalid_id_tries_reselection(conn_with_messages):
    """Invalid evidence IDs trigger re-selection; if successful, phase verified."""
    conn = conn_with_messages
    phases = [
        NarrativePhase(
            phase_title="阶段1",
            time_range="2023-01",
            core_conclusion="测试结论",
            evidence_msg_ids=[999],  # Non-existent
            reasoning_chain="推理",
            uncertainty_note="无",
            verified=False,
        ),
    ]
    llm = StubCoTLLM()
    result = reflect_on_evidence(phases, "问题", llm, conn, TALKER)
    assert len(result) == 1
    # StubCoTLLM reselection returns [1, 2, 3] - all exist
    assert result[0].verified is True
    assert result[0].evidence_msg_ids == [1, 2, 3]
    conn.close()


def test_reflect_invalid_id_reselection_fails(conn_with_messages):
    """Invalid IDs + reselection returns no valid IDs -> verified=False."""
    # Use empty DB so reselection has no messages to pick from
    conn = init_db(":memory:")
    phases = [
        NarrativePhase(
            phase_title="阶段1",
            time_range="2023-01",
            core_conclusion="测试结论",
            evidence_msg_ids=[999],
            reasoning_chain="推理",
            uncertainty_note="无",
            verified=False,
        ),
    ]
    llm = StubCoTLLM()
    result = reflect_on_evidence(phases, "问题", llm, conn, "empty_talker")
    assert len(result) == 1
    assert result[0].verified is False
    conn.close()


def test_reflect_semantic_mismatch_tries_reselection(conn_with_messages):
    """Semantic relevance fail triggers re-selection; StubCoTLLM returns relevant=True by default."""
    # StubCoTLLM returns relevant=True for relevance check, so we need a stub that returns False
    # For this test we verify the flow: valid IDs -> relevance check. With StubCoTLLM returning
    # relevant=True, we never hit the reselection path from relevance. So test_reflect_all_pass
    # covers that. For "semantic mismatch" we need a custom LLM that returns relevant=False.
    # Create a simple stub that returns false for relevance
    class RelevanceFalseStub:
        def think_and_complete(self, system, prompt, max_tokens=256, response_format=None):
            if "证据相关性" in system or "relevant" in system.lower():
                return '{"relevant": false, "reason": "不相关"}'
            if "证据选择" in system or "selected_ids" in system.lower():
                return '{"selected_ids": [1, 2, 3]}'
            return '{"result": "ok"}'

    conn = conn_with_messages
    phases = [
        NarrativePhase(
            phase_title="阶段1",
            time_range="2023-01",
            core_conclusion="测试结论",
            evidence_msg_ids=[1, 2, 3],
            reasoning_chain="推理",
            uncertainty_note="无",
            verified=False,
        ),
    ]
    llm = RelevanceFalseStub()
    result = reflect_on_evidence(phases, "问题", llm, conn, TALKER)
    assert len(result) == 1
    assert result[0].verified is True
    assert result[0].evidence_msg_ids == [1, 2, 3]
    conn.close()


def test_reflect_reselection_success(conn_with_messages):
    """Re-selection returns valid IDs -> phase updated and verified."""
    conn = conn_with_messages
    phases = [
        NarrativePhase(
            phase_title="阶段1",
            time_range="2023-01",
            core_conclusion="测试结论",
            evidence_msg_ids=[999],
            reasoning_chain="推理",
            uncertainty_note="无",
            verified=False,
        ),
    ]
    llm = StubCoTLLM()
    result = reflect_on_evidence(phases, "问题", llm, conn, TALKER)
    assert len(result) == 1
    assert result[0].verified is True
    assert set(result[0].evidence_msg_ids) <= {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    conn.close()
