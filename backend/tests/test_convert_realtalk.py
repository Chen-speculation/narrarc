"""Tests for scripts/convert_realtalk.py using REALTALK JSON fixture."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from convert_realtalk import convert, _parse_realtalk_datetime, _parse_locomo_datetime


@pytest.fixture
def realtalk_sample_path():
    return Path(__file__).parent / "fixtures" / "realtalk_chat1_sample.json"


class TestParseRealtalkDatetime:
    def test_parse_valid(self):
        ts = _parse_realtalk_datetime("29.12.2023, 22:42:04")
        assert ts > 0
        assert ts < 2e10  # seconds, not ms

    def test_parse_another(self):
        ts = _parse_realtalk_datetime("30.12.2023, 00:32:20")
        assert ts > _parse_realtalk_datetime("29.12.2023, 22:42:04")


class TestParseLocomoDatetime:
    def test_parse_valid(self):
        ts = _parse_locomo_datetime("1:56 pm on 8 May, 2023")
        assert ts > 0

    def test_parse_am(self):
        ts = _parse_locomo_datetime("10:30 am on 15 July, 2023")
        assert ts > 0


class TestConvert:
    def test_full_conversion(self, realtalk_sample_path, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_path=str(realtalk_sample_path),
            dyad_index=0,
            self_id="Emi",
            talker_id="realtalk_emi_elise",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        assert data["success"] is True
        assert data["count"] == 3
        assert len(data["messages"]) == 3
        assert data["talker"] == "realtalk_emi_elise"
        assert data["messages"][0]["senderUsername"] == "Emi"
        assert data["messages"][0]["isSend"] == 1
        assert data["messages"][1]["senderUsername"] == "elise"
        assert data["messages"][1]["isSend"] == 0

    def test_mapping_output(self, realtalk_sample_path, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        out_map = str(tmp_path / "mapping.json")
        mapping = convert(
            input_path=str(realtalk_sample_path),
            dyad_index=0,
            self_id="Emi",
            talker_id="realtalk_emi_elise",
            messages_path=out_msg,
            sessions_path=out_sess,
            mapping_path=out_map,
        )
        assert mapping is not None
        assert mapping["chat_id"] == "realtalk_emi_elise"
        assert mapping["dia_to_local"]["D1:1"] == 1
        assert mapping["dia_to_local"]["D1:2"] == 2
        assert mapping["local_to_dia"]["1"] == "D1:1"

    def test_roundtrip_via_json_file_datasource(self, realtalk_sample_path, tmp_path):
        from narrative_mirror.datasource import JsonFileDataSource

        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_path=str(realtalk_sample_path),
            dyad_index=0,
            self_id="Emi",
            talker_id="realtalk_emi_elise",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        ds = JsonFileDataSource(out_msg, out_sess)
        msgs = ds.get_messages("realtalk_emi_elise")
        assert len(msgs) == 3
        assert msgs[0].is_send is True
        assert msgs[1].is_send is False
