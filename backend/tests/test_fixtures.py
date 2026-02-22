"""Tests for JSON fixture files."""

import json
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "data"


def test_weflow_messages_valid_json():
    """weflow_messages.json should be valid JSON with correct envelope."""
    path = FIXTURES_DIR / "weflow_messages.json"
    with open(path, "r") as f:
        data = json.load(f)

    # Check envelope structure
    assert data["success"] is True
    assert data["talker"] == "wxid_ta_001"
    assert data["count"] == 20
    assert data["hasMore"] is False
    assert "messages" in data
    assert len(data["messages"]) == 20


def test_create_time_is_unix_seconds():
    """createTime values should be in Unix seconds (not milliseconds)."""
    path = FIXTURES_DIR / "weflow_messages.json"
    with open(path, "r") as f:
        data = json.load(f)

    for msg in data["messages"]:
        create_time = msg["createTime"]
        # Unix seconds should be < 2e10 (year ~2600)
        # Unix milliseconds would be > 2e10
        assert create_time < 2e10, f"createTime {create_time} appears to be in milliseconds"


def test_is_send_alternation():
    """isSend should alternate correctly based on the demo scenario."""
    path = FIXTURES_DIR / "weflow_messages.json"
    with open(path, "r") as f:
        data = json.load(f)

    # First message from user (isSend=1)
    assert data["messages"][0]["isSend"] == 1, "msg_001 should be from user (isSend=1)"
    # Second message from TA (isSend=0)
    assert data["messages"][1]["isSend"] == 0, "msg_002 should be from TA (isSend=0)"

    # Check expected pattern for first burst (msg_001-008)
    # User, TA, User, TA, TA, User, TA, User
    expected_is_send = [1, 0, 1, 0, 0, 1, 0, 1]
    for i, expected in enumerate(expected_is_send):
        assert data["messages"][i]["isSend"] == expected, f"msg_{i+1:03d} has wrong isSend"


def test_all_required_fields_present():
    """All required message fields should be present."""
    path = FIXTURES_DIR / "weflow_messages.json"
    with open(path, "r") as f:
        data = json.load(f)

    required_fields = [
        "localId", "talker", "localType", "createTime", "sortSeq",
        "isSend", "senderUsername", "content", "rawContent", "parsedContent",
        "serverId", "emojiCdnUrl", "imageMd5", "videoMd5", "xmlType",
        "linkTitle", "fileName", "cardNickname"
    ]

    for msg in data["messages"]:
        for field in required_fields:
            assert field in msg, f"Missing field: {field}"


def test_optional_fields_are_null():
    """Optional fields should be set to null."""
    path = FIXTURES_DIR / "weflow_messages.json"
    with open(path, "r") as f:
        data = json.load(f)

    optional_fields = [
        "emojiCdnUrl", "imageMd5", "videoMd5", "xmlType",
        "linkTitle", "fileName", "cardNickname"
    ]

    for msg in data["messages"]:
        for field in optional_fields:
            assert msg[field] is None, f"{field} should be null, got {msg[field]}"


def test_weflow_sessions_valid_json():
    """weflow_sessions.json should be valid JSON with correct envelope."""
    path = FIXTURES_DIR / "weflow_sessions.json"
    with open(path, "r") as f:
        data = json.load(f)

    # Check envelope structure
    assert data["success"] is True
    assert data["count"] == 1
    assert "sessions" in data
    assert len(data["sessions"]) == 1

    # Check session fields
    session = data["sessions"][0]
    assert session["username"] == "wxid_ta_001"
    assert session["displayName"] == "TA"
    assert session["type"] == 1
    assert session["lastTimestamp"] == 1707926400  # msg_020's createTime
    assert session["unreadCount"] == 0
