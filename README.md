# WorldReasoner

A scalable LLM forecast benchmark system implemented as a Model Context Protocol (MCP) server that evaluates LLM forecasting capabilities using temporal data access control and both real and synthetic datasets.

## Overview

WorldReasoner enables rigorous evaluation of Large Language Models' ability to predict future events by:

- **Temporal Access Control**: Simulates historical contexts by restricting information access to specific time periods
- **Real-World Benchmarks**: Uses actual news and events with verifiable outcomes
- **Synthetic Datasets**: Generates controlled scenarios to isolate forecasting abilities
- **Comprehensive Evaluation**: Measures accuracy, calibration, reasoning quality, and information efficiency

## Research Questions

1. **Can AI provide reasonable predictions of future events using current information?**
2. **Can AI reason about current events and identify causal factors?**
3. **Does AI exhibit similar forecasting capabilities on synthetic vs real-world data?**
   - Which properties of synthetic data best preserve forecasting difficulty?
   - Do different model architectures show different synthetic-to-real transfer?
   - Can we identify "synthetic data signatures" that fail to transfer?
   - What's the minimum synthetic data complexity needed to predict real-world performance?

## Example Use Case

Consider an LLM with knowledge cutoff in April 2024:

**Question**: "Who will win the US presidential election in November 2024?"

**Setup**: 
- The system simulates the environment of a designated date
- The LLM can only access information from on or before this date
- The LLM can search news, analyze polling data, and gather context
- After the actual outcome is known, we evaluate the LLM's prediction

**Value**: This tests genuine forecasting ability, not just memorized facts.

## Key Features

### 🤖 Agentic Pipeline System
- **LLM-Powered Agents**: Uses smolagents framework for intelligent data processing
- **Web Intelligence**: Combines web_search + advanced scraping (crawl4ai) for JavaScript-heavy sites
- **Type-Safe**: Generic types and Pydantic models ensure data integrity
- **Modular Design**: AgentFactory and ResultCollector patterns for maintainability

### 🕐 Temporal Gateway
- Enforces strict temporal boundaries on information access
- Prevents data leakage from future information
- Enables realistic forecasting scenarios

### 🔍 Advanced Search Tools
- Semantic search using embeddings
- Temporal weighting for trend detection
- Domain-specific filtering
- Causal relationship tracking

### 📊 Multi-Type Benchmarks
- **Boolean**: Yes/No predictions
- **Multiple Choice**: Select from options
- **Quantity Estimation**: Numerical predictions with ranges
- **Timeframe**: When will X occur?

### 🎯 Comprehensive Evaluation
- **Accuracy**: Correctness of predictions
- **Calibration**: Confidence alignment with accuracy
- **Resolution**: Ability to distinguish outcomes
- **Reasoning Quality**: Causal chain completeness
- **Information Efficiency**: Performance per article accessed

### 🌍 Multi-Domain Coverage
- Finance (stock markets, economics, corporate)
- Politics (elections, policy, international relations)
- Technology (product launches, adoption, breakthroughs)
- Healthcare (drug approvals, public health, clinical trials)
- Climate (emissions, weather, policy)

### 🧪 Synthetic Data Generation
- Controlled causal complexity
- Domain-specific scenarios
- Known ground truth by construction
- Adjustable difficulty parameters

## Architecture

### Design Patterns

WorldReasoner uses modern, maintainable design patterns:

- **AgentFactory Pattern**: Centralized agent creation with dependency injection
- **ResultCollector Pattern**: Stateless tools with clean separation of concerns
- **Pipeline Stage Pattern**: Composable, type-safe processing units
- **Token-Optimized Tools**: Agents receive summaries, tools process full content internally

### System Architecture

```
┌─────────────────────────────────────────────┐
│         LLM Client Applications             │
└───────────────┬─────────────────────────────┘
                │ MCP Protocol
┌───────────────┴─────────────────────────────┐
│           MCP Server Layer                  │
│  ┌────────────────────────────────────────┐ │
│  │     Temporal Gateway                   │ │
│  │  (Access Control & Validation)         │ │
│  └────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────┐ │
│  │        Resource Handlers               │ │
│  │  • Search  • Fetch  • Forecast         │ │
│  └────────────────────────────────────────┘ │
└───────────────┬─────────────────────────────┘
                │
┌───────────────┴─────────────────────────────┐
│        Dual Pipeline System                 │
│  ┌────────────────────────────────────────┐ │
│  │  Question Pipeline (Forward)           │ │
│  │  Sources → Events → Questions          │ │
│  └────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────┐ │
│  │  Evidence Pipeline (Backward)          │ │
│  │  Questions → Reasoning → Evidence      │ │
│  └────────────────────────────────────────┘ │
└───────────────┬─────────────────────────────┘
                │
┌───────────────┴─────────────────────────────┐
│           Data Layer                        │
│  ┌──────────────┐  ┌──────────────┐         │
│  │  PostgreSQL  │  │   Synthetic  │         │
│  │  (Articles,  │  │     Data     │         │
│  │   Events,    │  │   Generator  │         │
│  │   Questions, │  │              │         │
│  │   Graphs)    │  │              │         │
│  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
- Python 3.13+
- SQLite (included) or PostgreSQL 14+ (optional)
- API keys for LLM service (Gemini, OpenAI, etc.)
- Playwright for web scraping (auto-installed)

### Installation

```bash
# Clone the repository
git clone https://github.com/cyzus/worldreasoner.git
cd worldreasoner

# Create virtual environment
uv venv

# Activate the virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Install dependencies
uv sync

# Install Playwright browsers (for web scraping)
uv run playwright install

# Set up configuration
cp config/default.yaml config/local.yaml
# Edit config/local.yaml with your LLM API keys and settings
```

### Running the Pipeline

```bash
# Run the question generation pipeline
uv run python tests/integration/test_agentic_pipeline.py

# Run unit tests
uv run pytest tests/unit/ -v

# Run specific test file
uv run pytest tests/unit/test_agent_factory.py -v
```

### Running the MCP Server (Coming Soon)

```bash
# Start the server (planned)
python -m src.mcp_server --config=config/local.yaml

# In another terminal, run a test evaluation (planned)
python -m src.cli.evaluate --benchmark-id=standard_v1
```

### Using with Claude Desktop

Add to your Claude Desktop MCP configuration:

```json
{
  "mcpServers": {
    "worldreasoner": {
      "command": "python",
      "args": ["-m", "src.cli.server", "--config=config/local.yaml"],
      "cwd": "/path/to/worldreasoner"
    }
  }
}
```

## Dual Pipeline System

WorldReasoner uses **two complementary pipelines**:

### 1. Question Pipeline (Forward-Looking)
Creates forecast questions from current events:
- **Input**: News sources (RSS, APIs)
- **Process**: Articles → Events → Questions
- **Output**: Benchmark questions about future outcomes
- **Timing**: Runs monthly to generate fresh questions

### 2. Evidence Pipeline (Backward-Looking)
Builds causal explanations using hindsight:
- **Input**: Resolved questions with ground truth
- **Process**: Hindsight reasoning → Evidence collection → Causal graph
- **Output**: Validated causal explanations
- **Timing**: Immediately after questions are generated (and the ground truth is known)

This dual approach ensures:
- ✅ Ground truth explanations built WITH hindsight (accurate causality)
- ✅ LLM forecasts evaluated against validated causal reasoning

## Technical Highlights

### Code Architecture
- **AgentFactory Pattern**: Centralized agent creation reduces boilerplate by 40%
- **ResultCollector Pattern**: Stateless, reusable tools with dependency injection
- **Type-Safe Pipelines**: Generic types ensure compile-time correctness
- **Async-First**: Non-blocking I/O for efficient web scraping and API calls

### Data Processing
- **Token Optimization**: Tools process full content internally, return summaries (98% token savings)
- **Smart Deduplication**: Content hashing prevents duplicate article processing
- **Timezone-Aware**: All timestamps use UTC for consistent temporal logic
- **Schema Validation**: Pydantic models with automatic database schema generation

### Testing & Quality
- **44+ Unit Tests**: Comprehensive coverage of core functionality
- **Integration Tests**: End-to-end pipeline validation
- **Type Checking**: Full mypy support for type safety
- **Code Documentation**: Extensive docstrings and inline comments

### Technologies
- **smolagents**: LLM agent framework with tool calling
- **crawl4ai**: Advanced web scraping with JavaScript support
- **litellm**: Multi-provider LLM client (Gemini, OpenAI, etc.)
- **Pydantic**: Data validation and settings management
- **pytest**: Testing framework with async support

## Current Status

### ✅ Completed
- **Data Models**: Article, Event, Question, Forecast with full causal graph support
- **Event Architecture**: Events as causal nodes, Articles as documentation
- **Pipeline Framework**: Abstract base classes with type safety and observability
- **Dual Pipeline System**: Question Pipeline (3 stages) + Evidence Pipeline (3 stages)
- **Pipeline Stages**: 6 configured stages with clear specifications
- **Configuration**: QuestionConfig and DatabaseConfig with full settings
- **Agentic Pipeline**: Implemented using smolagents framework with LLM-powered tools
  - Article Collection: Web search + intelligent scraping
  - Event Identification: LLM-based event extraction and classification
  - Question Generation: Automated forecast question creation
- **Advanced Web Scraping**: crawl4ai integration for JavaScript-heavy sites
- **Code Architecture Improvements**:
  - **AgentFactory Pattern**: Centralized agent creation (40% boilerplate reduction)
  - **ResultCollector Pattern**: Stateless tools with clean separation of concerns
  - Token-optimized tools (98% reduction via internal processing)
- **Documentation**: 10+ comprehensive docs covering architecture, models, pipelines
- **Testing**: 44+ unit tests (all passing) including agent factory and collector tests

### 🚧 In Progress
- **Stage Implementation**: Refining and optimizing pipeline stages
  - ✅ Question Pipeline: Article collection, Event identification, Question generation (functional)
  - 🔄 Evidence Pipeline: Causal reasoning, Evidence collection, Graph building (planned)
- **Database Layer**: SQLite operational, PostgreSQL integration planned
- **Performance Optimization**: Caching, batch processing, async parallelization

### 📋 Planned
- **MCP Server**: Expose pipelines via Model Context Protocol
- **Temporal Gateway**: Control information access by cutoff date
- **Search Tools**: Semantic and temporal search
- **Evaluation Framework**: Scoring and metrics
- **Synthetic Data**: Generate controlled scenarios
- **Web Interface**: Visualize causal graphs and questions

See [ROADMAP.md](docs/ROADMAP.md) for detailed timeline.

## Example Interaction

```python
# Search for relevant articles
results = await mcp.call("search", {
    "query": "US election polling swing states",
    "current_date": "2024-09-30T00:00:00Z",
    "domain": "politics",
    "max_results": 20
})

# Fetch full article content
article = await mcp.call("fetch", {
    "article_id": "art_pol_20240928_001",
    "current_date": "2024-09-30T00:00:00Z"
})

# Submit a forecast
forecast = await mcp.call("submit_forecast", {
    "question_id": "q_pol_2024_001",
    "prediction": True,
    "confidence": 0.65,
    "reasoning": "Based on polling averages in swing states..."
})
```

## Data Pipeline

### Real Data
```
News Sources → Scraper → Processor → Outcome Identifier →
Causal Analyzer → Question Generator → Benchmark Dataset
```

### Synthetic Data
```
Outcome Generator → Causal Reasoner → Article Generator →
Consistency Checker → Domain Diversifier → Benchmark Dataset
```

## Research

If you use WorldReasoner in your research, please cite:

```bibtex
@software{worldreasoner2025,
  title = {WorldReasoner: A Temporal Forecast Benchmark for Large Language Models},
  author = {[Yizhou Chi]},
  year = {2025},
  url = {https://github.com/cyzus/worldreasoner}
}
```
