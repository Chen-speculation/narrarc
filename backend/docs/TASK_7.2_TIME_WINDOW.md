# Task 7.2: Time Window for Candidate Expansion — Investigation

**Date**: 2026-02-24  
**Status**: Time window is **not** exposed in config. Code changes required before running experiments.

---

## 1. Finding: Time Window Is Not Configurable

A search of the narrarc backend codebase shows that **no time window parameter for candidate expansion is exposed** in `config.yaml` or in the tools/query pipeline.

### Current Config (`eval.query`)

| Parameter            | Configurable | Location                          |
|----------------------|--------------|-----------------------------------|
| `q3_candidate_limit` | Yes          | `config.yaml` → `eval.query`      |
| `semantic_top_k`     | Yes          | `config.yaml` → `eval.query`      |
| `reranker_threshold` | Yes          | `config.yaml` → `eval.query`      |
| **time_window**      | **No**       | Not present                       |

### Relevant Code Locations (Hardcoded)

| Location | What | Current Value |
|----------|------|---------------|
| `tools.py` → `stratified_sample()` | Time buckets for overview sampling | `n_buckets = min(8, max(4, limit // 8))` |
| `tools.py` → `time_diversified_search()` | Time buckets for semantic diversification | `n_buckets = 4` |
| `query.py` → `expand_candidates()` | No time filter; uses anchors + thread neighbors | No time window |

### Interpretation of "Time Window"

For candidate expansion, "time window" could mean:

1. **Time bucket count** for stratified sampling / time diversification:  
   - `stratified_sample` uses 4–8 buckets to spread candidates across the timeline.  
   - `time_diversified_search` uses 4 buckets for semantic search diversification.  
   - More buckets → finer temporal spread; fewer buckets → coarser temporal spread.

2. **Anchor expansion window** (not implemented):  
   - Include nodes within ±N days of each anchor’s timestamp.  
   - Currently: all thread neighbors are included regardless of time distance.

3. **Semantic search time diversification** (partially):  
   - `time_diversified_search` uses 4 buckets; `top_k` is configurable via `semantic_top_k`.

---

## 2. Suggested Code Changes for Task 7.2

To make time window configurable and run experiments:

### 2.1 Add `eval.query.time_window` to config.yaml

```yaml
# config.yaml
eval:
  query:
    q3_candidate_limit: 80
    semantic_top_k: 15
    reranker_threshold: 0.5
    # Time diversification: number of buckets for stratified sampling and time_diversified_search
    time_window: 4   # e.g. 4, 6, 8 — more buckets = finer temporal spread
```

**Alternative naming** (if more specific):  
- `time_bucket_count` or `time_diversification_buckets`

### 2.2 Update `tools.py`

1. **`stratified_sample`**  
   - Add `n_buckets` parameter (or `time_window`).  
   - Pass from caller or config.

2. **`time_diversified_search`**  
   - Pass `n_buckets` parameter (or `time_window`).  
   - Replace hardcoded `n_buckets = 4` with the passed value.

3. **`retrieve_by_scope`**  
   - Accept `time_window` (or `n_buckets`).  
   - Call `stratified_sample` and `time_diversified_search` with the configured value.

### 2.3 Update `eval_realtalk_accuracy.py`

- Load `time_window` from `query_cfg.get("time_window", 4)`.
- Pass it into the workflow (agent mode) and one-shot pipeline.

### 2.4 Update `workflow.py` and `query.py`

- Accept `time_window` where `retrieve_by_scope` / `expand_candidates` are invoked.
- Pass it through to `retrieve_by_scope` and `stratified_sample` / `time_diversified_search`.

### 2.5 Update `baseline_tracking.py`

- In `capture_config_snapshot`, add `time_window` to the snapshot so experiments record it.

---

## 3. Experiment Run Plan (After Implementation)

1. Add `eval.query.time_window: 4` (baseline) to `config.yaml`.
2. Run eval with `--train-only --record-experiment --experiment-id time_window_4`.
3. Change to `time_window: 6` and run again.
4. Change to `time_window: 8` and run again.
5. Compare `train_exact_recall` across experiments.
6. Record results in `experiments.jsonl` and `baseline_metrics.csv`.

---

## 4. Files to Modify

| File | Change |
|------|--------|
| `config.yaml` | Add `eval.query.time_window` |
| `src/narrative_mirror/tools.py` | Add `n_buckets`/`time_window` to `stratified_sample`, `time_diversified_search`, `retrieve_by_scope` |
| `src/narrative_mirror/workflow.py` | Pass `time_window` into retrieval |
| `scripts/eval_realtalk_accuracy.py` | Load and pass `time_window` |
| `scripts/baseline_tracking.py` | Include `time_window` in config snapshot |

---

## 5. Summary

- **Time window is not configurable.**
- Implement the changes above to expose it and run experiments.
- Use `time_window` (or `time_bucket_count`) as the number of time buckets for diversification and stratified sampling.
