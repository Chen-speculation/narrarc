"""Tests for scripts/convert_kaggle_whatsapp.py using a 10-row synthetic CSV."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from convert_kaggle_whatsapp import convert

# 10-row synthetic CSV: date + hour + sender + message columns
CSV_DATE_HOUR = """\
date,hour,sender,message
2023-03-10,22:10:00,Alice,Hello there
2023-03-10,22:11:00,Bob,Hi!
2023-03-10,22:12:00,Alice,How are you?
2023-03-10,22:13:00,Bob,Good, thanks
2023-03-10,22:14:00,Charlie,I'm here too
2023-03-10,22:15:00,Alice,Nice weather
2023-03-10,22:16:00,Bob,Indeed
2023-03-10,22:17:00,Alice,See you soon
2023-03-10,22:18:00,Bob,Bye!
2023-03-10,22:19:00,Alice,Bye!
"""

# Combined datetime column variant
CSV_DATETIME = """\
datetime,sender,message
2023-03-10 22:10:00,Alice,First message
2023-03-10 22:11:00,Bob,Second message
2023-03-10 22:12:00,Alice,Third
2023-03-10 22:13:00,Bob,Fourth
"""


@pytest.fixture
def csv_date_hour(tmp_path):
    path = tmp_path / "chat.csv"
    path.write_text(CSV_DATE_HOUR, encoding="utf-8")
    return str(path)


@pytest.fixture
def csv_datetime(tmp_path):
    path = tmp_path / "chat_dt.csv"
    path.write_text(CSV_DATETIME, encoding="utf-8")
    return str(path)


class TestTwoSenderFilter:
    def test_filters_to_two_senders(self, csv_date_hour, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_csv=csv_date_hour,
            senders=["Alice", "Bob"],
            talker_id="kaggle_wa_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        # Charlie's message should be excluded
        assert data["count"] == 9
        senders = {m["senderUsername"] for m in data["messages"]}
        assert "Charlie" not in senders

    def test_is_send_assignment(self, csv_date_hour, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_csv=csv_date_hour,
            senders=["Alice", "Bob"],
            talker_id="kaggle_wa_01",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        msgs = data["messages"]
        # First message is Alice (isSend=1)
        assert msgs[0]["isSend"] == 1
        assert msgs[0]["senderUsername"] == "Alice"
        # Second message is Bob (isSend=0)
        assert msgs[1]["isSend"] == 0
        assert msgs[1]["senderUsername"] == "Bob"


class TestTimestampParsing:
    def test_date_hour_columns(self, csv_date_hour, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_csv=csv_date_hour,
            senders=["Alice", "Bob"],
            talker_id="t",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        # Timestamps should be in seconds
        for m in data["messages"]:
            assert m["createTime"] < 2e10

    def test_datetime_column(self, csv_datetime, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_csv=csv_datetime,
            senders=["Alice", "Bob"],
            talker_id="t",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        assert data["count"] == 4


class TestLocalIdAssignment:
    def test_monotonically_increasing(self, csv_date_hour, tmp_path):
        out_msg = str(tmp_path / "messages.json")
        out_sess = str(tmp_path / "sessions.json")
        convert(
            input_csv=csv_date_hour,
            senders=["Alice", "Bob"],
            talker_id="t",
            messages_path=out_msg,
            sessions_path=out_sess,
        )
        with open(out_msg) as f:
            data = json.load(f)
        ids = [m["localId"] for m in data["messages"]]
        assert ids == list(range(1, len(ids) + 1))
