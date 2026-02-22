# Narrative Mirror

Transform WeChat chat history into evidence-backed narrative arcs.

A Python backend that builds a two-layer index over chat messages and answers natural-language questions about relationship dynamics.

## Quick Start

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run the full pipeline with mock data
uv run python -m narrative_mirror.build --talker mock_talker_001 --debug
uv run python -m narrative_mirror.metadata --talker mock_talker_001 --debug
uv run python -m narrative_mirror.layer2 --talker mock_talker_001 --debug
uv run python -m narrative_mirror.query --talker mock_talker_001 "我们是怎么一步步分手的？"
```

## Architecture

```
src/narrative_mirror/
    models.py      # Dataclasses for messages, nodes, signals
    llm.py         # LLM protocols and stub implementations
    datasource.py  # Mock + WeFlow data sources
    db.py          # SQLite persistence
    build.py       # Layer 1: Burst aggregation + topic classification
    metadata.py    # Layer 1.5: Signal computation + anomaly detection
    layer2.py      # Layer 2: Semantic thread construction
    query.py       # Q1-Q5 query pipeline
```

## Pipeline Overview

### Build Phase (offline)

1. **Layer 1 - Topic Nodes**: Aggregate messages into bursts (30-min gap), classify each burst into topic nodes via LLM
2. **Layer 1.5 - Metadata**: Compute 7 signals per node (reply_delay, term_shift, silence_event, topic_frequency, initiator_ratio, emotional_tone, conflict_intensity)
3. **Layer 2 - Semantic Threads**: Embed nodes, find similar pairs, arbitrate with CoT LLM to create thread pointers

### Query Phase (runtime)

1. **Q1 - Intent Parsing**: Parse user question into structured intent
2. **Q2 - Anchor Lookup**: Find anomaly anchors matching focus dimensions
3. **Q3 - Candidate Expansion**: Expand via thread traversal
4. **Q4 - Narrative Segmentation**: Segment candidates into phases with evidence
5. **Q5 - Output Formatting**: Format as plain-text narrative cards

## Data Sources

### MockDataSource (default)

Hardcoded 20-message demo conversation from `init.md`. Used for development and testing without external dependencies.

### WeFlowDataSource

Connects to WeFlow's local HTTP API on port 5031.

```bash
# Run with WeFlow source
uv run python -m narrative_mirror.build --talker <wxid> --source weflow
```

Requirements:
- WeFlow running with HTTP server enabled (`Settings > Enable HTTP Server`)
- Default port: 5031

## LLM Configuration

The system uses two LLM types:

- **NonCoTLLM**: Fast completion for bulk classification and embedding
- **CoTLLM**: Chain-of-thought reasoning for arbitration and narrative

### Stub Implementations

For testing without real LLM calls:

```python
from narrative_mirror.llm import StubNonCoTLLM, StubCoTLLM

llm_noncot = StubNonCoTLLM()  # Returns hardcoded JSON, random embeddings
llm_cot = StubCoTLLM()        # Returns hardcoded narrative responses
```

### OpenAI-Compatible Implementations

Create `config.yml`:

```yaml
llm:
  provider: openai
  model: claude-3-5-sonnet-20241022
  api_key: YOUR_API_KEY
  base_url: https://api.anthropic.com/v1

embedding:
  provider: openai
  model: BAAI/bge-m3
  api_key: YOUR_API_KEY
  base_url: YOUR_EMBEDDING_ENDPOINT
```

## Database

- **SQLite**: `data/mirror.db` (raw messages, nodes, metadata, anchors, thread pointers)
- **ChromaDB**: `data/chroma/` (node embeddings)

Both directories are gitignored.

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=narrative_mirror

# Run specific test file
uv run pytest tests/test_e2e.py -v
```

## CLI Commands

```bash
# Layer 1: Build topic nodes
uv run python -m narrative_mirror.build --talker <id> [--source mock|weflow] [--burst-gap-seconds 1800]

# Layer 1.5: Compute metadata
uv run python -m narrative_mirror.metadata --talker <id>

# Layer 2: Build semantic threads
uv run python -m narrative_mirror.layer2 --talker <id> [--sim-threshold 0.5] [--top-k 10]

# Query
uv run python -m narrative_mirror.query --talker <id> "你的问题"
```

## Development

```bash
# Install dev dependencies
uv sync

# Type checking
uv run pyright src/

# Format code
uv run ruff format src/
```

## License

MIT
