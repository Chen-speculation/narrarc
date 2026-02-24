## MODIFIED Requirements

### Requirement: Evidence retrieval accuracy
The system SHALL retrieve evidence messages with exact recall greater than 30% on test set, up from current 0% baseline.

#### Scenario: Exact match retrieval
- **WHEN** user asks "When did Fahim Khan go for a morning run after the rain?" with expected evidence localId 4
- **THEN** system includes localId 4 in returned evidence set

#### Scenario: Multi-evidence retrieval
- **WHEN** query requires multiple evidence messages
- **THEN** system retrieves at least 30% of expected evidence localIds

### Requirement: Candidate generation expansion
The system SHALL generate sufficient candidate nodes to include ground truth evidence in at least 80% of cases.

#### Scenario: Q3 candidate expansion
- **WHEN** Q3 phase generates candidate nodes for retrieval
- **THEN** candidate set includes ground truth evidence localIds for at least 80% of evaluation cases

#### Scenario: Time window adjustment
- **WHEN** evidence spans multiple time periods
- **THEN** system expands time window to capture relevant nodes across sessions

### Requirement: Reranking effectiveness
The system SHALL rank ground truth evidence in top-N positions after reranking in at least 60% of cases where it appears in candidates.

#### Scenario: Reranker scoring
- **WHEN** reranker scores candidates including ground truth evidence
- **THEN** ground truth evidence appears in top-10 ranked results in at least 60% of cases

#### Scenario: Score threshold tuning
- **WHEN** applying reranker score thresholds
- **THEN** system retains ground truth evidence above threshold in at least 60% of cases

### Requirement: Final selection optimization
The system SHALL select ground truth evidence for final response in at least 50% of cases where it appears in top-ranked candidates.

#### Scenario: LLM grading selection
- **WHEN** LLM grades top-ranked candidates for relevance
- **THEN** system selects ground truth evidence for inclusion in at least 50% of cases

#### Scenario: Evidence limit handling
- **WHEN** final evidence set is limited to N messages
- **THEN** system prioritizes ground truth evidence in selection

### Requirement: Evidence ID visibility in segment_narrative
The system SHALL expose all message IDs within each candidate node to the LLM during Q4 segment_narrative, not just a truncated preview.

**Background**: Debug analysis (BASELINE_FINDINGS.md) shows 100% of failures occur at `final_selection`. Ground truth IDs are present at candidate_generation and post_retrieval (468 candidates, all GT present), but the LLM in Q4 only sees a 5-8 message preview per node and selects from those visible IDs. GT IDs not in the preview are permanently dropped.

#### Scenario: Full message ID list exposure
- **WHEN** `segment_narrative` builds node summaries for the LLM prompt
- **THEN** each node summary includes an `all_message_ids` list containing every `local_id` within the node's range
- **AND** the message preview (5-8 messages with content) is preserved for content understanding
- **AND** the LLM can select from `all_message_ids` rather than only from previewed IDs

#### Scenario: Coverage-oriented evidence selection prompt
- **WHEN** LLM selects evidence_msg_ids per phase
- **THEN** the prompt instructs the LLM to select all directly supporting IDs (not just representative samples)
- **AND** the prompt requires at least one ID from each node covered by the phase
- **AND** the evidence_per_phase upper bound for narrative mode is raised from 8 to 15

#### Scenario: Phase evidence upper bound
- **WHEN** output_mode is "narrative"
- **THEN** evidence_per_phase is configured as (3, 15) instead of (3, 8)
- **AND** the LLM is not penalized for exceeding 8 if more coverage is needed

### Requirement: Retrieval parameter configurability
The system SHALL expose key retrieval parameters for tuning without code changes.

#### Scenario: Candidate limit configuration
- **WHEN** configuration specifies Q3 candidate limit
- **THEN** system uses configured limit instead of hardcoded default

#### Scenario: Reranker model configuration
- **WHEN** configuration specifies reranker model
- **THEN** system loads and uses specified reranker model

#### Scenario: Embedding model configuration
- **WHEN** configuration specifies embedding model
- **THEN** system uses specified model for vector similarity search
