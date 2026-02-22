"""Database layer for Narrative Mirror - SQLite schema and access helpers."""

import sqlite3
from datetime import datetime
from typing import Optional
import uuid

from .models import (
    RawMessage,
    Burst,
    TopicNode,
    MetadataSignals,
    AnomalyAnchor,
)


def init_db(path: str) -> sqlite3.Connection:
    """Initialize the SQLite database with all required tables.

    Creates tables for:
    - raw_messages: Original messages from data source
    - bursts: Aggregated message bursts
    - topic_nodes: Layer 1 topic nodes
    - node_metadata: Layer 1.5 metadata signals
    - anomaly_anchors: Detected anomaly anchors
    - semantic_thread_pointers: Layer 2 thread links

    Args:
        path: Path to the SQLite database file.

    Returns:
        A sqlite3.Connection object.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode so concurrent reads (get_messages, list_sessions) can proceed
    # while build holds a write transaction (one writer + multiple readers)
    conn.execute("PRAGMA journal_mode=WAL")
    # Wait up to 60s on lock instead of blocking indefinitely (SQLITE_BUSY)
    conn.execute("PRAGMA busy_timeout=60000")

    cursor = conn.cursor()

    # Raw messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_messages (
            local_id INTEGER NOT NULL,
            talker_id TEXT NOT NULL,
            create_time INTEGER NOT NULL,
            is_send INTEGER NOT NULL,
            sender_username TEXT NOT NULL,
            parsed_content TEXT,
            local_type INTEGER NOT NULL,
            excluded INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (talker_id, local_id)
        )
    """)

    # Create index for time-based queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_messages_create_time
        ON raw_messages(talker_id, create_time)
    """)

    # Bursts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bursts (
            burst_id TEXT PRIMARY KEY,
            talker_id TEXT NOT NULL,
            start_local_id INTEGER NOT NULL,
            end_local_id INTEGER NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            message_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Create index for talker_id queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_bursts_talker_id
        ON bursts(talker_id)
    """)

    # Topic nodes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_nodes (
            node_id TEXT PRIMARY KEY,
            talker_id TEXT NOT NULL,
            burst_id TEXT NOT NULL,
            topic_name TEXT NOT NULL,
            start_local_id INTEGER NOT NULL,
            end_local_id INTEGER NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            parent_node_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(talker_id, node_id)
        )
    """)

    # Create indexes for topic_nodes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_topic_nodes_talker_id
        ON topic_nodes(talker_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_topic_nodes_burst_id
        ON topic_nodes(burst_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_topic_nodes_start_time
        ON topic_nodes(talker_id, start_time)
    """)

    # Node metadata table (Layer 1.5 signals)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS node_metadata (
            node_id TEXT PRIMARY KEY,
            talker_id TEXT NOT NULL,
            reply_delay_avg_s REAL NOT NULL DEFAULT 0.0,
            reply_delay_max_s REAL NOT NULL DEFAULT 0.0,
            term_shift_score REAL NOT NULL DEFAULT 0.0,
            silence_event INTEGER NOT NULL DEFAULT 0,
            topic_frequency INTEGER NOT NULL DEFAULT 0,
            initiator_ratio REAL NOT NULL DEFAULT 0.0,
            emotional_tone REAL NOT NULL DEFAULT 0.0,
            conflict_intensity REAL NOT NULL DEFAULT 0.0
        )
    """)

    # Create index for node_metadata
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_node_metadata_talker_id
        ON node_metadata(talker_id)
    """)

    # Anomaly anchors table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anomaly_anchors (
            anchor_id TEXT PRIMARY KEY,
            talker_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            signal_name TEXT NOT NULL,
            signal_value REAL NOT NULL,
            baseline_mean REAL NOT NULL,
            baseline_std REAL NOT NULL,
            event_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Create indexes for anomaly_anchors
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anomaly_anchors_talker_id
        ON anomaly_anchors(talker_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anomaly_anchors_signal_name
        ON anomaly_anchors(talker_id, signal_name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_anomaly_anchors_event_date
        ON anomaly_anchors(talker_id, event_date)
    """)

    # Semantic thread pointers table (Layer 2)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS semantic_thread_pointers (
            pointer_id TEXT PRIMARY KEY,
            talker_id TEXT NOT NULL,
            from_node_id TEXT NOT NULL,
            to_node_id TEXT NOT NULL,
            link_reason TEXT,
            similarity_score REAL,
            created_at TEXT NOT NULL
        )
    """)

    # Create indexes for semantic_thread_pointers
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_semantic_thread_pointers_talker_id
        ON semantic_thread_pointers(talker_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_semantic_thread_pointers_from_node_id
        ON semantic_thread_pointers(from_node_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_semantic_thread_pointers_to_node_id
        ON semantic_thread_pointers(to_node_id)
    """)

    # Build progress (for UI: current stage/step when build is running)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS build_progress (
            talker_id TEXT PRIMARY KEY,
            stage TEXT NOT NULL,
            step TEXT NOT NULL,
            detail TEXT,
            updated_at TEXT NOT NULL
        )
    """)

    conn.commit()
    return conn


def upsert_messages(conn: sqlite3.Connection, messages: list[RawMessage]) -> int:
    """Upsert messages into the raw_messages table with ignore-on-conflict semantics.

    Args:
        conn: SQLite connection.
        messages: List of RawMessage objects to upsert.

    Returns:
        Number of rows inserted (not counting ignored duplicates).
    """
    cursor = conn.cursor()
    inserted = 0

    for msg in messages:
        try:
            cursor.execute("""
                INSERT INTO raw_messages
                (local_id, talker_id, create_time, is_send, sender_username,
                 parsed_content, local_type, excluded)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg.local_id,
                msg.talker_id,
                msg.create_time,
                1 if msg.is_send else 0,
                msg.sender_username,
                msg.parsed_content,
                msg.local_type,
                1 if msg.excluded else 0,
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            # Duplicate - ignore
            pass

    conn.commit()
    return inserted


def upsert_burst(conn: sqlite3.Connection, burst: Burst) -> None:
    """Upsert a burst into the bursts table.

    Args:
        conn: SQLite connection.
        burst: Burst object to upsert.
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO bursts
        (burst_id, talker_id, start_local_id, end_local_id, start_time, end_time,
         message_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        burst.burst_id,
        burst.talker_id,
        burst.messages[0].local_id if burst.messages else 0,
        burst.messages[-1].local_id if burst.messages else 0,
        burst.start_time,
        burst.end_time,
        len(burst.messages),
        datetime.utcnow().isoformat(),
    ))
    conn.commit()


def upsert_node(conn: sqlite3.Connection, node: TopicNode) -> None:
    """Upsert a topic node into the topic_nodes table.

    Args:
        conn: SQLite connection.
        node: TopicNode object to upsert.
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO topic_nodes
        (node_id, talker_id, burst_id, topic_name, start_local_id, end_local_id,
         start_time, end_time, parent_node_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        node.node_id,
        node.talker_id,
        node.burst_id,
        node.topic_name,
        node.start_local_id,
        node.end_local_id,
        node.start_time,
        node.end_time,
        node.parent_node_id,
        datetime.utcnow().isoformat(),
    ))
    conn.commit()


def upsert_metadata(conn: sqlite3.Connection, signals: MetadataSignals) -> None:
    """Upsert metadata signals into the node_metadata table.

    Args:
        conn: SQLite connection.
        signals: MetadataSignals object to upsert.
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO node_metadata
        (node_id, talker_id, reply_delay_avg_s, reply_delay_max_s, term_shift_score,
         silence_event, topic_frequency, initiator_ratio, emotional_tone, conflict_intensity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        signals.node_id,
        signals.talker_id,
        signals.reply_delay_avg_s,
        signals.reply_delay_max_s,
        signals.term_shift_score,
        1 if signals.silence_event else 0,
        signals.topic_frequency,
        signals.initiator_ratio,
        signals.emotional_tone,
        signals.conflict_intensity,
    ))
    conn.commit()


def upsert_anchors(conn: sqlite3.Connection, anchors: list[AnomalyAnchor]) -> None:
    """Upsert anomaly anchors into the anomaly_anchors table.

    Args:
        conn: SQLite connection.
        anchors: List of AnomalyAnchor objects to upsert.
    """
    cursor = conn.cursor()
    for anchor in anchors:
        cursor.execute("""
            INSERT OR REPLACE INTO anomaly_anchors
            (anchor_id, talker_id, node_id, signal_name, signal_value,
             baseline_mean, baseline_std, event_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            anchor.anchor_id,
            anchor.talker_id,
            anchor.node_id,
            anchor.signal_name,
            anchor.signal_value,
            anchor.baseline_mean,
            anchor.baseline_std,
            anchor.event_date,
            datetime.utcnow().isoformat(),
        ))
    conn.commit()


def upsert_pointer(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
    talker_id: str,
    reason: str,
    score: float,
) -> None:
    """Upsert a semantic thread pointer for Layer 2 thread links.

    Args:
        conn: SQLite connection.
        from_id: Source node ID.
        to_id: Target node ID.
        talker_id: The conversation's talker ID.
        reason: Reason for the link (from LLM).
        score: Similarity score from Stage 1.
    """
    cursor = conn.cursor()
    pointer_id = str(uuid.uuid4())
    cursor.execute("""
        INSERT OR REPLACE INTO semantic_thread_pointers
        (pointer_id, talker_id, from_node_id, to_node_id, link_reason, similarity_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        pointer_id,
        talker_id,
        from_id,
        to_id,
        reason,
        score,
        datetime.utcnow().isoformat(),
    ))
    conn.commit()


def get_nodes(conn: sqlite3.Connection, talker_id: str) -> list[TopicNode]:
    """Get all topic nodes for a conversation.

    Args:
        conn: SQLite connection.
        talker_id: The conversation's talker ID.

    Returns:
        List of TopicNode objects, sorted by start_time ascending.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT node_id, talker_id, burst_id, topic_name, start_local_id, end_local_id,
               start_time, end_time, parent_node_id
        FROM topic_nodes
        WHERE talker_id = ?
        ORDER BY start_time ASC
    """, (talker_id,))

    nodes = []
    for row in cursor.fetchall():
        nodes.append(TopicNode(
            node_id=row[0],
            talker_id=row[1],
            burst_id=row[2],
            topic_name=row[3],
            start_local_id=row[4],
            end_local_id=row[5],
            start_time=row[6],
            end_time=row[7],
            parent_node_id=row[8],
        ))
    return nodes


def get_anchors(
    conn: sqlite3.Connection,
    talker_id: str,
    signals: Optional[list[str]] = None,
    time_range: Optional[str] = None,
) -> list[AnomalyAnchor]:
    """Get anomaly anchors for a conversation, optionally filtered by signals.

    Args:
        conn: SQLite connection.
        talker_id: The conversation's talker ID.
        signals: Optional list of signal names to filter by.
        time_range: Optional time range filter (e.g., "2023-06").

    Returns:
        List of AnomalyAnchor objects, sorted by event_date ascending.
    """
    cursor = conn.cursor()

    query = """
        SELECT anchor_id, talker_id, node_id, signal_name, signal_value,
               baseline_mean, baseline_std, event_date
        FROM anomaly_anchors
        WHERE talker_id = ?
    """
    params: list = [talker_id]

    if signals:
        placeholders = ", ".join("?" * len(signals))
        query += f" AND signal_name IN ({placeholders})"
        params.extend(signals)

    if time_range:
        query += " AND event_date LIKE ?"
        params.append(f"{time_range}%")

    query += " ORDER BY event_date ASC"

    cursor.execute(query, params)

    anchors = []
    for row in cursor.fetchall():
        anchors.append(AnomalyAnchor(
            anchor_id=row[0],
            talker_id=row[1],
            node_id=row[2],
            signal_name=row[3],
            signal_value=row[4],
            baseline_mean=row[5],
            baseline_std=row[6],
            event_date=row[7],
        ))
    return anchors


def get_messages_by_ids(
    conn: sqlite3.Connection,
    talker_id: str,
    local_ids: list[int],
) -> list[RawMessage]:
    """Get messages by their local IDs for Q4 evidence verification.

    Args:
        conn: SQLite connection.
        talker_id: The conversation's talker ID.
        local_ids: List of local_id values to fetch.

    Returns:
        List of RawMessage objects.
    """
    if not local_ids:
        return []

    cursor = conn.cursor()
    placeholders = ", ".join("?" * len(local_ids))
    cursor.execute(f"""
        SELECT local_id, talker_id, create_time, is_send, sender_username,
               parsed_content, local_type, excluded
        FROM raw_messages
        WHERE talker_id = ? AND local_id IN ({placeholders})
        ORDER BY create_time ASC
    """, [talker_id] + local_ids)

    messages = []
    for row in cursor.fetchall():
        messages.append(RawMessage(
            local_id=row[0],
            talker_id=row[1],
            create_time=row[2],
            is_send=bool(row[3]),
            sender_username=row[4],
            parsed_content=row[5] or "",
            local_type=row[6],
            excluded=bool(row[7]),
        ))
    return messages


def get_all_messages(
    conn: sqlite3.Connection,
    talker_id: str,
    excluded: bool = False,
) -> list[RawMessage]:
    """Get all messages for a conversation.

    Args:
        conn: SQLite connection.
        talker_id: The conversation's talker ID.
        excluded: If True, include excluded messages (system/forwarded).

    Returns:
        List of RawMessage objects, sorted by create_time ascending.
    """
    cursor = conn.cursor()

    if excluded:
        cursor.execute("""
            SELECT local_id, talker_id, create_time, is_send, sender_username,
                   parsed_content, local_type, excluded
            FROM raw_messages
            WHERE talker_id = ?
            ORDER BY create_time ASC
        """, (talker_id,))
    else:
        cursor.execute("""
            SELECT local_id, talker_id, create_time, is_send, sender_username,
                   parsed_content, local_type, excluded
            FROM raw_messages
            WHERE talker_id = ? AND excluded = 0
            ORDER BY create_time ASC
        """, (talker_id,))

    messages = []
    for row in cursor.fetchall():
        messages.append(RawMessage(
            local_id=row[0],
            talker_id=row[1],
            create_time=row[2],
            is_send=bool(row[3]),
            sender_username=row[4],
            parsed_content=row[5] or "",
            local_type=row[6],
            excluded=bool(row[7]),
        ))
    return messages


def get_existing_pointer(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
) -> bool:
    """Check if a pointer already exists between two nodes.

    Args:
        conn: SQLite connection.
        from_id: Source node ID.
        to_id: Target node ID.

    Returns:
        True if pointer exists, False otherwise.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 1 FROM semantic_thread_pointers
        WHERE from_node_id = ? AND to_node_id = ?
    """, (from_id, to_id))
    return cursor.fetchone() is not None


def get_node_by_burst(conn: sqlite3.Connection, burst_id: str) -> list[TopicNode]:
    """Get topic nodes by burst ID.

    Args:
        conn: SQLite connection.
        burst_id: The burst ID to look up.

    Returns:
        List of TopicNode objects for the burst.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT node_id, talker_id, burst_id, topic_name, start_local_id, end_local_id,
               start_time, end_time, parent_node_id
        FROM topic_nodes
        WHERE burst_id = ?
    """, (burst_id,))

    nodes = []
    for row in cursor.fetchall():
        nodes.append(TopicNode(
            node_id=row[0],
            talker_id=row[1],
            burst_id=row[2],
            topic_name=row[3],
            start_local_id=row[4],
            end_local_id=row[5],
            start_time=row[6],
            end_time=row[7],
            parent_node_id=row[8],
        ))
    return nodes


def get_metadata_by_node(conn: sqlite3.Connection, node_id: str) -> Optional[MetadataSignals]:
    """Get metadata signals for a specific node.

    Args:
        conn: SQLite connection.
        node_id: The node ID to look up.

    Returns:
        MetadataSignals object or None if not found.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT node_id, talker_id, reply_delay_avg_s, reply_delay_max_s, term_shift_score,
               silence_event, topic_frequency, initiator_ratio, emotional_tone, conflict_intensity
        FROM node_metadata
        WHERE node_id = ?
    """, (node_id,))

    row = cursor.fetchone()
    if row is None:
        return None

    return MetadataSignals(
        node_id=row[0],
        talker_id=row[1],
        reply_delay_avg_s=row[2],
        reply_delay_max_s=row[3],
        term_shift_score=row[4],
        silence_event=bool(row[5]),
        topic_frequency=row[6],
        initiator_ratio=row[7],
        emotional_tone=row[8],
        conflict_intensity=row[9],
    )


def get_all_metadata(conn: sqlite3.Connection, talker_id: str) -> list[MetadataSignals]:
    """Get all metadata signals for a conversation.

    Args:
        conn: SQLite connection.
        talker_id: The conversation's talker ID.

    Returns:
        List of MetadataSignals objects.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT node_id, talker_id, reply_delay_avg_s, reply_delay_max_s, term_shift_score,
               silence_event, topic_frequency, initiator_ratio, emotional_tone, conflict_intensity
        FROM node_metadata
        WHERE talker_id = ?
    """, (talker_id,))

    signals = []
    for row in cursor.fetchall():
        signals.append(MetadataSignals(
            node_id=row[0],
            talker_id=row[1],
            reply_delay_avg_s=row[2],
            reply_delay_max_s=row[3],
            term_shift_score=row[4],
            silence_event=bool(row[5]),
            topic_frequency=row[6],
            initiator_ratio=row[7],
            emotional_tone=row[8],
            conflict_intensity=row[9],
        ))
    return signals


def get_talkers_with_stats(conn: sqlite3.Connection) -> list[dict]:
    """Aggregate raw_messages to return per-talker stats.

    Returns a list of dicts with: talker_id, message_count, last_timestamp (ms),
    display_name (first sender_username where is_send=0, else talker_id).
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT talker_id,
               COUNT(*) AS message_count,
               MAX(create_time) AS last_timestamp
        FROM raw_messages
        GROUP BY talker_id
    """)
    rows = cursor.fetchall()

    result = []
    for row in rows:
        talker_id = row[0]
        message_count = row[1]
        last_timestamp = row[2] or 0

        # display_name: first sender_username where is_send=0, else talker_id
        cursor.execute("""
            SELECT sender_username FROM raw_messages
            WHERE talker_id = ? AND is_send = 0
            ORDER BY create_time ASC
            LIMIT 1
        """, (talker_id,))
        first_row = cursor.fetchone()
        display_name = first_row[0] if first_row else talker_id

        result.append({
            "talker_id": talker_id,
            "message_count": message_count,
            "last_timestamp": last_timestamp,
            "display_name": display_name,
        })
    return result


def get_build_status(conn: sqlite3.Connection, talker_id: str) -> str:
    """Infer build status from SQLite table completeness.

    Returns:
        "pending": topic_nodes has no data for talker_id
        "in_progress": build running (Layer 1/1.5/2) or topic_nodes without node_metadata
        "complete": full build done (topic_nodes + node_metadata + build_progress cleared)
    """
    cursor = conn.cursor()

    cursor.execute(
        "SELECT 1 FROM topic_nodes WHERE talker_id = ? LIMIT 1",
        (talker_id,),
    )
    has_nodes = cursor.fetchone() is not None

    if not has_nodes:
        prog = get_build_progress(conn, talker_id)
        return "in_progress" if prog else "pending"

    cursor.execute(
        "SELECT 1 FROM node_metadata WHERE talker_id = ? LIMIT 1",
        (talker_id,),
    )
    has_metadata = cursor.fetchone() is not None

    if not has_metadata:
        return "in_progress"

    # Layer 1.5 done, but Layer 2 may still be running. build_progress is only
    # cleared when the full build (including Layer 2) completes.
    prog = get_build_progress(conn, talker_id)
    if prog:
        return "in_progress"

    return "complete"


def set_build_progress(
    conn: sqlite3.Connection,
    talker_id: str,
    stage: str,
    step: str,
    detail: str = "",
) -> None:
    """Record current build progress for a talker (for UI display)."""
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat() + "Z"
    cursor.execute(
        """
        INSERT INTO build_progress (talker_id, stage, step, detail, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(talker_id) DO UPDATE SET
            stage = excluded.stage,
            step = excluded.step,
            detail = excluded.detail,
            updated_at = excluded.updated_at
        """,
        (talker_id, stage, step, detail, now),
    )
    conn.commit()


def get_build_progress(
    conn: sqlite3.Connection, talker_id: str
) -> Optional[dict]:
    """Return current build progress for a talker, or None if not building."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT stage, step, detail, updated_at FROM build_progress WHERE talker_id = ?",
        (talker_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "stage": row[0],
        "step": row[1],
        "detail": row[2] or "",
        "updated_at": row[3],
    }


def clear_build_progress(conn: sqlite3.Connection, talker_id: str) -> None:
    """Remove build progress record when build completes or is cleared."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM build_progress WHERE talker_id = ?", (talker_id,))
    conn.commit()


def delete_session(conn: sqlite3.Connection, talker_id: str) -> None:
    """Delete all data for a session (talker_id) from SQLite.

    Removes from: raw_messages, bursts, topic_nodes, node_metadata,
    anomaly_anchors, semantic_thread_pointers, build_progress.
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM raw_messages WHERE talker_id = ?", (talker_id,))
    cursor.execute("DELETE FROM bursts WHERE talker_id = ?", (talker_id,))
    cursor.execute("DELETE FROM topic_nodes WHERE talker_id = ?", (talker_id,))
    cursor.execute("DELETE FROM node_metadata WHERE talker_id = ?", (talker_id,))
    cursor.execute("DELETE FROM anomaly_anchors WHERE talker_id = ?", (talker_id,))
    cursor.execute("DELETE FROM semantic_thread_pointers WHERE talker_id = ?", (talker_id,))
    cursor.execute("DELETE FROM build_progress WHERE talker_id = ?", (talker_id,))
    conn.commit()


def get_messages_for_node(
    conn: sqlite3.Connection,
    talker_id: str,
    node: "TopicNode",
) -> list[RawMessage]:
    """Get all messages within a TopicNode's local_id range.

    Args:
        conn: SQLite connection.
        talker_id: The conversation's talker ID.
        node: TopicNode whose messages to retrieve.

    Returns:
        List of RawMessage objects sorted by local_id ascending.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT local_id, talker_id, create_time, is_send, sender_username,
               parsed_content, local_type, excluded
        FROM raw_messages
        WHERE talker_id = ? AND local_id BETWEEN ? AND ?
        ORDER BY local_id ASC
    """, (talker_id, node.start_local_id, node.end_local_id))

    messages = []
    for row in cursor.fetchall():
        messages.append(RawMessage(
            local_id=row[0],
            talker_id=row[1],
            create_time=row[2],
            is_send=bool(row[3]),
            sender_username=row[4],
            parsed_content=row[5] or "",
            local_type=row[6],
            excluded=bool(row[7]),
        ))
    return messages
