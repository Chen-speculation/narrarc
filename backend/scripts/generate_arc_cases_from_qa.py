"""Generate arc_cases.json from REALTALK qa array for eval_realtalk_accuracy.

Each qa item becomes one arc case with a single expected_phase containing
all evidence_dia_ids. Supports all categories (1=fact, 2=date, 3=inference).

Usage:
    python scripts/generate_arc_cases_from_qa.py \\
        --input /path/to/Chat_10_Fahim_Muhhamed.json \\
        --output tests/data/realtalk_eval/realtalk_fahim_muhhamed_arc_cases.json
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
                part = part.rstrip(".")
                if part:
                    result.append(part)
        else:
            result.append(str(item))
    return result


def extract_arc_cases(realtalk_path: str) -> list[dict]:
    """Extract arc_cases from REALTALK qa array.

    Returns list of {question, expected_phases: [{title, time_range, evidence_dia_ids}]}.
    """
    with open(realtalk_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    qa = data.get("qa", [])
    arc_cases = []

    for item in qa:
        evidence = item.get("evidence", [])
        evidence_dia_ids = _normalize_evidence(evidence)
        if not evidence_dia_ids:
            continue

        arc_cases.append({
            "question": item.get("question", ""),
            "query_type": "arc_narrative",
            "expected_phases": [
                {
                    "title": item.get("answer", "")[:80] or "Evidence",
                    "time_range": "",
                    "evidence_dia_ids": evidence_dia_ids,
                }
            ],
        })

    return arc_cases


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate arc_cases from REALTALK qa for eval"
    )
    parser.add_argument("--input", required=True, help="Path to REALTALK JSON")
    parser.add_argument("--output", required=True, help="Output arc_cases.json path")
    args = parser.parse_args()

    cases = extract_arc_cases(args.input)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(cases)} arc cases to {args.output}")


if __name__ == "__main__":
    main()
