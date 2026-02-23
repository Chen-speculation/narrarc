#!/usr/bin/env python3
"""One-shot pipeline: convert RealTalk JSON → run backend eval.

RealTalk JSON 结构:
  1. session_N       - 消息数组 (clean_text, speaker, date_time, dia_id)
  2. events_session_N - 事件标注 (agent_a/agent_b sub-events)
  3. session_N_date_time - 会话时间
  4. qa              - 问答对 (question, answer, evidence dia_ids, category)

Usage:
    uv run python scripts/run_realtalk_eval.py \\
        --input /path/to/REALTALK/data/Chat_10_Fahim_Muhhamed.json \\
        --self-id "Fahim Khan" \\
        --talker-id realtalk_fahim_muhhamed \\
        [--limit-cases 3]   # 只跑前 N 个 arc case（调试用）
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVAL_DIR = ROOT / "tests" / "data" / "realtalk_eval"


def main():
    parser = argparse.ArgumentParser(description="Convert RealTalk + run eval")
    parser.add_argument("--input", required=True, help="RealTalk JSON path")
    parser.add_argument("--self-id", required=True, help="Participant for isSend=1")
    parser.add_argument("--talker-id", required=True, help="Output chat_id")
    parser.add_argument("--limit-cases", type=int, default=None, help="Limit arc cases (for debugging)")
    parser.add_argument("--mode", choices=["oneshot", "agent"], default="oneshot")
    args = parser.parse_args()

    msg_path = str(EVAL_DIR / f"{args.talker_id}_messages.json")
    sess_path = str(EVAL_DIR / f"{args.talker_id}_sessions.json")
    mapping_path = str(EVAL_DIR / f"{args.talker_id}_mapping.json")
    arc_path = str(EVAL_DIR / f"{args.talker_id}_arc_cases.json")

    # Step 1: convert
    print("=== Step 1: Convert RealTalk → messages + sessions + mapping ===")
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "convert_realtalk.py"),
            "--input", args.input,
            "--self-id", args.self_id,
            "--talker-id", args.talker_id,
            "--output", msg_path,
            "--sessions-output", sess_path,
            "--mapping-output", mapping_path,
        ],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        sys.exit(r.returncode)

    # Step 2: generate arc_cases from qa
    print("\n=== Step 2: Generate arc_cases from qa ===")
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_arc_cases_from_qa.py"),
            "--input", args.input,
            "--output", arc_path,
        ],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        sys.exit(r.returncode)

    # Step 3: optionally limit cases
    if args.limit_cases:
        import json
        with open(arc_path) as f:
            cases = json.load(f)
        cases = cases[: args.limit_cases]
        with open(arc_path, "w") as f:
            json.dump(cases, f, ensure_ascii=False, indent=2)
        print(f"Limited to {len(cases)} arc cases")

    # Step 4: run eval
    print("\n=== Step 3: Run eval pipeline ===")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "eval_realtalk_accuracy.py"),
        "--chat-id", args.talker_id,
        "--mode", args.mode,
    ]
    r = subprocess.run(cmd, cwd=str(ROOT))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
