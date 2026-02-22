"""Tests for scripts/converter_utils.py shared helpers."""

import json
import tempfile
from pathlib import Path

import pytest

# Import directly from the scripts directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from converter_utils import msg_dict, build_weflow_envelope, write_fixture_files


class TestMsgDict:
    def test_required_top_level_keys(self):
        m = msg_dict(1, "ta_001", 1678457400, 1, "user_001", "Hello")
        required = [
            "localId", "talker", "localType", "createTime", "sortSeq",
            "isSend", "senderUsername", "content", "rawContent", "parsedContent",
            "serverId", "emojiCdnUrl", "imageMd5", "videoMd5", "xmlType",
            "linkTitle", "fileName", "cardNickname",
        ]
        for key in required:
            assert key in m, f"Missing key: {key}"

    def test_optional_fields_null(self):
        m = msg_dict(1, "ta_001", 1678457400, 1, "user_001", "Hello")
        for field in ("emojiCdnUrl", "imageMd5", "videoMd5", "xmlType", "linkTitle", "fileName", "cardNickname"):
            assert m[field] is None

    def test_field_values(self):
        m = msg_dict(5, "ta_001", 1678457400, 0, "ta_001", "World")
        assert m["localId"] == 5
        assert m["createTime"] == 1678457400
        assert m["sortSeq"] == 1678457400
        assert m["isSend"] == 0
        assert m["senderUsername"] == "ta_001"
        assert m["content"] == "World"
        assert m["parsedContent"] == "World"
        assert m["localType"] == 1
        assert m["talker"] == ""


class TestBuildWeflowEnvelope:
    def test_required_keys(self):
        envelope = build_weflow_envelope([], "ta_001")
        for key in ("success", "talker", "count", "hasMore", "messages"):
            assert key in envelope

    def test_count_matches_messages(self):
        messages = [msg_dict(i + 1, "ta", 1000 + i, 0, "ta", "x") for i in range(3)]
        envelope = build_weflow_envelope(messages, "ta")
        assert envelope["count"] == 3
        assert len(envelope["messages"]) == 3

    def test_talker_set(self):
        envelope = build_weflow_envelope([], "wxid_ta_001")
        assert envelope["talker"] == "wxid_ta_001"
        assert envelope["success"] is True
        assert envelope["hasMore"] is False


class TestRoundTrip:
    """Assert a message round-trips through JsonFileDataSource."""

    def test_single_message_roundtrip(self, tmp_path):
        from narrative_mirror.datasource import JsonFileDataSource

        msg = msg_dict(1, "ta_001", 1678457400, 1, "user_001", "Hello!")
        messages_path = str(tmp_path / "messages.json")
        sessions_path = str(tmp_path / "sessions.json")
        write_fixture_files([msg], "ta_001", "TA", messages_path, sessions_path)

        ds = JsonFileDataSource(messages_path, sessions_path)
        msgs = ds.get_messages("ta_001")
        assert len(msgs) == 1
        assert msgs[0].parsed_content == "Hello!"
        assert msgs[0].create_time == 1678457400 * 1000  # seconds→ms conversion
