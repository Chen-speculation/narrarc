"""Profile each pipeline stage: wall time + API call count."""
import time, os, sqlite3
from pathlib import Path
from narrative_mirror.config import load_config
from narrative_mirror.llm import from_config
from narrative_mirror.db import init_db, upsert_anchors
from narrative_mirror.datasource import JsonFileDataSource
from narrative_mirror.build import build_layer1
from narrative_mirror.metadata import compute_all_metadata, detect_anomalies
from narrative_mirror.layer2 import build_layer2
from narrative_mirror.query import run_query

# Monkey-patch to count API calls
call_counts = {"llm_complete": 0, "llm_think": 0, "embed": 0, "rerank": 0}
call_times = {"llm_complete": 0.0, "llm_think": 0.0, "embed": 0.0, "rerank": 0.0}

def patch_llm(noncot, cot, reranker):
    orig_complete = noncot.complete
    orig_embed = noncot.embed
    orig_think = cot.think_and_complete
    orig_rerank = reranker.rerank

    def wrapped_complete(*a, **kw):
        t = time.time()
        r = orig_complete(*a, **kw)
        call_times["llm_complete"] += time.time() - t
        call_counts["llm_complete"] += 1
        return r

    def wrapped_embed(*a, **kw):
        t = time.time()
        r = orig_embed(*a, **kw)
        call_times["embed"] += time.time() - t
        call_counts["embed"] += 1
        return r

    def wrapped_think(*a, **kw):
        t = time.time()
        r = orig_think(*a, **kw)
        call_times["llm_think"] += time.time() - t
        call_counts["llm_think"] += 1
        return r

    def wrapped_rerank(*a, **kw):
        t = time.time()
        r = orig_rerank(*a, **kw)
        call_times["rerank"] += time.time() - t
        call_counts["rerank"] += 1
        return r

    noncot.complete = wrapped_complete
    noncot.embed = wrapped_embed
    cot.think_and_complete = wrapped_think
    reranker.rerank = wrapped_rerank

cfg = load_config("config.yml")
noncot, cot, reranker = from_config(cfg)
patch_llm(noncot, cot, reranker)

for f in ["profile_mirror.db"]:
    if os.path.exists(f): os.remove(f)
import shutil
if os.path.exists("profile_chroma"): shutil.rmtree("profile_chroma")

conn = init_db("profile_mirror.db")
ds = JsonFileDataSource(str(Path("tests/data/weflow_messages.json")), str(Path("tests/data/weflow_sessions.json")))
TID = "wxid_ta_001"

def reset():
    for k in call_counts: call_counts[k] = 0
    for k in call_times: call_times[k] = 0.0

def report(stage):
    total_calls = sum(call_counts.values())
    total_api_time = sum(call_times.values())
    print(f"  API calls: {dict(call_counts)}  total={total_calls}")
    print(f"  API time:  {dict({k: f'{v:.1f}s' for k,v in call_times.items()})}  total={total_api_time:.1f}s")

reset()
t0 = time.time()
nodes = build_layer1(TID, ds, noncot, conn)
print(f"\nLayer 1: {time.time()-t0:.1f}s  ({len(nodes)} nodes)")
report("L1")

reset()
t0 = time.time()
signals = compute_all_metadata(TID, noncot, conn)
print(f"\nLayer 1.5: {time.time()-t0:.1f}s  ({len(signals)} signals)")
report("L1.5")

reset()
t0 = time.time()
anchors = detect_anomalies(signals, TID)
upsert_anchors(conn, anchors)
print(f"\nAnomalies: {time.time()-t0:.1f}s  ({len(anchors)} anchors)")

reset()
t0 = time.time()
embedded, pointers = build_layer2(TID, noncot, reranker, cot, conn, "profile_chroma", sim_threshold=0.1, rerank_threshold=0.2)
print(f"\nLayer 2: {time.time()-t0:.1f}s  ({embedded} embedded, {pointers} pointers)")
report("L2")

reset()
t0 = time.time()
result = run_query(question="我们是怎么一步步分手的？", talker_id=TID, llm=cot, conn=conn)
print(f"\nQuery: {time.time()-t0:.1f}s")
report("Query")

conn.close()
