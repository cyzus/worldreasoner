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

## Architecture

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
cp config/config.example.yaml config/config.yaml
# Edit config/config.yaml with your LLM API keys and settings
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
