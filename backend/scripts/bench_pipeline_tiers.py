"""Tiered pipeline benchmark: small / medium / large datasets.

Usage:
    uv run python scripts/bench_pipeline_tiers.py [small|medium|large|all]
"""

import sys, os, time, shutil, tempfile, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narrative_mirror.config import load_config
from narrative_mirror.llm import from_config
from narrative_mirror.db import init_db, upsert_anchors
from narrative_mirror.datasource import JsonFileDataSource
from narrative_mirror.build import build_layer1
from narrative_mirror.metadata import compute_all_metadata, detect_anomalies
from narrative_mirror.layer2 import build_layer2
from narrative_mirror.query import run_query

BASE = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(BASE, "tests", "data")
REALTALK = os.path.join(DATA, "realtalk_eval")


def load_arc_questions(path: str) -> list[str]:
    if not os.path.exists(path):
        return ["How did the relationship evolve over time?"]
    with open(path) as f:
        cases = json.load(f)
    return [c["question"] for c in cases[:3]]


cfg = load_config(os.path.join(BASE, "config.yml"))
noncot, cot, reranker = from_config(cfg)

TIERS = {
    "small": {
        "name": "weflow_fixture (20 msgs)",
        "messages": os.path.join(DATA, "weflow_messages.json"),
        "sessions": os.path.join(DATA, "weflow_sessions.json"),
        "talker_id": "wxid_ta_001",
        "arc_questions": ["我们是怎么认识的？"],
    },
    "medium": {
        "name": "emi_elise (476 msgs)",
        "messages": os.path.join(REALTALK, "realtalk_emi_elise_messages.json"),
        "sessions": os.path.join(REALTALK, "realtalk_emi_elise_sessions.json"),
        "talker_id": "realtalk_emi_elise",
        "arc_questions": load_arc_questions(
            os.path.join(REALTALK, "realtalk_emi_elise_arc_cases.json")
        ),
    },
    "large": {
        "name": "nicolas_nebraas (1548 msgs)",
        "messages": os.path.join(REALTALK, "realtalk_nicolas_nebraas_messages.json"),
        "sessions": os.path.join(REALTALK, "realtalk_nicolas_nebraas_sessions.json"),
        "talker_id": "realtalk_nicolas_nebraas",
        "arc_questions": load_arc_questions(
            os.path.join(REALTALK, "realtalk_nicolas_nebraas_arc_cases.json")
        ),
    },
}


def run_tier(tier_name: str, tier: dict) -> dict:
    print(f"\n{'='*60}")
    print(f"[{tier_name.upper()}] {tier['name']}")
    print(f"{'='*60}")

    tmpdir = tempfile.mkdtemp(prefix=f"bench_{tier_name}_")
    db_path = os.path.join(tmpdir, "mirror.db")
    chroma_dir = os.path.join(tmpdir, "chroma")

    try:
        conn = init_db(db_path)
        ds = JsonFileDataSource(tier["messages"], tier["sessions"])

        # Layer 1
        t0 = time.time()
        nodes = build_layer1(tier["talker_id"], ds, noncot, conn)
        l1_time = time.time() - t0
        print(f"  Layer 1:   {l1_time:6.1f}s  ({len(nodes)} nodes)")

        # Layer 1.5
        t0 = time.time()
        signals = compute_all_metadata(tier["talker_id"], noncot, conn)
        anchors = detect_anomalies(signals, tier["talker_id"])
        upsert_anchors(conn, anchors)
        l15_time = time.time() - t0
        print(f"  Layer 1.5: {l15_time:6.1f}s  ({len(signals)} signals, {len(anchors)} anchors)")

        # Layer 2
        t0 = time.time()
        embedded, pointers = build_layer2(
            tier["talker_id"], noncot, reranker, cot, conn, chroma_dir,
            sim_threshold=0.1, rerank_threshold=0.2,
        )
        l2_time = time.time() - t0
        print(f"  Layer 2:   {l2_time:6.1f}s  ({embedded} embedded, {pointers} pointers)")

        build_total = l1_time + l15_time + l2_time

        # Query
        q_times = []
        for q in tier["arc_questions"]:
            t0 = time.time()
            run_query(q, tier["talker_id"], cot, conn)
            qt = time.time() - t0
            q_times.append(qt)
            print(f"  Query:     {qt:6.1f}s  \"{q[:55]}\"")

        q_avg = sum(q_times) / len(q_times) if q_times else 0
        total = build_total + sum(q_times)
        print(f"\n  BUILD={build_total:.1f}s  QUERY_avg={q_avg:.1f}s  TOTAL={total:.1f}s")

        conn.close()
        return {
            "tier": tier_name,
            "name": tier["name"],
            "nodes": len(nodes),
            "l1": l1_time, "l15": l15_time, "l2": l2_time,
            "build": build_total,
            "q_avg": q_avg, "q_count": len(q_times),
            "total": total,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    tiers_to_run = list(TIERS.keys()) if target == "all" else [target]

    results = []
    for t in tiers_to_run:
        if t not in TIERS:
            print(f"Unknown tier: {t}. Choose: {list(TIERS.keys())} or all")
            sys.exit(1)
        results.append(run_tier(t, TIERS[t]))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Tier':<8} {'Dataset':<30} {'Nodes':>5} {'L1':>7} {'L1.5':>7} {'L2':>7} {'Build':>7} {'Q_avg':>7} {'Total':>8}")
    print("-" * 88)
    for r in results:
        print(
            f"{r['tier']:<8} {r['name']:<30} {r['nodes']:>5} "
            f"{r['l1']:>6.1f}s {r['l15']:>6.1f}s {r['l2']:>6.1f}s "
            f"{r['build']:>6.1f}s {r['q_avg']:>6.1f}s {r['total']:>7.1f}s"
        )
