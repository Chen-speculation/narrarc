"""Convert REALTALK dataset JSON to WeFlow JSON fixture format.

REALTALK JSON format:
    - name.speaker_1, name.speaker_2
    - session_1, session_2, ... (arrays of messages)
    - Each message: clean_text, speaker, date_time (DD.MM.YYYY, HH:MM:SS), dia_id

LoCoMo JSON format (--locomo):
    - conversation.speaker_a, conversation.speaker_b
    - conversation.session_1, session_2, ... (arrays of messages)
    - Each message: text, speaker, dia_id (no per-message date_time)
    - conversation.session_N_date_time: "1:56 pm on 8 May, 2023"

Usage:
    python scripts/convert_realtalk.py \\
        --input  /path/to/Chat_1_Emi_Elise.json  # or directory
        --dyad-index 0                             # when input is directory
        --self-id Emi
        --talker-id realtalk_emi_elise
        --output tests/data/realtalk_messages.json
        --sessions-output tests/data/realtalk_sessions.json
        [--mapping-output tests/data/realtalk_emi_elise_mapping.json]
        [--locomo]  # for LoCoMo format
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from converter_utils import msg_dict, write_fixture_files

# REALTALK: DD.MM.YYYY, HH:MM:SS
_REALTALK_DT_FMT = "%d.%m.%Y, %H:%M:%S"

# LoCoMo: "1:56 pm on 8 May, 2023"
_LOCOMO_DT_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(am|pm)\s+on\s+(\d{1,2})\s+(\w+),\s+(\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_realtalk_datetime(ts: str) -> int:
    """Parse REALTALK date_time to Unix seconds (UTC)."""
    dt = datetime.strptime(ts.strip(), _REALTALK_DT_FMT)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _parse_locomo_datetime(ts: str) -> int:
    """Parse LoCoMo session_date_time to Unix seconds (UTC)."""
    m = _LOCOMO_DT_RE.match(ts.strip())
    if not m:
        return 0
    hour, minute, ampm, day, month_str, year = m.groups()
    hour = int(hour)
    minute = int(minute)
    day = int(day)
    year = int(year)
    month = _MONTHS.get(month_str[:3].lower(), 1)
    if ampm.lower() == "pm" and hour != 12:
        hour += 12
    elif ampm.lower() == "am" and hour == 12:
        hour = 0
    dt = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _get_message_text(msg: dict, is_locomo: bool) -> str:
    """Extract message content from REALTALK or LoCoMo message."""
    text = msg.get("text" if is_locomo else "clean_text", "").strip()
    if not text and msg.get("blip_caption"):
        text = msg["blip_caption"]
    if not text:
        text = "[Image]"
    return text


def _collect_messages_realtalk(data: dict, self_id: str) -> list[tuple[int, int, str, str, str]]:
    """Collect (create_time_s, is_send, sender, text, dia_id) from REALTALK JSON."""
    records = []
    self_lower = self_id.lower()

    def session_key(k):
        m = re.match(r"session_(\d+)", k)
        return (int(m.group(1)),) if m else (999999,)

    for key in sorted(data.keys(), key=session_key):
        if not re.match(r"session_\d+$", key):
            continue
        for msg in data.get(key, []):
            dia_id = msg.get("dia_id", "")
            ts_str = msg.get("date_time", "")
            create_time_s = _parse_realtalk_datetime(ts_str) if ts_str else 0
            speaker = msg.get("speaker", "")
            text = _get_message_text(msg, is_locomo=False)
            is_send = 1 if speaker.lower() == self_lower else 0
            records.append((create_time_s, is_send, speaker, text, dia_id))

    return records


def _collect_messages_locomo(data: dict, self_id: str) -> list[tuple[int, int, str, str, str]]:
    """Collect (create_time_s, is_send, sender, text, dia_id) from LoCoMo JSON."""
    conv = data.get("conversation", {})
    records = []
    self_lower = self_id.lower()

    def session_key(k):
        m = re.match(r"session_(\d+)", k)
        return (int(m.group(1)),) if m else (999999,)

    for key in sorted(conv.keys(), key=session_key):
        if not re.match(r"session_\d+$", key):
            continue
        session_num = int(re.match(r"session_(\d+)", key).group(1))
        dt_key = f"session_{session_num}_date_time"
        session_ts = _parse_locomo_datetime(conv.get(dt_key, ""))
        for i, msg in enumerate(conv.get(key, [])):
            dia_id = msg.get("dia_id", "")
            # Approximate: session start + i seconds
            create_time_s = session_ts + i if session_ts else i
            speaker = msg.get("speaker", "")
            text = _get_message_text(msg, is_locomo=True)
            is_send = 1 if speaker.lower() == self_lower else 0
            records.append((create_time_s, is_send, speaker, text, dia_id))

    return records


def _sort_and_assign_local_ids(
    records: list[tuple[int, int, str, str, str]],
) -> tuple[list[tuple[int, int, str, str, str, int]], dict[str, int], dict[str, str]]:
    """Sort by (create_time_s, original order), assign localId, build dia_id mapping."""
    # Add original index for stable sort when times are equal
    indexed = [(r[0], r[1], r[2], r[3], r[4], i) for i, r in enumerate(records)]
    indexed.sort(key=lambda x: (x[0], x[5]))
    dia_to_local = {}
    local_to_dia = {}
    result = []
    for local_id, (ct, is_send, sender, text, dia_id, _) in enumerate(indexed, start=1):
        result.append((ct, is_send, sender, text, dia_id, local_id))
        if dia_id:
            dia_to_local[dia_id] = local_id
            local_to_dia[str(local_id)] = dia_id
    return result, dia_to_local, local_to_dia


def convert(
    input_path: str,
    dyad_index: int,
    self_id: str,
    talker_id: str,
    messages_path: str,
    sessions_path: str,
    mapping_path: str | None = None,
    locomo: bool = False,
) -> dict | None:
    """Convert REALTALK/LoCoMo JSON to WeFlow fixture files.

    Args:
        input_path: Path to a single JSON file or directory of Chat_*.json files.
        dyad_index: When input_path is a directory, index (0-based) of file to use.
        self_id: Participant whose messages become isSend=1.
        talker_id: Value for the talker field in the output envelope.
        messages_path: Output path for messages JSON.
        sessions_path: Output path for sessions JSON.
        mapping_path: Optional path for dia_id <-> localId mapping JSON.
        locomo: If True, parse LoCoMo format (conversation.session_N, text, etc.).

    Returns:
        Mapping dict {chat_id, dia_to_local, local_to_dia} if mapping_path given, else None.
    """
    path = Path(input_path)
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix == ".json")
        if not files:
            raise ValueError(f"No JSON files found in {input_path}")
        if dyad_index >= len(files):
            raise ValueError(f"dyad_index {dyad_index} out of range (found {len(files)} files)")
        json_path = files[dyad_index]
    else:
        json_path = path

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if locomo:
        records = _collect_messages_locomo(data, self_id)
        conv = data.get("conversation", {})
        s1 = conv.get("speaker_1") or conv.get("speaker_a", "")
        s2 = conv.get("speaker_2") or conv.get("speaker_b", "")
    else:
        records = _collect_messages_realtalk(data, self_id)
        name = data.get("name", {})
        s1 = name.get("speaker_1", "")
        s2 = name.get("speaker_2", "")

    sorted_records, dia_to_local, local_to_dia = _sort_and_assign_local_ids(records)

    messages = [
        msg_dict(
            local_id=local_id,
            talker_id=talker_id,
            create_time_s=create_time_s,
            is_send=is_send,
            sender=sender,
            text=text,
        )
        for create_time_s, is_send, sender, text, _dia_id, local_id in sorted_records
    ]

    other_ids = {r[2] for r in records if r[2].lower() != self_id.lower()}
    display_name = next(iter(other_ids), s2 or s1 or "TA")

    write_fixture_files(messages, talker_id, display_name, messages_path, sessions_path)
    print(f"Wrote {len(messages)} messages to {messages_path}")
    print(f"Wrote sessions to {sessions_path}")

    mapping_data = None
    if mapping_path:
        mapping_data = {
            "chat_id": talker_id,
            "dia_to_local": dia_to_local,
            "local_to_dia": local_to_dia,
        }
        Path(mapping_path).parent.mkdir(parents=True, exist_ok=True)
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(mapping_data, f, ensure_ascii=False, indent=2)
        print(f"Wrote dia_id mapping to {mapping_path}")

    return mapping_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert REALTALK/LoCoMo JSON to WeFlow JSON fixture"
    )
    parser.add_argument("--input", required=True, help="Path to JSON file or directory")
    parser.add_argument("--dyad-index", type=int, default=0, help="File index when input is dir")
    parser.add_argument("--self-id", required=True, help="Participant ID for isSend=1")
    parser.add_argument("--talker-id", required=True, help="talker_id in output envelope")
    parser.add_argument("--output", required=True, help="Output messages JSON path")
    parser.add_argument("--sessions-output", required=True, help="Output sessions JSON path")
    parser.add_argument("--mapping-output", default=None, help="Output dia_id mapping JSON path")
    parser.add_argument("--locomo", action="store_true", help="Parse LoCoMo format")
    args = parser.parse_args()

    convert(
        input_path=args.input,
        dyad_index=args.dyad_index,
        self_id=args.self_id,
        talker_id=args.talker_id,
        messages_path=args.output,
        sessions_path=args.sessions_output,
        mapping_path=args.mapping_output,
        locomo=args.locomo,
    )


if __name__ == "__main__":
    main()
