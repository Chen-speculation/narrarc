"""Convert Kaggle WhatsApp export CSV to WeFlow JSON fixture format.

Supported CSV column layouts (case-insensitive):
    1. date + hour + sender + message
    2. datetime + sender + message
    3. date + time + sender + message

The first ``--senders`` value becomes isSend=1; the second becomes isSend=0.
Rows from other senders are dropped.

Usage:
    python scripts/convert_kaggle_whatsapp.py \\
        --input  chat.csv \\
        --senders "Alice" "Bob"           # first = self (isSend=1)
        --talker-id kaggle_wa_01 \\
        --output tests/data/kaggle_wa_messages.json \\
        --sessions-output tests/data/kaggle_wa_sessions.json
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from converter_utils import msg_dict, write_fixture_files


def _normalise_columns(headers: list[str]) -> dict[str, str]:
    """Map actual CSV headers to canonical names.

    Returns a dict like ``{"datetime": "actual_col", "sender": "actual_col", ...}``
    """
    lower = {h.lower().strip(): h for h in headers}
    mapping: dict[str, str] = {}

    # datetime (combined)
    for alias in ("datetime", "date_time", "timestamp"):
        if alias in lower:
            mapping["datetime"] = lower[alias]
            break

    # date
    for alias in ("date",):
        if alias in lower:
            mapping["date"] = lower[alias]
            break

    # hour / time
    for alias in ("hour", "time"):
        if alias in lower:
            mapping["time"] = lower[alias]
            break

    # sender
    for alias in ("sender", "author", "from", "name"):
        if alias in lower:
            mapping["sender"] = lower[alias]
            break

    # message
    for alias in ("message", "text", "content", "msg"):
        if alias in lower:
            mapping["message"] = lower[alias]
            break

    return mapping


def _parse_datetime(row: dict, col_map: dict[str, str]) -> int:
    """Extract a Unix-seconds timestamp from a CSV row."""
    if "datetime" in col_map:
        raw = row[col_map["datetime"]].strip()
        # Try common formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt)
                return int(dt.replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                pass
        raise ValueError(f"Unrecognised datetime format: {raw!r}")

    date_raw = row[col_map["date"]].strip()
    time_raw = row.get(col_map.get("time", ""), "00:00").strip()
    combined = f"{date_raw} {time_raw}"
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ):
        try:
            dt = datetime.strptime(combined, fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date/time format: {combined!r}")


def convert(
    input_csv: str,
    senders: list[str],
    talker_id: str,
    messages_path: str,
    sessions_path: str,
) -> None:
    """Convert a Kaggle WhatsApp CSV to WeFlow JSON fixture files.

    Args:
        input_csv: Path to the CSV file.
        senders: Two sender names; first = self (isSend=1), second = TA.
        talker_id: Value for the ``talker`` field in the output envelope.
        messages_path: Output path for messages JSON.
        sessions_path: Output path for sessions JSON.
    """
    if len(senders) != 2:
        raise ValueError("Exactly two --senders values required")

    self_sender, ta_sender = senders[0], senders[1]
    allowed = {self_sender, ta_sender}

    rows: list[tuple[int, int, str, str]] = []  # (create_time_s, is_send, sender, text)

    with open(input_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no header row")

        col_map = _normalise_columns(list(reader.fieldnames))

        if "sender" not in col_map or "message" not in col_map:
            raise ValueError(
                f"Could not find sender/message columns. Found: {list(reader.fieldnames)}"
            )
        if "datetime" not in col_map and "date" not in col_map:
            raise ValueError(
                f"Could not find datetime/date column. Found: {list(reader.fieldnames)}"
            )

        for row in reader:
            sender = row[col_map["sender"]].strip()
            if sender not in allowed:
                continue
            try:
                create_time_s = _parse_datetime(row, col_map)
            except ValueError:
                continue
            text = row[col_map["message"]].strip()
            is_send = 1 if sender == self_sender else 0
            rows.append((create_time_s, is_send, sender, text))

    # Sort by timestamp (in case CSV is unsorted)
    rows.sort(key=lambda r: r[0])

    messages = [
        msg_dict(
            local_id=i + 1,
            talker_id=talker_id,
            create_time_s=create_time_s,
            is_send=is_send,
            sender=sender,
            text=text,
        )
        for i, (create_time_s, is_send, sender, text) in enumerate(rows)
    ]

    write_fixture_files(messages, talker_id, ta_sender, messages_path, sessions_path)
    print(f"Wrote {len(messages)} messages to {messages_path}")
    print(f"Wrote sessions to {sessions_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Kaggle WhatsApp CSV to WeFlow JSON fixture"
    )
    parser.add_argument("--input", required=True, help="Path to WhatsApp export CSV")
    parser.add_argument(
        "--senders", nargs=2, required=True, metavar=("SELF", "TA"),
        help="Two sender names; first = self (isSend=1)"
    )
    parser.add_argument("--talker-id", required=True, help="talker_id in output envelope")
    parser.add_argument("--output", required=True, help="Output messages JSON path")
    parser.add_argument("--sessions-output", required=True, help="Output sessions JSON path")
    args = parser.parse_args()

    convert(
        input_csv=args.input,
        senders=args.senders,
        talker_id=args.talker_id,
        messages_path=args.output,
        sessions_path=args.sessions_output,
    )


if __name__ == "__main__":
    main()
