"""Data source layer for Narrative Mirror."""

import json
import sys
from typing import Protocol, Optional
from datetime import datetime
from pathlib import Path

import httpx

from .models import RawMessage, Session, Contact


class DataSourceError(Exception):
    """Exception raised when data source operations fail."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        self.message = message
        self.cause = cause
        super().__init__(message)


class ChatDataSource(Protocol):
    """Protocol for chat data sources."""

    def list_sessions(self) -> list[Session]:
        """List all available chat sessions.

        Returns:
            List of Session objects.
        """
        ...

    def get_messages(
        self,
        talker_id: str,
        limit: int = 100,
        offset: int = 0,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> list[RawMessage]:
        """Get messages for a specific conversation.

        Args:
            talker_id: The conversation's talker ID.
            limit: Maximum number of messages to return.
            offset: Number of messages to skip (for pagination).
            start_ts: Optional start timestamp filter (milliseconds).
            end_ts: Optional end timestamp filter (milliseconds).

        Returns:
            List of RawMessage objects, sorted by create_time ascending.
        """
        ...

    def get_contact(self, username: str) -> Optional[Contact]:
        """Get contact information for a username.

        Args:
            username: The contact's username.

        Returns:
            Contact object or None if not found.
        """
        ...


class MockDataSource:
    """Mock data source with the 20-message demo conversation from init.md."""

    def __init__(self):
        self._talker_id = "mock_talker_001"
        self._user_username = "user_self"
        self._ta_username = "ta_partner"
        self._ta_display_name = "TA"

        # Build the 20-message demo conversation
        # Timestamps are in milliseconds
        self._messages = self._build_demo_messages()

    def _build_demo_messages(self) -> list[RawMessage]:
        """Build the 20-message demo conversation from init.md."""
        messages = []

        # Helper to create timestamp from date string
        def ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
            dt = datetime(year, month, day, hour, minute)
            return int(dt.timestamp() * 1000)

        talker_id = self._talker_id
        user = self._user_username
        ta = self._ta_username

        # Burst A: 2023.03.10 22:10-23:02 (msg_001-008)
        messages.extend([
            RawMessage(1, talker_id, ts(2023, 3, 10, 22, 10), True, user, "今天好累，被老板骂了一顿", 1, False),
            RawMessage(2, talker_id, ts(2023, 3, 10, 22, 11), False, ta, "宝贝！怎么了，说来听听", 1, False),
            RawMessage(3, talker_id, ts(2023, 3, 10, 22, 35), True, user, "就说我报告数据不对，其实是他自己改了需求", 1, False),
            RawMessage(4, talker_id, ts(2023, 3, 10, 22, 36), False, ta, "气死我了！你已经很厉害了，不用理他", 1, False),
            RawMessage(5, talker_id, ts(2023, 3, 10, 22, 37), False, ta, "周末去吃你最喜欢的火锅？", 1, False),
            RawMessage(6, talker_id, ts(2023, 3, 10, 22, 38), True, user, "好呀好呀！爱你", 1, False),
            RawMessage(7, talker_id, ts(2023, 3, 10, 23, 1), False, ta, "晚安宝贝❤", 1, False),
            RawMessage(8, talker_id, ts(2023, 3, 10, 23, 2), True, user, "晚安❤", 1, False),
        ])

        # Burst B: 2023.06.05 23:41 - 2023.06.06 09:20 (msg_009-012)
        messages.extend([
            RawMessage(9, talker_id, ts(2023, 6, 5, 23, 41), True, user, "今天老板又骂我了，一整天都在加班", 1, False),
            RawMessage(10, talker_id, ts(2023, 6, 6, 2, 43), False, ta, "哦", 1, False),  # 3 hours later
            RawMessage(11, talker_id, ts(2023, 6, 6, 9, 15), True, user, "你昨晚睡了？", 1, False),
            RawMessage(12, talker_id, ts(2023, 6, 6, 9, 20), False, ta, "嗯，困了", 1, False),
        ])

        # Burst C: 2023.09.15 20:00-20:17 (msg_013-018)
        messages.extend([
            RawMessage(13, talker_id, ts(2023, 9, 15, 20, 0), True, user, "你最近是不是不想理我", 1, False),
            RawMessage(14, talker_id, ts(2023, 9, 15, 20, 5), False, ta, "没有，就是最近压力大", 1, False),
            RawMessage(15, talker_id, ts(2023, 9, 15, 20, 6), True, user, "你压力大我理解，但你有没有想过我也需要你", 1, False),
            RawMessage(16, talker_id, ts(2023, 9, 15, 20, 15), False, ta, "好了好了，我知道了", 1, False),  # 9 min later
            RawMessage(17, talker_id, ts(2023, 9, 15, 20, 16), True, user, "你能不能好好说话", 1, False),
            RawMessage(18, talker_id, ts(2023, 9, 15, 20, 17), False, ta, "我真的很累", 1, False),
        ])

        # Burst D: 2023.12.20 (msg_019)
        messages.append(
            RawMessage(19, talker_id, ts(2023, 12, 20, 23, 55), True, user, "晚安", 1, False)
        )

        # Burst E: 2024.02.14 (msg_020)
        messages.append(
            RawMessage(20, talker_id, ts(2024, 2, 14, 21, 0), True, user, "我们谈谈吧", 1, False)
        )

        return messages

    def list_sessions(self) -> list[Session]:
        """Return the mock session."""
        return [
            Session(
                username=self._talker_id,
                display_name=self._ta_display_name,
                last_timestamp=self._messages[-1].create_time,
            )
        ]

    def get_messages(
        self,
        talker_id: str,
        limit: int = 100,
        offset: int = 0,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> list[RawMessage]:
        """Get messages for the mock conversation.

        Args:
            talker_id: The conversation's talker ID (ignored in mock).
            limit: Maximum number of messages to return.
            offset: Number of messages to skip (for pagination).
            start_ts: Optional start timestamp filter (milliseconds).
            end_ts: Optional end timestamp filter (milliseconds).

        Returns:
            List of RawMessage objects, sorted by create_time ascending.
        """
        # Filter by time range if specified
        filtered = self._messages
        if start_ts is not None:
            filtered = [m for m in filtered if m.create_time >= start_ts]
        if end_ts is not None:
            filtered = [m for m in filtered if m.create_time <= end_ts]

        # Apply pagination
        paginated = filtered[offset:offset + limit]
        return paginated

    def get_contact(self, username: str) -> Optional[Contact]:
        """Get contact information for a username.

        Args:
            username: The contact's username.

        Returns:
            Contact object or None if not found.
        """
        if username == self._ta_username:
            return Contact(username=self._ta_username, display_name=self._ta_display_name)
        if username == self._user_username:
            return Contact(username=self._user_username, display_name="我")
        return None


class WeFlowDataSource:
    """Data source that connects to WeFlow's local HTTP API."""

    def __init__(self, base_url: str = "http://localhost:5031"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=30.0)

        # Check connection on construction
        try:
            response = self._client.get("/api/v1/sessions")
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise DataSourceError(
                f"Cannot connect to WeFlow at {self.base_url}. "
                f"Please ensure WeFlow is running with HTTP server enabled on port 5031. "
                f"Error: {e}",
                cause=e,
            )

    def list_sessions(self) -> list[Session]:
        """List all available chat sessions from WeFlow.

        Returns:
            List of Session objects.
        """
        try:
            response = self._client.get("/api/v1/sessions")
            response.raise_for_status()
            data = response.json()

            sessions = []
            for item in data.get("sessions", []):
                sessions.append(Session(
                    username=item.get("username", ""),
                    display_name=item.get("displayName", item.get("username", "")),
                    last_timestamp=item.get("lastTimestamp", 0),
                ))
            return sessions
        except httpx.HTTPError as e:
            raise DataSourceError(f"Failed to list sessions: {e}", cause=e)

    def get_messages(
        self,
        talker_id: str,
        limit: int = 100,
        offset: int = 0,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> list[RawMessage]:
        """Get messages for a specific conversation with pagination.

        Implements paginated fetching: repeatedly calls the API with increasing
        offset until fewer than `limit` records are returned.

        Args:
            talker_id: The conversation's talker ID.
            limit: Maximum number of messages per batch.
            offset: Starting offset (for manual pagination).
            start_ts: Optional start timestamp filter (milliseconds).
            end_ts: Optional end timestamp filter (milliseconds).

        Returns:
            List of RawMessage objects, sorted by create_time ascending.
        """
        all_messages = []
        current_offset = offset
        batch_size = limit

        while True:
            try:
                params = {
                    "talkerId": talker_id,
                    "limit": batch_size,
                    "offset": current_offset,
                }
                if start_ts is not None:
                    params["startTs"] = start_ts
                if end_ts is not None:
                    params["endTs"] = end_ts

                response = self._client.get("/api/v1/messages", params=params)
                response.raise_for_status()
                data = response.json()

                batch = data.get("messages", [])
                if not batch:
                    break

                for item in batch:
                    local_type = item.get("localType", 1)
                    excluded = local_type in (10000, 10002)  # System/forwarded messages

                    all_messages.append(RawMessage(
                        local_id=item.get("localId", 0),
                        talker_id=talker_id,
                        create_time=item.get("createTime", 0),
                        is_send=item.get("isSend", 0) == 1,
                        sender_username=item.get("senderUsername", ""),
                        parsed_content=item.get("parsedContent", ""),
                        local_type=local_type,
                        excluded=excluded,
                    ))

                # If we got fewer than requested, we've reached the end
                if len(batch) < batch_size:
                    break

                current_offset += batch_size

            except httpx.HTTPError as e:
                raise DataSourceError(f"Failed to get messages: {e}", cause=e)

        # Sort by create_time ascending
        all_messages.sort(key=lambda m: m.create_time)
        return all_messages

    def get_contact(self, username: str) -> Optional[Contact]:
        """Get contact information for a username.

        Args:
            username: The contact's username.

        Returns:
            Contact object or None if not found.
        """
        try:
            response = self._client.get(f"/api/v1/contacts/{username}")
            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            return Contact(
                username=data.get("username", username),
                display_name=data.get("displayName", username),
            )
        except httpx.HTTPError as e:
            raise DataSourceError(f"Failed to get contact: {e}", cause=e)

    def __del__(self):
        """Clean up the HTTP client."""
        if hasattr(self, "_client"):
            self._client.close()


class JsonFileDataSource:
    """Data source that reads WeFlow-format JSON files."""

    def __init__(self, messages_path: str, sessions_path: str):
        """Initialize with paths to JSON fixture files.

        Args:
            messages_path: Path to the messages JSON file.
            sessions_path: Path to the sessions JSON file.

        Raises:
            DataSourceError: If files cannot be read or are not valid JSON.
        """
        self._messages: list[RawMessage] = []
        self._sessions: list[Session] = []
        self._talker_id: str = ""
        self._contacts: dict[str, Contact] = {}

        # Load messages file
        try:
            messages_path_obj = Path(messages_path)
            if not messages_path_obj.exists():
                raise DataSourceError(f"Messages file not found: {messages_path}")

            with open(messages_path_obj, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._talker_id = data.get("talker", "")

            for item in data.get("messages", []):
                # Convert createTime from seconds to milliseconds
                create_time_ms = item.get("createTime", 0) * 1000

                # Map camelCase to snake_case
                self._messages.append(RawMessage(
                    local_id=item.get("localId", 0),
                    talker_id=self._talker_id,
                    create_time=create_time_ms,
                    is_send=item.get("isSend", 0) == 1,
                    sender_username=item.get("senderUsername", ""),
                    parsed_content=item.get("parsedContent", ""),
                    local_type=item.get("localType", 1),
                    excluded=False,
                ))

        except json.JSONDecodeError as e:
            raise DataSourceError(f"Invalid JSON in messages file: {messages_path}", cause=e)
        except Exception as e:
            if isinstance(e, DataSourceError):
                raise
            raise DataSourceError(f"Failed to load messages file: {messages_path}", cause=e)

        # Load sessions file
        try:
            sessions_path_obj = Path(sessions_path)
            if not sessions_path_obj.exists():
                raise DataSourceError(f"Sessions file not found: {sessions_path}")

            with open(sessions_path_obj, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data.get("sessions", []):
                username = item.get("username", "")
                display_name = item.get("displayName", username)
                last_timestamp_ms = item.get("lastTimestamp", 0) * 1000

                self._sessions.append(Session(
                    username=username,
                    display_name=display_name,
                    last_timestamp=last_timestamp_ms,
                ))

                # Build contact lookup
                self._contacts[username] = Contact(
                    username=username,
                    display_name=display_name,
                )

        except json.JSONDecodeError as e:
            raise DataSourceError(f"Invalid JSON in sessions file: {sessions_path}", cause=e)
        except Exception as e:
            if isinstance(e, DataSourceError):
                raise
            raise DataSourceError(f"Failed to load sessions file: {sessions_path}", cause=e)

    def list_sessions(self) -> list[Session]:
        """Return sessions from the sessions fixture file.

        Returns:
            List of Session objects.
        """
        return self._sessions

    def get_messages(
        self,
        talker_id: str,
        limit: int = 100,
        offset: int = 0,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> list[RawMessage]:
        """Get messages for a specific conversation with pagination.

        Args:
            talker_id: The conversation's talker ID.
            limit: Maximum number of messages to return.
            offset: Number of messages to skip (for pagination).
            start_ts: Optional start timestamp filter (milliseconds).
            end_ts: Optional end timestamp filter (milliseconds).

        Returns:
            List of RawMessage objects, sorted by create_time ascending.
        """
        # Filter by time range if specified
        filtered = self._messages
        if start_ts is not None:
            filtered = [m for m in filtered if m.create_time >= start_ts]
        if end_ts is not None:
            filtered = [m for m in filtered if m.create_time <= end_ts]

        # Apply pagination
        paginated = filtered[offset:offset + limit]
        return paginated

    def get_contact(self, username: str) -> Optional[Contact]:
        """Get contact information for a username.

        Performs a best-effort lookup from the sessions list.
        Returns a Contact with display_name = username if not found.

        Args:
            username: The contact's username.

        Returns:
            Contact object (always returns a Contact, never None).
        """
        if username in self._contacts:
            return self._contacts[username]

        # Fallback: return a Contact with username as display_name
        return Contact(username=username, display_name=username)


def get_data_source(
    source: str = "mock",
    weflow_base_url: str = "http://localhost:5031",
    messages_path: Optional[str] = None,
    sessions_path: Optional[str] = None,
) -> ChatDataSource:
    """Get a data source by name.

    Args:
        source: Data source name ("mock", "weflow", or "file").
        weflow_base_url: WeFlow base URL (used when source="weflow").
        messages_path: Path to messages JSON file (used when source="file").
        sessions_path: Path to sessions JSON file (used when source="file").

    Returns:
        A ChatDataSource instance.

    Raises:
        ValueError: If source is unknown or required arguments are missing.
    """
    if source == "mock":
        return MockDataSource()
    elif source == "weflow":
        return WeFlowDataSource(base_url=weflow_base_url)
    elif source == "file":
        if not messages_path:
            raise ValueError("messages_path is required when source='file'")
        if not sessions_path:
            raise ValueError("sessions_path is required when source='file'")
        return JsonFileDataSource(messages_path, sessions_path)
    else:
        raise ValueError(f"Unknown data source: {source}")


def main():
    """CLI helper for listing sessions."""
    import argparse

    parser = argparse.ArgumentParser(description="List available chat sessions")
    parser.add_argument(
        "--source",
        choices=["mock", "weflow"],
        default="mock",
        help="Data source to use (default: mock)",
    )
    parser.add_argument(
        "--weflow-url",
        default="http://localhost:5031",
        help="WeFlow base URL (default: http://localhost:5031)",
    )
    args = parser.parse_args()

    try:
        ds = get_data_source(args.source, args.weflow_url)
        sessions = ds.list_sessions()

        print(f"Found {len(sessions)} session(s):")
        for session in sessions:
            print(f"  {session.username}: {session.display_name}")

    except DataSourceError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
