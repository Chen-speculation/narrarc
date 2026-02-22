"""Tests for scripts/convert_candor.py using a synthetic 3-turn session JSON."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from convert_candor import parse_session, convert

SYNTHETIC_SESSION = {
    "start_epoch": 1678457400,
    "turns": [
        {"start_time": 0, "speaker_id": "A", "text": "Hello there!"},
        {"start_time": 30, "speaker_id": "B", "text": "Hi, how are you?"},
        {"start_time": 65, "speaker_id": "A", "text": "Doing well, thanks."},
    ],
}

SYNTHETIC_SESSION_LIST = [
    {"start_epoch": 1000, "turns": [{"start_time": 0, "speaker_id": "X", "text": "wrong"}]},
    SYNTHETIC_SESSION,
]


@pytest.fixture
def session_file(tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps(SYNTHETIC_SESSION), encoding="utf-8")
    return str(path)


@pytest.fixture
def session_list_file(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps(SYNTHETIC_SESSION_LIST), encoding="utf-8")
    return str(path)


class TestParseSession:
    def test_record_count(self):
        records = parse_session(SYNTHETIC_SESSION, self_id="A")
        assert len(records) == 3

    def test_absolute_timestamps(self):
        records = parse_session(SYNTHETIC_SESSION, self_id="A")
        # start_epoch=1678457400, offsets 0, 30, 65
        assert records[0][0] == 1678457400       # 1678457400 + 0
        assert records[1][0] == 1678457430       # 1678457400 + 30
        assert records[2][0] == 1678457465       # 1678457400 + 65

    def test_is_send_assignment(self):
        records = parse_session(SYNTHETIC_SESSION, self_id="A")
        assert records[0][1] == 1   # A
        assert records[1][1] == 0   # B
        assert records[2][1] == 1   # A


class TestConvert:
    def test_single_session_file(self, session_file, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_path=session_file,
            session_index=0,
            self_id="A",
            talker_id="candor_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        assert data["count"] == 3
        assert data["talker"] == "candor_01"

    def test_session_list_index(self, session_list_file, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        # Index 1 → SYNTHETIC_SESSION (start_epoch=1678457400)
        convert(
            input_path=session_list_file,
            session_index=1,
            self_id="A",
            talker_id="candor_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        assert data["messages"][0]["createTime"] == 1678457400

    def test_roundtrip_via_json_file_datasource(self, session_file, tmp_path):
        from narrative_mirror.datasource import JsonFileDataSource

        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_path=session_file,
            session_index=0,
            self_id="A",
            talker_id="candor_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        ds = JsonFileDataSource(out_msg, out_sess)
        msgs = ds.get_messages("candor_01")
        assert len(msgs) == 3
        # Verify seconds→ms conversion
        assert msgs[0].create_time == 1678457400 * 1000
        assert msgs[1].create_time == 1678457430 * 1000
