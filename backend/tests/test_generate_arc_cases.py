"""Tests for scripts/generate_arc_cases_from_qa.py."""

import json
from pathlib import Path

import pytest

sys_path = Path(__file__).parent.parent / "scripts"
import sys
sys.path.insert(0, str(sys_path))
from generate_arc_cases_from_qa import extract_arc_cases, _normalize_evidence


class TestNormalizeEvidence:
    def test_single(self):
        assert _normalize_evidence(["D1:4"]) == ["D1:4"]

    def test_semicolon_split(self):
        assert _normalize_evidence(["D8:6; D9:17"]) == ["D8:6", "D9:17"]

    def test_trailing_dot(self):
        assert _normalize_evidence(["D5:3."]) == ["D5:3"]


class TestExtractArcCases:
    def test_from_fahim_muhhamed(self):
        # REALTALK: sibling of chat-mirror under learning-project
        root = Path(__file__).resolve().parent.parent.parent.parent
        path = root / "REALTALK" / "data" / "Chat_10_Fahim_Muhhamed.json"
        if not path.exists():
            pytest.skip("REALTALK data not available")
        cases = extract_arc_cases(str(path))
        assert len(cases) >= 80
        c = cases[0]
        assert "question" in c
        assert "expected_phases" in c
        assert c["query_type"] == "arc_narrative"
        assert len(c["expected_phases"]) >= 1
        assert "evidence_dia_ids" in c["expected_phases"][0]
        assert "D1:4" in c["expected_phases"][0]["evidence_dia_ids"]
