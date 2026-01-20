# Agents & Tools

This document details the AI agents and tools within WorldReasoner.

## Multi-Agent System

### HindsightAgent
**Location**: `src/agents/hindsight_agent.py`

A manager agent that orchestrates deep causal analysis of resolved questions using a hierarchical team of specialized agents.

-   **Manager Agent**: Coordinates the workflow, self-corrects, and ensures quality.
-   **Evidence Collector**: Specializes in gathering relevant articles and data from the past (provenance-aware).
-   **Causal Analyzer**: Builds multiple levels of causal graphs to explain *why* an event happened.

**Usage**:
```python
from src.agents.hindsight_agent import HindsightAgent

agent = HindsightAgent(
    question_id="q123",  # For provenance tracking
    db_path="worldreasoner.db"
)
result = agent.run("Analyze the causal factors for X")
```

### Other Agents

-   **ForecastAgent** (`src/agents/forecast_agent.py`): Performs forward-looking predictions based on current evidence.
-   **WebAgent** (`src/agents/web_agent.py`): General-purpose agent for web research and synthesis.

## Agent Factory
**Location**: `src/agents/factory.py`

Centralized factory for creating agents with consistent configuration and dependency injection.

```python
from src.agents.factory import AgentFactory

# Create a web agent with specific tools
agent = AgentFactory.create_web_agent(tools=[my_tool])
```

## Key Tools
**Location**: `src/tools/`

Tools are "token-optimized" - they perform heavy lifting internally and return concise summaries to the LLM.

### Analysis Tools
-   **CausalReasonerTool**: Identifies causal links between events.
-   **EventIdentifierTool**: Extracts discrete events from text.
-   **GraphInspectorTool**: Analyzes the structure of the event graph.
-   **ArticleInspectorTool**: Analyzes temporal coverage of articles for a given topic.

### Data Retrieval
-   **ArticleCollector**: Fetches and stores articles (supports temporal filtering).
-   **WebSearch**: search via DuckDuckGo or SearXNG.
-   **WebFetch**: Retrieves full page content.

### Patterns
-   **Provenance**: Most tools accept `question_id` to tag generated data.
-   **Result Collectors**: Tools often write full data to a `ResultCollector` and return only IDs/summaries to the agent.

# Article analysis
from src.utils.article_analysis import analyze_article_timeline
gaps = analyze_article_timeline(articles, start_date, end_date)

# Graph analysis
from src.utils.graph_analysis import analyze_graph_depth
depth = analyze_graph_depth(event_id, hypotheses)
```

## Scripts and Examples

### Scripts Directory (`scripts/`)

- `build_search_index.py` - Build hybrid search indices for articles
- `create_forecasts_table.py` - Initialize forecasts database table
- `fetch_knowledge_cutoff_date.py` - Fetch and update LLM knowledge cutoff dates
- `test_hybrid_search.py` - Test search functionality

### Example Scripts (`examples/`)

**Question Collection:**
- `run_goal_collection.py` - Goal-oriented question collection with targets

**Evidence and Analysis:**
- `run_evidence_pipeline.py` - Standard evidence pipeline
- `run_adaptive_evidence_pipeline.py` - Adaptive multi-agent pipeline
- `deep_causal_analysis.py` - Deep causal chain analysis

**Forecasting:**
- `run_realtime_forecast.py` - Real-time forecasting with live data
- `run_forecast_smolagents.py` - Forecasting using smolagents framework
- `run_temporal_forecast_analysis.py` - Temporal analysis of forecasts

**Evaluation:**
- `run_benchmark_evaluation.py` - Benchmark evaluation
- `evaluate_forecasts.py` - Forecast accuracy evaluation
- `visualize_benchmarks.py` - Visualization of benchmark results

**Usage:**
```bash
# Goal-oriented collection
python examples/run_goal_collection.py --goal config/collection_goal.yaml --db worldreasoner.db

# Adaptive evidence pipeline
python examples/run_adaptive_evidence_pipeline.py --db worldreasoner.db

# Real-time forecasting
python examples/run_realtime_forecast.py --question-id q123
```

## Key Architecture Decisions

1. **SQLite over PostgreSQL**: Simplicity for local development, single-file portability
2. **smolagents framework**: Lightweight agentic framework with LiteLLM integration
3. **Content hashing**: Article deduplication across pipeline runs
4. **Event/Article separation**: Events are causal nodes (graph), articles are documentation (info)
5. **Token optimization**: Tools minimize token usage by processing internally
6. **Generic type safety**: `PipelineStage[TInput, TOutput]` ensures compile-time correctness
7. **Service extraction over monoliths**: QuestionCollectionOrchestrator refactored from 660→366 lines by extracting focused services (`SourceCoordinator`, `GapAnalyzer`, `GapFiller`, `QuotaManager`) while maintaining flat hierarchy (max 2 levels)

## Testing Strategy

### Unit Tests (`tests/unit/`)
- Test individual functions/classes in isolation
- Fast, no external dependencies
- Mock collectors, agents, and databases

**New Unit Tests:**
- `tests/unit/domain/test_question_estimated_start.py` - Estimated start time validation
- `tests/unit/pipelines/stages/test_question_quality.py` - Quality scoring
- `tests/unit/tools/test_question_quality_scorer.py` - Quality scorer tool
- `tests/unit/utils/test_question_filters.py` - Question filtering
- `tests/unit/test_gap_analyzer.py` - Gap analysis
- `tests/unit/test_gap_filler.py` - Gap filling
- `tests/unit/test_source_coordinator.py` - Source coordination
- `tests/unit/test_polymarket.py` - Polymarket integration

### Integration Tests (`tests/integration/`)
- Test components working together
- Marked with `@pytest.mark.integration`
- Include end-to-end pipeline tests
- Run separately: `uv run pytest -m integration`

**New Integration Tests:**
- `tests/integration/pipelines/test_evidence_pipeline_integration.py` - End-to-end evidence
- `tests/integration/pipelines/test_orchestrator.py` - Orchestrator integration
- `tests/integration/test_pipeline_runner.py` - Pipeline runner

### Test Database Fixtures

From `tests/conftest.py`:

```python
def test_something(test_db_path):
    # Auto-cleaned temporary database
    stage = ArticleCollectionStage(config, db_path=test_db_path)

def test_debug(persistent_test_db_path):
    # Persistent database in ./test-dbs/<testname>.db (NOT auto-cleaned)
    stage = ArticleCollectionStage(config, db_path=persistent_test_db_path)
```

## Troubleshooting

### Articles/Events/Questions Not Being Collected

**Symptom**: Logs show processing but collector has 0 items.

**Cause**: Using `if self.collector:` instead of `if self.collector is not None:`

**Solution**: `ResultCollector.__bool__()` returns `False` when empty. Always check `is not None`.

### Test Shows 0 Outputs But Stage Completed

**Symptom**: `result.status == COMPLETED` but `len(result.outputs) == 0`

**Cause**: Accessing `stage.tool.collected_items` instead of `result.outputs`

**Solution**: Always use `result.outputs` after `stage.execute()`

### Windows Encoding Errors in Logs

**Symptom**: `UnicodeEncodeError: 'gbk' codec can't encode character`

**Cause**: Using Unicode characters (✓, ✗) in log messages on Windows

**Solution**: Use ASCII only, or set UTF-8 encoding:
```python
import sys, codecs
if sys.platform == "win32":
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
```

### Database Column Missing Errors

**Symptom**: `sqlite3.OperationalError: table articles has no column named metadata`

**Cause**: Database was created before the `metadata` field was added to the Article model

**Solution**: Run the migration script:
```bash
python migrations/add_article_metadata.py
```

The migration will:
- Check if the column already exists (safe to run multiple times)
- Add the `metadata` column to the `articles` table
- Set default value to `'{}'` (empty JSON object)

**Note**: This happens when you upgrade to a version with new fields and have an existing database. See `migrations/README.md` for more details.

### CLI Command Not Found

**Symptom**: `wr: command not found` or `'wr' is not recognized`

**Cause**: Package not installed in editable mode or virtual environment not activated

**Solution**:
```bash
# Ensure virtual environment is activated
.venv\Scripts\Activate.ps1  # Windows
source .venv/bin/activate    # Linux/Mac

# Install in editable mode
uv pip install -e .

# Verify installation
wr --help
```

### Frontend Build Errors

**Symptom**: `npm run dev` fails with dependency errors

**Cause**: Dependencies not installed or outdated

**Solution**:
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run dev
```

## Database Migrations

When new fields are added to models, existing databases need to be migrated. Migration scripts are in the `migrations/` folder.

**Available Migrations:**
- `add_article_metadata.py` - Add `metadata` field to articles table
- `add_estimated_start_time.py` - Add `estimated_start_time` field to questions table

**Running Migrations:**
```bash
# Run specific migration
python migrations/add_estimated_start_time.py

# Migrations are idempotent (safe to run multiple times)
```

**Creating New Migrations:**
1. Create new script in `migrations/` folder
2. Check if column exists before adding (idempotency)
3. Use proper SQL ALTER TABLE syntax
4. Set appropriate default values
5. Document in `migrations/README.md`

**Migration Template:**
```python
import sqlite3

def migrate(db_path: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if column exists
    cursor.execute("PRAGMA table_info(table_name)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'new_column' not in columns:
        cursor.execute("ALTER TABLE table_name ADD COLUMN new_column TEXT DEFAULT ''")
        conn.commit()
        print("✓ Added new_column")
    else:
        print("✓ new_column already exists")

    conn.close()
```

**See also:** `migrations/README.md` for detailed migration guide

## Dependencies

Key dependencies (see `pyproject.toml` for full list):
- **smolagents[toolkit,litellm,mcp]**: Agentic framework with tool calling
- **litellm**: Multi-provider LLM client (Gemini, OpenAI, etc.)
- **crawl4ai**: Advanced web scraping with JavaScript support
- **pydantic**: Data validation and settings
- **pytest-asyncio**: Async test support
- **loguru**: Professional logging with rotation
- **feedparser**: RSS/Atom feed parsing
- **typer**: Modern CLI framework for the `wr` command
- **rich**: Rich terminal output (tables, progress bars, syntax highlighting)
- **fastmcp**: MCP (Model Context Protocol) server framework
- **websockets**: WebSocket support for real-time updates
