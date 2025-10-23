# WorldReasoner AI Agent Instructions

## General Guidelines

**DO NOT create documentation files** (README.md, guides, etc.) unless the user explicitly requests them. Focus on implementing features and writing code.

## Project Overview

WorldReasoner is an **LLM forecasting benchmark system** that tests AI's ability to predict future events using temporal access control. It uses a dual-pipeline architecture powered by **smolagents** to generate forecast questions from news data and evaluate predictions.

**Core Concept**: Events are causal nodes in a graph; articles are information sources documenting them. The temporal gateway restricts what information an LLM can access during forecasting.

### Directory Structure (Option B Architecture)

```
src/
├── config/              # All configuration
│   ├── __init__.py
│   ├── app.py          # App, Server, LLM configs
│   ├── database.py     # SQLite config
│   └── pipeline.py     # Pipeline configs
├── core/               # Shared infrastructure
│   ├── database.py     # Generic database layer
│   └── __init__.py
├── domain/             # Business logic & models
│   ├── models/
│   │   ├── article.py
│   │   ├── event.py
│   │   ├── question.py
│   │   └── forecast.py
│   └── __init__.py
├── pipelines/          # Data processing pipelines
│   ├── base.py        # Pipeline base classes
│   ├── question/      # Question generation pipeline
│   ├── stages/        # Reusable pipeline stages
│   ├── prompts/       # Agent prompt templates
│   └── __init__.py
├── agents/            # AI agents (smolagents)
│   ├── base.py
│   ├── web_agent.py
│   └── factory.py
└── mcp_server/        # MCP server (future)
```

**Benefits of this structure**:
- Clear separation: domain (what), core (how), pipelines (when), config (settings)
- Easy to navigate: models in domain/, infrastructure in core/
- Scalable: pipelines/ can grow independently
- Testable: tests/ mirrors src/ structure

## Architecture

### Dual Pipeline System

```
Question Pipeline (Forward):  Sources → Articles → Events → Questions
Evidence Pipeline (Backward): Resolved Questions → Evidence → Causal Graph
```

- **Question Pipeline** (`src/pipelines/question/pipeline.py`): Creates benchmark questions from current events
- **Evidence Pipeline** (planned): Collects hindsight evidence for resolved questions
- **Pipeline Stages** (`src/pipelines/stages/`): Composable, type-safe processing units with error handling

### Dual Collection Approach

Article collection supports **two methods** (automatically detected via `scraper_type`):

1. **RSS-based** (`scraper_type: "rss"`): Fast, reliable feed parsing
   - Uses `RssFetchTool` to parse RSS/Atom feeds
   - Fetches full content via `ArticleCollectorTool`
   - ~0.07 articles/sec, zero LLM costs
   - 95%+ reliability for sites with RSS feeds

2. **Agent-based** (`scraper_type: "web"`): Flexible AI-guided scraping
   - Uses `WebAgent` with `web_search` for discovery
   - Intelligent filtering and content extraction
   - ~0.03 articles/sec, uses LLM tokens
   - Works for sites without RSS

**Best practice**: Configure both in `config/sources.yaml` for optimal coverage
- Use RSS for 90% of news sites (fast, free)
- Use agent-based as fallback (flexible, handles edge cases)

See `docs/RSS_VS_AGENT_COLLECTION.md` for detailed comparison

### Agentic Tools Pattern (Token Optimization)

**Critical Design**: Tools fetch/process heavy data internally, returning only summaries to agents (98% token reduction).

**Example** - `ArticleCollectorTool` (`src/pipelines/stages/tools/article_collector.py`):
- Agent finds URLs via `web_search` → calls tool with **only URL + metadata**
- Tool fetches full content internally using `VisitWebpageTool`
- Returns token-efficient JSON summary to agent

**Always**:
- Keep agent prompts minimal (see `src/pipelines/prompts/`)
- Pass IDs/references to tools, not full objects
- Tools handle heavy lifting (web scraping, content processing, DB operations)

### Data Models

Located in `src/domain/models/`:
- **Article** (`article.py`): Raw news content with deduplication via content hashing
- **Event** (`event.py`): Causal graph nodes with `CausalLink` relationships
- **Question** (`question.py`): Forecast tasks with `ground_truth` and `resolution_date`
- **Forecast** (`forecast.py`): LLM predictions for evaluation

All models use `@register_model` decorator for automatic DB schema generation.

### Database Layer

**Generic Database** (`src/core/database.py`):
- Type-safe interface using Pydantic models
- SQLite with JSON serialization for complex types
- Auto-generates schemas from model field annotations
- Models register via `@register_model('table_name', indexes=['field1', 'field2'])`

## Development Workflows

### Running Pipelines

```powershell
# Activate virtual environment
& .venv/Scripts/Activate.ps1

# Run question pipeline (generates forecast questions)
python -m tests.test_agentic_pipeline
```

### Testing

Uses pytest with async support:
- `tests/unit/`: Unit tests for individual components
- `tests/integration/`: Integration tests (marked with `@pytest.mark.integration`)
  - `test_agentic_pipeline.py`: End-to-end pipeline orchestration test
  - `test_pipeline_stages.py`: Individual stage tests + manual integration
- Run with: `pytest -v` or `pytest -m "not integration"` (skip integration)

**Test Types**:
- **Unit tests**: Test individual functions/classes in isolation
- **Integration tests**: Test components working together
- **End-to-end tests**: Test full pipeline via `QuestionPipeline.run()`

**Key Testing Pattern** for pipeline stages:
```python
# Create stage
stage = ArticleCollectionStage(config, db_path="test_worldreasoner.db")

# Execute stage (returns PipelineStageResult)
result = await stage.execute(inputs)

# Access outputs from result (NOT from tool properties!)
outputs = result.outputs  # ✅ Correct
# outputs = stage.tool.collected_items  # ❌ Wrong!

# Validate results
assert len(outputs) > 0
assert result.status == PipelineStageStatus.COMPLETED
assert result.items_output == len(outputs)
```

### Configuration

- **Default config**: `config/default.yaml`
- **Override via env vars**: `WORLDREASONER__DATABASE__PASSWORD`
- **Config access**: Use `src.utils.config.get_config()` (singleton pattern)
- **LLM setup**: Uses `litellm` wrapper (`src/llm.py`) supporting multiple providers

### Adding New Pipeline Stages

1. Inherit from `PipelineStage[TInput, TOutput]` in `src/pipelines/base.py`
2. Implement `async def process(self, inputs: List[TInput]) -> List[TOutput]`
3. Return `PipelineStageResult` with metrics and error handling
4. Add to pipeline via `pipeline.add_stage(your_stage)`

### Creating Agentic Tools

1. Inherit from `smolagents.Tool`
2. Define `name`, `description`, `inputs` (schema), `output_type`
3. Implement `forward()` method that does heavy work internally
4. Return minimal JSON strings (not full objects)
5. See examples: `ArticleCollectorTool`, `EventIdentifierTool`, `QuestionGeneratorTool`

## Critical Conventions

### ResultCollector Pattern (IMPORTANT!)

**Critical Bug to Avoid**: `ResultCollector[T]` has a custom `__bool__` method that returns `False` when empty. This breaks the intuitive `if collector:` check.

```python
# ❌ WRONG - Will fail when collector is empty (even if it exists!)
if self.collector:
    self.collector.add(item)

# ✅ CORRECT - Always use 'is not None' for existence checks
if self.collector is not None:
    self.collector.add(item)
```

**Why this matters**: Tools store results in collectors. Using `if self.collector:` causes data loss when the collector starts empty (which is always the case). See `docs/COLLECTOR_BUG_FIX.md` for full details.

**Fixed files**: `ArticleCollectorTool`, `EventIdentifierTool`, `QuestionGeneratorTool`

### Accessing Pipeline Stage Outputs

Pipeline stages use `execute()` which returns `PipelineStageResult[TOutput]`:

```python
# ✅ CORRECT - Access outputs from result
result = await stage.execute(inputs)
outputs = result.outputs  # List[TOutput] with actual results

# ❌ WRONG - Don't access tool internal properties
outputs = stage.tool.collected_items  # These may be empty!
```

**Why**: After refactoring, outputs flow through `PipelineStageResult.outputs`, not tool properties. Tests must use `result.outputs` to get actual processed data.

### Logging with Loguru

Use `loguru` for all logging (never `print()`):

```python
from src.utils.logging import logger

logger.info("Stage completed successfully")
logger.debug(f"Processing {len(items)} items")
logger.warning("Unexpected condition detected")
logger.error(f"Failed to process: {e}")
```

**Configuration**: Auto-configured via `src/utils/logging.py` with file rotation and colored console output. Avoid Unicode characters (like ✓) on Windows to prevent encoding errors.

### Timezone-Aware Datetimes

**Always use timezone-aware datetimes** (UTC). Events, questions, and articles use `datetime.now(timezone.utc)`.

```python
from datetime import datetime, timezone
now = datetime.now(timezone.utc)  # ✓ Correct
```

### Agent Prompts (src/pipelines/prompts/)

Use `ContextualPromptGenerator[T]` base class:
- Define `PromptTemplate` with `required_vars` and `optional_vars`
- Implement `format_item()` for per-item formatting
- Implement `get_instruction()` for full instruction generation
- Include current date context via `format_datetime()`

### Model Registration

```python
@register_model('table_name', indexes=['indexed_field'])
class YourModel(BaseModel):
    id: str = Field(..., description="Unique identifier")
```

### Validation Date Ranges

Question resolution dates validated in `QuestionGeneratorTool`:
- **Min**: Earliest related event's occurred_date
- **Max**: Current date + 1 year
- Ground truth only included for PAST events

## Key Files Reference

- **Configuration**: `src/config/__init__.py` (main), `src/config/database.py` (SQLite), `src/config/app.py`, `src/config/pipeline.py`
- **Database layer**: `src/core/database.py` (GenericDatabase + Database wrapper)
- **Domain models**: `src/domain/models/` (Article, Event, Question, Forecast)
- **Pipeline base**: `src/pipelines/base.py`
- **Question pipeline**: `src/pipelines/question/pipeline.py`
- **Pipeline stages**: `src/pipelines/stages/`
- **Agent tools**: `src/pipelines/stages/tools/`
- **Agent initialization**: `src/agents/base.py`, `src/agents/web_agent.py`, `src/agents/factory.py`
- **LLM client**: `src/llm.py` (litellm wrapper)

## Common Patterns

### Running Agent-Based Stages

```python
from src.agents.web_agent import WebAgent
from src.data.pipelines.stages.tools import ArticleCollectorTool

tool = ArticleCollectorTool(db=database)
agent = WebAgent(config=config, tools=[tool])
instruction = "Search for articles about climate change..."
result = agent.run(instruction)
```

### Database Operations

```python
from src.core.database import GenericDatabase
from src.domain.models import Article

db = GenericDatabase[Article]("worldreasoner.db")
article = Article(id="art_123", title="...", ...)
db.insert(Article, article)  # Type-safe insert
articles = db.get_many(Article, filters={'domain': 'tech'})
```

### Error Handling in Stages

```python
async def execute(self, inputs: List[TInput]) -> PipelineStageResult:
    result = PipelineStageResult(stage_name=self.name, ...)
    try:
        outputs = await self.process(inputs)
        result.status = PipelineStageStatus.COMPLETED
    except Exception as e:
        result.status = PipelineStageStatus.FAILED
        result.error_message = str(e)
        raise
```

## Project-Specific Decisions

1. **Why SQLite over PostgreSQL**: Simplicity for local development, single-file portability, easy upgrade path if needed
2. **Why smolagents**: Lightweight agentic framework with tool calling and LiteLLM integration
3. **Why content hashing**: Deduplication across pipeline runs (see `ArticleCollectorTool._hash_content`)
4. **Why separate Event/Article models**: Events are causal nodes (graph layer), articles are documentation (info layer)
5. **Why token optimization**: Agent context windows limited; tools must minimize token usage
6. **Why Option B structure**: Cleaner separation between domain (business logic), core (infrastructure), pipelines (processes), and config
7. **Why loguru for logging**: Professional rotating file logs, color-coded console output, better than print()
8. **Why PipelineStageResult.outputs**: Centralized output storage for pipeline stages, enables proper testing and metrics

## Recent Refactoring (2025-10)

### Logging Migration
- Migrated from `print()` to `loguru` for all logging
- Added `src/utils/logging.py` with auto-configuration
- File rotation: `logs/worldreasoner_{time}.log` (10MB max, 10 file retention)
- Removed Unicode characters from logs to prevent Windows encoding errors

### ResultCollector Bug Fix
- Discovered `ResultCollector.__bool__()` returns `False` when empty
- Fixed all tools to use `if self.collector is not None:` instead of `if self.collector:`
- Documented in `docs/COLLECTOR_BUG_FIX.md`
- Affected tools: ArticleCollectorTool, EventIdentifierTool, QuestionGeneratorTool

### Pipeline Stage Execution
- Enhanced `PipelineStageResult[TOutput]` to be generic and store outputs
- `execute()` now returns outputs in `result.outputs` field
- Tests must access `result.outputs` instead of tool internal properties
- Enables proper validation and metrics tracking

### Configuration Standardization
- Standardized on `get_config()` singleton pattern (removed `load_config()`)
- All modules now use centralized config access
- Pydantic v2 migration: Class-based `Config` → `ConfigDict`

## Dependencies

- **smolagents**: Agentic framework with `[toolkit,litellm,mcp]` extras
- **litellm**: Multi-provider LLM client (Gemini, OpenAI, etc.)
- **pydantic**: Data validation and settings management
- **pytest-asyncio**: Async test support
- **loguru**: Professional logging with rotation

See `pyproject.toml` for full dependency list.

## Troubleshooting

### Articles/Events/Questions Not Being Collected

**Symptom**: Logs show "status: stored" but collector has 0 items.

**Cause**: Using `if self.collector:` instead of `if self.collector is not None:`

**Solution**: The `ResultCollector.__bool__()` method returns `False` when empty. Always check existence with `is not None`.

### Test Shows 0 Outputs But Stage Completed Successfully

**Symptom**: `result.status == COMPLETED` but `len(outputs) == 0` in tests.

**Cause**: Accessing wrong property - using `stage.tool.collected_items` instead of `result.outputs`.

**Solution**: Always get outputs from `result.outputs` after calling `stage.execute()`.

### Windows Encoding Errors in Logs

**Symptom**: `UnicodeEncodeError: 'gbk' codec can't encode character`

**Cause**: Using Unicode characters (✓, ✗, etc.) in log messages on Windows.

**Solution**: Use ASCII characters only in logs, or set UTF-8 encoding at script start:
```python
import sys, codecs
if sys.platform == "win32":
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
```

### Pipeline Returns Empty Questions

**Symptom**: Pipeline runs successfully but generates no questions.

**Possible causes**:
1. No events identified from articles (check event identification logs)
2. Events don't meet question generation criteria (difficulty, resolution date)
3. Agent fails to generate valid JSON (check agent logs for errors)

**Debug**: Run `test_pipeline_stages.py` to test each stage individually.
