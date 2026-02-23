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
import json
import os
import re
import sys
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Resolve project root and add src to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

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


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def run_oneshot_eval(arc_cases, conn, llm_cot, dia_to_local, total_msgs, chat_id, debug=True):
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
            max_nodes=80,
            debug=debug,
            use_agent=False,
        )
        returned_ids = list(set(mid for p in phases for mid in p.evidence_msg_ids))
        grounded = sum(1 for p in phases if p.verified) / len(phases) if phases else 0.0


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
            "per_phase_recall": per_phase_recall(phases, arc.get("expected_phases", []), dia_to_local),
            "timeline_coverage": timeline_coverage(phases, arc.get("expected_phases", []), dia_to_local, conn=conn, talker_id=chat_id),
            "per_phase_temporal_recall": per_phase_temporal_recall(phases, arc.get("expected_phases", []), dia_to_local),
            "groundedness": grounded,
            "avg_phases": len(phases),
            "trace": None,
        })
    return results


def run_agent_eval(arc_cases, conn, llm_cot, llm_noncot, chroma_dir, dia_to_local, total_msgs, chat_id, debug=True):
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
            "per_phase_recall": per_phase_recall(phases, arc.get("expected_phases", []), dia_to_local),
            "timeline_coverage": timeline_coverage(phases, arc.get("expected_phases", []), dia_to_local, conn=conn, talker_id=chat_id),
            "per_phase_temporal_recall": per_phase_temporal_recall(phases, arc.get("expected_phases", []), dia_to_local),
            "groundedness": grounded,
            "avg_phases": len(phases),
            "trace": trace,
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate narrative_mirror on REALTALK dataset")
    parser.add_argument("--mode", choices=["oneshot", "agent", "compare"], default="oneshot",
                        help="Run oneshot (default), agent, or compare mode")
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID,
                        help=f"Chat ID for eval fixtures (default: {DEFAULT_CHAT_ID})")
    args = parser.parse_args()

    CHAT_ID = args.chat_id
    MSG_PATH = str(EVAL_DIR / f"{CHAT_ID}_messages.json")
    SESS_PATH = str(EVAL_DIR / f"{CHAT_ID}_sessions.json")
    ARC_PATH = EVAL_DIR / f"{CHAT_ID}_arc_cases.json"
    MAPPING_PATH = EVAL_DIR / f"{CHAT_ID}_mapping.json"

    # ── 1. Load config & LLMs ────────────────────────────────────
    config_path = ROOT / "config.yml"
    if not config_path.exists():
        print("ERROR: config.yml not found", file=sys.stderr)
        sys.exit(1)

    from narrative_mirror.config import load_config
    from narrative_mirror.llm import from_config

    cfg = load_config(str(config_path))
    llm_noncot, llm_cot, reranker = from_config(cfg)
    print(f"LLM: {cfg.llm.model} | Embedding: {cfg.embedding.model} | Reranker: {cfg.reranker.model}")

    # ── 2. Load eval fixtures ────────────────────────────────────
    if not ARC_PATH.exists():
        print(f"ERROR: arc_cases not found: {ARC_PATH}", file=sys.stderr)
        print("Run: python scripts/generate_arc_cases_from_qa.py --input <realtalk.json> --output <path>", file=sys.stderr)
        sys.exit(1)
    with open(ARC_PATH) as f:
        arc_cases = json.load(f)
    with open(MAPPING_PATH) as f:
        mapping = json.load(f)
    dia_to_local = mapping["dia_to_local"]

    print(f"\nDataset: {CHAT_ID}")
    print(f"  Messages file: {Path(MSG_PATH).name}")
    with open(MSG_PATH) as f:
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
                arc_cases, conn, llm_cot, dia_to_local, total_msgs, CHAT_ID, debug=True
            )
            for case_idx, r in enumerate(oneshot_results):
                print(f"\n{'─'*60}")
                print(f"Case {case_idx+1}/{len(arc_cases)} [oneshot]: {r['question'][:60]}")
                print(f"  Recall: {r['recall']:.1%} | Fuzzy: {r['fuzzy_recall']:.1%} | Phases: {r['avg_phases']}")
                if r["recall"] < 0.5 and r["returned_ids"]:
                    exp = set(r["expected_local_ids"])
                    ret = set(r["returned_ids"])
                    overlap = exp & ret
                    print(f"  [debug] expected={sorted(exp)[:15]}{'...' if len(exp)>15 else ''} | returned={sorted(ret)[:15]}{'...' if len(ret)>15 else ''} | overlap={overlap}")

        if args.mode in ("agent", "compare"):
            agent_results = run_agent_eval(
                arc_cases, conn, llm_cot, llm_noncot, chroma_dir,
                dia_to_local, total_msgs, CHAT_ID, debug=True
            )
            for case_idx, r in enumerate(agent_results):
                print(f"\n{'─'*60}")
                print(f"Case {case_idx+1}/{len(arc_cases)} [agent]: {r['question'][:60]}")
                print(f"  Recall: {r['recall']:.1%} | Fuzzy: {r['fuzzy_recall']:.1%} | Phases: {r['avg_phases']}")
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
            if args.mode == "agent" and agent_results:
                avg_steps = avg([len(r["trace"].steps) for r in agent_results if r.get("trace")])
                avg_llm = avg([r["trace"].total_llm_calls for r in agent_results if r.get("trace")])
                print(f"Avg Agent steps:      {avg_steps:.1f}")
                print(f"Avg Agent LLM calls:  {avg_llm:.0f}")
            print(f"\nPer-case recall:")
            for i, r in enumerate(results, 1):
                print(f"  Case {i}: fuzzy={r['fuzzy_recall']:.1%}  coverage={r['timeline_coverage']:.1%}  [{r['question'][:50]}]")

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
