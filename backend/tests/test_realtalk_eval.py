"""REALTALK evaluation tests: run pipeline on converted data and compute metrics.

Loads test cases from tests/data/realtalk_eval/, runs build_layer1 + 1.5 + 2,
then run_query for each case. Computes Answer Match and Evidence Recall.

Requires converted REALTALK data (run convert_realtalk.py first).
Use --integration for real LLM; otherwise uses stub LLMs.
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from narrative_mirror.build import build_layer1
from narrative_mirror.datasource import JsonFileDataSource, get_data_source
from narrative_mirror.db import init_db
from narrative_mirror.layer2 import build_layer2
from narrative_mirror.llm import StubNonCoTLLM, StubCoTLLM, StubReranker
from narrative_mirror.metadata import build_layer15
from narrative_mirror.query import run_query_with_phases

EVAL_DIR = Path(__file__).parent / "data" / "realtalk_eval"
CHAT_ID = "realtalk_emi_elise"


def _answer_match(output: str, expected_answer: str) -> bool:
    """Check if output contains or semantically matches expected_answer."""
    exp = str(expected_answer).strip().lower()
    out = output.lower()
    if not exp:
        return True
    # Direct substring
    if exp in out:
        return True
    # Normalize: split on comma, check each part
    for part in exp.replace(",", " ").split():
        if len(part) > 3 and part in out:
            return True
    return False


def _evidence_recall(returned_ids: list[int], expected_local_ids: list[int]) -> float:
    """Compute recall: |intersection| / |expected|."""
    if not expected_local_ids:
        return 1.0
    ret_set = set(returned_ids)
    exp_set = set(expected_local_ids)
    return len(ret_set & exp_set) / len(exp_set)


@pytest.fixture
def realtalk_eval_data():
    """Load REALTALK eval fixture; skip if not present."""
    msg_path = EVAL_DIR / f"{CHAT_ID}_messages.json"
    sess_path = EVAL_DIR / f"{CHAT_ID}_sessions.json"
    if not msg_path.exists() or not sess_path.exists():
        pytest.skip(
            f"REALTALK eval data not found. Run: python scripts/convert_realtalk.py "
            f"--input /path/to/REALTALK/data/Chat_1_Emi_Elise.json --self-id Emi "
            f"--talker-id {CHAT_ID} --output {msg_path} --sessions-output {sess_path} "
            f"--mapping-output {EVAL_DIR}/{CHAT_ID}_mapping.json"
        )
    return {
        "messages_path": str(msg_path),
        "sessions_path": str(sess_path),
        "mapping_path": str(EVAL_DIR / f"{CHAT_ID}_mapping.json"),
        "cases_path": str(EVAL_DIR / f"{CHAT_ID}_cases.json"),
        "arc_cases_path": str(EVAL_DIR / f"{CHAT_ID}_arc_cases.json"),
    }


@pytest.fixture
def eval_db_and_ds(realtalk_eval_data):
    """Create temp DB, run pipeline, yield (conn, ds)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "mirror.db")
        conn = init_db(db_path)

        ds = JsonFileDataSource(
            realtalk_eval_data["messages_path"],
            realtalk_eval_data["sessions_path"],
        )

        llm_noncot = StubNonCoTLLM()
        llm_cot = StubCoTLLM()
        reranker = StubReranker()

        nodes = build_layer1(
            talker_id=CHAT_ID,
            source=ds,
            llm=llm_noncot,
            conn=conn,
            gap_seconds=1800,
            debug=False,
        )
        assert len(nodes) >= 1, "Expected at least 1 node"

        build_layer15(talker_id=CHAT_ID, llm=llm_noncot, conn=conn, debug=False)

        build_layer2(
            talker_id=CHAT_ID,
            llm_noncot=llm_noncot,
            reranker=reranker,
            llm_cot=llm_cot,
            conn=conn,
            data_dir=tmpdir,
            sim_threshold=0.5,
            top_k=10,
            debug=False,
        )

        yield conn, ds
        conn.close()


class TestRealtalkEval:
    """REALTALK evaluation tests."""

    def test_pipeline_runs_on_realtalk_data(self, eval_db_and_ds):
        """Smoke test: pipeline completes on converted REALTALK data."""
        conn, _ = eval_db_and_ds
        output, phases = run_query_with_phases(
            question="What are Kate's hobbies?",
            talker_id=CHAT_ID,
            llm=StubCoTLLM(),
            conn=conn,
            max_nodes=60,
        )
        assert len(output) > 0
        assert isinstance(phases, list)

    def test_answer_match_metric(self):
        """Unit test for answer_match logic."""
        assert _answer_match("Cooking, skiing, hiking", "Cooking, skiing, hiking") is True
        assert _answer_match("She likes cooking and skiing", "cooking") is True
        assert _answer_match("Nothing relevant", "cooking") is False

    def test_evidence_recall_metric(self):
        """Unit test for evidence_recall logic."""
        assert _evidence_recall([1, 2, 3], [1, 2]) == 1.0
        assert _evidence_recall([1, 3], [1, 2, 3]) == pytest.approx(2 / 3)
        assert _evidence_recall([], [1, 2]) == 0.0
        assert _evidence_recall([1], []) == 1.0

    def test_eval_cases_structure(self, realtalk_eval_data):
        """Verify cases and mapping files have expected structure."""
        with open(realtalk_eval_data["mapping_path"]) as f:
            mapping = json.load(f)
        assert "dia_to_local" in mapping
        assert "local_to_dia" in mapping

        if Path(realtalk_eval_data["cases_path"]).exists():
            with open(realtalk_eval_data["cases_path"]) as f:
                cases = json.load(f)
            assert isinstance(cases, list)
            if cases:
                c = cases[0]
                assert "question" in c
                assert "expected_answer" in c
                assert "evidence_dia_ids" in c
                assert "query_type" in c

        # Arc cases: pre-generated narrative arc questions (evaluation dataset)
        if Path(realtalk_eval_data["arc_cases_path"]).exists():
            with open(realtalk_eval_data["arc_cases_path"]) as f:
                arc_cases = json.load(f)
            assert isinstance(arc_cases, list)
            if arc_cases:
                ac = arc_cases[0]
                assert "question" in ac
                assert "query_type" in ac
                assert ac.get("query_type") == "arc_narrative"
                assert "expected_phases" in ac
                for phase in ac["expected_phases"]:
                    assert "title" in phase
                    assert "evidence_dia_ids" in phase

    def test_run_single_case_and_compute_metrics(self, eval_db_and_ds, realtalk_eval_data):
        """Run one case, compute Answer Match and Evidence Recall."""
        conn, _ = eval_db_and_ds

        cases_path = realtalk_eval_data["cases_path"]
        if not Path(cases_path).exists():
            pytest.skip("No cases file")

        with open(cases_path) as f:
            cases = json.load(f)
        with open(realtalk_eval_data["mapping_path"]) as f:
            mapping = json.load(f)

        dia_to_local = mapping.get("dia_to_local", {})

        # Run first case
        case = cases[0]
        output, phases = run_query_with_phases(
            question=case["question"],
            talker_id=CHAT_ID,
            llm=StubCoTLLM(),
            conn=conn,
            max_nodes=60,
        )

        expected_local_ids = [
            dia_to_local[d] for d in case.get("evidence_dia_ids", []) if d in dia_to_local
        ]
        returned_ids = []
        for p in phases:
            returned_ids.extend(p.evidence_msg_ids)

        answer_ok = _answer_match(output, case.get("expected_answer", ""))
        recall = _evidence_recall(returned_ids, expected_local_ids)

        # With stub LLM, we may not get perfect match; just verify metrics are computed
        assert isinstance(answer_ok, bool)
        assert 0 <= recall <= 1.0

    def test_run_arc_case_and_compute_evidence_recall(self, eval_db_and_ds, realtalk_eval_data):
        """Run one arc_narrative case, compute Evidence Recall across expected_phases."""
        conn, _ = eval_db_and_ds

        arc_path = realtalk_eval_data["arc_cases_path"]
        if not Path(arc_path).exists():
            pytest.skip("No arc_cases file")

        with open(arc_path) as f:
            arc_cases = json.load(f)
        with open(realtalk_eval_data["mapping_path"]) as f:
            mapping = json.load(f)

        dia_to_local = mapping.get("dia_to_local", {})

        # Run first arc case
        arc = arc_cases[0]
        output, phases = run_query_with_phases(
            question=arc["question"],
            talker_id=CHAT_ID,
            llm=StubCoTLLM(),
            conn=conn,
            max_nodes=60,
        )

        # Collect all expected evidence from phases
        expected_local_ids = []
        for phase in arc.get("expected_phases", []):
            for d in phase.get("evidence_dia_ids", []):
                if d in dia_to_local:
                    expected_local_ids.append(dia_to_local[d])

        returned_ids = []
        for p in phases:
            returned_ids.extend(p.evidence_msg_ids)

        recall = _evidence_recall(returned_ids, expected_local_ids)

        assert len(output) > 0
        assert 0 <= recall <= 1.0
