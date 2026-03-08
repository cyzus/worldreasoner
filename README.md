# WorldReasoner

A scalable LLM forecast benchmark system evaluating forecasting capabilities using temporal data access control and real/synthetic datasets.

## Overview

WorldReasoner tests if AI can predict future events by strictly controlling information access (simulated historical context).

-   **Temporal Access Control**: LLMs only see data available before a specific date.
-   **Dual Pipelines**: Generates questions from news (forward) and builds causal explanations (backward).
-   **Comprehensive Evaluation**: Measures accuracy, calibration, and reasoning quality.

## Quick Start

### Prerequisites
-   Python 3.13+
-   `uv` for dependency management

### Installation

```bash
git clone https://github.com/cyzus/worldreasoner.git
cd worldreasoner

# Install dependencies and browsers
uv sync
uv run playwright install

# Configuration
cp config/config.example.yaml config/config.yaml
# Edit config/config.yaml with your specific API keys
```

### Running the System

**1. Unified CLI**
```bash
# View all commands
uv run wr --help

# 1. Run the evidence pipeline for a question (generates NL explanation)
uv run wr evidence run -q <id>

# 2. Build the causal graph from the explanation
uv run wr graph build -q <id>

# 3. Audit the graph for quality (chronology, orphan checks)
uv run wr graph audit -q <id>
```

**2. MCP Forecasting Server**
Provides temporal-aware tools to agents (e.g., in Claude Desktop).

```bash
# Run server (stdio mode)
uv run worldreasoner-mcp-forecast
```
See [docs/mcp-server.md](docs/mcp-server.md) for full documentation and Claude Desktop setup.

**3. Visualization Dashboard**
```bash
# Backend
uv run worldreasoner --reload

# Frontend
cd frontend && npm run dev
```

## Architecture

![System Architecture](docs/images/architecture_diagram.png)

### Core Components

1.  **Temporal Gateway**: The security layer that enforces time-travel rules. It filters every database access to ensure no future knowledge leaks into the forecasting process.
2.  **Question Pipeline**: Runs monthly. ingest news -> identify events -> generate forecast questions.
3.  **Evidence Pipeline**: Runs after resolution. collects ground truth -> builds causal graph -> validates reasoning.
4.  **Hindsight Agent**: A multi-agent system that iteratively builds deep causal explanations. See [AGENTS.md](AGENTS.md).

### Directory Structure
-   `src/agents`: AI agent implementations.
-   `src/pipelines`: Data processing pipelines (Question & Evidence).
-   `src/api/mcp_forecasting_server.py`: Model Context Protocol server.
-   `src/cli`: Command-line interface logic.


## Documentation

- [System Architecture](AGENTS.md): Detailed breakdown of the multi-agent system.
- [CLI Reference](docs/cli.md): Complete guide to `wr` command-line tools.
- [MCP Server Setup](docs/mcp-server.md): How to connect Claude Desktop to WorldReasoner.
- [Evaluation & Benchmarking](docs/benchmarking.md): How to run tests and score LLM performance.
- [Market Analysis](docs/market-turning-points.md): How the system detects shifts in Polymarket curves.
- [Temporal Context](docs/context-window-guide.md): How simulated past dates are calculated.

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
