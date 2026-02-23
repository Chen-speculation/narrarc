"""Time hint resolution for Narrative Mirror scope-based retrieval."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def resolve_time_hint(
    conn: "sqlite3.Connection",
    talker_id: str,
    time_hint: dict,
) -> tuple[int, int]:
    """Resolve time_hint from Q1 intent to (start_ms, end_ms) for filtering.

    Args:
        conn: SQLite connection for get_time_range.
        talker_id: The conversation's talker ID.
        time_hint: Dict with optional keys:
            - start, end: ISO format strings (e.g. "2023-01-01")
            - relative: Natural language time description

    Returns:
        (start_ms, end_ms) as Unix timestamps in milliseconds.
    """
    from .db import get_time_range

    min_ms, max_ms = get_time_range(conn, talker_id)
    if min_ms == 0 and max_ms == 0:
        return (0, 0)

    min_dt = datetime.fromtimestamp(min_ms / 1000)
    max_dt = datetime.fromtimestamp(max_ms / 1000)

    # Explicit start/end
    if time_hint.get("start") and time_hint.get("end"):
        try:
            start_str = time_hint["start"]
            end_str = time_hint["end"]
            # Support ISO format with or without time
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            # Strip tzinfo for comparison with naive timestamps
            if start_dt.tzinfo:
                start_dt = start_dt.replace(tzinfo=None)
            if end_dt.tzinfo:
                end_dt = end_dt.replace(tzinfo=None)
            return (
                int(start_dt.timestamp() * 1000),
                int(end_dt.timestamp() * 1000),
            )
        except (ValueError, TypeError):
            pass

    relative = (time_hint.get("relative") or "").strip()
    if not relative:
        return (min_ms, max_ms)

    # 早期
    early_kw = ["刚认识", "最初", "一开始", "刚入职", "刚开学", "开题前", "刚来"]
    if any(k in relative for k in early_kw):
        span = (max_dt - min_dt) * 0.15
        end_dt = min_dt + span
        return (
            int(min_dt.timestamp() * 1000),
            int(end_dt.timestamp() * 1000),
        )

    # 近期
    if "最近" in relative:
        m = re.search(r"(\d+)\s*个?月", relative)
        months = int(m.group(1)) if m else 3
        start_dt = max_dt - timedelta(days=months * 30)
        return (
            int(start_dt.timestamp() * 1000),
            int(max_dt.timestamp() * 1000),
        )

    # 季度
    quarter_map = {"上个季度": 1, "上上个季度": 2, "这个季度": 0}
    for label, offset in quarter_map.items():
        if label in relative:
            q_end = max_dt - timedelta(days=offset * 90)
            q_start = q_end - timedelta(days=90)
            return (
                int(q_start.timestamp() * 1000),
                int(q_end.timestamp() * 1000),
            )

    # 年份
    m = re.search(r"(20\d{2})\s*年", relative)
    if m:
        year = int(m.group(1))
        start_dt = datetime(year, 1, 1)
        end_dt = datetime(year, 12, 31, 23, 59, 59)
        return (
            int(start_dt.timestamp() * 1000),
            int(end_dt.timestamp() * 1000),
        )

    # 月份："去年7月"、"今年3月"
    m = re.search(r"(?:去年|今年|前年)?\s*(\d{1,2})\s*月", relative)
    if m:
        month = int(m.group(1))
        year = max_dt.year
        if "去年" in relative:
            year -= 1
        elif "前年" in relative:
            year -= 2
        start_dt = datetime(year, month, 1)
        if month == 12:
            end_dt = datetime(year + 1, 1, 1) - timedelta(microseconds=1)
        else:
            end_dt = datetime(year, month + 1, 1) - timedelta(microseconds=1)
        return (
            int(start_dt.timestamp() * 1000),
            int(end_dt.timestamp() * 1000),
        )

    return (min_ms, max_ms)
