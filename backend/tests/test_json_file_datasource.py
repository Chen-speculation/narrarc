"""Tests for JsonFileDataSource."""

import json
import pytest
import tempfile
from pathlib import Path

from narrative_mirror.datasource import JsonFileDataSource, DataSourceError
from narrative_mirror.models import RawMessage, Session, Contact


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_messages(temp_dir: Path):
    """Create a sample messages JSON file."""
    data = {
        "success": True,
        "talker": "wxid_test_001",
        "count": 3,
        "hasMore": False,
        "messages": [
            {
                "localId": 1,
                "talker": "",
                "localType": 1,
                "createTime": 1678457400,  # 2023-03-10 in seconds
                "sortSeq": 1678457400,
                "isSend": 1,
                "senderUsername": "wxid_user_001",
                "content": "Hello",
                "rawContent": "Hello",
                "parsedContent": "Hello",
                "serverId": 0,
                "emojiCdnUrl": None,
                "imageMd5": None,
                "videoMd5": None,
                "xmlType": None,
                "linkTitle": None,
                "fileName": None,
                "cardNickname": None,
            },
            {
                "localId": 2,
                "talker": "",
                "localType": 1,
                "createTime": 1678457460,
                "sortSeq": 1678457460,
                "isSend": 0,
                "senderUsername": "wxid_ta_001",
                "content": "Hi there",
                "rawContent": "Hi there",
                "parsedContent": "Hi there",
                "serverId": 0,
                "emojiCdnUrl": None,
                "imageMd5": None,
                "videoMd5": None,
                "xmlType": None,
                "linkTitle": None,
                "fileName": None,
                "cardNickname": None,
            },
            {
                "localId": 3,
                "talker": "",
                "localType": 1,
                "createTime": 1678458000,
                "sortSeq": 1678458000,
                "isSend": 1,
                "senderUsername": "wxid_user_001",
                "content": "How are you?",
                "rawContent": "How are you?",
                "parsedContent": "How are you?",
                "serverId": 0,
                "emojiCdnUrl": None,
                "imageMd5": None,
                "videoMd5": None,
                "xmlType": None,
                "linkTitle": None,
                "fileName": None,
                "cardNickname": None,
            },
        ]
    }
    path = temp_dir / "messages.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return str(path)


@pytest.fixture
def sample_sessions(temp_dir: Path):
    """Create a sample sessions JSON file."""
    data = {
        "success": True,
        "count": 1,
        "sessions": [
            {
                "username": "wxid_ta_001",
                "displayName": "Test Contact",
                "type": 1,
                "lastTimestamp": 1678458000,
                "unreadCount": 0,
            }
        ]
    }
    path = temp_dir / "sessions.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return str(path)


class TestJsonFileDataSourceConstruction:
    """Tests for JsonFileDataSource construction."""

    def test_successful_construction(self, sample_messages, sample_sessions):
        """Should construct successfully with valid files."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")
        assert len(messages) == 3

    def test_missing_messages_file_raises(self, temp_dir, sample_sessions):
        """Should raise DataSourceError for missing messages file."""
        with pytest.raises(DataSourceError) as exc_info:
            JsonFileDataSource(str(temp_dir / "nonexistent.json"), sample_sessions)
        assert "not found" in str(exc_info.value)

    def test_missing_sessions_file_raises(self, sample_messages, temp_dir):
        """Should raise DataSourceError for missing sessions file."""
        with pytest.raises(DataSourceError) as exc_info:
            JsonFileDataSource(sample_messages, str(temp_dir / "nonexistent.json"))
        assert "not found" in str(exc_info.value)

    def test_invalid_json_raises(self, temp_dir, sample_sessions):
        """Should raise DataSourceError for invalid JSON."""
        bad_json = temp_dir / "bad.json"
        with open(bad_json, "w") as f:
            f.write("not valid json")

        with pytest.raises(DataSourceError) as exc_info:
            JsonFileDataSource(str(bad_json), sample_sessions)
        assert "Invalid JSON" in str(exc_info.value)


class TestSecondsToMsConversion:
    """Tests for createTime seconds-to-milliseconds conversion."""

    def test_create_time_conversion(self, sample_messages, sample_sessions):
        """createTime should be converted from seconds to milliseconds."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")

        # First message has createTime 1678457400 seconds
        # Should be 1678457400000 milliseconds
        assert messages[0].create_time == 1678457400000

    def test_all_times_in_ms(self, sample_messages, sample_sessions):
        """All create_time values should be in milliseconds."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")

        for msg in messages:
            # Millisecond timestamps are much larger than second timestamps
            assert msg.create_time > 1e12, f"Time {msg.create_time} appears to be in seconds"


class TestFieldMapping:
    """Tests for camelCase to snake_case field mapping."""

    def test_local_id_mapping(self, sample_messages, sample_sessions):
        """localId should map to local_id."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")
        assert messages[0].local_id == 1

    def test_is_send_mapping(self, sample_messages, sample_sessions):
        """isSend should map to is_send (as boolean)."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")
        assert messages[0].is_send is True  # isSend=1
        assert messages[1].is_send is False  # isSend=0

    def test_sender_username_mapping(self, sample_messages, sample_sessions):
        """senderUsername should map to sender_username."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")
        assert messages[0].sender_username == "wxid_user_001"
        assert messages[1].sender_username == "wxid_ta_001"

    def test_parsed_content_mapping(self, sample_messages, sample_sessions):
        """parsedContent should map to parsed_content."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")
        assert messages[0].parsed_content == "Hello"

    def test_local_type_mapping(self, sample_messages, sample_sessions):
        """localType should map to local_type."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001")
        assert messages[0].local_type == 1


class TestPagination:
    """Tests for pagination support."""

    def test_offset_pagination(self, sample_messages, sample_sessions):
        """Should support offset-based pagination."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001", limit=2, offset=1)
        assert len(messages) == 2
        assert messages[0].local_id == 2
        assert messages[1].local_id == 3

    def test_limit(self, sample_messages, sample_sessions):
        """Should limit the number of returned messages."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        messages = ds.get_messages("wxid_test_001", limit=1)
        assert len(messages) == 1


class TestTimeRangeFilter:
    """Tests for time range filtering."""

    def test_start_ts_filter(self, sample_messages, sample_sessions):
        """Should filter by start timestamp (milliseconds)."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        # Filter from second message onward
        start_ts = 1678457460000  # Second message time in ms
        messages = ds.get_messages("wxid_test_001", start_ts=start_ts)
        assert len(messages) == 2
        assert messages[0].local_id == 2

    def test_end_ts_filter(self, sample_messages, sample_sessions):
        """Should filter by end timestamp (milliseconds)."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        # Filter up to second message
        end_ts = 1678457460000  # Second message time in ms
        messages = ds.get_messages("wxid_test_001", end_ts=end_ts)
        assert len(messages) == 2
        assert messages[1].local_id == 2


class TestListSessions:
    """Tests for list_sessions."""

    def test_returns_sessions(self, sample_messages, sample_sessions):
        """Should return sessions from fixture file."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        sessions = ds.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].username == "wxid_ta_001"
        assert sessions[0].display_name == "Test Contact"

    def test_last_timestamp_in_ms(self, sample_messages, sample_sessions):
        """lastTimestamp should be converted to milliseconds."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        sessions = ds.list_sessions()
        # Original lastTimestamp is 1678458000 seconds
        assert sessions[0].last_timestamp == 1678458000000


class TestGetContact:
    """Tests for get_contact."""

    def test_contact_found(self, sample_messages, sample_sessions):
        """Should return contact when found."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        contact = ds.get_contact("wxid_ta_001")
        assert contact is not None
        assert contact.username == "wxid_ta_001"
        assert contact.display_name == "Test Contact"

    def test_contact_not_found_fallback(self, sample_messages, sample_sessions):
        """Should return fallback contact when not found."""
        ds = JsonFileDataSource(sample_messages, sample_sessions)
        contact = ds.get_contact("wxid_unknown_999")
        assert contact is not None
        assert contact.username == "wxid_unknown_999"
        assert contact.display_name == "wxid_unknown_999"
