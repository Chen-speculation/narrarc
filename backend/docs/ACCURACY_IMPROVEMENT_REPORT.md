# Accuracy Improvement Report

Summary of evidence recall accuracy improvements for the Narrative Mirror system on the RealTalk dataset.

---

## Baseline vs Final Metrics

| Metric | Baseline | Final | Notes |
|--------|----------|-------|-------|
| QA Exact Recall (train) | TBD | TBD | |
| QA Exact Recall (test) | TBD | TBD | |
| QA Fuzzy Recall (train) | TBD | TBD | |
| QA Fuzzy Recall (test) | TBD | TBD | |
| QA Precision (train) | TBD | TBD | |
| QA Precision (test) | TBD | TBD | |
| ARC Global Recall (train) | TBD | TBD | |
| ARC Global Recall (test) | TBD | TBD | |
| ARC Phase Coverage (train) | TBD | TBD | |
| ARC Phase Coverage (test) | TBD | TBD | |

*Fill with actual values after running baseline and final evaluations.*

---

## Target Metrics

### QA Exact Recall

- **Definition**: `|returned ∩ expected| / |expected|` — fraction of ground truth evidence messages that appear in system output.
- **Target**: >30% on test set (short-term); ≥50% with Fuzzy–Exact gap <20% (mid-term).
- **Current baseline**: 0% (exact); Fuzzy Recall can be misleading (nearby messages counted).

### ARC Global Recall

- **Definition**: For ARC cases, flatten all `expected_phases[i].evidence_dia_ids` into one set; compute exact recall vs system’s returned evidence across all phases.
- **Target**: ≥30% on train set (short-term); ≥50% on test set (validation).
- **Note**: ARC cases test cross-timeline narrative evolution; fewer cases per conversation than QA.

### ARC Phase Coverage

- **Definition**: Fraction of expected phases where `per_phase_recall > 0` (i.e., at least one evidence message from that phase is returned).
- **Target**: ≥60% (mid-term).
- **Note**: Indicates whether the system covers all narrative phases or collapses evidence into fewer phases.

---

## Run Instructions for Final Validation (Task 8.2)

From the `backend` directory:

```bash
cd backend
python scripts/run_realtalk_eval.py --test-only --record-experiment --experiment-id final_test
```

This runs evaluation on the test set (Chat_8, Chat_9, Chat_10) and records metrics to the baseline tracking system. Ensure `REALTALK/data` and `REALTALK/arc_data` are available (default: sibling of narrarc).

---

## Next Steps and Open Questions

From [design.md](../../openspec/changes/improve-evidence-recall-accuracy/design.md):

- **Per-QA split fallback**: Should we implement per-QA split within files if file-level split proves insufficient?
- **Recall threshold**: What exact recall threshold justifies moving to test validation (20%? 30%?)?
- **Mode scope**: Do we need to evaluate both oneshot and agent modes, or focus only on agent since oneshot is deprecated?
- **Baseline tracking granularity**: Should baseline tracking include hyperparameters (embedding model, reranker model) or just high-level config changes?
