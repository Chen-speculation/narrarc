## Why

The Narrative Mirror system currently has 0% Evidence Recall (exact) on the RealTalk dataset, meaning it fails to retrieve the correct evidence messages that support user queries. This critical accuracy issue prevents the system from fulfilling its core purpose of providing evidence-backed narrative responses from chat history.

## What Changes

- Implement train/test dataset splitting to prevent overfitting during development
- Add comprehensive evaluation framework supporting both QA and ARC (narrative arc) evaluation modes
- Enhance retrieval pipeline (Q3/Retriever) to improve evidence ranking and selection
- Add detailed logging and debugging capabilities for retrieval analysis
- Establish baseline metrics and iterative improvement workflow
- Create evaluation scripts that support both oneshot and agent query modes

## Capabilities

### New Capabilities

- `dataset-splitting`: Train/test split management for RealTalk data to ensure valid evaluation (file-level and QA-level splitting)
- `evaluation-framework`: Comprehensive evaluation system supporting QA metrics (Evidence Recall, Precision, Groundedness) and ARC metrics (Global Recall, Phase Coverage)
- `retrieval-debugging`: Logging and analysis tools to trace evidence retrieval through Q3/Retriever pipeline and identify failure points
- `baseline-tracking`: Metric tracking system to measure improvements across iterations on train vs test sets

### Modified Capabilities

- `query-pipeline`: Enhanced evidence retrieval and ranking in Q3/Retriever stages to improve exact recall from 0% to meaningful levels

## Impact

- **Code**: Query pipeline (`query.py`, `workflow.py`), retrieval stages (Q3, Retriever), evaluation scripts (`run_realtalk_eval.py`)
- **Data**: RealTalk dataset organization and access patterns, ARC case file handling
- **Configuration**: May need new config parameters for retrieval tuning (embedding models, reranker settings, candidate limits)
- **Evaluation**: New evaluation modes and metrics reporting, separate train/test evaluation workflows
- **Dependencies**: Potential updates to ChromaDB, reranker, or LLM configurations for improved retrieval
