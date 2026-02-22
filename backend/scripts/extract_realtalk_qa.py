"""Extract QA from REALTALK JSON to test case format for event_retrieval and time_point.

Reads REALTALK JSON (or LoCoMo with qa at root), maps:
  - category 1 (fact) -> event_retrieval
  - category 2 (date) -> time_point
  - category 3 (inference) -> excluded (arc_narrative uses pre-generated *_arc_cases.json in tests/data/realtalk_eval/)

Usage:
    python scripts/extract_realtalk_qa.py \\
        --input /path/to/Chat_1_Emi_Elise.json
        --chat-id realtalk_emi_elise
        --output tests/data/realtalk_eval/realtalk_emi_elise_cases.json
"""

import argparse
import json
import re
from pathlib import Path


def _normalize_evidence(evidence: list) -> list[str]:
    """Flatten evidence list; split 'D8:6; D9:17' into ['D8:6', 'D9:17']."""
    result = []
    for item in evidence:
        if isinstance(item, str):
            for part in re.split(r"\s*;\s*", item.strip()):
                if part:
                    result.append(part)
        else:
            result.append(str(item))
    return result


def extract_cases(realtalk_path: str, chat_id: str) -> list[dict]:
    """Extract event_retrieval and time_point test cases from REALTALK qa.

    Args:
        realtalk_path: Path to REALTALK or LoCoMo JSON file.
        chat_id: Chat identifier for the output (e.g. realtalk_emi_elise).

    Returns:
        List of case dicts: {question, expected_answer, evidence_dia_ids, query_type, category}.
    """
    with open(realtalk_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    qa = data.get("qa", [])
    cases = []

    for item in qa:
        category = item.get("category", 0)
        if category == 3:
            continue  # inference -> arc_narrative, generated separately
        if category == 1:
            query_type = "event_retrieval"
        elif category == 2:
            query_type = "time_point"
        else:
            continue

        evidence = item.get("evidence", [])
        evidence_dia_ids = _normalize_evidence(evidence)

        cases.append({
            "question": item.get("question", ""),
            "expected_answer": item.get("answer", ""),
            "evidence_dia_ids": evidence_dia_ids,
            "query_type": query_type,
            "category": category,
        })

    return cases


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract REALTALK QA to test cases (event_retrieval, time_point)"
    )
    parser.add_argument("--input", required=True, help="Path to REALTALK/LoCoMo JSON")
    parser.add_argument("--chat-id", required=True, help="Chat ID for output (e.g. realtalk_emi_elise)")
    parser.add_argument("--output", required=True, help="Output path for *_cases.json")
    args = parser.parse_args()

    cases = extract_cases(args.input, args.chat_id)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(cases)} cases to {args.output}")


if __name__ == "__main__":
    main()
