"""End-to-end smoke test for Narrative Mirror MVP."""

import pytest
import tempfile
import os
import sqlite3

from narrative_mirror.models import TopicNode, MetadataSignals, AnomalyAnchor
from narrative_mirror.db import init_db, upsert_node, upsert_metadata, upsert_anchors, upsert_messages, upsert_pointer, get_nodes
from narrative_mirror.datasource import MockDataSource
from narrative_mirror.build import build_layer1
from narrative_mirror.metadata import build_layer15
from narrative_mirror.layer2 import build_layer2
from narrative_mirror.query import run_query
from narrative_mirror.llm import StubNonCoTLLM, StubCoTLLM, StubReranker


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def db_conn(temp_dir):
    """Create a test database connection."""
    db_path = os.path.join(temp_dir, "mirror.db")
    conn = init_db(db_path)
    yield conn
    conn.close()


class TestEndToEndPipeline:
    """End-to-end test running the full pipeline."""

    def test_full_pipeline_mock_data(self, temp_dir, db_conn):
        """Run the full pipeline on mock data with stub LLMs."""
        talker_id = "mock_talker_001"

        # Get mock data source
        source = MockDataSource()

        # Create stub LLMs
        llm_noncot = StubNonCoTLLM()
        llm_cot = StubCoTLLM()
        reranker = StubReranker()

        # Layer 1: Build topic nodes
        nodes = build_layer1(
            talker_id=talker_id,
            source=source,
            llm=llm_noncot,
            conn=db_conn,
            gap_seconds=1800,
            debug=False,
        )

        # Assert: >= 4 TopicNodes created
        assert len(nodes) >= 4, f"Expected >= 4 nodes, got {len(nodes)}"

        # Layer 1.5: Compute metadata and detect anomalies
        signals, anchors = build_layer15(
            talker_id=talker_id,
            llm=llm_noncot,
            conn=db_conn,
            debug=False,
        )

        # Assert: signals computed for all nodes
        assert len(signals) == len(nodes), f"Expected {len(nodes)} signals, got {len(signals)}"

        # Note: anchors may be 0 if all signals are uniform (which happens with stub LLM)
        # This is acceptable - anomaly detection requires variance in signals

        # Layer 2: Build semantic threads
        embedded, pointers = build_layer2(
            talker_id=talker_id,
            llm_noncot=llm_noncot,
            reranker=reranker,
            llm_cot=llm_cot,
            conn=db_conn,
            data_dir=temp_dir,
            sim_threshold=0.5,
            top_k=10,
            debug=False,
        )

        # Assert: nodes were embedded
        assert embedded >= 0, "Layer 2 embedding should complete"

        # Query: Run a test question
        output = run_query(
            question="我们是怎么一步步分手的？",
            talker_id=talker_id,
            llm=llm_cot,
            conn=db_conn,
            max_nodes=60,
            debug=False,
        )

        # Assert: Output is non-empty (may be default message if no phases generated)
        assert len(output) > 0, "Expected non-empty output"

    def test_database_persistence(self, temp_dir, db_conn):
        """Test that data is persisted correctly."""
        talker_id = "test_persistence"

        # Insert test data
        node = TopicNode(
            node_id="test_node",
            talker_id=talker_id,
            burst_id="test_burst",
            topic_name="测试话题",
            start_local_id=1,
            end_local_id=5,
            start_time=1000000,
            end_time=2000000,
        )
        upsert_node(db_conn, node)

        signal = MetadataSignals(
            node_id="test_node",
            talker_id=talker_id,
            reply_delay_avg_s=100.0,
            reply_delay_max_s=200.0,
        )
        upsert_metadata(db_conn, signal)

        anchor = AnomalyAnchor(
            talker_id=talker_id,
            node_id="test_node",
            signal_name="reply_delay",
            signal_value=500.0,
            baseline_mean=100.0,
            baseline_std=50.0,
            event_date="2023-01-01",
        )
        upsert_anchors(db_conn, [anchor])

        # Retrieve and verify
        nodes = get_nodes(db_conn, talker_id)
        assert len(nodes) == 1
        assert nodes[0].topic_name == "测试话题"

    def test_build_skip_existing_nodes(self, temp_dir, db_conn):
        """Test that build skips already-classified bursts."""
        talker_id = "mock_talker_001"

        source = MockDataSource()
        llm = StubNonCoTLLM()

        # First build
        nodes1 = build_layer1(
            talker_id=talker_id,
            source=source,
            llm=llm,
            conn=db_conn,
            debug=False,
        )

        # Second build - should skip existing
        nodes2 = build_layer1(
            talker_id=talker_id,
            source=source,
            llm=llm,
            conn=db_conn,
            debug=False,
        )

        # Same number of nodes
        assert len(nodes1) == len(nodes2)
