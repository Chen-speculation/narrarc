## ADDED Requirements

### Requirement: Three-checkpoint logging
The system SHALL log retrieval pipeline state at three checkpoints: candidate generation, post-reranking, and final selection.

#### Scenario: Candidate generation logging
- **WHEN** Q3 phase or Retriever node generates candidate evidence nodes
- **THEN** system logs total candidate count and whether ground truth localIds appear in candidates

#### Scenario: Post-reranking logging
- **WHEN** reranker scores candidates
- **THEN** system logs top-N candidate IDs with scores and whether ground truth localIds appear in top-N

#### Scenario: Final selection logging
- **WHEN** system selects final evidence set for response generation
- **THEN** system logs selected evidence IDs and whether ground truth localIds were selected

### Requirement: Ground truth tracking
The system SHALL track whether expected evidence localIds appear at each retrieval checkpoint during evaluation.

#### Scenario: Ground truth presence detection
- **WHEN** processing evaluation case with expected localIds [4, 14]
- **THEN** system logs at each checkpoint whether localId 4 and localId 14 are present in the candidate/ranked/selected sets

#### Scenario: Failure point identification
- **WHEN** ground truth evidence is lost between checkpoints
- **THEN** system logs which checkpoint caused the loss (e.g., "localId 4 present in candidates but absent after reranking")

### Requirement: Structured debug output
The system SHALL output debug logs in structured format for programmatic analysis.

#### Scenario: JSON debug format
- **WHEN** debug logging is enabled
- **THEN** system outputs each checkpoint as JSON with fields: checkpoint_name, candidate_ids, ground_truth_ids, ground_truth_present, scores

#### Scenario: Debug log aggregation
- **WHEN** evaluation completes
- **THEN** system aggregates debug logs across all cases to identify common failure patterns

### Requirement: Configurable debug verbosity
The system SHALL support multiple debug verbosity levels to control log detail.

#### Scenario: Minimal debug mode
- **WHEN** debug level set to minimal
- **THEN** system logs only ground truth presence/absence at each checkpoint

#### Scenario: Full debug mode
- **WHEN** debug level set to full
- **THEN** system logs all candidate IDs, scores, node metadata, and retrieval parameters at each checkpoint

### Requirement: Performance impact minimization
The system SHALL ensure debug logging does not significantly degrade retrieval performance.

#### Scenario: Debug overhead measurement
- **WHEN** debug logging is enabled
- **THEN** system completes evaluation within 110% of baseline time without debug logging
