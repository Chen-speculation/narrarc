## ADDED Requirements

### Requirement: Experiment tracking
The system SHALL record each experimental iteration with unique identifier, timestamp, configuration changes, and resulting metrics.

#### Scenario: Experiment record creation
- **WHEN** evaluation completes with new configuration
- **THEN** system creates experiment record with experiment_id, date, train_recall, test_recall, and config_changes fields

#### Scenario: Configuration change documentation
- **WHEN** recording experiment
- **THEN** system captures specific configuration changes (e.g., "increased Q3 candidate limit from 50 to 100")

### Requirement: Metric history persistence
The system SHALL maintain historical record of all metrics across experiments for comparison and trend analysis.

#### Scenario: CSV metric logging
- **WHEN** experiment completes
- **THEN** system appends metrics row to CSV file with columns: experiment_id, date, train_exact_recall, train_precision, test_exact_recall, test_precision, config_summary

#### Scenario: JSON metric logging
- **WHEN** experiment completes
- **THEN** system appends full experiment record to JSON file including all metrics and detailed configuration

### Requirement: Train vs test metric separation
The system SHALL separately track metrics for train set and test set to detect overfitting.

#### Scenario: Train set metric recording
- **WHEN** evaluation runs on train set
- **THEN** system records metrics under train_* fields without updating test_* fields

#### Scenario: Test set metric recording
- **WHEN** evaluation runs on test set
- **THEN** system records metrics under test_* fields and flags this as final validation run

### Requirement: Baseline comparison
The system SHALL support comparing current experiment metrics against baseline or previous experiments.

#### Scenario: Baseline metric retrieval
- **WHEN** user requests baseline comparison
- **THEN** system displays first recorded experiment metrics as baseline reference

#### Scenario: Best experiment identification
- **WHEN** user requests best performing configuration
- **THEN** system identifies experiment with highest test_exact_recall metric

### Requirement: Experiment reproducibility
The system SHALL record sufficient configuration detail to reproduce any experiment.

#### Scenario: Configuration snapshot
- **WHEN** recording experiment
- **THEN** system captures embedding model, reranker model, candidate limits, LLM model, and prompt versions

#### Scenario: Experiment replay
- **WHEN** user specifies experiment_id to replay
- **THEN** system loads configuration from that experiment and re-runs evaluation

### Requirement: Metric visualization support
The system SHALL output metrics in format suitable for visualization and analysis tools.

#### Scenario: Time series export
- **WHEN** user exports metric history
- **THEN** system generates CSV with date-ordered rows suitable for plotting recall trends over time

#### Scenario: Configuration impact analysis
- **WHEN** user exports experiment data
- **THEN** system includes configuration parameters as columns for correlation analysis
