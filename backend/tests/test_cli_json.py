"""Tests for cli_json JSON CLI API."""

import json
import os
import sqlite3
import subprocess
import tempfile
import pytest

from narrative_mirror.db import (
    init_db,
    upsert_messages,
    upsert_node,
    upsert_metadata,
    upsert_anchors,
    get_talkers_with_stats,
    get_build_status,
)
from narrative_mirror.models import RawMessage, TopicNode, MetadataSignals, AnomalyAnchor


TALKER = "test_cli_talker"


def _run_cli(args: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    """Run cli_json, return (exit_code, stdout, stderr)."""
    cmd = ["uv", "run", "python", "-m", "narrative_mirror.cli_json"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=stdin,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite DB with test data (raw_messages, topic_nodes, node_metadata)."""
    db_path = tmp_path / "mirror.db"
    conn = init_db(str(db_path))

    msgs = [
        RawMessage(
            local_id=i,
            talker_id=TALKER,
            create_time=i * 100_000,
            is_send=(i % 2 == 1),  # odd = sent by user
            sender_username="partner" if i % 2 == 0 else "me",
            parsed_content=f"msg {i}",
            local_type=1,
        )
        for i in range(1, 11)
    ]
    upsert_messages(conn, msgs)

    node = TopicNode(
        node_id="n1",
        talker_id=TALKER,
        burst_id="b1",
        topic_name="Test",
        start_local_id=1,
        end_local_id=10,
        start_time=100_000,
        end_time=1_000_000,
    )
    upsert_node(conn, node)

    meta = MetadataSignals(
        node_id="n1",
        talker_id=TALKER,
        reply_delay_avg_s=0.0,
        reply_delay_max_s=0.0,
        term_shift_score=0.0,
        silence_event=False,
        topic_frequency=0,
        initiator_ratio=0.0,
        emotional_tone=0.0,
        conflict_intensity=0.0,
    )
    upsert_metadata(conn, meta)

    anchor = AnomalyAnchor(
        anchor_id="a1",
        talker_id=TALKER,
        node_id="n1",
        signal_name="conflict_intensity",
        signal_value=0.9,
        baseline_mean=0.2,
        baseline_std=0.1,
        event_date="2024-01-01",
    )
    upsert_anchors(conn, [anchor])

    conn.close()
    return str(db_path)


@pytest.fixture
def tmp_db_pending(tmp_path):
    """DB with only raw_messages (build_status=pending)."""
    db_path = tmp_path / "pending.db"
    conn = init_db(str(db_path))
    upsert_messages(conn, [
        RawMessage(1, "p1", 1000, True, "u", "a", 1),
    ])
    conn.close()
    return str(db_path)


@pytest.fixture
def tmp_db_in_progress(tmp_path):
    """DB with raw_messages + topic_nodes (build_status=in_progress)."""
    db_path = tmp_path / "inprogress.db"
    conn = init_db(str(db_path))
    upsert_messages(conn, [RawMessage(1, "p2", 1000, True, "u", "a", 1)])
    node = TopicNode(
        node_id="n1", talker_id="p2", burst_id="b1",
        topic_name="T", start_local_id=1, end_local_id=1,
        start_time=1000, end_time=1000,
    )
    upsert_node(conn, node)
    conn.close()
    return str(db_path)


def test_list_sessions_output_format(tmp_db):
    """8.2: list_sessions outputs JSON array with 5 fields per element."""
    code, out, err = _run_cli(["--db", tmp_db, "list_sessions"])
    assert code == 0
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) >= 1
    sess = next(s for s in data if s["talker_id"] == TALKER)
    assert set(sess.keys()) >= {
        "talker_id",
        "display_name",
        "last_timestamp",
        "build_status",
        "message_count",
    }
    assert isinstance(sess["talker_id"], str)
    assert isinstance(sess["display_name"], str)
    assert isinstance(sess["last_timestamp"], int)
    assert sess["build_status"] in ("pending", "in_progress", "complete")
    assert isinstance(sess["message_count"], int)


def test_get_messages_sender_display(tmp_db):
    """8.3: get_messages maps is_send=True to sender_display='我'."""
    code, out, err = _run_cli(["--db", tmp_db, "get_messages", "--talker", TALKER])
    assert code == 0
    data = json.loads(out)
    assert isinstance(data, list)
    for m in data:
        if m.get("is_send"):
            assert m["sender_display"] == "我"
        else:
            assert m["sender_display"] != "我"


def test_query_output_format(tmp_db, tmp_path):
    """8.4: query output has conversation_id, phase_index, total_duration_ms, uncertainty_note null."""
    chroma_dir = str(tmp_path / "chroma")
    os.makedirs(chroma_dir, exist_ok=True)

    code, out, err = _run_cli([
        "--db", tmp_db,
        "query",
        "--talker", TALKER,
        "--question", "测试问题",
        "--stub",
        "--chroma-dir", chroma_dir,
    ])
    assert code == 0, f"stderr: {err}"
    data = json.loads(out)

    assert data["conversation_id"] == TALKER
    assert "phases" in data
    for i, p in enumerate(data["phases"]):
        assert p["phase_index"] == i + 1
        unc = p.get("uncertainty_note")
        if unc is not None and unc == "":
            pytest.fail("uncertainty_note should be null when empty, not ''")
        # empty string -> null
        if "uncertainty_note" in p and p["uncertainty_note"] == "":
            pytest.fail("uncertainty_note empty string should become null")

    assert "agent_trace" in data
    assert data["agent_trace"]["total_duration_ms"] >= 0
    assert "all_messages" in data


def test_import_weflow_format(tmp_path):
    """Import accepts WeFlow format: session.displayName + messages with content (no parsedContent)."""
    from narrative_mirror.cli_json import parse_import_json

    weflow_json = """
    {
      "weflow": {"version": "1.0.3"},
      "session": {
        "wxid": "wxid_abc123",
        "displayName": "不让叫琪",
        "remark": "备注名"
      },
      "messages": [
        {"localId": 1, "createTime": 1700029034, "content": "你好", "isSend": 0, "localType": 1}
      ]
    }
    """
    display_name, talker_id, messages = parse_import_json(weflow_json)
    assert display_name == "不让叫琪"
    assert talker_id == "wxid_abc123"
    assert len(messages) == 1
    assert messages[0].parsed_content == "你好"
    assert messages[0].sender_username == ""


def test_import_idempotency(tmp_path):
    """8.5: import is idempotent - second import does not duplicate rows."""
    db_path = tmp_path / "import.db"
    json_path = tmp_path / "import.json"
    json_path.write_text(
        '{"display_name":"张三","messages":['
        '{"localId":1,"createTime":1704000000,"isSend":1,"parsedContent":"hi","localType":1}'
        ']}',
        encoding="utf-8",
    )

    code1, out1, err1 = _run_cli(["--db", str(db_path), "import", "--file", str(json_path)])
    assert code1 == 0
    data1 = json.loads(out1)
    assert data1["message_count"] == 1

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM raw_messages")
    count1 = cur.fetchone()[0]
    conn.close()
    assert count1 == 1

    code2, out2, err2 = _run_cli(["--db", str(db_path), "import", "--file", str(json_path)])
    assert code2 == 0
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM raw_messages")
    count2 = cur.fetchone()[0]
    conn.close()
    assert count2 == 1, "Idempotency: second import should not add duplicate rows"


def test_get_build_status_pending(tmp_db_pending):
    """8.6: build_status is pending when only raw_messages exists."""
    code, out, err = _run_cli(["--db", tmp_db_pending, "list_sessions"])
    assert code == 0
    data = json.loads(out)
    sess = next(s for s in data if s["talker_id"] == "p1")
    assert sess["build_status"] == "pending"


def test_get_build_status_in_progress(tmp_db_in_progress):
    """8.6: build_status is in_progress when topic_nodes exist but node_metadata does not."""
    code, out, err = _run_cli(["--db", tmp_db_in_progress, "list_sessions"])
    assert code == 0
    data = json.loads(out)
    sess = next(s for s in data if s["talker_id"] == "p2")
    assert sess["build_status"] == "in_progress"


def test_get_build_status_complete(tmp_db):
    """8.6: build_status is complete when both topic_nodes and node_metadata exist."""
    code, out, err = _run_cli(["--db", tmp_db, "list_sessions"])
    assert code == 0
    data = json.loads(out)
    sess = next(s for s in data if s["talker_id"] == TALKER)
    assert sess["build_status"] == "complete"


def test_list_sessions_empty_db(tmp_path):
    """list_sessions returns [] when db exists but has no messages."""
    db_path = tmp_path / "empty.db"
    init_db(str(db_path))
    code, out, err = _run_cli(["--db", str(db_path), "list_sessions"])
    assert code == 0
    assert json.loads(out) == []


def test_delete_session(tmp_db):
    """delete_session removes talker data and returns JSON."""
    code, out, err = _run_cli(["--db", tmp_db, "delete_session", "--talker", TALKER])
    assert code == 0
    data = json.loads(out)
    assert data == {"status": "deleted", "talker_id": TALKER}

    code2, out2, _ = _run_cli(["--db", tmp_db, "list_sessions"])
    assert code2 == 0
    sessions = json.loads(out2)
    assert not any(s["talker_id"] == TALKER for s in sessions)


def test_delete_session_not_found(tmp_db):
    """delete_session exits non-0 when talker does not exist."""
    code, _, err = _run_cli(["--db", tmp_db, "delete_session", "--talker", "nonexistent_talker"])
    assert code != 0
    assert "not found" in err.lower()


def test_list_sessions_db_not_found():
    """list_sessions exits non-0 when db file does not exist."""
    code, out, err = _run_cli(["--db", "/nonexistent/path/db.sqlite", "list_sessions"])
    assert code != 0
    assert "not found" in err.lower() or "error" in err.lower()
