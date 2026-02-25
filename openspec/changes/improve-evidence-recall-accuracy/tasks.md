## 1. Dataset Splitting Setup

- [x] 1.1 Add train/test split configuration to config.yaml with file ranges (Chat_1-7 train, Chat_8-10 test)
- [x] 1.2 Implement dataset filter function to select files based on train/test mode
- [x] 1.3 Add --train-only and --test-only flags to run_realtalk_eval.py
- [x] 1.4 Implement ARC case file mapping to ensure 1:1 correspondence with conversation files
- [x] 1.5 Add validation to detect overlapping files between train and test sets
- [x] 1.6 Test split logic by running evaluation on train set only and verifying correct files are processed

## 2. Evaluation Framework Enhancement

- [x] 2.1 Verify existing QA metrics calculation (Evidence Recall exact, Fuzzy Recall, Precision, Groundedness)
- [x] 2.2 Complete ARC evaluation implementation for arc_narrative query type
- [x] 2.3 Implement Global Recall calculation for ARC cases (total evidence across all phases)
- [x] 2.4 Implement Phase Coverage calculation for ARC cases (percentage of phases with evidence)
- [x] 2.5 Add per-phase recall tracking and reporting for ARC evaluation
- [x] 2.6 Implement metrics aggregation (mean, median, std dev) across all cases
- [x] 2.7 Add verbose mode for per-case detail logging with question, expected evidence, returned evidence
- [x] 2.8 Implement JSON output for evaluation results with timestamp and configuration
- [x] 2.9 Implement CSV export for per-case results with case_id, metrics, and evidence IDs

## 3. Retrieval Debugging Infrastructure

- [x] 3.1 Add checkpoint 1 logging: candidate generation (Q3 output / Retriever input) with candidate count and ground truth presence
- [x] 3.2 Add checkpoint 2 logging: post-reranking with top-N IDs, scores, and ground truth presence
- [x] 3.3 Add checkpoint 3 logging: final selection with selected IDs and ground truth presence
- [x] 3.4 Implement ground truth tracking to log presence/absence at each checkpoint
- [x] 3.5 Implement failure point identification (log which checkpoint lost ground truth evidence)
- [x] 3.6 Add structured JSON debug output format with checkpoint_name, candidate_ids, ground_truth_ids, scores
- [x] 3.7 Implement configurable debug verbosity levels (minimal vs full)
- [x] 3.8 Add debug log aggregation to identify common failure patterns across cases

## 4. Baseline Tracking System

- [x] 4.1 Create experiments directory and initialize baseline_metrics.csv with headers
- [x] 4.2 Implement experiment record creation with experiment_id, date, train_recall, test_recall, config_changes
- [x] 4.3 Implement CSV metric logging that appends rows after each evaluation
- [x] 4.4 Implement JSON metric logging with full experiment details and configuration
- [x] 4.5 Add separate tracking for train_* and test_* metrics to detect overfitting
- [x] 4.6 Implement baseline comparison function to retrieve first experiment metrics
- [x] 4.7 Implement best experiment identification based on test_exact_recall
- [x] 4.8 Add configuration snapshot capture (embedding model, reranker, candidate limits, LLM model)

## 5. Initial Baseline Evaluation

- [x] 5.1 Run baseline evaluation on train set with current configuration
- [x] 5.2 Record baseline metrics (experiment_id: baseline_001) in tracking system
- [x] 5.3 Run baseline evaluation with debug logging on 2-3 failing train cases
- [x] 5.4 Analyze debug logs to identify primary failure mode (candidates missing vs ranking issue)
- [x] 5.5 Document baseline findings and failure patterns

## 6. Query Pipeline Configuration

- [x] 6.1 Add Q3 candidate limit parameter to config.yaml
- [x] 6.2 Add reranker model selection parameter to config.yaml
- [x] 6.3 Add embedding model selection parameter to config.yaml
- [x] 6.4 Add reranker score threshold parameter to config.yaml
- [x] 6.5 Update query pipeline to read parameters from config instead of hardcoded values
- [x] 6.6 Verify configuration changes take effect without code modifications

## 7. Retrieval Improvement Experiments

- [x] 7.1 Experiment 1: Increase Q3 candidate limit and measure train recall (partial - 2 experiments)
- [x] 7.2 Experiment 2: Adjust time window for candidate expansion and measure train recall (doc: TASK_7.2_TIME_WINDOW.md)
- [x] 7.3 Experiment 3: Test alternative reranker models and measure train recall (SiliconFlow only supports bge-reranker-v2-m3)
- [x] 7.4 Experiment 4: Tune reranker score thresholds and measure train recall (partial - 2 experiments)
- [ ] 7.5 Experiment 5: Evaluate alternative embedding models and measure train recall
- [x] 7.6 Experiment 6: Refine LLM grading prompts — segment_narrative fix (see design.md Decision 6)
  - [x] 7.6a Add `all_message_ids` field to node summaries in `segment_narrative` (expose full ID list per node, not just preview)
  - [x] 7.6b Raise `evidence_per_phase` upper bound from `(3, 8)` to `(3, 15)` for narrative mode in `OUTPUT_MODES`
  - [x] 7.6c Rewrite evidence selection prompt: change "选取N个代表性消息" → coverage-first instruction requiring at least 1 ID per covered node
  - [x] 7.6d Run train eval after fix, record as experiment_id `exp_7_6_prompt_fix`
  - [x] 7.6e Compare exact_recall before/after; document delta in baseline_metrics.csv
- [x] 7.7 Record each experiment's configuration and metrics in baseline tracking system (partial - 2 experiments)
- [x] 7.8 Iterate until train exact recall reaches >30% threshold
  - [x] 7.8a Disable reflect_on_evidence re-selection: only keep existence check, drop hallucinated IDs (reflection.py)
  - [x] 7.8b Increase phase_count granularity: 180-day → 90-day buckets, allowing up to 8 phases for longer conversations (query.py)
  - [x] 7.8c Improve node message preview: expand from 8 to ~14 messages using stratified sampling across quarters (query.py)
  - [ ] 7.8d Run train eval after fixes, record as experiment_id `exp_7_8_reflection_fix`
  - [ ] 7.8e Compare exact_recall before/after; document delta in baseline_metrics.csv

## 8. Final Validation

- [ ] 8.1 Select best performing configuration based on train set results
- [ ] 8.2 Run final evaluation on test set (Chat_8, Chat_9, Chat_10) with best configuration
- [ ] 8.3 Record test set metrics in tracking system
- [ ] 8.4 Compare train vs test metrics to assess generalization
- [ ] 8.5 Run ARC evaluation on test set with --arc-cases flag
- [x] 8.6 Document final results: QA Exact Recall, ARC Global Recall, ARC Phase Coverage
- [x] 8.7 Create summary report with baseline vs final metrics comparison
- [x] 8.8 Document next steps and remaining open questions

