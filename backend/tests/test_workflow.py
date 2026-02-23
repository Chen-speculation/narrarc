"""Unit tests for the graph workflow module."""

import json
import sqlite3
import tempfile
import os
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from narrative_mirror.db import init_db, upsert_messages, upsert_node, upsert_anchors, upsert_pointer
from narrative_mirror.models import RawMessage, TopicNode, AnomalyAnchor
from narrative_mirror.llm import StubCoTLLM, StubNonCoTLLM
from narrative_mirror.tools import get_all_tools
from narrative_mirror.workflow import run_workflow, route_after_grading, route_after_planning


TALKER = "test_workflow"


@pytest.fixture
def populated_db():
    """Create in-memory DB with nodes, messages, anchors, and thread pointers."""
    conn = init_db(":memory:")

    # Messages local_id 1-20
    msgs = [
        RawMessage(
            local_id=i, talker_id=TALKER, create_time=i * 100_000,
            is_send=(i % 2 == 0), sender_username="u",
            parsed_content=f"msg content {i}", local_type=1,
        )
        for i in range(1, 21)
    ]
    upsert_messages(conn, msgs)

    # 3 nodes
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

    # Anchor for node_b
    anchor = AnomalyAnchor(
        anchor_id="anc_1", talker_id=TALKER, node_id="node_b",
        signal_name="conflict_intensity", signal_value=0.9,
        baseline_mean=0.2, baseline_std=0.1,
        event_date="1970-01-01",
    )
    upsert_anchors(conn, [anchor])

    # Thread pointer node_a -> node_c
    upsert_pointer(conn, "node_a", "node_c", TALKER, "related topic", 0.85)

    return conn


@pytest.fixture
def mock_llm_noncot():
    m = MagicMock()
    m.embed.return_value = [0.1] * 10
    return m


def test_run_workflow_planner_to_generator_straight_path(populated_db, mock_llm_noncot):
    """Test full workflow: Planner -> Retriever -> Grader -> Generator (sufficient path)."""
    conn = populated_db
    llm = StubCoTLLM()
    tools = get_all_tools(conn, TALKER, "/tmp/chroma_test", mock_llm_noncot)

    trace = run_workflow(
        question="我们是怎么一步步分手的？",
        talker_id=TALKER,
        llm=llm,
        conn=conn,
        tools=tools,
        llm_noncot=mock_llm_noncot,
        max_iterations=3,
        debug=False,
    )

    assert trace.question == "我们是怎么一步步分手的？"
    assert len(trace.steps) >= 4  # planner, retriever, grader, generator
    assert trace.phases is not None
    assert len(trace.phases) >= 1
    assert trace.total_llm_calls >= 3  # parse_intent, planner queries, grader, generator

    node_names = [s.node_name for s in trace.steps]
    assert "planner" in node_names
    assert "retriever" in node_names
    assert "grader" in node_names
    assert "generator" in node_names


def test_route_after_grading_sufficient():
    """route_after_grading returns 'generate' when evaluation is sufficient."""
    state = {"evaluation": '{"evaluation": "sufficient"}', "iterations": 0, "max_iterations": 3}
    assert route_after_grading(state) == "generate"


def test_route_after_grading_insufficient():
    """route_after_grading returns 'explore' when evaluation is insufficient."""
    state = {
        "evaluation": '{"evaluation": "insufficient", "reason": "缺少数据"}',
        "iterations": 0,
        "max_iterations": 3,
    }
    assert route_after_grading(state) == "explore"


def test_route_after_grading_max_iterations_forces_generate():
    """When iterations >= max_iterations, force 'generate' even if insufficient."""
    state = {
        "evaluation": '{"evaluation": "insufficient"}',
        "iterations": 3,
        "max_iterations": 3,
    }
    assert route_after_grading(state) == "generate"


def test_agent_trace_records_steps(populated_db, mock_llm_noncot):
    """Verify AgentTrace records correct execution path and step counts."""
    conn = populated_db
    llm = StubCoTLLM()
    tools = get_all_tools(conn, TALKER, "/tmp/chroma_test", mock_llm_noncot)

    trace = run_workflow(
        question="测试问题",
        talker_id=TALKER,
        llm=llm,
        conn=conn,
        tools=tools,
        llm_noncot=mock_llm_noncot,
        max_iterations=3,
        debug=False,
    )

    total_from_steps = sum(s.llm_calls for s in trace.steps)
    assert trace.total_llm_calls == total_from_steps
    assert trace.total_llm_calls > 0


class GraderSequenceStub:
    """Stub that returns insufficient on first grader call, sufficient on second."""

    def __init__(self):
        self._grader_call_count = 0

    def think_and_complete(self, system, prompt, max_tokens=4096, response_format=None):
        sys_lower = system.lower()
        prompt_lower = prompt.lower()

        if "queries" in sys_lower or "语义检索" in system or "搜索查询" in system:
            return '{"queries": ["用户问题"]}'
        if ("evaluation" in sys_lower or "信息充足性" in system) and "phases" not in sys_lower:
            self._grader_call_count += 1
            if self._grader_call_count == 1:
                return '{"evaluation": "insufficient", "reason": "缺早期数据", "suggested_action": "topic_search", "params": {"query": "早期对话"}}'
            return '{"evaluation": "sufficient"}'
        if "phases" in sys_lower or "叙事阶段" in system or "叙事分析" in system:
            return '{"phases": [{"phase_title": "阶段1", "time_range": "2023-01", "core_conclusion": "结论", "evidence_msg_ids": [1, 2, 3], "reasoning_chain": "推理", "uncertainty_note": "无"}]}'
        if "query_type" in prompt_lower or "意图" in prompt_lower:
            return '{"query_type": "arc_narrative", "focus_dimensions": ["reply_delay"], "time_range": null}'
        return '{"result": "ok"}'


def test_grader_loop_path(populated_db, mock_llm_noncot):
    """Test Grader -> Explorer -> Grader -> Generator when first grader returns insufficient."""
    conn = populated_db
    llm = GraderSequenceStub()
    tools = get_all_tools(conn, TALKER, "/tmp/chroma_test", mock_llm_noncot)

    trace = run_workflow(
        question="测试问题",
        talker_id=TALKER,
        llm=llm,
        conn=conn,
        tools=tools,
        llm_noncot=mock_llm_noncot,
        max_iterations=3,
        debug=False,
    )

    node_names = [s.node_name for s in trace.steps]
    assert "planner" in node_names
    assert "retriever" in node_names
    assert "grader" in node_names
    assert "explorer" in node_names
    assert "generator" in node_names
    assert node_names.count("grader") >= 2
    assert len(trace.phases) >= 1


def test_explorer_no_new_data_forces_sufficient(populated_db, mock_llm_noncot):
    """When Explorer finds no new nodes, it forces evaluation to sufficient to avoid loop."""
    conn = populated_db
    # Grader returns insufficient; Explorer gets no new data (chroma empty, etc)
    # and overwrites evaluation to sufficient
    llm = GraderSequenceStub()
    tools = get_all_tools(conn, TALKER, "/tmp/chroma_test", mock_llm_noncot)

    trace = run_workflow(
        question="测试",
        talker_id=TALKER,
        llm=llm,
        conn=conn,
        tools=tools,
        llm_noncot=mock_llm_noncot,
        max_iterations=2,
        debug=False,
    )

    # Should complete (Explorer forces sufficient when no new nodes)
    assert "generator" in [s.node_name for s in trace.steps]
    assert len(trace.phases) >= 1


# ---------------------------------------------------------------------------
# Factual RAG path tests
# ---------------------------------------------------------------------------

class FactualIntentStub:
    """Stub that returns event_retrieval intent to trigger factual_rag path."""

    def think_and_complete(self, system: str, prompt: str, max_tokens: int = 4096, response_format=None) -> str:
        sys_lower = system.lower()
        if "queries" in sys_lower or "语义检索" in system or "搜索查询" in system:
            return '{"queries": ["吃饭"]}'
        if "直接回答" in system or "查询助手" in system:
            return '{"answer": "去年7月你们去了一家火锅店。", "evidence_msg_ids": [1, 2]}'
        if "query_type" in prompt.lower() or "意图" in prompt.lower():
            return '{"query_type": "event_retrieval", "focus_dimensions": [], "time_range": "2023-07"}'
        return '{"result": "ok"}'


def test_route_after_planning_always_retrieve():
    """route_after_planning always returns 'retrieve' - all queries go agentic path."""
    assert route_after_planning({"answer_mode": "factual_rag"}) == "retrieve"
    assert route_after_planning({"answer_mode": "full_narrative"}) == "retrieve"


def test_factual_rag_path(populated_db, mock_llm_noncot):
    """Test factual_rag goes agentic path: Planner -> Retriever -> Grader -> Explorer -> Generator."""
    conn = populated_db
    llm = FactualIntentStub()
    tools = get_all_tools(conn, TALKER, "/tmp/chroma_test", mock_llm_noncot)

    trace = run_workflow(
        question="去年7月我们吃了什么？",
        talker_id=TALKER,
        llm=llm,
        conn=conn,
        tools=tools,
        llm_noncot=mock_llm_noncot,
        max_iterations=3,
        debug=False,
    )

    assert trace.answer_mode == "factual_rag"
    assert trace.factual_answer is not None
    assert "answer" in trace.factual_answer
    assert isinstance(trace.factual_answer["evidence_msg_ids"], list)

    node_names = [s.node_name for s in trace.steps]
    assert "planner" in node_names
    assert "retriever" in node_names
    assert "grader" in node_names
    assert "generator" in node_names


def test_message_id_heuristic_forces_factual(populated_db, mock_llm_noncot):
    """Question with message ID (e.g. '292消息') triggers factual_rag even if LLM returns narrative."""
    conn = populated_db
    # Stub returns arc_narrative (would give full_narrative) - heuristic should override to factual_rag
    class NarrativeIntentStub:
        def think_and_complete(self, system, prompt, max_tokens=4096, response_format=None):
            if "query_type" in prompt.lower() or "意图" in prompt.lower():
                return '{"query_type": "arc_narrative", "focus_dimensions": [], "output_mode": "narrative"}'
            if "queries" in system.lower() or "搜索查询" in system:
                return '{"queries": ["Central Park"]}'
            if "直接回答" in system or "查询助手" in system:
                return '{"answer": "Central Perk 是 Greenwich Village 的咖啡馆。", "evidence_msg_ids": [292]}'
            return '{"result": "ok"}'

    tools = get_all_tools(conn, TALKER, "/tmp/chroma_test", mock_llm_noncot)
    trace = run_workflow(
        question="292消息里提到的Central Park是什么？",
        talker_id=TALKER,
        llm=NarrativeIntentStub(),
        conn=conn,
        tools=tools,
        llm_noncot=mock_llm_noncot,
        max_iterations=3,
        debug=False,
    )
    assert trace.answer_mode == "factual_rag"
    assert trace.factual_answer is not None
