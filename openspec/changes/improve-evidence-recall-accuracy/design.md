## Context

The Narrative Mirror system processes chat history through L1 (topic aggregation) → L1.5 (metadata signals) → L2 (semantic threads) → Query pipeline. Currently, the query pipeline has two modes: oneshot (deprecated) and agent (LangGraph workflow with Planner → Retriever → Grader → Generator).

The system achieves 0% Evidence Recall (exact) on RealTalk dataset, meaning retrieved evidence messages never match ground truth annotations. While Fuzzy Recall (±3 messages) shows 100% for agent mode, this is misleading - the system returns nearby messages but misses the actual evidence. The retrieval pipeline (Q3 phase in oneshot, Retriever node in agent) fails to rank correct messages highly enough.

Current evaluation runs on the full RealTalk dataset without train/test separation, risking overfitting during iterative improvements. The system needs a structured approach to diagnose retrieval failures, implement fixes, and validate improvements on held-out data.

## Goals / Non-Goals

**Goals:**
- Establish train/test split for RealTalk dataset (file-level: Chat_1-7 train, Chat_8-10 test)
- Create evaluation framework supporting both QA metrics (Evidence Recall, Precision) and ARC metrics (Global Recall, Phase Coverage)
- Add retrieval debugging to trace candidate generation, ranking, and selection through Q3/Retriever
- Improve exact Evidence Recall from 0% to meaningful levels (target: >30% on test set)
- Support iterative experimentation on train set with final validation on test set

**Non-Goals:**
- Rewriting L1/L1.5/L2 processing (focus is on query/retrieval stages)
- Changing the agent workflow architecture (keep LangGraph structure)
- Optimizing for speed (accuracy is the priority)
- Supporting datasets beyond RealTalk in this phase

## Decisions

### Decision 1: File-Level Train/Test Split

**Choice**: Split RealTalk by conversation files (Chat_1-7 train, Chat_8-10 test) rather than random QA sampling.

**Rationale**:
- Conversations are independent units - no information leakage between files
- ARC case files map 1:1 to conversation files, making split management cleaner
- Simpler to implement and reason about than per-QA splitting
- Test set (3 files) provides sufficient validation data

**Alternatives Considered**:
- Per-QA random split within each file: More complex, risks leakage if same conversation context appears in train/test
- Temporal split: Not applicable since RealTalk files aren't chronologically ordered

### Decision 2: Evaluation Framework Architecture

**Choice**: Extend existing `run_realtalk_eval.py` with `--train-only` and `--test-only` flags, support both QA and ARC evaluation modes via `--arc-cases` flag.

**Rationale**:
- Builds on existing evaluation infrastructure
- Single script handles both evaluation types
- Clear separation of train/test runs prevents accidental contamination
- ARC evaluation already partially implemented, needs completion

**Alternatives Considered**:
- Separate scripts for QA vs ARC: More code duplication, harder to maintain consistent metrics
- Jupyter notebooks: Less reproducible, harder to integrate into CI/CD

### Decision 3: Retrieval Debugging Strategy

**Choice**: Add structured logging at three checkpoints: (1) candidate generation (Q3 output / Retriever input), (2) post-reranking scores, (3) final selection. Log whether ground truth localIds appear at each stage.

**Rationale**:
- Pinpoints where correct evidence is lost (never retrieved vs retrieved but ranked low vs retrieved but not selected)
- Minimal code changes - add logging without altering retrieval logic
- Enables data-driven decisions on where to focus improvements

**Alternatives Considered**:
- Full trace logging: Too verbose, hard to analyze
- Only final output logging: Doesn't reveal where failures occur

### Decision 4: Retrieval Improvement Approach

**Choice**: Iterative experimentation on train set with these levers:
1. Candidate expansion (increase Q3 node limit, adjust time window)
2. Reranker tuning (model selection, score thresholds)
3. Embedding model evaluation (compare alternatives)
4. LLM grading prompt refinement (for agent mode)

**Rationale**:
- Addresses the full retrieval pipeline systematically
- Each lever is independently testable
- Debugging logs reveal which stage needs attention
- Avoids premature optimization

**Alternatives Considered**:
- Rewrite retrieval from scratch: Too risky, loses existing functionality
- Focus only on reranker: May not address root cause if candidates are missing

### Decision 6: segment_narrative Evidence Selection Fix (Empirically Derived)

**Background**: Debug evaluation on 2 train cases (BASELINE_FINDINGS.md) revealed that 100% of failures occur at `final_selection` (Q4/`segment_narrative`), not during retrieval. Ground truth is present in all 468 candidates, but the LLM only receives a truncated preview (5-8 messages per node) and selects from those visible IDs. GT IDs absent from the preview are permanently dropped.

**Choice**: Three-part fix to `segment_narrative` in `query.py`:
1. **Full ID exposure**: Add `all_message_ids` field to each node summary passed to the LLM, listing every `local_id` in the node's range. Keep the message preview for content understanding, but ensure the LLM can select from the complete ID set.
2. **Coverage-oriented prompt**: Replace "选取 N 个代表性消息" (select N representative messages) with "选取所有直接支撑本阶段结论的消息ID，每个涵盖节点至少选 1 个" (select all directly supporting IDs, at least 1 from each covered node). The upper bound becomes a soft cap, not a hard constraint.
3. **Raise evidence_per_phase upper bound**: Change `(3, 8)` → `(3, 15)` for narrative mode to accommodate coverage-first selection.

**Rationale**:
- Fix A addresses the root cause: the LLM's selection is bounded by what it can see. If GT IDs aren't in the preview, they can't be selected.
- Fix B changes the selection objective from "representativeness" (favors diversity, hurts recall) to "completeness" (favors recall, which is the target metric).
- Fix C prevents the upper bound from forcing the LLM to drop IDs it would otherwise include.
- All three fixes are local to `segment_narrative` — no changes to retrieval pipeline, reranker, or workflow.

**Alternatives Considered**:
- Increase preview size to show all messages (with content): Token-expensive; with 468 nodes × avg 15 messages = 7000+ lines of content in prompt. Showing only IDs (Fix A) achieves the same benefit without token explosion.
- Post-selection augmentation (add node start/end IDs to output): Doesn't help with mid-range GT IDs, and adds IDs the LLM didn't reason about (harms precision).
- Two-pass selection (phase assignment → evidence selection separately): More LLM calls per query; Fix A+B achieves equivalent result in one pass.

### Decision 5: Baseline Tracking

**Choice**: Manual CSV/JSON logging of metrics after each experiment iteration, with columns: experiment_id, date, train_recall, test_recall, config_changes.

**Rationale**:
- Simple to implement and maintain
- Sufficient for tracking ~10-20 iterations
- Easy to visualize in spreadsheet or notebook

**Alternatives Considered**:
- MLflow/Weights & Biases: Overkill for this scale, adds dependency
- Git commit messages only: Hard to query and compare metrics

## Risks / Trade-offs

**[Risk]** Train set too small (7 files) may not capture full diversity → **Mitigation**: If results don't generalize, consider per-QA split within files to increase train size

**[Risk]** Retrieval improvements may degrade other metrics (e.g., Precision drops while Recall rises) → **Mitigation**: Track all metrics together, define acceptable trade-off thresholds

**[Risk]** Test set contamination if developers inadvertently tune on test data → **Mitigation**: Document strict rule: never make decisions based on test metrics until final validation

**[Risk]** ARC evaluation implementation incomplete, may need significant work → **Mitigation**: Verify ARC evaluation works on train set before relying on it; prioritize QA metrics if ARC is blocked

**[Trade-off]** Focusing on exact recall may miss cases where nearby messages are acceptable → **Acceptance**: Exact recall is the ground truth metric; fuzzy recall is supplementary

## Migration Plan

**Phase 1: Setup (Week 1)**
1. Implement train/test split logic in evaluation script
2. Add `--train-only` / `--test-only` flags
3. Verify ARC evaluation path works on train set
4. Run baseline evaluation on train set, record metrics

**Phase 2: Debugging (Week 1-2)**
1. Add retrieval logging at three checkpoints
2. Run on 2-3 failing train cases, analyze logs
3. Identify primary failure mode (candidates missing vs ranking issue)

**Phase 3: Iteration (Week 2-4)**
1. Experiment with retrieval improvements on train set
2. Log each experiment's config and metrics
3. Iterate until train recall >30%

**Phase 4: Validation (Week 4)**
1. Run final configuration on test set (once only)
2. Compare train vs test metrics
3. Document findings and next steps

**Rollback**: No production deployment in this phase - all changes are evaluation/debugging infrastructure. If retrieval changes degrade performance, revert to baseline config.

## Open Questions

- Should we implement per-QA split as a fallback if file-level split proves insufficient?
- What exact recall threshold justifies moving to test validation (20%? 30%?)?
- Do we need to evaluate both oneshot and agent modes, or focus only on agent since oneshot is deprecated?
- Should baseline tracking include hyperparameters (embedding model, reranker model) or just high-level config changes?
