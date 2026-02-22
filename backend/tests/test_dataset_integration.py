"""Dataset integration tests using public corpora converted to WeFlow JSON format.

These tests require both --integration AND the raw dataset to be present locally.
If the raw dataset is absent (env var not set), the test is skipped with a clear message.

Environment variables:
    REALTALK_PATH       – path to the REALTALK dyad directory
    KAGGLE_WA_CSV       – path to the Kaggle WhatsApp export CSV
    CANDOR_SESSION_JSON – path to the CANDOR session JSON file
"""

import os
import sys
import sqlite3
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ── shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def llms_and_reranker():
    """Real LLMs from config.yml — skips if config absent."""
    config_path = Path("config.yml")
    if not config_path.exists():
        pytest.skip("config.yml not found — skipping integration tests")
    from narrative_mirror.config import load_config
    from narrative_mirror.llm import from_config
    cfg = load_config(str(config_path))
    return from_config(cfg)


# ── REALTALK ──────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.dataset
class TestREALTALKPipeline:
    """Full pipeline test using a REALTALK dyad converted to WeFlow format."""

    def test_arc_narrative(self, tmp_path, llms_and_reranker):
        from conftest import converted_fixture
        from convert_realtalk import convert as realtalk_convert
        from narrative_mirror.datasource import JsonFileDataSource
        from narrative_mirror.db import init_db, upsert_anchors
        from narrative_mirror.build import build_layer1
        from narrative_mirror.metadata import compute_all_metadata, detect_anomalies
        from narrative_mirror.layer2 import build_layer2
        from narrative_mirror.query import run_query

        raw_path = converted_fixture("realtalk", os.getenv("REALTALK_PATH"))

        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        realtalk_convert(
            input_dir=raw_path,
            dyad_index=0,
            self_id="A",
            talker_id="realtalk_dyad_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )

        noncot_llm, cot_llm, reranker = llms_and_reranker
        conn = init_db(str(tmp_path / "mirror.db"))
        try:
            ds = JsonFileDataSource(out_msg, out_sess)
            nodes = build_layer1("realtalk_dyad_01", ds, noncot_llm, conn)
            assert len(nodes) >= 1, "Expected at least 1 TopicNode"

            signals = compute_all_metadata("realtalk_dyad_01", noncot_llm, conn)
            anchors = detect_anomalies(signals, "realtalk_dyad_01")
            upsert_anchors(conn, anchors)

            build_layer2(
                "realtalk_dyad_01", noncot_llm, reranker, cot_llm, conn,
                str(tmp_path / "chroma"),
            )

            result = run_query(
                "how did the relationship evolve?",
                "realtalk_dyad_01",
                cot_llm,
                conn,
            )
            assert result and len(result) > 0
        finally:
            conn.close()


# ── Kaggle WhatsApp ───────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.dataset
class TestKaggleWhatsAppPipeline:
    """Full pipeline test using a Kaggle WhatsApp CSV converted to WeFlow format."""

    def test_arc_narrative(self, tmp_path, llms_and_reranker):
        from conftest import converted_fixture
        from convert_kaggle_whatsapp import convert as wa_convert
        from narrative_mirror.datasource import JsonFileDataSource
        from narrative_mirror.db import init_db, upsert_anchors
        from narrative_mirror.build import build_layer1
        from narrative_mirror.metadata import compute_all_metadata, detect_anomalies
        from narrative_mirror.layer2 import build_layer2

        raw_path = converted_fixture("kaggle_wa", os.getenv("KAGGLE_WA_CSV"))

        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")

        # The CSV must have at least two identifiable senders; use env var overrides
        sender_self = os.getenv("KAGGLE_WA_SENDER_SELF", "")
        sender_ta = os.getenv("KAGGLE_WA_SENDER_TA", "")
        if not sender_self or not sender_ta:
            pytest.skip(
                "Set KAGGLE_WA_SENDER_SELF and KAGGLE_WA_SENDER_TA to specify senders"
            )

        wa_convert(
            input_csv=raw_path,
            senders=[sender_self, sender_ta],
            talker_id="kaggle_wa_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )

        noncot_llm, cot_llm, reranker = llms_and_reranker
        conn = init_db(str(tmp_path / "mirror.db"))
        try:
            ds = JsonFileDataSource(out_msg, out_sess)
            nodes = build_layer1("kaggle_wa_01", ds, noncot_llm, conn)
            assert len(nodes) >= 4, f"Expected >= 4 TopicNodes, got {len(nodes)}"

            signals = compute_all_metadata("kaggle_wa_01", noncot_llm, conn)
            anchors = detect_anomalies(signals, "kaggle_wa_01")
            upsert_anchors(conn, anchors)
            assert len(anchors) >= 1, f"Expected >= 1 anomaly anchor, got {len(anchors)}"
        finally:
            conn.close()


# ── CANDOR ────────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.dataset
class TestCANDORPipeline:
    """Layer 1 segment count test using a CANDOR session converted to WeFlow format."""

    def test_segment_count(self, tmp_path, llms_and_reranker):
        from conftest import converted_fixture
        from convert_candor import convert as candor_convert
        from narrative_mirror.datasource import JsonFileDataSource
        from narrative_mirror.db import init_db
        from narrative_mirror.build import build_layer1

        raw_path = converted_fixture("candor", os.getenv("CANDOR_SESSION_JSON"))

        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        self_id = os.getenv("CANDOR_SELF_ID", "A")
        candor_convert(
            input_path=raw_path,
            session_index=0,
            self_id=self_id,
            talker_id="candor_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )

        noncot_llm, cot_llm, _ = llms_and_reranker
        conn = init_db(str(tmp_path / "mirror.db"))
        try:
            ds = JsonFileDataSource(out_msg, out_sess)
            nodes = build_layer1("candor_01", ds, noncot_llm, conn)
            assert len(nodes) >= 2, f"Expected >= 2 TopicNodes, got {len(nodes)}"
        finally:
            conn.close()
