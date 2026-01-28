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

### Tool Base Classes (`src/tools/`)

WorldReasoner provides reusable base classes to eliminate code duplication across tools:

**DatabaseAwareTool** (`src/tools/database_mixin.py`)
- Base class for tools that need database access
- Standardizes database initialization (db instance, db_path, or default)
- Provides `not_found_response()` helper for consistent error handling
- Optional table creation via `ensure_tables` parameter
- Used by: ArticleRetrievalTool, EventDetailsTool, GraphInspectorTool, and 6+ others

**Example:**
```python
from src.tools.database_mixin import DatabaseAwareTool
from src.domain.models import Article

class MyTool(DatabaseAwareTool):
    name = "my_tool"
    description = "My custom tool"
    inputs = {"item_id": {"type": "string", "description": "ID to look up"}}
    output_type = "string"

    def __init__(self, db=None, db_path=None):
        # Initialize with database access
        super().__init__(db=db, db_path=db_path, ensure_tables=[Article])

    def forward(self, item_id: str) -> str:
        article = self.db.get(Article, item_id)
        if not article:
            # Use helper for consistent error responses
            return self.not_found_response("Article", item_id, Article)
        return json.dumps({"title": article.title})
```

**CollectorAwareTool** (`src/tools/base.py`)
- Base class for tools that collect/store results
- Provides unified `store_result()` interface
- Used by: EventIdentifierTool, CausalReasonerTool

**ToolResponseMixin** (`src/tools/base.py`)
- Mixin for standardized JSON responses
- Methods: `json_response()`, `error_response()`, `success_response()`
- Handles datetime/enum serialization automatically
- Available for incremental adoption across tools

### Data Retrieval
-   **ArticleCollector**: Fetches and stores articles (supports temporal filtering).
-   **WebSearch**: search via DuckDuckGo or SearXNG.
-   **WebFetch**: Retrieves full page content.

### Patterns
-   **Provenance**: Most tools accept `question_id` to tag generated data.
-   **Result Collectors**: Tools often write full data to a `ResultCollector` and return only IDs/summaries to the agent.

**Example usage:**
```python
# Temporal filtering (recommended - uses new service layer)
from src.core.temporal_filter_service import TemporalFilterService

window_start, window_end = TemporalFilterService.get_evidence_window(
    resolution_date, estimated_start_time
)
filtered = TemporalFilterService.filter_by_window(articles, window_start, window_end)

# Article timeline analysis
from src.utils.article_analysis import analyze_timeline, identify_gaps

timeline = analyze_timeline(articles, resolution_date, coverage_start)
gaps = identify_gaps(timeline, min_gap_days=7)

# Graph structure analysis
from src.utils.graph_analysis import analyze_graph_structure

graph_stats = analyze_graph_structure(hypotheses)
```

## Service Layer Architecture

The codebase follows a layered architecture with clear separation of concerns:

### Domain Services (`src/domain/`)

Pure business logic with no CLI or presentation dependencies.

**ServiceBase** (`src/domain/service_base.py`)
- Base class for all domain services
- Provides common utilities like `get_db()` for database path handling
- Eliminates repeated patterns across services

**QuestionService** (`src/domain/question_service.py`)
- Domain operations for questions (evidence checking, cascade analysis, deletion)
- Used by both CLI and pipelines to avoid circular dependencies
- Example:
```python
from src.domain.question_service import QuestionService

service = QuestionService(db)
has_evidence = service.has_evidence(question_id)
service.clear_evidence(question_id, cascade=True)
```

**ForecastContextService** (`src/domain/forecast_context_service.py`)
- Manages forecasting context extraction and validation from MCP request headers
- Parses X-Question-ID, X-Simulated-Date, X-Knowledge-Cutoff headers
- Validates temporal consistency (knowledge cutoff < simulated date)
- Caches Question objects
- Example:
```python
from src.domain.forecast_context_service import ForecastContextService

service = ForecastContextService(db)
context = service.parse_context_from_headers(headers)
service.validate_context(context)  # Raises if invalid
question = service.get_question_for_context(context)
```

**ArticleOperationsService** (`src/domain/article_operations_service.py`)
- Handles article search and retrieval with temporal filtering
- Integrates with HybridSearch for semantic + keyword search
- Validates temporal access (articles only accessible before simulated date)
- Example:
```python
from src.domain.article_operations_service import ArticleOperationsService

service = ArticleOperationsService(db, hybrid_search)
articles = await service.search_articles(
    query="climate change",
    simulated_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
    max_results=10
)
article = service.fetch_article(article_id, simulated_date)
```

**ForecastSubmissionService** (`src/domain/forecast_submission_service.py`)
- Validates and submits forecasts with graph linking
- Validates predictions based on question type (binary, MCQ, quantity)
- Creates Forecast records with metadata
- Links ForecastEvent and ForecastHypothesis to forecast_id
- Example:
```python
from src.domain.forecast_submission_service import ForecastSubmissionService

service = ForecastSubmissionService(db)

# Validate prediction
valid, parsed, error = service.validate_prediction(question, "0.75")
if not valid:
    print(f"Invalid: {error}")

# Create forecast
forecast = service.create_forecast(
    question_id="q123",
    session_id="session123",
    prediction=parsed,
    confidence=0.8,
    reasoning="Analysis shows...",
    articles_accessed=["a1", "a2"],
    simulated_date=datetime.now(timezone.utc)
)

# Link graph elements
graph_counts = service.link_forecast_graph(forecast.id, session_id)
print(f"Linked {graph_counts['events']} events, {graph_counts['hypotheses']} hypotheses")
```

### Core Services (`src/core/`)

Low-level services for infrastructure concerns.

**TemporalFilterService** (`src/core/temporal_filter_service.py`)
- Unified temporal filtering for articles, events, and other timestamped entities
- Eliminates duplication between article_analysis.py and event_analysis.py
- Calculates evidence windows with fallback logic
- Filters entities by time windows or cutoff dates
- Example:
```python
from src.core.temporal_filter_service import TemporalFilterService

# Calculate evidence window
window_start, window_end = TemporalFilterService.get_evidence_window(
    resolution_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
    estimated_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    fallback_window_days=365
)

# Filter articles by window
filtered_articles = TemporalFilterService.filter_by_window(
    articles, window_start, window_end, date_field="published_date"
)

# Filter events by cutoff
accessible_events = TemporalFilterService.filter_by_cutoff(
    events, cutoff_date, date_field="occurred_date"
)
```

**TemporalGateway** (`src/core/temporal_gateway.py`)
- Provides temporal access control for forecasting scenarios
- Ensures forecasts only use information available before a specified cutoff date
- **Architecture**: Delegates filtering logic to TemporalFilterService for consistency
- Adds logging, database integration, and forecast validation on top of core filtering

**Key methods**:
- `filter_articles()` - Filters articles before cutoff (delegates to TemporalFilterService)
- `filter_events()` - Filters events before cutoff (delegates to TemporalFilterService)
- `is_article_accessible()` - Check single article accessibility
- `is_event_accessible()` - Check single event accessibility
- `validate_forecast()` - Complex validation with database integration

**Usage**:
```python
from src.core.temporal_gateway import TemporalGateway
from datetime import datetime, timezone

gateway = TemporalGateway(cutoff_date=datetime(2024, 11, 4, tzinfo=timezone.utc))
accessible_articles = gateway.filter_articles(all_articles)
accessible_events = gateway.filter_events(all_events)

# Check single item
if gateway.is_article_accessible(article):
    # Process article
    pass
```

**Design**: Thin wrapper around TemporalFilterService with added:
- Debug logging for filtered counts
- Database integration (via GenericDatabase)
- Forecast validation logic with temporal constraints

### Utility Services (`src/utils/`)

**Serialization** (`src/utils/serialization.py`)
- Common serialization patterns for enums and domains
- Eliminates repeated `value.value if hasattr(value, 'value') else value` pattern
- Example:
```python
from src.utils.serialization import serialize_domain

# Works with both Enum instances and strings
domain_str = serialize_domain(question.domain)  # "politics"
```

### Pipeline Services (`src/pipelines/`)

Orchestration logic for running pipelines with progress tracking.

**PipelineExecutor** (`src/pipelines/executor.py`)
- Executes all pipeline types (evidence, forecast, collection, etc.)
- Progress tracking via callbacks
- Used directly by backend API
- Example:
```python
from src.pipelines.executor import PipelineExecutor
from src.pipelines.types import PipelineType

executor = PipelineExecutor(config, db_path)
result = await executor.execute(
    PipelineType.EVIDENCE,
    question_ids=["q1", "q2"],
    on_progress=lambda p: print(f"{p.current}/{p.total}")
)
```

**PipelineFactory** (`src/pipelines/factory.py`)
- Centralized pipeline creation with consistent configuration
- Example:
```python
from src.pipelines.factory import PipelineFactory

pipeline = PipelineFactory.create_evidence_pipeline(
    config, db_path, adaptive=True, agent_max_steps=50
)
```

**Unified Types** (`src/pipelines/types.py`)
- Single source of truth for `PipelineType`, `PipelineProgress`, `PipelineResult`
- Shared across CLI, backend API, and pipelines (no duplicate enums)

### CLI Layer (`src/cli/core/`)

Thin wrappers that delegate to services.

**PipelineRunner** (`src/cli/core/pipeline_runner.py`)
- CLI wrapper for PipelineExecutor
- Maintains backward compatibility with existing commands
- 87% smaller after service extraction (819→106 lines)

**QuestionManager** (`src/cli/core/question_manager.py`)
- CLI wrapper for QuestionService
- Adds presentation-specific methods (`list_questions`, `show_question`, `get_stats`)
- Delegates domain logic to QuestionService

### Benefits

1. **No Circular Dependencies**: Pipelines use `QuestionService`, not CLI classes
2. **Reusability**: Backend API uses `PipelineExecutor` and `QuestionService` directly
3. **Testability**: Services are pure functions testable in isolation
4. **Maintainability**: Each service has a single, focused responsibility
5. **Flat Hierarchy**: Max 2 levels deep (domain/ and pipelines/)

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
7. **Service extraction over monoliths**: Systematic pattern of extracting domain logic and orchestration into focused services:
   - QuestionCollectionOrchestrator: 660→366 lines via `SourceCoordinator`, `GapAnalyzer`, `GapFiller`, `QuotaManager`
   - PipelineRunner: 819→106 lines (87% reduction) via `PipelineExecutor`, `QuestionService`
   - Maintains flat hierarchy (max 2 levels: domain/ and pipelines/)
   - Breaks circular dependencies (pipelines no longer import from CLI layer)

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
