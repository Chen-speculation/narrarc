## ADDED Requirements

### Requirement: File-level train/test split
The system SHALL support splitting RealTalk dataset by conversation files, with Chat_1 through Chat_7 designated as training set and Chat_8 through Chat_10 designated as test set.

#### Scenario: Train set identification
- **WHEN** evaluation script runs with `--train-only` flag
- **THEN** system processes only Chat_1 through Chat_7 conversation files and their corresponding ARC case files

#### Scenario: Test set identification
- **WHEN** evaluation script runs with `--test-only` flag
- **THEN** system processes only Chat_8, Chat_9, and Chat_10 conversation files and their corresponding ARC case files

#### Scenario: Full dataset processing
- **WHEN** evaluation script runs without train/test flags
- **THEN** system processes all RealTalk conversation files

### Requirement: ARC case file mapping
The system SHALL maintain 1:1 mapping between conversation files and ARC case files during train/test splitting.

#### Scenario: Train set ARC mapping
- **WHEN** processing train set conversations
- **THEN** system uses only the 6 ARC case files corresponding to Chat_1 through Chat_7

#### Scenario: Test set ARC mapping
- **WHEN** processing test set conversations
- **THEN** system uses only the 3 ARC case files corresponding to Chat_8, Chat_9, and Chat_10

### Requirement: Split configuration
The system SHALL provide configuration mechanism to define train/test split boundaries without code changes.

#### Scenario: Configurable split
- **WHEN** split configuration specifies different file ranges
- **THEN** system applies the configured split instead of default Chat_1-7/Chat_8-10 split

### Requirement: Split validation
The system SHALL validate that train and test sets are mutually exclusive with no overlapping conversation files.

#### Scenario: Overlap detection
- **WHEN** configuration specifies overlapping files in train and test sets
- **THEN** system raises validation error before processing begins
