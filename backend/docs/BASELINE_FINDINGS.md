# Baseline Findings: Evidence Recall Accuracy

This document summarizes baseline metrics, primary failure modes, and failure patterns for the Narrative Mirror evidence recall system on the RealTalk dataset. It supports tasks 5.4 and 5.5 in [openspec/changes/improve-evidence-recall-accuracy/tasks.md](../../openspec/changes/improve-evidence-recall-accuracy/tasks.md).

---

## 1. Baseline Metrics

Source: `backend/experiments/baseline_metrics.csv`, `backend/experiments/experiments.jsonl`

### Train Set (ARC Cases, N=4)

| Metric | Value | Notes |
|--------|-------|-------|
| **Exact Recall** | ~52% | `|returned ∩ expected| / |expected|` |
| **Fuzzy Recall** | ~66–70% | ±3 message tolerance |
| **Precision** | ~34–39% | Fraction of returned evidence that is correct |
| **ARC Phase Coverage** | ~71–75% | Fraction of expected phases with at least one hit |

### Test Set

| Metric | Value | Notes |
|--------|-------|-------|
| **Exact Recall** | 0% | No test run recorded yet |
| **Fuzzy Recall** | 0% | |
| **Precision** | 0% | |
| **ARC Phase Coverage** | 0% | |

*Test metrics are 0 because baseline evaluation has only been run on the train set (Chat_1–7). Test set (Chat_8–10) has not been evaluated.*

### Experiment Configuration (baseline_001)

- **experiment_id**: baseline_001
- **config_snapshot**: `q3_candidate_limit=80`, `reranker_threshold=0.5`
- **split**: train
- **case_count**: 4 ARC cases

---

## 2. Primary Failure Mode: Ranking / Selection vs Candidates Missing

Source: `backend/experiments/debug_baseline.json` (retrieval debug logs from 2 failing train cases)

### Summary

**Primary failure mode: ranking / selection issue**, not candidates missing.

In both debug cases, ground truth evidence was **present** at both `candidate_generation` and `post_retrieval` checkpoints. Evidence was **lost** at `final_selection`, where the LLM/Generator chooses which evidence IDs to include in the narrative output.

### Checkpoint Definitions

| Checkpoint | Description |
|------------|-------------|
| **candidate_generation** | Q3/Retriever output — candidate nodes before any filtering |
| **post_retrieval** | After reranking (same as candidates in arc_narrative path) |
| **final_selection** | Evidence IDs selected by Generator (Q4/LLM) for the narrative |

### Per-Case Evidence

**Case 1** — "How did Kate's cooking skills evolve throughout the conversations?"

| Checkpoint | Ground Truth | Present | Missing |
|------------|--------------|---------|---------|
| candidate_generation | [64, 6, 474, 470, 90, 91] | All 6 | — |
| post_retrieval | [64, 6, 474, 470, 90, 91] | All 6 | — |
| final_selection | [64, 6, 474, 470, 90, 91] | [474, 470] | [64, 6, 90, 91] |

→ 4 of 6 ground truth IDs dropped at final selection.

**Case 2** — "How did Emily's interest in art develop over the conversations?"

| Checkpoint | Ground Truth | Present | Missing |
|------------|--------------|---------|---------|
| candidate_generation | [68, 70, 262, 266, 268, 271, 62] | All 7 | — |
| post_retrieval | [68, 70, 262, 266, 268, 271, 62] | All 7 | — |
| final_selection | [68, 70, 262, 266, 268, 271, 62] | [68, 70, 262, 268, 271, 62] | [266] |

→ 1 of 7 ground truth IDs dropped at final selection.

---

## 3. Failure Patterns from Checkpoint Aggregation

Source: `backend/experiments/debug_baseline.json` → `aggregate_failure_patterns()` in `retrieval_debug.py`

```json
{
  "failure_at_checkpoint": {
    "final_selection": 2
  }
}
```

### Interpretation

- **100% of failures** occur at `final_selection`.
- **0%** at `candidate_generation` (candidates missing).
- **0%** at `post_retrieval` (reranking dropping ground truth).

### Implications

1. **Retrieval pipeline (Q3/Retriever)** is bringing ground truth into the candidate set.
2. **Reranker** is not filtering out ground truth in these cases.
3. **Generator (Q4/LLM)** is the bottleneck: it receives correct candidates but selects a subset that omits some ground truth evidence.

### Recommended Focus (per tasks 5.4, 5.5)

- Refine **LLM grading/selection prompts** (agent mode) so the Generator retains more relevant evidence.
- Consider **passing more context** (e.g., candidate count, phase structure) to the Generator.
- Evaluate **evidence selection heuristics** (e.g., top-k by relevance vs. LLM choice).

---

## 4. Relation to OpenSpec Tasks

| Task | Description | Status |
|------|-------------|--------|
| **5.4** | Analyze debug logs to identify primary failure mode (candidates missing vs ranking issue) | Done — primary mode: **ranking/selection** at final_selection |
| **5.5** | Document baseline findings and failure patterns | Done — this document |

---

## 5. References

- [ACCURACY_IMPROVEMENT_TASK.md](./ACCURACY_IMPROVEMENT_TASK.md) — evaluation context, metrics, dataset split
- [openspec/changes/improve-evidence-recall-accuracy/tasks.md](../../openspec/changes/improve-evidence-recall-accuracy/tasks.md) — task 5.4, 5.5
- [retrieval-debugging spec](../../openspec/changes/improve-evidence-recall-accuracy/specs/retrieval-debugging/spec.md) — checkpoint logging design
