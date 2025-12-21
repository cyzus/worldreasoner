# AGENTS.md

This file provides guidance to AI Code Assistants when working with code in this repository.

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
cp config/config.example.yaml config/config.yaml
# Edit config/config.yaml with your LLM API keys
```

### Using the CLI
```bash
# Unified CLI interface
wr --help                          # Show all commands

# Database management
wr db stats                        # Database statistics
wr db list questions               # List all questions
wr db list questions --domain politics --type binary
wr db show question <id>           # Show question details
wr db clear-evidence <id>          # Clear evidence for question

# Question collection
wr question collect                # Interactive collection
wr question collect --goal config/collection_goal.yaml

# Evidence pipeline
wr evidence run                    # Run evidence pipeline
wr evidence run --question-id <id> # Single question

# Forecasting
wr forecast make                   # Make forecasts
wr forecast evaluate               # Evaluate forecasts
```

### Running the Pipeline
```bash
# Run goal-oriented question collection with CLI tool
python examples/run_goal_collection.py --goal config/collection_goal.yaml --db worldreasoner.db

# Run integration test (full pipeline)
uv run python tests/integration/test_agentic_pipeline.py
```

### Running the MCP Server
```bash
# Standard stdio mode (for Claude Desktop)
python -m src.mcp_forecasting_server

# HTTP REST mode
python -m src.mcp_forecasting_server --mode http --port 8100

# Streaming mode (SSE)
python -m src.mcp_forecasting_server --mode stream --port 8110

# Interactive development mode
uv run fastmcp dev src.mcp_forecasting_server
```

See [docs/MCP_SERVER.md](docs/MCP_SERVER.md) for detailed documentation on all modes and tools.

### Running the Graph Visualization System
```bash
# Start backend API server (development mode with auto-reload)
uv run worldreasoner --reload

# In another terminal, start frontend
cd frontend
npm install  # First time only
npm run dev

# Access at:
# - Frontend: http://localhost:3000
# - API docs: http://localhost:8018/docs
```

See `GRAPH_VISUALIZATION.md` for detailed documentation.

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
    - Flow: Resolved Questions → Evidence Articles → Target Event Identification → Causal Hypotheses → Event Graph Updates
   - Runs after questions resolve to create ground truth explanations
   - Uses async processing with per-question analysis for parallelism
   - Implementation: `src/pipelines/evidence/pipeline.py`

**Target Event Identification** (New Stage):
- Automatically creates or identifies target events for questions without them (e.g., Polymarket)
- Runs between evidence collection and causal reasoning
- Analyzes question + ground truth to extract event description
- Matches existing events or creates new ones
- See `docs/TARGET_EVENT_IDENTIFICATION.md` for details

### Unified CLI System

WorldReasoner provides a comprehensive command-line interface via the `wr` command:

**Architecture** (`src/cli/`):
- `main.py` - Entry point using Typer framework
- `commands/` - Command groups:
  - `db.py` - Database inspection and management
  - `question.py` - Question collection workflows
  - `evidence.py` - Evidence pipeline execution
  - `forecast.py` - Forecasting operations
- `core/` - Shared utilities:
  - `pipeline_runner.py` - Pipeline execution management
  - `question_manager.py` - Question CRUD operations
  - `question_selector.py` - Interactive question selection
- `ui/` - Rich terminal UI components (tables, progress bars)

**Entry Points** (defined in `pyproject.toml`):
- `wr` - Unified CLI
- `worldreasoner` - Backend API server
- `worldreasoner-mcp-forecast` - MCP forecasting server

**Usage Pattern:**
```python
# CLI uses rich terminal output with tables and progress bars
from src.cli.ui.tables import create_questions_table
from src.cli.core.pipeline_runner import PipelineRunner

runner = PipelineRunner(db_path, config)
await runner.run_evidence_pipeline(question_id)
```

### HindsightAgent Multi-Agent System

**NEW** - `src/agents/hindsight_agent.py`

Sophisticated multi-agent reasoning system for deep causal analysis:

**Agent Hierarchy:**
1. **Manager Agent** - Orchestrates overall causal analysis workflow
2. **Evidence Collector Agent** - Specialized in gathering relevant articles
3. **Causal Analyzer Agent** - Builds deep causal graphs (3+ levels)

**Key Features:**
- **Provenance Tracking**: All analysis tagged with `question_id` for traceability
- **Self-Evaluation**: Agents evaluate their own outputs and iterate
- **Adaptive Depth**: Builds multi-level causal chains vs rigid 1-level analysis
- **Coverage Analysis**: Uses `ArticleInspectorTool` to analyze timeline coverage

**Implementation:**
- **Adaptive Pipeline** (`src/pipelines/evidence/adaptive_pipeline.py`) - Uses HindsightAgent
- **Base Pipeline** (`src/pipelines/evidence/pipeline.py`) - Uses single agent
- **Prompts** (`src/pipelines/prompts/hindsight_causal_analysis.py`) - Agent instructions

**Usage:**
```python
from src.agents.hindsight_agent import HindsightAgent

agent = HindsightAgent(
    model_id="gpt-4o",
    question_id="q123",  # For provenance tracking
    db=database
)

result = agent.analyze_causal_chain(
    question=question,
    ground_truth=ground_truth,
    evidence_articles=articles
)
```

**Comparison:**
- **Base Pipeline**: Faster, single-agent, good for straightforward questions
- **Adaptive Pipeline**: Deeper analysis, multi-agent, better for complex causality

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

**Question Collection Orchestrator** (`src/pipelines/question/orchestrator.py`):
- Refactored from 660 lines to 366 lines (44.5% reduction)
- Uses service-based architecture with dependency injection
- **Services** (flat hierarchy in `src/pipelines/question/`):
  - `SourceCoordinator` - Parallel/sequential source execution
  - `GapAnalyzer` - Identifies gaps in type/category distribution
  - `GapFiller` - Targeted collection to fill specific gaps
  - `QuotaManager` - Calculates source quotas and budgets
- Maintains same public API - no breaking changes
- See `docs/ORCHESTRATOR_REFACTORING.md` for design details

**Collection Goal Pattern** (`src/config/collection_goal.py`):
- Goal-oriented question collection with targets
- Type and category distribution requirements
- Quality thresholds and source minimums
- Gap analysis and targeted filling

**Quality Scoring Pattern** (`src/pipelines/stages/question_quality.py`):
- Automated LLM-based quality assessment
- Multi-dimensional scoring (clarity, measurability, relevance, difficulty)
- Integration into collection pipeline
- Ranking and filtering by quality scores

**Modular Source Pattern** (`src/pipelines/question/sources/polymarket_client.py`):
- Separation of API client and parsing logic
- `PolymarketClient` - HTTP wrapper
- `MarketParser` - Data parsing and validation
- `PolymarketRunner` - Orchestration using client + parser
- Enables easier testing and maintenance

### Directory Structure

```
worldreasoner/
├── backend/            # FastAPI backend & graph services
│   ├── api/
│   │   ├── routes/
│   │   │   ├── graph.py      # Graph endpoints
│   │   │   ├── events.py     # Event endpoints
│   │   │   ├── questions.py  # Question endpoints
│   │   │   ├── database.py   # NEW: Database management
│   │   │   ├── pipelines.py  # NEW: Pipeline execution
│   │   │   ├── forecast_graphs.py  # NEW: Forecast graphs
│   │   │   └── websocket.py  # WebSocket support
│   │   └── app.py     # FastAPI app factory
│   ├── services/
│   │   └── graph/     # Graph abstraction layer
│   └── server.py      # CLI entry point
├── frontend/          # React visualization frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── GraphVisualization.jsx  # Event graph visualization
│   │   │   ├── EventDetails.jsx        # Event detail view
│   │   │   ├── Timeline.jsx            # Timeline view
│   │   │   ├── QuestionList.jsx        # NEW: Question browsing/filtering
│   │   │   ├── QuestionEditModal.jsx   # NEW: Edit question details
│   │   │   ├── QuestionPreviewList.jsx # NEW: Preview during collection
│   │   │   ├── QuestionCollectionPage.jsx # NEW: Collection interface
│   │   │   ├── CollectionConfigPanel.jsx  # NEW: Configure goals
│   │   │   ├── ManualQuestionForm.jsx     # NEW: Manual entry
│   │   │   ├── PipelinePage.jsx        # NEW: Pipeline management
│   │   │   ├── PipelineControl.jsx     # NEW: Pipeline execution
│   │   │   ├── ForecastPage.jsx        # NEW: Forecasting interface
│   │   │   ├── ForecastGraph.jsx       # NEW: Forecast graph viz
│   │   │   ├── TimeSeriesChart.jsx     # NEW: Price history charts
│   │   │   ├── EventGraphsPage.jsx     # NEW: Event graph explorer
│   │   │   ├── ArticleCoverage.jsx     # NEW: Coverage analysis
│   │   │   ├── DatabaseDropdown.jsx    # NEW: Database switcher
│   │   │   └── DatabaseSelector.jsx    # NEW: Database selection
│   │   ├── api/
│   │   │   └── graphApi.js            # API client
│   │   └── App.jsx                     # Main application
│   └── package.json
├── src/               # Core WorldReasoner
│   ├── cli/          # NEW: Unified CLI system
│   │   ├── commands/  # Command groups
│   │   │   ├── db.py       # Database management
│   │   │   ├── question.py # Question collection
│   │   │   ├── evidence.py # Evidence pipeline
│   │   │   └── forecast.py # Forecasting commands
│   │   ├── core/      # Shared CLI utilities
│   │   │   ├── common.py
│   │   │   ├── pipeline_runner.py
│   │   │   ├── question_manager.py
│   │   │   └── question_selector.py
│   │   ├── ui/        # UI components (tables)
│   │   └── main.py    # CLI entry point
│   ├── config/        # Configuration (app, database, pipeline)
│   │   ├── app.py    # App and LLM config
│   │   ├── database.py  # SQLite config
│   │   ├── pipeline.py  # Pipeline configs
│   │   └── collection_goal.py  # NEW: Collection targets
│   ├── core/         # Shared infrastructure
│   │   ├── database.py  # Generic database layer (ONLY db interface)
│   │   ├── temporal_gateway.py  # Temporal filtering
│   │   ├── collectors.py  # Result collectors
│   │   └── hybrid_search.py  # Search indexing
│   ├── domain/       # Business logic & models
│   │   ├── models/   # Data models
│   │   │   ├── article.py
│   │   │   ├── event.py
│   │   │   ├── question.py
│   │   │   ├── question_helpers.py
│   │   │   ├── forecast.py
│   │   │   ├── forecast_graph.py  # NEW: Forecast-specific graphs
│   │   │   ├── domain.py
│   │   │   └── causal_hypothesis.py
│   │   └── evaluation/  # Evaluation metrics
│   ├── pipelines/    # Data processing pipelines
│   │   ├── base.py  # PipelineStage, Pipeline base classes
│   │   ├── question/  # Question generation pipeline
│   │   │   ├── orchestrator.py       # Slim coordinator (366 lines)
│   │   │   ├── source_coordinator.py # Parallel/sequential execution
│   │   │   ├── gap_analyzer.py       # Gap identification
│   │   │   ├── gap_filler.py         # Targeted gap filling
│   │   │   ├── quota_manager.py      # Source quota management
│   │   │   ├── progress.py           # Progress tracking
│   │   │   └── sources/              # Question sources
│   │   ├── evidence/  # Evidence & causal reasoning pipeline
│   │   │   ├── pipeline.py  # Base evidence pipeline
│   │   │   └── adaptive_pipeline.py  # NEW: Multi-agent adaptive pipeline
│   │   ├── stages/    # Reusable pipeline stages
│   │   │   ├── article_collection.py
│   │   │   ├── event_identification.py
│   │   │   ├── evidence_collection.py
│   │   │   ├── causal_reasoning.py
│   │   │   ├── question_generation.py
│   │   │   ├── question_quality.py  # NEW: Quality scoring
│   │   │   ├── target_event_identification.py  # NEW
│   │   │   ├── graph_building.py
│   │   │   └── collectors.py
│   │   └── prompts/   # Agent prompt templates
│   │       ├── base.py
│   │       ├── article_collection.py
│   │       ├── event_identification.py
│   │       ├── question_generation.py
│   │       ├── question_categorization.py  # NEW
│   │       ├── question_quality.py  # NEW
│   │       ├── target_event_identification.py  # NEW
│   │       ├── hindsight_analysis.py
│   │       ├── hindsight_causal_analysis.py  # NEW
│   │       └── forecast.py  # NEW
│   ├── tools/         # NEW: Agentic tools (extracted from pipelines/stages/tools)
│   │   ├── base.py    # Base tool classes
│   │   ├── article_collector.py
│   │   ├── article_retrieval.py
│   │   ├── article_inspector.py  # NEW: Timeline analysis
│   │   ├── batch_article_collector.py
│   │   ├── batch_article_retrieval.py
│   │   ├── batch_event_identifier.py
│   │   ├── batch_question_generator.py
│   │   ├── event_identifier.py
│   │   ├── event_details.py
│   │   ├── question_generator.py
│   │   ├── question_quality_scorer.py  # NEW
│   │   ├── question_articles.py  # NEW: Question-specific articles
│   │   ├── causal_reasoner.py
│   │   ├── forecast_causal_reasoner.py  # NEW
│   │   ├── forecast_event_identifier.py  # NEW
│   │   ├── forecast_graph_inspector.py  # NEW
│   │   ├── graph_inspector.py  # NEW
│   │   ├── rss_fetch.py
│   │   ├── web_fetch.py
│   │   └── web_search.py
│   ├── agents/        # AI agents (smolagents)
│   │   ├── base.py       # BaseAgent
│   │   ├── web_agent.py  # WebAgent with web_search
│   │   ├── factory.py    # AgentFactory pattern
│   │   ├── forecast_agent.py  # ForecastAgent for predictions
│   │   └── hindsight_agent.py  # NEW: Multi-agent hindsight reasoning
│   ├── utils/         # Utilities
│   │   ├── logging.py
│   │   ├── usage_tracking.py
│   │   ├── search_indexing.py
│   │   ├── similarity.py
│   │   ├── enums.py     # NEW: Enum parsing
│   │   ├── date_utils.py  # NEW: Date parsing
│   │   ├── id_generator.py  # NEW: ID generation
│   │   ├── article_analysis.py  # NEW
│   │   ├── graph_analysis.py  # NEW
│   │   ├── graph_visualization.py  # NEW
│   │   ├── llm_utils.py  # NEW
│   │   ├── polymarket.py  # NEW
│   │   ├── question_filters.py  # NEW
│   │   └── question_loader.py  # NEW
│   ├── llm.py         # LLM client
│   └── mcp_forecasting_server.py  # MCP server implementation

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
- **ForecastEvent** (`forecast_graph.py`): Events identified during forecasting (separate from main graph)
- **ForecastHypothesis** (`forecast_graph.py`): Causal hypotheses from forecasting process
- **CausalHypothesis** (`causal_hypothesis.py`): Causal links with confidence scores (ground truth)

**Forecast Graph Models** - NEW in `forecast_graph.py`:
```python
@register_model('forecast_events')
class ForecastEvent(BaseModel):
    """Events identified during forecasting (not ground truth)"""
    forecast_id: Optional[str]  # Link to forecast
    session_id: str             # Track forecasting session
    # ... event details

@register_model('forecast_hypotheses')
class ForecastHypothesis(BaseModel):
    """Causal hypotheses from forecasting"""
    forecast_id: Optional[str]
    session_id: str
    source_event_id: str
    target_event_id: str
    reasoning: str
    confidence: float
```

**Purpose:** Separate forecasting reasoning from ground truth causal graphs. This prevents contamination of the benchmark data with LLM-generated hypotheses.

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

- **Default**: `config/config.example.yaml` (committed template)
- **Local overrides**: `config/config.yaml` (gitignored, create from example)
- **Article sources**: `config/sources.yaml` (RSS and web scraping configs)
- **Collection goals**: `config/collection_goal.yaml` (active), `config/collection_goal.example.yaml` (template)
- **Agent sources**: `config/agent_sources.yaml` (agent-specific article sources)
- **Test sources**: `config/test_sources.yaml` (testing configurations)
- **LLM knowledge cutoffs**: `config/llm_cutoff_dates.json` (comprehensive database of model cutoff dates)
- **Access**: Use `src.config.get_config()` (singleton pattern)
- **LLM**: Uses `litellm` wrapper supporting Gemini, OpenAI, etc.

**LLM Knowledge Cutoff Dates** - NEW:
The system tracks knowledge cutoff dates for 50+ LLM models to ensure temporal validity:
- OpenAI models (GPT-3, GPT-4, GPT-4o, o1, o3)
- Google models (Gemini 1.0, 1.5, 2.0, 2.5, 3)
- Anthropic models (Claude 2, 3, 3.5, 3.7, 4, 4.5)
- Meta models (Llama 2, 3, 3.1, 3.2, 3.3, 4)
- Others (Qwen, DeepSeek, Phi, Mistral, Grok)

**Fetching script:** `scripts/fetch_knowledge_cutoff_date.py`

**Server Ports**:
- **Backend API** (FastAPI): `server.host:server.port` (default: localhost:8018)
- **MCP Server** (forecasting agents): `server.mcp_host:server.mcp_port` (default: localhost:8110)

The system runs two servers:
1. FastAPI backend for visualization and API endpoints (port 8018)
2. MCP forecasting server for agent tools and temporal access (port 8110)

Agents connect to the MCP server using `config.server.mcp_host` and `config.server.mcp_port`.

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

### Using New Analysis Tools

```python
# Article timeline coverage analysis
from src.tools.article_inspector import ArticleInspectorTool

inspector = ArticleInspectorTool(db_path="worldreasoner.db")
coverage = inspector.forward(
    question_id="q123",
    start_date="2024-01-01",
    end_date="2024-12-31"
)
# Returns: timeline coverage gaps, article distribution

# Graph analysis
from src.tools.graph_inspector import GraphInspectorTool

graph_tool = GraphInspectorTool(db_path="worldreasoner.db")
analysis = graph_tool.forward(event_id="evt_123")
# Returns: depth, paths, connected events

# Question quality scoring
from src.tools.question_quality_scorer import QuestionQualityScorerTool

scorer = QuestionQualityScorerTool(model_id="gpt-4o")
score = scorer.forward(question_text="Will X happen by Y?")
# Returns: multi-dimensional quality scores
```

### Utility Modules

```python
# Unified ID generation
from src.utils.id_generator import generate_article_id, generate_event_id
article_id = generate_article_id(url)  # art_<hash>
event_id = generate_event_id()         # evt_<uuid>

# Date parsing with timezone handling
from src.utils.date_utils import parse_iso_datetime
date = parse_iso_datetime("2024-12-21T10:00:00Z")  # Always UTC

# Enum parsing with safe fallbacks
from src.utils.enums import parse_question_type
q_type = parse_question_type("binary")  # QuestionType.BINARY

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
