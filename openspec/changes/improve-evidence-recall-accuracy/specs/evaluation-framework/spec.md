## ADDED Requirements

### Requirement: QA evaluation metrics
The system SHALL compute and report QA evaluation metrics including Evidence Recall (exact), Fuzzy Recall (±3), Precision, Timeline Coverage, and Groundedness.

#### Scenario: Exact recall calculation
- **WHEN** system evaluates a QA case with expected evidence localIds [4, 14] and returns [4, 28]
- **THEN** system reports Evidence Recall (exact) as 50% (1 out of 2 expected IDs matched)

#### Scenario: Fuzzy recall calculation
- **WHEN** system returns localId 6 and expected evidence includes localId 4
- **THEN** system counts this as a fuzzy match (within ±3 range) for Fuzzy Recall metric

#### Scenario: Precision calculation
- **WHEN** system returns 5 evidence IDs and 2 match expected evidence
- **THEN** system reports Precision as 40% (2 out of 5 returned IDs are valid)

### Requirement: ARC evaluation metrics
The system SHALL compute and report ARC evaluation metrics including Global Recall and Phase Coverage for narrative arc cases.

#### Scenario: Global recall calculation
- **WHEN** ARC case expects 10 total evidence IDs across all phases and system returns 7 of them
- **THEN** system reports Global Recall as 70%

#### Scenario: Phase coverage calculation
- **WHEN** ARC case has 4 narrative phases and system retrieves evidence from 3 phases
- **THEN** system reports Phase Coverage as 75%

#### Scenario: Per-phase recall tracking
- **WHEN** evaluating ARC case with multiple phases
- **THEN** system reports recall percentage for each individual phase

### Requirement: Dual evaluation mode support
The system SHALL support both QA evaluation mode and ARC evaluation mode through command-line flags.

#### Scenario: QA mode execution
- **WHEN** evaluation script runs without `--arc-cases` flag
- **THEN** system evaluates using QA metrics on standard question-answer cases

#### Scenario: ARC mode execution
- **WHEN** evaluation script runs with `--arc-cases` flag
- **THEN** system evaluates using ARC metrics on narrative arc cases from arc_data directory

### Requirement: Query mode compatibility
The system SHALL support evaluation of both oneshot and agent query modes.

#### Scenario: Agent mode evaluation
- **WHEN** evaluation runs with agent workflow enabled
- **THEN** system executes LangGraph workflow (Planner → Retriever → Grader → Generator) and collects metrics

#### Scenario: Oneshot mode evaluation
- **WHEN** evaluation runs with oneshot mode enabled
- **THEN** system executes Q1-Q5 pipeline and collects metrics

### Requirement: Metrics aggregation
The system SHALL aggregate metrics across all evaluated cases and report summary statistics.

#### Scenario: Summary report generation
- **WHEN** evaluation completes processing all cases
- **THEN** system outputs mean, median, and standard deviation for each metric

#### Scenario: Per-case detail logging
- **WHEN** evaluation runs in verbose mode
- **THEN** system logs individual case results with question text, expected evidence, returned evidence, and per-case metrics

### Requirement: Evaluation result persistence
The system SHALL save evaluation results to structured output files for later analysis.

#### Scenario: JSON output generation
- **WHEN** evaluation completes
- **THEN** system writes results to JSON file with timestamp, configuration, and all metrics

#### Scenario: CSV export for analysis
- **WHEN** evaluation completes
- **THEN** system writes per-case results to CSV file with columns for case_id, metrics, and evidence IDs
