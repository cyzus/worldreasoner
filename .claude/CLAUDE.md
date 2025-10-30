# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WorldReasoner is an **LLM forecasting benchmark system** that evaluates how well Large Language Models can predict future events. It uses temporal access control to simulate historical contexts, ensuring LLMs only access information from specific time periods. The system combines real-world news data with synthetic datasets to test genuine forecasting ability.

**Core Concept**: Events are causal nodes in a graph; articles are information sources documenting them. The temporal gateway restricts what information an LLM can access during forecasting.

## Development Commands

### Environment Setup
```powershell
# Create and activate virtual environment
uv venv
.venv\Scripts\Activate.ps1  # Windows PowerShell
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
uv sync

# Install Playwright browsers (for web scraping)
uv run playwright install

# Set up configuration
cp config/default.yaml config/local.yaml
# Edit config/local.yaml with your LLM API keys
```

### Running the Pipeline
```bash
# Run question pipeline with CLI tool
python run_question_pipeline.py --sources config/sources.yaml --db worldreasoner.db --max-questions 10

# Run integration test (full pipeline)
uv run python tests/integration/test_agentic_pipeline.py
```

### Testing
```bash
# Run all unit tests
uv run pytest tests/unit/ -v

# Run specific test file
uv run pytest tests/unit/test_agent_factory.py -v

# Run specific test function
uv run pytest tests/unit/test_result_collector.py::TestResultCollector::test_bool_builtin -v

# Skip integration tests (marked with @pytest.mark.integration)
uv run pytest -m "not integration"

# Keep test databases for inspection
uv run pytest --basetemp=./test-output tests/
```

### Database Inspection
```bash
# SQLite databases can be inspected directly
sqlite3 worldreasoner.db
# .schema articles
# SELECT * FROM articles LIMIT 5;
```

## Architecture

### Dual Pipeline System

WorldReasoner uses **two complementary pipelines**:

1. **Question Pipeline (Forward-Looking)**: Creates forecast questions from current events
   - Flow: News Sources → Articles → Events → Questions
   - Runs monthly to generate fresh benchmark questions
   - Implementation: `src/pipelines/question/pipeline.py`

2. **Evidence Pipeline (Backward-Looking)**: Builds causal explanations using hindsight
   - Flow: Resolved Questions → Hindsight Reasoning → Evidence → Causal Graph
   - Runs after questions resolve to create ground truth explanations
   - Status: Planned (not yet implemented)

### Design Patterns

**AgentFactory Pattern** (`src/agents/factory.py`):
- Centralized agent creation with dependency injection
- Reduces boilerplate by 40%
- Usage: `AgentFactory.create_web_agent(tools=[my_tool])`

**ResultCollector Pattern** (`src/pipelines/stages/collectors.py`):
- Stateless tools with clean separation of concerns
- Tools process data, collectors store results, stages orchestrate
- **CRITICAL**: Always check existence with `is not None`, not truthiness (see bug details below)

**Pipeline Stage Pattern** (`src/pipelines/base.py`):
- Composable, type-safe processing units: `PipelineStage[TInput, TOutput]`
- Generic types ensure compile-time correctness
- Stages return `PipelineStageResult[TOutput]` with metrics

**Token-Optimized Tools**:
- Agents receive summaries, tools process full content internally
- Achieves 98% token reduction
- Example: `ArticleCollectorTool` fetches full HTML internally, returns JSON summary

### Directory Structure

```
src/
├── config/              # Configuration (app, database, pipeline)
│   ├── app.py          # App and LLM config
│   ├── database.py     # SQLite config
│   └── pipeline.py     # Pipeline configs
├── core/               # Shared infrastructure
│   └── database.py     # Generic database layer (ONLY db interface)
├── domain/             # Business logic & models
│   └── models/         # Article, Event, Question, Forecast
├── pipelines/          # Data processing pipelines
│   ├── base.py        # PipelineStage, Pipeline base classes
│   ├── question/      # Question generation pipeline
│   ├── stages/        # Reusable pipeline stages
│   └── prompts/       # Agent prompt templates
├── agents/            # AI agents (smolagents)
│   ├── base.py       # BaseAgent
│   ├── web_agent.py  # WebAgent with web_search
│   └── factory.py    # AgentFactory pattern
└── utils/            # Utilities (logging)

tests/
├── unit/              # Unit tests
│   ├── agents/       # Agent tests
│   ├── domain/       # Model tests
│   └── tools/        # Tool tests
└── integration/       # Integration tests (marked)
```

### Data Models

Located in `src/domain/models/`, all models use `@register_model` decorator for automatic DB schema generation:

- **Article** (`article.py`): Raw news content with deduplication via content hashing
- **Event** (`event.py`): Causal graph nodes with `CausalLink` relationships
- **Question** (`question.py`): Forecast tasks with `ground_truth` and `resolution_date`
- **Forecast** (`forecast.py`): LLM predictions for evaluation

### Database Layer

**GenericDatabase** (`src/core/database.py`):
- Type-safe interface using Pydantic models
- SQLite with JSON serialization for complex types
- Auto-generates schemas from `@register_model` decorators
- **Integrated temporal filtering** - automatically filters Articles and Events by cutoff date
- This is the **ONLY** database interface - all models use this

```python
# Without temporal filtering (normal operation)
db = GenericDatabase('worldreasoner.db')
db.save(Article, article_instance)
articles = db.get_many(Article)  # Returns all articles

# With temporal filtering (for forecasting benchmarks)
from datetime import datetime, timezone
cutoff = datetime(2024, 11, 4, tzinfo=timezone.utc)
db = GenericDatabase('worldreasoner.db', cutoff_date=cutoff)
articles = db.get_many(Article)  # Returns only articles strictly before cutoff (< not <=)
article = db.get(Article, "art_id")  # Returns None if published at or after cutoff

# Using TemporalContext (automatic cutoff detection)
from src.core import TemporalContext
with TemporalContext(cutoff_date=cutoff):
    db = GenericDatabase('worldreasoner.db')  # Automatically uses cutoff from context
    articles = db.get_many(Article)  # Temporally filtered

# High-level wrapper (for application code)
db = Database('worldreasoner.db')
db.save_article(article_instance)
```

### Temporal Gateway (Forecasting Validity)

**Critical Component**: The Temporal Gateway (`src/core/temporal_gateway.py`) ensures forecasting benchmarks are valid by preventing information leakage.

**Core Classes**:
- **TemporalGateway**: Filters Articles and Events based on cutoff dates
- **TemporalContext**: Context manager for setting temporal constraints
- **ValidationResult**: Results from forecast validation

**How it works**:
1. Each Question has a `cutoff_date` representing when the forecast was "made"
2. The Gateway filters out Articles published at or after the cutoff (strictly before: `<`)
3. The Gateway filters out Events that occurred at or after the cutoff (strictly before: `<`)
4. Events with `occurred_date=None` are conservatively rejected
5. **IMPORTANT**: Cutoff dates are **exclusive** - items exactly at the cutoff are NOT accessible

**Usage**:
```python
from datetime import datetime, timezone
from src.core import TemporalGateway, TemporalContext

# Direct usage
cutoff = datetime(2024, 11, 4, tzinfo=timezone.utc)
gateway = TemporalGateway(cutoff_date=cutoff)

accessible_articles = gateway.filter_articles(all_articles)
accessible_events = gateway.filter_events(all_events)
is_accessible = gateway.is_article_accessible(article)

# Context manager (recommended)
with TemporalContext(cutoff_date=cutoff):
    # Database automatically uses this cutoff
    db = GenericDatabase('worldreasoner.db')
    articles = db.get_many(Article)  # Automatically filtered

# Validate forecasts
validation = gateway.validate_forecast(forecast, question, db)
if not validation.valid:
    print(f"Errors: {validation.errors}")
```

**Integration with Database**:
GenericDatabase uses TemporalGateway internally when `cutoff_date` is provided:
- SQL-level filtering for performance (`published_date < cutoff` - strictly before)
- Python-level filtering for safety (handles None dates, edge cases)
- Transparent to the caller - just works automatically
- Items exactly at cutoff are excluded (not accessible)

**IMPORTANT**: Always use timezone-aware datetimes (UTC):
```python
# ✅ CORRECT
cutoff = datetime(2024, 11, 4, tzinfo=timezone.utc)

# ❌ WRONG - Will raise ValueError
cutoff = datetime(2024, 11, 4)  # Naive datetime
```

### Configuration

- **Default**: `config/default.yaml` (committed)
- **Local overrides**: `config/local.yaml` (gitignored, create from default)
- **Article sources**: `config/sources.yaml` (RSS and web scraping configs)
- **Access**: Use `src.config.get_config()` (singleton pattern)
- **LLM**: Uses `litellm` wrapper supporting Gemini, OpenAI, etc.

## Critical Conventions

### 1. ResultCollector Pattern (IMPORTANT!)

**Critical Bug**: `ResultCollector[T]` has a custom `__bool__` method that returns `False` when empty.

```python
# ❌ WRONG - Fails when collector is empty (always at start!)
if self.collector:
    self.collector.add(item)

# ✅ CORRECT - Use 'is not None' for existence checks
if self.collector is not None:
    self.collector.add(item)
```

**Why this matters**: Using `if self.collector:` causes data loss when the collector starts empty. The collector exists but evaluates to `False`, so items are never added.

### 2. Accessing Pipeline Stage Outputs

```python
# ✅ CORRECT - Access outputs from result
result = await stage.execute(inputs)
outputs = result.outputs  # List[TOutput]

# ❌ WRONG - Don't access tool internal properties
outputs = stage.tool.collected_items  # May be empty!
```

After refactoring, outputs flow through `PipelineStageResult.outputs`. Tests must use `result.outputs`.

### 3. Logging with Loguru

```python
from src.utils.logging import logger

logger.info("Stage completed successfully")
logger.debug(f"Processing {len(items)} items")
logger.warning("Unexpected condition")
logger.error(f"Failed: {e}")
```

**Never use `print()`**. Loguru provides:
- File rotation: `logs/worldreasoner_{time}.log` (10MB max, 10 files)
- Color-coded console output
- Avoid Unicode characters on Windows (encoding errors)

### 4. Timezone-Aware Datetimes

Always use timezone-aware datetimes (UTC):

```python
from datetime import datetime, timezone
now = datetime.now(timezone.utc)  # ✅ Correct
```

### 5. Model Registration

```python
from src.core.database import register_model

@register_model('table_name', indexes=['indexed_field'])
class YourModel(BaseModel):
    id: str = Field(..., description="Unique identifier")
```

### 6. Agent Prompts

Use `ContextualPromptGenerator[T]` base class (`src/pipelines/prompts/base.py`):
- Define `PromptTemplate` with required/optional variables
- Implement `format_item()` for per-item formatting
- Implement `get_instruction()` for full instruction generation
- Include current date context via `format_datetime()`

## Common Development Patterns

### Creating Pipeline Stages

```python
from src.pipelines.base import PipelineStage

class MyStage(PipelineStage[InputType, OutputType]):
    def __init__(self, config, db_path: str):
        super().__init__("stage_name", config)
        self.db = GenericDatabase(db_path)

    async def process(self, inputs: List[InputType]) -> List[OutputType]:
        outputs = []
        for item in inputs:
            # Process item
            outputs.append(processed_item)
        return outputs
```

### Creating Agentic Tools

```python
from smolagents import Tool

class MyTool(Tool):
    name = "my_tool"
    description = "What this tool does"
    inputs = {
        "param": {"type": "string", "description": "Parameter description"}
    }
    output_type = "string"

    def __init__(self, collector: Optional[ResultCollector[T]] = None):
        super().__init__()
        self.collector = collector

    def forward(self, param: str) -> str:
        # Do heavy processing internally
        result = self._fetch_and_process(param)

        # Store in collector if provided
        if self.collector is not None:  # ✅ CRITICAL: Use 'is not None'
            self.collector.add(result)

        # Return minimal summary (token optimization)
        return json.dumps({"status": "success", "id": result.id})
```

### Using AgentFactory

```python
from src.agents.factory import AgentFactory
from src.pipelines.stages.tools import ArticleCollectorTool

# Create tool with collector
collector = ResultCollector[Article]()
tool = ArticleCollectorTool(collector=collector)

# Create agent with tool
agent = AgentFactory.create_web_agent(tools=[tool])

# Run agent
result = agent.run("Search for AI news articles from last week")

# Get collected results
articles = collector.get_all()
```

### Database Operations

```python
from src.core.database import GenericDatabase
from src.domain.models import Article

db = GenericDatabase("worldreasoner.db")

# Create table (automatic from @register_model)
db.create_table(Article)

# Insert
article = Article(id="art_123", title="...", ...)
db.save(Article, article)

# Query
articles = db.get_many(Article, filters={'domain': 'tech'})
article = db.get(Article, "art_123")
```

## Key Architecture Decisions

1. **SQLite over PostgreSQL**: Simplicity for local development, single-file portability
2. **smolagents framework**: Lightweight agentic framework with LiteLLM integration
3. **Content hashing**: Article deduplication across pipeline runs
4. **Event/Article separation**: Events are causal nodes (graph), articles are documentation (info)
5. **Token optimization**: Tools minimize token usage by processing internally
6. **Generic type safety**: `PipelineStage[TInput, TOutput]` ensures compile-time correctness

## Testing Strategy

### Unit Tests (`tests/unit/`)
- Test individual functions/classes in isolation
- Fast, no external dependencies
- Mock collectors, agents, and databases

### Integration Tests (`tests/integration/`)
- Test components working together
- Marked with `@pytest.mark.integration`
- Include end-to-end pipeline tests
- Run separately: `uv run pytest -m integration`

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

## Database Migrations

When new fields are added to models, existing databases need to be migrated. Migration scripts are in the `migrations/` folder.

**Check for available migrations**: See `migrations/README.md`

**Creating new migrations**: If you add a field to a model, create a migration script following the pattern in existing migrations.

## Dependencies

Key dependencies (see `pyproject.toml` for full list):
- **smolagents[toolkit,litellm,mcp]**: Agentic framework with tool calling
- **litellm**: Multi-provider LLM client (Gemini, OpenAI, etc.)
- **crawl4ai**: Advanced web scraping with JavaScript support
- **pydantic**: Data validation and settings
- **pytest-asyncio**: Async test support
- **loguru**: Professional logging with rotation
- **feedparser**: RSS/Atom feed parsing
