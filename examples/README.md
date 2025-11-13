# WorldReasoner Examples

Example scripts demonstrating WorldReasoner functionality.

## MCP Server Examples

### 1. MCP Server Test (`test_mcp_server.py`)

Comprehensive test script with two modes:

**Smoke test** - Quick validation with temporary database (no data required):

```bash
python examples/test_mcp_server.py --smoke
```

**What it tests**:
- ✓ list_questions - Question listing
- ✓ start_forecast_session - Session initialization
- ✓ get_session_info - Session state tracking
- ✓ temporal_search_articles - Temporal filtering
- ✓ submit_forecast - Forecast submission

**Integration test** - Full validation with production database (requires data):

```bash
python examples/test_mcp_server.py
```

**What it tests**:
- Database connectivity
- Question retrieval
- Temporal filtering with real data
- Article accessibility
- Tool interface compatibility

**Both tests**:
```bash
python examples/test_mcp_server.py --all
```

## Pipeline Examples

### 3. Question Pipeline (`run_question_pipeline.py`)

Generate forecast questions from news sources.

```bash
python examples/run_question_pipeline.py
```

### 4. Evidence Pipeline (`run_evidence_pipeline.py`)

Build causal explanations using hindsight.

```bash
python examples/run_evidence_pipeline.py
```

## Running Examples

### Prerequisites

```bash
# Ensure environment is set up
uv sync

# Optional: Configure database path
export WORLDREASONER_DB=worldreasoner.db  # Linux/Mac
$env:WORLDREASONER_DB="worldreasoner.db"   # Windows PowerShell
```

### Quick Start

```bash
# 1. Smoke test (no data required)
python examples/smoke_check_mcp_server.py

# 2. Interactive test (requires data)
python examples/test_mcp_server.py

# 3. Generate questions
python examples/run_question_pipeline.py

# 4. Build evidence graph
python examples/run_evidence_pipeline.py
```

## See Also

- [MCP Server Documentation](../docs/MCP_SERVER.md) - Complete MCP guide (quick start, tools, all modes)
