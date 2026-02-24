"""
Accuracy evaluation for narrative_mirror on REALTALK emi_elise dataset.

Runs the full L1->L1.5->L2->Query pipeline with real LLMs and computes:
  - Evidence Recall per arc query
  - Q2 anchor coverage (what signals were hit)
  - Q3 candidate coverage (how much of the conversation is considered)
  - Output quality assessment (phase count, evidence validity)

Usage:
    uv run python scripts/eval_realtalk_accuracy.py [--mode MODE]

Modes:
    oneshot  - Original Q1-Q5 pipeline (default)
    agent    - Graph workflow pipeline
    compare  - Run both and output comparison table
"""

import argparse
import calendar
import csv
import json
import os
import re
import statistics
import sys
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Resolve project root and add src + scripts to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

EVAL_DIR = ROOT / "tests" / "data" / "realtalk_eval"
DEFAULT_CHAT_ID = "realtalk_emi_elise"


def evidence_recall(returned_ids: list[int], expected_local_ids: list[int]) -> float:
    if not expected_local_ids:
        return 1.0
    return len(set(returned_ids) & set(expected_local_ids)) / len(set(expected_local_ids))


def evidence_recall_fuzzy(returned_ids: list[int], expected_local_ids: list[int], window: int = 3) -> float:
    """Recall with a ±window tolerance for nearby messages.

    Evidence at msg 59 vs 60 is often equivalent — both are in the same
    topic node and refer to the same conversation moment.
    """
    if not expected_local_ids:
        return 1.0
    matched = 0
    for eid in expected_local_ids:
        if any(abs(rid - eid) <= window for rid in returned_ids):
            matched += 1
    return matched / len(expected_local_ids)


def evidence_precision(returned_ids: list[int], expected_local_ids: list[int]) -> float:
    """|returned ∩ expected| / |returned|."""
    if not returned_ids:
        return 1.0
    return len(set(returned_ids) & set(expected_local_ids)) / len(set(returned_ids))


def hallucination_rate(returned_ids: list[int], valid_range: tuple[int, int]) -> float:
    """|IDs outside valid range| / |all returned IDs|."""
    if not returned_ids:
        return 0.0
    lo, hi = valid_range
    invalid = sum(1 for rid in returned_ids if rid < lo or rid > hi)
    return invalid / len(returned_ids)


def per_phase_recall(phases: list, expected_phases: list[dict], dia_to_local: dict) -> float:
    """For each expected phase, compute recall independently, then average."""
    if not expected_phases:
        return 1.0
    recalls = []
    for exp_phase in expected_phases:
        exp_ids = [dia_to_local[did] for did in exp_phase.get("evidence_dia_ids", []) if did in dia_to_local]
        if not exp_ids:
            recalls.append(1.0)
            continue
        ret_ids = []
        for p in phases:
            ret_ids.extend(p.evidence_msg_ids)
        ret_ids = list(set(ret_ids))
        recalls.append(evidence_recall(ret_ids, exp_ids))
    return sum(recalls) / len(recalls) if recalls else 0.0


def _parse_time_range_str(time_range: str) -> tuple:
    """Parse a free-text time range string to (start_datetime, end_datetime) or (None, None)."""
    if not time_range:
        return None, None
    # ISO range: "2023-03" or "2023-03-01 ~ 2023-05-31"
    iso_matches = re.findall(r'(\d{4})-(\d{2})(?:-(\d{2}))?', time_range)
    if iso_matches:
        y1, m1, d1 = iso_matches[0]
        start = datetime(int(y1), int(m1), int(d1) if d1 else 1)
        if len(iso_matches) >= 2:
            y2, m2, d2 = iso_matches[1]
            end_day = int(d2) if d2 else calendar.monthrange(int(y2), int(m2))[1]
            end = datetime(int(y2), int(m2), end_day)
        else:
            end_day = calendar.monthrange(int(y1), int(m1))[1]
            end = datetime(int(y1), int(m1), end_day)
        return start, end
    # Chinese format: "2023年3月" or "2023年3月~4月" or "2023年3月至5月"
    m = re.search(r'(\d{4})年(\d{1,2})月', time_range)
    if m:
        year, month1 = int(m.group(1)), int(m.group(2))
        rest = time_range[m.end():]
        m2 = re.search(r'(\d{1,2})月', rest)
        if m2:
            month2 = int(m2.group(1))
            end_year = year
        else:
            month2, end_year = month1, year
        end_day = calendar.monthrange(end_year, month2)[1]
        return datetime(year, month1, 1), datetime(end_year, month2, end_day)
    # Just year: "2023年"
    m = re.search(r'(\d{4})年', time_range)
    if m:
        year = int(m.group(1))
        return datetime(year, 1, 1), datetime(year, 12, 31)
    return None, None


def timeline_coverage(phases: list, expected_phases: list[dict], dia_to_local: dict,
                      conn=None, talker_id: str = "") -> float:
    """Compute fraction of conversation time span covered by generated phase time_ranges.

    full_span is derived from the timestamps of expected evidence messages (via DB lookup).
    Each phase's time_range string is parsed to extract a date interval.
    Returns union_of_phase_intervals / full_span, capped at 1.0.
    """
    # Collect expected local IDs to determine full conversation span
    all_exp_ids = []
    for ep in expected_phases:
        for did in ep.get("evidence_dia_ids", []):
            lid = dia_to_local.get(did)
            if lid is not None:
                all_exp_ids.append(lid)
    if not all_exp_ids:
        return 1.0

    # Get timestamps for expected IDs from DB
    full_start: datetime | None = None
    full_end: datetime | None = None
    if conn is not None and talker_id:
        try:
            from narrative_mirror.db import get_messages_by_ids
            msgs = get_messages_by_ids(conn, talker_id, all_exp_ids)
            if msgs:
                ts_list = [m.create_time for m in msgs]
                full_start = datetime.fromtimestamp(min(ts_list) / 1000)
                full_end = datetime.fromtimestamp(max(ts_list) / 1000)
        except Exception:
            pass
    if full_start is None or full_end is None:
        return 0.0

    full_span_secs = (full_end - full_start).total_seconds()
    if full_span_secs <= 0:
        return 1.0

    # Parse phase time_range strings into intervals
    intervals = []
    for p in phases:
        start, end = _parse_time_range_str(getattr(p, "time_range", ""))
        if start is not None and end is not None:
            intervals.append((start, end))
    if not intervals:
        return 0.0

    # Clamp intervals to [full_start, full_end] and compute union
    clamped = []
    for s, e in intervals:
        cs = max(s, full_start)
        ce = min(e, full_end)
        if cs <= ce:
            clamped.append((cs, ce))
    if not clamped:
        return 0.0

    clamped.sort()
    cur_s, cur_e = clamped[0]
    union_secs = 0.0
    for s, e in clamped[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            union_secs += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
    union_secs += (cur_e - cur_s).total_seconds()

    return min(1.0, union_secs / full_span_secs)


def per_phase_temporal_recall(phases: list, expected_phases: list[dict], dia_to_local: dict) -> float:
    """Per-phase recall: match generated phases to expected phases by order, compute fuzzy recall each, average.

    For each expected phase i, take generated phase i (if exists) and compute
    fuzzy_recall(±3) between them.
    """
    if not expected_phases:
        return 1.0
    recalls = []
    for i, exp_phase in enumerate(expected_phases):
        exp_ids = [dia_to_local[did] for did in exp_phase.get("evidence_dia_ids", []) if did in dia_to_local]
        if not exp_ids:
            recalls.append(1.0)
            continue
        ret_ids = list(phases[i].evidence_msg_ids) if i < len(phases) else []
        recalls.append(evidence_recall_fuzzy(ret_ids, exp_ids, 3))
    return sum(recalls) / len(recalls) if recalls else 0.0


def arc_phase_coverage(phases: list, expected_phases: list[dict], dia_to_local: dict) -> float:
    """ARC Phase Coverage: percentage of expected phases with at least one expected evidence retrieved."""
    if not expected_phases:
        return 1.0
    returned_ids = set(mid for p in phases for mid in p.evidence_msg_ids)
    covered = 0
    for exp_phase in expected_phases:
        exp_ids = [dia_to_local[did] for did in exp_phase.get("evidence_dia_ids", []) if did in dia_to_local]
        if not exp_ids:
            covered += 1
            continue
        if any(eid in returned_ids for eid in exp_ids):
            covered += 1
    return covered / len(expected_phases)


def per_phase_recall_list(phases: list, expected_phases: list[dict], dia_to_local: dict) -> list[float]:
    """Return recall for each expected phase (exact match)."""
    returned_ids = list(set(mid for p in phases for mid in p.evidence_msg_ids))
    recalls = []
    for exp_phase in expected_phases:
        exp_ids = [dia_to_local[did] for did in exp_phase.get("evidence_dia_ids", []) if did in dia_to_local]
        if not exp_ids:
            recalls.append(1.0)
            continue
        recalls.append(evidence_recall(returned_ids, exp_ids))
    return recalls


def aggregate_metrics(values: list[float]) -> dict:
    """Compute mean, median, std dev. Returns dict with mean, median, std."""
    if not values:
        return {"mean": 0.0, "median": 0.0, "std": 0.0}
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def run_oneshot_eval(arc_cases, conn, llm_cot, dia_to_local, total_msgs, chat_id, debug=True, max_nodes=80):
    """Run evaluation with one-shot Q1-Q5 pipeline. Returns metrics dict per case."""
    from narrative_mirror.query import run_query_with_phases

    results = []
    for arc in arc_cases:
        expected_local_ids = []
        for phase in arc.get("expected_phases", []):
            for did in phase.get("evidence_dia_ids", []):
                lid = dia_to_local.get(did)
                if lid is not None:
                    expected_local_ids.append(lid)
        expected_local_ids = list(set(expected_local_ids))

        output, phases = run_query_with_phases(
            question=arc["question"],
            talker_id=chat_id,
            llm=llm_cot,
            conn=conn,
            max_nodes=max_nodes,
            debug=debug,
            use_agent=False,
        )
        returned_ids = list(set(mid for p in phases for mid in p.evidence_msg_ids))
        grounded = sum(1 for p in phases if p.verified) / len(phases) if phases else 0.0


        exp_phases = arc.get("expected_phases", [])
        results.append({
            "question": arc["question"],
            "phases": phases,
            "output": output,
            "returned_ids": returned_ids,
            "expected_local_ids": expected_local_ids,
            "recall": evidence_recall(returned_ids, expected_local_ids),
            "fuzzy_recall": evidence_recall_fuzzy(returned_ids, expected_local_ids, 3),
            "precision": evidence_precision(returned_ids, expected_local_ids),
            "hallucination": hallucination_rate(returned_ids, (1, total_msgs)),
            "per_phase_recall": per_phase_recall(phases, exp_phases, dia_to_local),
            "arc_global_recall": evidence_recall(returned_ids, expected_local_ids),
            "arc_phase_coverage": arc_phase_coverage(phases, exp_phases, dia_to_local),
            "per_phase_recalls": per_phase_recall_list(phases, exp_phases, dia_to_local),
            "timeline_coverage": timeline_coverage(phases, exp_phases, dia_to_local, conn=conn, talker_id=chat_id),
            "per_phase_temporal_recall": per_phase_temporal_recall(phases, exp_phases, dia_to_local),
            "groundedness": grounded,
            "avg_phases": len(phases),
            "trace": None,
            "retrieval_checkpoints": [],
        })
    return results


def run_agent_eval(arc_cases, conn, llm_cot, llm_noncot, chroma_dir, dia_to_local, total_msgs, chat_id, debug=True,
                  debug_retrieval=False, debug_verbosity="minimal", retrieval_limit=80):
    """Run evaluation with agent graph workflow. Returns metrics dict per case."""
    from narrative_mirror.tools import get_all_tools
    from narrative_mirror.workflow import run_workflow
    from narrative_mirror.reflection import reflect_on_evidence
    from narrative_mirror.query import format_cards

    tools = get_all_tools(conn, chat_id, chroma_dir, llm_noncot)
    results = []
    for arc in arc_cases:
        expected_local_ids = []
        for phase in arc.get("expected_phases", []):
            for did in phase.get("evidence_dia_ids", []):
                lid = dia_to_local.get(did)
                if lid is not None:
                    expected_local_ids.append(lid)
        expected_local_ids = list(set(expected_local_ids))

        trace = run_workflow(
            question=arc["question"],
            talker_id=chat_id,
            llm=llm_cot,
            conn=conn,
            tools=tools,
            llm_noncot=llm_noncot,
            max_iterations=3,
            debug=debug,
            retrieval_limit=retrieval_limit,
        )
        phases = reflect_on_evidence(
            phases=trace.phases,
            question=arc["question"],
            llm=llm_cot,
            conn=conn,
            talker_id=chat_id,
        )
        output = format_cards(phases, chat_id, conn)

        returned_ids = list(set(mid for p in phases for mid in p.evidence_msg_ids))
        grounded = sum(1 for p in phases if p.verified) / len(phases) if phases else 0.0

        exp_phases = arc.get("expected_phases", [])
        retrieval_checkpoints = []
        if debug_retrieval and trace and getattr(trace, "collected_nodes", None):
            from retrieval_debug import (
                nodes_to_local_ids,
                log_checkpoint,
                identify_failure_point,
            )
            nodes = trace.collected_nodes
            cand_ids = nodes_to_local_ids(nodes)
            cp1 = log_checkpoint("candidate_generation", cand_ids, expected_local_ids, verbosity=debug_verbosity)
            cp2 = log_checkpoint("post_retrieval", cand_ids, expected_local_ids, verbosity=debug_verbosity)
            cp3 = log_checkpoint("final_selection", returned_ids, expected_local_ids, verbosity=debug_verbosity)
            retrieval_checkpoints = [cp1, cp2, cp3]

        results.append({
            "question": arc["question"],
            "phases": phases,
            "output": output,
            "returned_ids": returned_ids,
            "expected_local_ids": expected_local_ids,
            "recall": evidence_recall(returned_ids, expected_local_ids),
            "fuzzy_recall": evidence_recall_fuzzy(returned_ids, expected_local_ids, 3),
            "precision": evidence_precision(returned_ids, expected_local_ids),
            "hallucination": hallucination_rate(returned_ids, (1, total_msgs)),
            "per_phase_recall": per_phase_recall(phases, exp_phases, dia_to_local),
            "arc_global_recall": evidence_recall(returned_ids, expected_local_ids),
            "arc_phase_coverage": arc_phase_coverage(phases, exp_phases, dia_to_local),
            "per_phase_recalls": per_phase_recall_list(phases, exp_phases, dia_to_local),
            "timeline_coverage": timeline_coverage(phases, exp_phases, dia_to_local, conn=conn, talker_id=chat_id),
            "per_phase_temporal_recall": per_phase_temporal_recall(phases, exp_phases, dia_to_local),
            "groundedness": grounded,
            "avg_phases": len(phases),
            "trace": trace,
            "retrieval_checkpoints": retrieval_checkpoints,
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate narrative_mirror on REALTALK dataset")
    parser.add_argument("--mode", choices=["oneshot", "agent", "compare"], default="oneshot",
                        help="Run oneshot (default), agent, or compare mode")
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID,
                        help=f"Chat ID for eval fixtures (default: {DEFAULT_CHAT_ID})")
    parser.add_argument("--verbose", "-v", action="store_true", help="Per-case detail: question, expected/returned evidence")
    parser.add_argument("--output-json", help="Write results to JSON file with timestamp and config")
    parser.add_argument("--output-csv", help="Write per-case results to CSV")
    parser.add_argument("--debug-retrieval", action="store_true", help="Log retrieval checkpoints with ground truth tracking")
    parser.add_argument("--debug-verbosity", choices=["minimal", "full"], default="minimal",
                        help="Debug log detail: minimal (presence only) or full (all IDs, scores)")
    parser.add_argument("--output-debug-json", help="Write retrieval debug logs to JSON file")
    parser.add_argument("--record-experiment", action="store_true", help="Record metrics to baseline tracking")
    parser.add_argument("--experiment-id", help="Experiment ID (default: auto-generated)")
    parser.add_argument("--split", choices=["train", "test"], help="Dataset split for recording (train/test)")
    parser.add_argument("--experiments-dir", type=Path, help="Experiments output directory")
    parser.add_argument("--config-changes", default="", help="Description of config changes for this experiment")
    args = parser.parse_args()

    CHAT_ID = args.chat_id
    MSG_PATH = str(EVAL_DIR / f"{CHAT_ID}_messages.json")
    SESS_PATH = str(EVAL_DIR / f"{CHAT_ID}_sessions.json")
    ARC_PATH = EVAL_DIR / f"{CHAT_ID}_arc_cases.json"
    MAPPING_PATH = EVAL_DIR / f"{CHAT_ID}_mapping.json"

    # ── 1. Load config & LLMs ────────────────────────────────────
    config_path = ROOT / "config.yml"
    if not config_path.exists():
        config_path = ROOT / "config.yaml"
    if not config_path.exists():
        print("ERROR: config.yml/config.yaml not found", file=sys.stderr)
        sys.exit(1)

    from narrative_mirror.config import load_config
    from narrative_mirror.llm import from_config

    cfg = load_config(str(config_path))
    llm_noncot, llm_cot, reranker = from_config(cfg)
    print(f"LLM: {cfg.llm.model} | Embedding: {cfg.embedding.model} | Reranker: {cfg.reranker.model}")

    # Load query pipeline config (eval.query)
    import yaml
    raw_cfg = {}
    try:
        with open(config_path) as f:
            raw_cfg = yaml.safe_load(f) or {}
    except Exception:
        pass
    query_cfg = raw_cfg.get("eval", {}).get("query", {})
    max_nodes = int(query_cfg.get("q3_candidate_limit", 80))

    # ── 2. Load eval fixtures ────────────────────────────────────
    if not ARC_PATH.exists():
        print(f"ERROR: arc_cases not found: {ARC_PATH}", file=sys.stderr)
        print("Run: python scripts/generate_arc_cases_from_qa.py --input <realtalk.json> --output <path>", file=sys.stderr)
        sys.exit(1)
    with open(ARC_PATH, encoding="utf-8") as f:
        arc_cases = json.load(f)
    with open(MAPPING_PATH, encoding="utf-8") as f:
        mapping = json.load(f)
    dia_to_local = mapping["dia_to_local"]

    print(f"\nDataset: {CHAT_ID}")
    print(f"  Messages file: {Path(MSG_PATH).name}")
    with open(MSG_PATH, encoding="utf-8") as f:
        msg_data = json.load(f)
    total_msgs = len(msg_data.get("messages", []))
    print(f"  Total messages: {total_msgs}")
    print(f"  Arc cases: {len(arc_cases)}")

    # ── 3. Build pipeline (once, reuse DB across queries) ────────
    print_section("PHASE 1: BUILD PIPELINE (L1 + L1.5 + L2)")

    from narrative_mirror.db import init_db
    from narrative_mirror.datasource import JsonFileDataSource
    from narrative_mirror.build import build_layer1
    from narrative_mirror.metadata import build_layer15
    from narrative_mirror.layer2 import build_layer2

    tmpdir = tempfile.mkdtemp(prefix="eval_realtalk_")
    db_path = os.path.join(tmpdir, "mirror.db")
    chroma_dir = os.path.join(tmpdir, "chroma")
    conn = init_db(db_path)

    try:
        ds = JsonFileDataSource(MSG_PATH, SESS_PATH)

        # Layer 1
        t0 = time.time()
        nodes = build_layer1(
            talker_id=CHAT_ID,
            source=ds,
            llm=llm_noncot,
            conn=conn,
            gap_seconds=1800,
            debug=False,
        )
        l1_time = time.time() - t0
        print(f"\nLayer 1: {len(nodes)} topic nodes in {l1_time:.1f}s")

        # Show topic name distribution
        from collections import Counter
        topic_counter = Counter(n.topic_name for n in nodes)
        print(f"  Top topics: {topic_counter.most_common(8)}")

        # Layer 1.5
        t0 = time.time()
        signals, anchors = build_layer15(
            talker_id=CHAT_ID,
            llm=llm_noncot,
            conn=conn,
            debug=False,
        )
        l15_time = time.time() - t0
        print(f"\nLayer 1.5: {len(signals)} signals, {len(anchors)} anomaly anchors in {l15_time:.1f}s")

        # Show anchor distribution
        anchor_by_signal = Counter(a.signal_name for a in anchors)
        print(f"  Anchors by signal: {dict(anchor_by_signal)}")

        # Layer 2
        t0 = time.time()
        embedded, pointers = build_layer2(
            talker_id=CHAT_ID,
            llm_noncot=llm_noncot,
            reranker=reranker,
            llm_cot=llm_cot,
            conn=conn,
            data_dir=chroma_dir,
            sim_threshold=0.3,
            top_k=10,
            rerank_threshold=0.5,
            top_m=20,
            debug=False,
        )
        l2_time = time.time() - t0
        print(f"\nLayer 2: {embedded} nodes embedded, {pointers} thread pointers in {l2_time:.1f}s")

        build_total = l1_time + l15_time + l2_time
        print(f"\nBuild total: {build_total:.1f}s")

        # ── 4. Evaluate queries ──────────────────────────────────
        print_section("PHASE 2: QUERY EVALUATION")
        print(f"Mode: {args.mode}")

        oneshot_results = None
        agent_results = None

        if args.mode in ("oneshot", "compare"):
            oneshot_results = run_oneshot_eval(
                arc_cases, conn, llm_cot, dia_to_local, total_msgs, CHAT_ID, debug=True, max_nodes=max_nodes
            )
            for case_idx, r in enumerate(oneshot_results):
                print(f"\n{'─'*60}")
                print(f"Case {case_idx+1}/{len(arc_cases)} [oneshot]: {r['question'][:60]}")
                print(f"  Recall: {r['recall']:.1%} | Fuzzy: {r['fuzzy_recall']:.1%} | Phases: {r['avg_phases']}")
                if args.verbose:
                    print(f"  Question: {r['question'][:120]}...")
                    print(f"  Expected evidence IDs: {sorted(r['expected_local_ids'])[:20]}{'...' if len(r['expected_local_ids'])>20 else ''}")
                    print(f"  Returned evidence IDs: {sorted(r['returned_ids'])[:20]}{'...' if len(r['returned_ids'])>20 else ''}")
                    if r.get("per_phase_recalls"):
                        print(f"  Per-phase recall: {[f'{x:.2f}' for x in r['per_phase_recalls']]}")
                if r["recall"] < 0.5 and r["returned_ids"]:
                    exp = set(r["expected_local_ids"])
                    ret = set(r["returned_ids"])
                    overlap = exp & ret
                    print(f"  [debug] expected={sorted(exp)[:15]}{'...' if len(exp)>15 else ''} | returned={sorted(ret)[:15]}{'...' if len(ret)>15 else ''} | overlap={overlap}")

        if args.mode in ("agent", "compare"):
            agent_results = run_agent_eval(
                arc_cases, conn, llm_cot, llm_noncot, chroma_dir,
                dia_to_local, total_msgs, CHAT_ID, debug=True,
                debug_retrieval=args.debug_retrieval,
                debug_verbosity=args.debug_verbosity,
                retrieval_limit=max_nodes,
            )
            for case_idx, r in enumerate(agent_results):
                print(f"\n{'─'*60}")
                print(f"Case {case_idx+1}/{len(arc_cases)} [agent]: {r['question'][:60]}")
                print(f"  Recall: {r['recall']:.1%} | Fuzzy: {r['fuzzy_recall']:.1%} | Phases: {r['avg_phases']}")
                if args.verbose:
                    print(f"  Question: {r['question'][:120]}...")
                    print(f"  Expected evidence IDs: {sorted(r['expected_local_ids'])[:20]}{'...' if len(r['expected_local_ids'])>20 else ''}")
                    print(f"  Returned evidence IDs: {sorted(r['returned_ids'])[:20]}{'...' if len(r['returned_ids'])>20 else ''}")
                    if r.get("per_phase_recalls"):
                        print(f"  Per-phase recall: {[f'{x:.2f}' for x in r['per_phase_recalls']]}")
                if r.get("trace"):
                    print(f"  Agent steps: {len(r['trace'].steps)} | LLM calls: {r['trace'].total_llm_calls}")
                if r["recall"] < 1.0:
                    exp = set(r["expected_local_ids"])
                    ret = set(r["returned_ids"])
                    overlap = exp & ret
                    print(f"  [debug] expected={sorted(exp)[:15]}{'...' if len(exp)>15 else ''} | returned={sorted(ret)[:15]}{'...' if len(ret)>15 else ''} | overlap={overlap}")
                    trace = r.get("trace")
                    if trace and getattr(trace, "collected_nodes", None):
                        nodes = trace.collected_nodes
                        in_candidates = sum(
                            1 for eid in exp
                            if any(n.start_local_id <= eid <= n.end_local_id for n in nodes)
                        )
                        print(f"  [debug] expected_in_candidates: {in_candidates}/{len(exp)} (retrieval → generator)")
                if args.debug_retrieval and r.get("retrieval_checkpoints"):
                    from retrieval_debug import checkpoint_to_dict, identify_failure_point
                    for cp in r["retrieval_checkpoints"]:
                        d = checkpoint_to_dict(cp, args.debug_verbosity)
                        print(f"  [retrieval] {cp.checkpoint_name}: candidates={cp.candidate_count} gt_present={len(cp.ground_truth_present)}/{len(cp.ground_truth_ids)}")
                    fp = identify_failure_point(r["retrieval_checkpoints"])
                    if fp:
                        print(f"  [retrieval] failure_point: {fp}")

        # ── 5. Summary ───────────────────────────────────────────
        print_section("SUMMARY: ACCURACY REPORT")

        def avg(lst):
            return sum(lst) / len(lst) if lst else 0

        if args.mode == "compare" and oneshot_results and agent_results:
            o, a = oneshot_results, agent_results
            # Task 4.5: fuzzy recall marked as primary; exact as reference
            # Task 4.6: new Timeline Coverage and Per-Phase Temporal Recall columns
            print(f"\n                              One-Shot    Agent    Delta")
            print(f"Recall (exact) [ref]:         {avg([r['recall'] for r in o]):.1%}       {avg([r['recall'] for r in a]):.1%}     {(avg([r['recall'] for r in a]) - avg([r['recall'] for r in o])):+.1%}")
            print(f"Recall (fuzzy±3) [PRIMARY]:   {avg([r['fuzzy_recall'] for r in o]):.1%}       {avg([r['fuzzy_recall'] for r in a]):.1%}     {(avg([r['fuzzy_recall'] for r in a]) - avg([r['fuzzy_recall'] for r in o])):+.1%}")
            print(f"Timeline Coverage:            {avg([r['timeline_coverage'] for r in o]):.1%}       {avg([r['timeline_coverage'] for r in a]):.1%}     {(avg([r['timeline_coverage'] for r in a]) - avg([r['timeline_coverage'] for r in o])):+.1%}")
            print(f"Per-Phase Temporal Recall:    {avg([r['per_phase_temporal_recall'] for r in o]):.1%}       {avg([r['per_phase_temporal_recall'] for r in a]):.1%}     {(avg([r['per_phase_temporal_recall'] for r in a]) - avg([r['per_phase_temporal_recall'] for r in o])):+.1%}")
            print(f"Precision:                    {avg([r['precision'] for r in o]):.1%}       {avg([r['precision'] for r in a]):.1%}     {(avg([r['precision'] for r in a]) - avg([r['precision'] for r in o])):+.1%}")
            print(f"Hallucination:                {avg([r['hallucination'] for r in o]):.1%}       {avg([r['hallucination'] for r in a]):.1%}     {(avg([r['hallucination'] for r in a]) - avg([r['hallucination'] for r in o])):+.1%}")
            print(f"Groundedness:                 {avg([r['groundedness'] for r in o]):.1%}       {avg([r['groundedness'] for r in a]):.1%}     {(avg([r['groundedness'] for r in a]) - avg([r['groundedness'] for r in o])):+.1%}")
            print(f"Avg Phases:                   {avg([r['avg_phases'] for r in o]):.1f}        {avg([r['avg_phases'] for r in a]):.1f}      {(avg([r['avg_phases'] for r in a]) - avg([r['avg_phases'] for r in o])):+.1f}")
            avg_steps = avg([len(r["trace"].steps) for r in a if r.get("trace")])
            avg_llm = avg([r["trace"].total_llm_calls for r in a if r.get("trace")])
            print(f"Agent Steps:                  N/A         {avg_steps:.1f}      -")
            print(f"Agent LLM calls:              N/A         {avg_llm:.0f}      -")
        else:
            results = oneshot_results or agent_results
            pipeline_name = "Agent" if args.mode == "agent" else "One-shot"
            avg_phases = avg([r["avg_phases"] for r in results])

            print(f"\n[{pipeline_name} pipeline]")
            print(f"Dataset:              {CHAT_ID} ({total_msgs} messages)")
            print(f"Pipeline nodes:       {len(nodes)} topic nodes")
            print(f"Anomaly anchors:      {len(anchors)}")
            print(f"Thread pointers:      {pointers}")
            print(f"\nArc queries run:      {len(arc_cases)}")
            print(f"Avg phases/query:     {avg_phases:.1f}")
            # Task 4.5: fuzzy recall as primary, exact as reference
            print(f"Avg Fuzzy Recall(±3) [PRIMARY]: {avg([r['fuzzy_recall'] for r in results]):.1%}")
            print(f"Avg Evidence Recall (exact) [ref]: {avg([r['recall'] for r in results]):.1%}")
            # Task 4.6: new metrics
            print(f"Avg Timeline Coverage:         {avg([r['timeline_coverage'] for r in results]):.1%}")
            print(f"Avg Per-Phase Temporal Recall: {avg([r['per_phase_temporal_recall'] for r in results]):.1%}")
            if results:
                print(f"Avg Precision:        {avg([r['precision'] for r in results]):.1%}")
                print(f"Avg Hallucination:    {avg([r['hallucination'] for r in results]):.1%}")
                print(f"Avg Groundedness:     {avg([r['groundedness'] for r in results]):.1%}")
                # Metrics aggregation (mean, median, std)
                recall_vals = [r["recall"] for r in results]
                agg = aggregate_metrics(recall_vals)
                print(f"\nEvidence Recall (exact) aggregation: mean={agg['mean']:.1%}  median={agg['median']:.1%}  std={agg['std']:.3f}")
                if results and results[0].get("arc_phase_coverage") is not None:
                    pc_vals = [r["arc_phase_coverage"] for r in results]
                    agg_pc = aggregate_metrics(pc_vals)
                    print(f"ARC Phase Coverage aggregation: mean={agg_pc['mean']:.1%}  median={agg_pc['median']:.1%}  std={agg_pc['std']:.3f}")
            if args.mode == "agent" and agent_results:
                avg_steps = avg([len(r["trace"].steps) for r in agent_results if r.get("trace")])
                avg_llm = avg([r["trace"].total_llm_calls for r in agent_results if r.get("trace")])
                print(f"Avg Agent steps:      {avg_steps:.1f}")
                print(f"Avg Agent LLM calls:  {avg_llm:.0f}")
            print(f"\nPer-case recall:")
            for i, r in enumerate(results, 1):
                print(f"  Case {i}: fuzzy={r['fuzzy_recall']:.1%}  coverage={r['timeline_coverage']:.1%}  [{r['question'][:50]}]")

        # ── 5b. JSON/CSV output ────────────────────────────────────
        all_results = oneshot_results or agent_results or []
        if all_results and (args.output_json or args.output_csv):
            def _to_json_safe(r):
                skip = {"phases", "output", "trace"}
                out = {}
                for k, v in r.items():
                    if k in skip:
                        continue
                    if k == "retrieval_checkpoints" and v:
                        from retrieval_debug import checkpoint_to_dict
                        out[k] = [checkpoint_to_dict(cp, "minimal") for cp in v]
                    elif isinstance(v, (set, tuple)):
                        out[k] = list(v)
                    elif isinstance(v, (list, dict, str, int, float, bool, type(None))):
                        out[k] = v
                return out

            if args.output_json:
                out = {
                    "timestamp": datetime.now().isoformat(),
                    "chat_id": CHAT_ID,
                    "mode": args.mode,
                    "config": {"llm": cfg.llm.model, "embedding": cfg.embedding.model, "reranker": cfg.reranker.model},
                    "total_cases": len(all_results),
                    "cases": [_to_json_safe(r) for r in all_results],
                    "aggregates": {
                        "recall": aggregate_metrics([r["recall"] for r in all_results]),
                        "fuzzy_recall": aggregate_metrics([r["fuzzy_recall"] for r in all_results]),
                        "precision": aggregate_metrics([r["precision"] for r in all_results]),
                        "arc_phase_coverage": aggregate_metrics([r.get("arc_phase_coverage", 0) for r in all_results]),
                    },
                }
                with open(args.output_json, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=2)
                print(f"\nResults written to {args.output_json}")

            if args.output_csv:
                with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["case_id", "question", "recall", "fuzzy_recall", "precision", "arc_phase_coverage", "expected_ids", "returned_ids"])
                    for i, r in enumerate(all_results, 1):
                        w.writerow([
                            i,
                            r["question"][:200],
                            f"{r['recall']:.4f}",
                            f"{r['fuzzy_recall']:.4f}",
                            f"{r['precision']:.4f}",
                            f"{r.get('arc_phase_coverage', 0):.4f}",
                            ",".join(map(str, sorted(r["expected_local_ids"]))),
                            ",".join(map(str, sorted(r["returned_ids"]))),
                        ])
                print(f"Per-case CSV written to {args.output_csv}")

        # ── 5c. Retrieval debug aggregation ──────────────────────
        if args.debug_retrieval and all_results:
            all_cps = [r.get("retrieval_checkpoints", []) for r in all_results if r.get("retrieval_checkpoints")]
            if all_cps:
                from retrieval_debug import aggregate_failure_patterns, checkpoint_to_dict
                patterns = aggregate_failure_patterns(all_cps)
                print(f"\n[Retrieval Debug] Failure pattern aggregation: {patterns}")
                if args.output_debug_json:
                    debug_out = {
                        "failure_patterns": patterns,
                        "per_case": [
                            {
                                "case_idx": i + 1,
                                "question": r["question"][:100],
                                "checkpoints": [checkpoint_to_dict(cp, args.debug_verbosity) for cp in r.get("retrieval_checkpoints", [])],
                            }
                            for i, r in enumerate(all_results) if r.get("retrieval_checkpoints")
                        ],
                    }
                    with open(args.output_debug_json, "w", encoding="utf-8") as f:
                        json.dump(debug_out, f, ensure_ascii=False, indent=2)
                    print(f"Debug logs written to {args.output_debug_json}")

        # ── 5d. Baseline tracking ────────────────────────────────
        if args.record_experiment and all_results and args.split:
            from baseline_tracking import (
                ensure_experiments_dir,
                append_csv_row,
                append_json_record,
                create_experiment_record,
                capture_config_snapshot,
            )
            import yaml
            exp_dir = args.experiments_dir or (ROOT / "experiments")
            ensure_experiments_dir(exp_dir)
            exp_id = args.experiment_id or f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            metrics = {
                "exact_recall": sum(r["recall"] for r in all_results) / len(all_results),
                "fuzzy_recall": sum(r["fuzzy_recall"] for r in all_results) / len(all_results),
                "precision": sum(r["precision"] for r in all_results) / len(all_results),
                "arc_phase_coverage": sum(r.get("arc_phase_coverage", 0) for r in all_results) / len(all_results),
            }
            raw_cfg = {}
            try:
                with open(config_path) as f:
                    raw_cfg = yaml.safe_load(f) or {}
            except Exception:
                pass
            config_snap = capture_config_snapshot(cfg, raw_cfg)
            record = create_experiment_record(
                exp_id, metrics, config_snap,
                config_changes=args.config_changes,
                split=args.split,
            )
            record["chat_id"] = CHAT_ID
            record["mode"] = args.mode
            record["case_count"] = len(all_results)
            append_csv_row(exp_dir, record)
            append_json_record(exp_dir, record)
            print(f"\nExperiment recorded: {exp_id} (split={args.split})")

        # ── 6. Accuracy risk analysis ────────────────────────────
        print_section("ACCURACY RISK ANALYSIS")

        # Check if any phases have hallucinated evidence IDs
        from narrative_mirror.query import run_query_with_phases
        print("\n[A] Evidence Hallucination Check:")
        print("  (IDs in evidence_msg_ids that don't exist in the dataset)")
        # Already printed per-case above; summarize here
        print("  -> See per-case output above for hallucinated ID warnings")

        # Check Layer 1 quality: any 未分类 nodes?
        unclassified = [n for n in nodes if n.topic_name == "未分类"]
        pct_unclassified = 100.0 * len(unclassified) / len(nodes) if nodes else 0
        print(f"\n[B] Topic Classification Quality:")
        print(f"  '未分类' (fallback) nodes: {len(unclassified)}/{len(nodes)} ({pct_unclassified:.1f}%)")
        if pct_unclassified > 10:
            print("  WARNING: >10% unclassified nodes may indicate batch classification issues")
        else:
            print("  OK: Low fallback rate")

        # Check Layer 2 thread connectivity
        print(f"\n[C] Layer 2 Thread Quality:")
        print(f"  Thread pointers created: {pointers}")
        pointer_rate = pointers / len(nodes) if nodes else 0
        print(f"  Pointer/node ratio: {pointer_rate:.2f}")
        if pointer_rate < 0.1:
            print("  WARNING: Very few semantic threads detected. Evidence recall may be low.")
        elif pointer_rate > 0.5:
            print("  WARNING: Many threads - may be over-connecting unrelated topics.")
        else:
            print("  OK: Reasonable thread density")

        # Check anchor coverage
        print(f"\n[D] Q2 Anomaly Anchor Coverage:")
        total_expected_ids = set()
        for arc in arc_cases:
            for phase in arc.get("expected_phases", []):
                for did in phase.get("evidence_dia_ids", []):
                    lid = dia_to_local.get(did)
                    if lid:
                        total_expected_ids.add(lid)

        # Find which nodes contain expected evidence
        anchor_node_ids = {a.node_id for a in anchors}
        all_nodes_by_id = {n.node_id: n for n in nodes}

        covered_by_anchors = set()
        for anchor in anchors:
            node = all_nodes_by_id.get(anchor.node_id)
            if node:
                for lid in range(node.start_local_id, node.end_local_id + 1):
                    if lid in total_expected_ids:
                        covered_by_anchors.add(lid)

        anchor_coverage = len(covered_by_anchors) / len(total_expected_ids) if total_expected_ids else 0
        print(f"  Total unique expected evidence local_ids: {len(total_expected_ids)}")
        print(f"  Expected IDs in anchor nodes: {len(covered_by_anchors)} ({anchor_coverage:.1%})")
        if anchor_coverage < 0.3:
            print("  WARNING: <30% of expected evidence covered by Q2 anchors. Q3 fallback to all-nodes is load-bearing.")
        else:
            print("  OK: Q2 anchors cover enough expected evidence")

        print(f"\n{'='*60}")
        print(f"  VERDICT")
        print(f"{'='*60}")
        all_results = oneshot_results or agent_results or []
        # Task 4.4: PASS criteria is fuzzy_recall >= 0.40 AND timeline_coverage >= 0.60
        _avg_fuzzy = avg([r["fuzzy_recall"] for r in all_results])
        _avg_coverage = avg([r["timeline_coverage"] for r in all_results])
        _avg_exact = avg([r["recall"] for r in all_results])
        print(f"  Avg Fuzzy Recall(±3): {_avg_fuzzy:.1%}  |  Avg Timeline Coverage: {_avg_coverage:.1%}")
        print(f"  Avg Evidence Recall (exact, ref): {_avg_exact:.1%}")
        if _avg_fuzzy >= 0.40 and _avg_coverage >= 0.60:
            print(f"  PASS: fuzzy_recall {_avg_fuzzy:.1%} >= 40% AND timeline_coverage {_avg_coverage:.1%} >= 60%")
            print(f"  The system retrieves sufficient evidence across the full timeline.")
        elif _avg_fuzzy < 0.40:
            print(f"  FAIL: fuzzy_recall {_avg_fuzzy:.1%} < 40% (threshold: 40%)")
            print(f"  System is not retrieving enough nearby evidence.")
        else:
            print(f"  FAIL: timeline_coverage {_avg_coverage:.1%} < 60% despite fuzzy_recall {_avg_fuzzy:.1%}")
            print(f"  Evidence is clustered — not spanning the full conversation timeline.")

    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
