"""Convert CANDOR corpus session JSON to WeFlow JSON fixture format.

CANDOR session JSON format:
    {
        "start_epoch": <unix-seconds>,
        "turns": [
            {
                "start_time": <offset-seconds (float)>,
                "speaker_id": "<id>",
                "text": "<utterance>"
            },
            ...
        ]
    }

Absolute epoch for each turn = ``start_epoch + floor(start_time)``.

Usage:
    python scripts/convert_candor.py \\
        --input  session.json \\
        --session-index 0         # if file is a list of sessions (default 0)
        --self-id A               # speaker_id whose turns are isSend=1
        --talker-id candor_01 \\
        --output tests/data/candor_messages.json \\
        --sessions-output tests/data/candor_sessions.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from converter_utils import msg_dict, write_fixture_files


def parse_session(session: dict, self_id: str) -> list[tuple[int, int, str, str]]:
    """Parse a CANDOR session dict into (create_time_s, is_send, sender, text) tuples.

    Args:
        session: A single session dict with ``start_epoch`` and ``turns``.
        self_id: Speaker ID whose turns become isSend=1.

    Returns:
        List of (create_time_s, is_send, speaker_id, text) tuples.
    """
    start_epoch = int(session["start_epoch"])
    records: list[tuple[int, int, str, str]] = []
    for turn in session.get("turns", []):
        offset = int(turn.get("start_time", 0))
        create_time_s = start_epoch + offset
        speaker = str(turn.get("speaker_id", ""))
        text = str(turn.get("text", ""))
        is_send = 1 if speaker == self_id else 0
        records.append((create_time_s, is_send, speaker, text))
    return records


def convert(
    input_path: str,
    session_index: int,
    self_id: str,
    talker_id: str,
    messages_path: str,
    sessions_path: str,
) -> None:
    """Convert a CANDOR session JSON to WeFlow JSON fixture files.

    Args:
        input_path: Path to the session JSON file (single session dict or list).
        session_index: If the file contains a list, which session to use.
        self_id: Speaker ID whose turns become isSend=1.
        talker_id: Value for the ``talker`` field in the output envelope.
        messages_path: Output path for messages JSON.
        sessions_path: Output path for sessions JSON.
    """
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        if session_index >= len(data):
            raise ValueError(
                f"session_index {session_index} out of range (found {len(data)} sessions)"
            )
        session = data[session_index]
    else:
        session = data

    records = parse_session(session, self_id)

    messages = [
        msg_dict(
            local_id=i + 1,
            talker_id=talker_id,
            create_time_s=create_time_s,
            is_send=is_send,
            sender=speaker,
            text=text,
        )
        for i, (create_time_s, is_send, speaker, text) in enumerate(records)
    ]

    other_ids = {r[2] for r in records if r[2] != self_id}
    display_name = next(iter(other_ids), "TA")

    write_fixture_files(messages, talker_id, display_name, messages_path, sessions_path)
    print(f"Wrote {len(messages)} messages to {messages_path}")
    print(f"Wrote sessions to {sessions_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert CANDOR session JSON to WeFlow JSON fixture"
    )
    parser.add_argument("--input", required=True, help="Path to CANDOR session JSON file")
    parser.add_argument(
        "--session-index", type=int, default=0,
        help="Which session to use if file is a list (default 0)"
    )
    parser.add_argument("--self-id", required=True, help="Speaker ID for isSend=1")
    parser.add_argument("--talker-id", required=True, help="talker_id in output envelope")
    parser.add_argument("--output", required=True, help="Output messages JSON path")
    parser.add_argument("--sessions-output", required=True, help="Output sessions JSON path")
    args = parser.parse_args()

    convert(
        input_path=args.input,
        session_index=args.session_index,
        self_id=args.self_id,
        talker_id=args.talker_id,
        messages_path=args.output,
        sessions_path=args.sessions_output,
    )


if __name__ == "__main__":
    main()
