"""Shared utilities for converting external datasets to WeFlow JSON format."""

import json


def msg_dict(
    local_id: int,
    talker_id: str,
    create_time_s: int,
    is_send: int,
    sender: str,
    text: str,
) -> dict:
    """Return a fully-populated WeFlow message dict with null optional fields.

    Args:
        local_id: Monotonically increasing message ID (1-based).
        talker_id: The talker (contact) username — stored as talker context,
            not written into the message dict's ``talker`` field (which WeFlow
            leaves empty for individual messages).
        create_time_s: Unix timestamp in seconds.
        is_send: 1 = sent by self, 0 = received.
        sender: Sender's username.
        text: Message text content.

    Returns:
        A WeFlow-format message dict matching the canonical fixture schema.
    """
    return {
        "localId": local_id,
        "talker": "",
        "localType": 1,
        "createTime": create_time_s,
        "sortSeq": create_time_s,
        "isSend": is_send,
        "senderUsername": sender,
        "content": text,
        "rawContent": text,
        "parsedContent": text,
        "serverId": 0,
        "emojiCdnUrl": None,
        "imageMd5": None,
        "videoMd5": None,
        "xmlType": None,
        "linkTitle": None,
        "fileName": None,
        "cardNickname": None,
    }


def build_weflow_envelope(messages: list[dict], talker_id: str) -> dict:
    """Wrap message dicts into the canonical WeFlow JSON envelope.

    Args:
        messages: List of message dicts produced by :func:`msg_dict`.
        talker_id: The talker (contact) username for the top-level envelope.

    Returns:
        ``{success, talker, count, hasMore, messages[]}`` dict.
    """
    return {
        "success": True,
        "talker": talker_id,
        "count": len(messages),
        "hasMore": False,
        "messages": messages,
    }


def write_fixture_files(
    messages: list[dict],
    talker_id: str,
    display_name: str,
    messages_path: str,
    sessions_path: str,
) -> None:
    """Write messages and sessions JSON fixture files to disk.

    Args:
        messages: List of message dicts (from :func:`msg_dict`).
        talker_id: The talker (contact) username.
        display_name: Human-readable display name for the talker.
        messages_path: Output path for messages JSON.
        sessions_path: Output path for sessions JSON.
    """
    envelope = build_weflow_envelope(messages, talker_id)
    with open(messages_path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)

    last_ts = messages[-1]["createTime"] if messages else 0
    sessions_data = {
        "success": True,
        "count": 1,
        "sessions": [
            {
                "username": talker_id,
                "displayName": display_name,
                "type": 1,
                "lastTimestamp": last_ts,
                "unreadCount": 0,
            }
        ],
    }
    with open(sessions_path, "w", encoding="utf-8") as f:
        json.dump(sessions_data, f, ensure_ascii=False, indent=2)
