"""Unit tests for MockDataSource."""

import pytest

from narrative_mirror.datasource import MockDataSource


class TestMockDataSource:
    """Tests for MockDataSource."""

    def test_session_count(self):
        """MockDataSource should return exactly 1 session."""
        ds = MockDataSource()
        sessions = ds.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].username == "mock_talker_001"

    def test_message_count(self):
        """MockDataSource should return 20 messages total."""
        ds = MockDataSource()
        messages = ds.get_messages("mock_talker_001")
        assert len(messages) == 20

    def test_pagination(self):
        """Pagination should work correctly."""
        ds = MockDataSource()
        talker_id = "mock_talker_001"

        # Get first 5 messages
        batch1 = ds.get_messages(talker_id, limit=5, offset=0)
        assert len(batch1) == 5

        # Get next 5 messages
        batch2 = ds.get_messages(talker_id, limit=5, offset=5)
        assert len(batch2) == 5

        # Verify no overlap
        ids1 = {m.local_id for m in batch1}
        ids2 = {m.local_id for m in batch2}
        assert ids1.isdisjoint(ids2)

        # Get from offset 10 with limit 5 should give 5 messages starting from 11th
        batch3 = ds.get_messages(talker_id, limit=5, offset=10)
        assert len(batch3) == 5
        assert batch3[0].local_id == 11

    def test_time_ordering(self):
        """Messages should be returned in ascending create_time order."""
        ds = MockDataSource()
        messages = ds.get_messages("mock_talker_001")

        timestamps = [m.create_time for m in messages]
        assert timestamps == sorted(timestamps)

    def test_time_range_filter(self):
        """Time range filters should work correctly."""
        ds = MockDataSource()
        talker_id = "mock_talker_001"

        # Get messages from March 2023 only (msg_001-008)
        # 2023-03-01 00:00:00 to 2023-04-01 00:00:00
        import datetime
        start_ts = int(datetime.datetime(2023, 3, 1).timestamp() * 1000)
        end_ts = int(datetime.datetime(2023, 4, 1).timestamp() * 1000)

        messages = ds.get_messages(talker_id, start_ts=start_ts, end_ts=end_ts)
        assert len(messages) == 8
        assert messages[0].local_id == 1
        assert messages[-1].local_id == 8

    def test_get_contact_ta(self):
        """Should return contact for TA."""
        ds = MockDataSource()
        contact = ds.get_contact("ta_partner")
        assert contact is not None
        assert contact.display_name == "TA"

    def test_get_contact_user(self):
        """Should return contact for user."""
        ds = MockDataSource()
        contact = ds.get_contact("user_self")
        assert contact is not None
        assert contact.display_name == "我"

    def test_get_contact_unknown(self):
        """Should return None for unknown contact."""
        ds = MockDataSource()
        contact = ds.get_contact("unknown_user")
        assert contact is None

    def test_message_content(self):
        """Messages should have correct content."""
        ds = MockDataSource()
        messages = ds.get_messages("mock_talker_001")

        # Check first message
        assert messages[0].local_id == 1
        assert messages[0].is_send is True  # User sent
        assert "老板" in messages[0].parsed_content

        # Check second message (TA's response)
        assert messages[1].local_id == 2
        assert messages[1].is_send is False  # TA sent
        assert "宝贝" in messages[1].parsed_content

    def test_burst_gap_detection(self):
        """Messages should show expected burst gaps for aggregation testing."""
        ds = MockDataSource()
        messages = ds.get_messages("mock_talker_001")

        # Gap between msg_008 (23:02) and msg_009 (23:41 on different day)
        # This is a large gap (months), should trigger new burst
        gap_ms = messages[8].create_time - messages[7].create_time
        gap_seconds = gap_ms / 1000
        # Should be approximately 87 days in seconds
        assert gap_seconds > 1800  # More than 30 minutes

        # Gap between msg_004 (22:36) and msg_005 (22:37) should be small
        small_gap_ms = messages[4].create_time - messages[3].create_time
        small_gap_seconds = small_gap_ms / 1000
        assert small_gap_seconds <= 60  # Less than or equal to 1 minute
