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
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVAL_DIR = ROOT / "tests" / "data" / "realtalk_eval"



def run_single_eval_batch(input_path, self_id, talker_id, arc_cases_path, limit_cases, mode, output_json, debug_retrieval=False, output_debug_json=None):
    msg_path = str(EVAL_DIR / f"{talker_id}_messages.json")
    sess_path = str(EVAL_DIR / f"{talker_id}_sessions.json")
    mapping_path = str(EVAL_DIR / f"{talker_id}_mapping.json")
    arc_path = str(EVAL_DIR / f"{talker_id}_arc_cases.json")
    print("=== Step 1: Convert RealTalk ===")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "convert_realtalk.py"), "--input", input_path, "--self-id", self_id, "--talker-id", talker_id, "--output", msg_path, "--sessions-output", sess_path, "--mapping-output", mapping_path], cwd=str(ROOT))
    if r.returncode != 0: return r.returncode
    if arc_cases_path and Path(arc_cases_path).exists():
        import shutil
        shutil.copy(arc_cases_path, arc_path)
        print("Using ARC cases from", arc_cases_path)
    else:
        print("Generate arc_cases from qa")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_arc_cases_from_qa.py"), "--input", input_path, "--output", arc_path], cwd=str(ROOT))
        if r.returncode != 0: return r.returncode
    if limit_cases:
        with open(arc_path, encoding='utf-8') as f: cases = json.load(f)
        cases = cases[:limit_cases]
        with open(arc_path, 'w', encoding='utf-8') as f: json.dump(cases, f, ensure_ascii=False, indent=2)
        print("Limited to", len(cases), "arc cases")
    print("=== Step 3: Run eval pipeline ===")
    cmd = [sys.executable, str(ROOT / "scripts" / "eval_realtalk_accuracy.py"), "--chat-id", talker_id, "--mode", mode, "--output-json", output_json]
    r = subprocess.run(cmd, cwd=str(ROOT))
    return r.returncode

def main():
    parser = argparse.ArgumentParser(description="Convert RealTalk + run eval")
    parser.add_argument("--input", help="RealTalk JSON path")
    parser.add_argument("--self-id", help="Participant for isSend=1")
    parser.add_argument("--talker-id", help="Output chat_id")
    parser.add_argument("--limit-cases", type=int, default=None, help="Limit arc cases (for debugging)")
    parser.add_argument("--mode", choices=["oneshot", "agent"], default="agent")
    parser.add_argument("--train-only", action="store_true", help="Process only train set (Chat_1-7)")
    parser.add_argument("--test-only", action="store_true", help="Process only test set (Chat_8-10)")
    parser.add_argument("--realtalk-dir", type=Path, default=Path(r"c:\Users\Administrator\REALTALK\data"), help="RealTalk data dir")
    parser.add_argument("--arc-dir", type=Path, default=Path(r"c:\Users\Administrator\REALTALK\arc_data"), help="ARC cases dir")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml", help="Config file")
    parser.add_argument("--dry-run", action="store_true", help="Only list files")
    parser.add_argument("--record-experiment", action="store_true", help="Record metrics")
    parser.add_argument("--experiment-id", help="Experiment ID")
    parser.add_argument("--config-changes", default="", help="Config change description")
    args = parser.parse_args()

    batch = args.train_only or args.test_only
    if batch:
        if args.input:
            parser.error("--input cannot be used with --train-only or --test-only")
        sys.path.insert(0, str(Path(__file__).parent))
        from dataset_splitting import filter_chat_files, chat_file_to_arc_file, get_self_id_from_chat
        mode = "train" if args.train_only else "test"
        config_path = args.config if args.config.exists() else ROOT / "config.yml"
        pairs = filter_chat_files(args.realtalk_dir, mode, config_path=config_path)
        if not pairs:
            print("No", mode, "files found in", args.realtalk_dir, file=sys.stderr)
            sys.exit(1)
        names = [p.name for p, _ in pairs]
        print("Processing", len(pairs), mode, "files:", names)
        for chat_path, talker_id in pairs:
            arc_path = chat_file_to_arc_file(chat_path, args.arc_dir)
            aname = arc_path.name if arc_path else "generate from qa"
            print(" ", chat_path.name, "->", talker_id, "(arc:", aname + ")")
        if args.dry_run:
            print("Dry run: no evaluation executed.")
            sys.exit(0)
        last_code = 0
        agg_jsons = []
        for chat_path, talker_id in list(pairs)[:2]:
            print("\n" + "="*60 + "\nProcessing", chat_path.name, "(" + talker_id + ")\n" + "="*60)
            arc_path = chat_file_to_arc_file(chat_path, args.arc_dir)
            arc_str = str(arc_path) if arc_path else None
            self_id = get_self_id_from_chat(chat_path)
            out_dir = EVAL_DIR / "experiment_outputs"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_json = str(out_dir / ("eval_" + talker_id + ".json"))
            code = run_single_eval_batch(str(chat_path), self_id, talker_id, arc_str, args.limit_cases, args.mode, out_json)
            if code != 0: last_code = code
            agg_jsons.append(out_json)
        if args.record_experiment and agg_jsons:
            from baseline_tracking import ensure_experiments_dir, append_csv_row, append_json_record, capture_config_snapshot
            import yaml
            exp_dir = ROOT / "experiments"
            ensure_experiments_dir(exp_dir)
            exp_id = args.experiment_id or ("exp_" + __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S"))
            all_cases = []
            for jp in agg_jsons:
                if Path(jp).exists():
                    with open(jp, encoding="utf-8") as f:
                        data = json.load(f)
                        all_cases.extend(data.get("cases", []))
            if all_cases:
                n = len(all_cases)
                metrics = {"exact_recall": sum(c.get("recall",0) for c in all_cases)/n, "fuzzy_recall": sum(c.get("fuzzy_recall",0) for c in all_cases)/n, "precision": sum(c.get("precision",0) for c in all_cases)/n, "arc_phase_coverage": sum(c.get("arc_phase_coverage",0) for c in all_cases)/n}
                raw_cfg = {}
                try:
                    cfg_path = ROOT / "config.yaml" if (ROOT / "config.yaml").exists() else ROOT / "config.yml"
                    if cfg_path.exists():
                        with open(cfg_path, encoding="utf-8") as f:
                            raw_cfg = yaml.safe_load(f) or {}
                except Exception: pass
                config_snap = capture_config_snapshot(None, raw_cfg)
                record = {"experiment_id": exp_id, "date": __import__("datetime").datetime.now().isoformat(), "config_changes": args.config_changes, "config_snapshot": config_snap, "split": mode, "case_count": n}
                for k,v in metrics.items(): record["train_"+k] = v
                append_csv_row(exp_dir, record)
                append_json_record(exp_dir, record)
                print("\nExperiment recorded:", exp_id, "(split=" + mode + ",", n, "cases)")
                print("  exact_recall=" + str(round(metrics["exact_recall"], 4)) + ", fuzzy_recall=" + str(round(metrics["fuzzy_recall"], 4)))
        sys.exit(last_code)

    if not args.input or not args.self_id or not args.talker_id:
        parser.error("Single file mode requires --input, --self-id, and --talker-id")


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



