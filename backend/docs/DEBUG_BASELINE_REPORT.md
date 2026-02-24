# Baseline Evaluation Debug Report

**Date:** 2026-02-24
**Command:** python scripts/run_realtalk_eval.py --train-only --record-experiment --experiment-id debug_baseline --debug-retrieval --limit-cases 2
**Working dir:** c:\Users\Administrator\narrarc\backend
**Python:** .venv\Scripts\python.exe

---

## 1. Run Summary

- **Train files processed:** 2 (Chat_1_Emi_Elise, Chat_2_Kevin_Elise)
- **Arc cases per file:** 2 (limited)
- **Total cases:** 4
- **Recorded metrics:** exact_recall=0.5188, fuzzy_recall=0.6632

### Runtime Error (Non-blocking)

The eval hit httpx.HTTPStatusError: 400 Bad Request for api.siliconflow.cn/v1/rerank during Layer 2 build (stage1_5_rerank). The pipeline used cached outputs from prior runs, so the experiment was still recorded.

---

## 2. Retrieval Checkpoint Presence

Debug output is written to experiments/debug_baseline.json (copied to docs/debug_baseline_retrieval.json).

**Checkpoints logged:** candidate_generation, post_retrieval, final_selection

---

## 3. Failure Point Analysis

From debug_baseline.json: failure_patterns.failure_at_checkpoint.final_selection = 2

Case 1: candidate_generation 468 candidates, 6/6 GT present. post_retrieval 468, 6/6. final_selection 9, only 2/6 (missing 64,6,90,91).

Case 2: candidate_generation 468, 7/7. post_retrieval 468, 7/7. final_selection 15, 6/7 (missing 266).

---

## 4. Conclusion

- Retrieval checkpoints: Present and logged.
- Failure point: final_selection - GT present in candidate_generation and post_retrieval but dropped when reducing to top-k.
- Root cause: Rerank/filter step discards relevant evidence. Consider increasing top_m or adjusting reranker thresholds.

---

## 5. Artifacts

- Full run log: backend/docs/debug_baseline_run.txt
- Retrieval debug JSON: backend/docs/debug_baseline_retrieval.json
- Experiment record: backend/experiments/debug_baseline.json
