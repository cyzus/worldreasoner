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
- The system simulates the environment of September 30, 2024
- The LLM can only access information from on or before this date
- The LLM can search news, analyze polling data, and gather context
- After the actual outcome is known, we evaluate the LLM's prediction

**Value**: This tests genuine forecasting ability, not just memorized facts.

## Key Features

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

```
┌─────────────────────────────────────────────┐
│         LLM Client Applications             │
└───────────────┬─────────────────────────────┘
                │ MCP Protocol
┌───────────────┴─────────────────────────────┐
│           MCP Server Layer                  │
│  ┌────────────────────────────────────┐     │
│  │     Temporal Gateway               │     │
│  │  (Access Control & Validation)     │     │
│  └────────────────────────────────────┘     │
│  ┌────────────────────────────────────┐     │
│  │        Resource Handlers           │     │
│  │  • Search  • Fetch  • Forecast     │     │
│  └────────────────────────────────────┘     │
└───────────────┬─────────────────────────────┘
                │
┌───────────────┴─────────────────────────────┐
│           Data Layer                        │
│  ┌──────────────┐  ┌──────────────┐         │
│  │  Real Data   │  │  Synthetic   │         │
│  │   Store      │  │  Data Store  │         │
│  └──────────────┘  └──────────────┘         │
│  ┌────────────────────────────────────┐     │
│  │   Vector Index & Search Engine     │     │
│  └────────────────────────────────────┘     │
└───────────────┬─────────────────────────────┘
                │
┌───────────────┴─────────────────────────────┐
│      Evaluation & Pipeline Layer            │
│  • Data Generation  • Metrics  • Reports    │
└─────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Redis (for caching)
- API keys for embedding service (OpenAI/Cohere)

### Installation

```bash
# Clone the repository
git clone https://github.com/cyzus/worldreasoner.git
cd worldreasoner

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements/base.txt

# Set up configuration
cp config/default.yaml config/local.yaml
# Edit config/local.yaml with your settings

# Initialize database
python scripts/setup_db.py

# Load sample data
python scripts/seed_data.py
```

### Running the MCP Server

```bash
# Start the server
python -m src.cli.server --config=config/local.yaml

# In another terminal, run a test evaluation
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

## Documentation

- **[Architecture](docs/ARCHITECTURE.md)**: System design and components
- **[Code Structure](docs/CODE_STRUCTURE.md)**: Project organization and module details
- **[MCP API](docs/MCP_API.md)**: API reference and examples
- **[Data Schema](docs/DATA_SCHEMA.md)**: Database and data model specifications
- **[Evaluation](docs/EVALUATION.md)**: Metrics and evaluation framework
- **[Benchmark Tasks](docs/BENCHMARK_TASKS.md)**: Task types and examples
- **[Roadmap](docs/ROADMAP.md)**: Development timeline and milestones

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

## Contributing

We welcome contributions! Areas of interest:

- **Data Sources**: Add new news scrapers or data feeds
- **Domains**: Expand to new forecasting domains
- **Metrics**: Develop new evaluation metrics
- **Benchmarks**: Create domain-specific benchmark suites
- **Synthetic Generation**: Improve synthetic data realism

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Research

If you use WorldReasoner in your research, please cite:

```bibtex
@software{worldreasoner2024,
  title = {WorldReasoner: A Temporal Forecast Benchmark for Large Language Models},
  author = {[Authors]},
  year = {2024},
  url = {https://github.com/cyzus/worldreasoner}
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Model Context Protocol (MCP) by Anthropic
- News data providers and APIs
- Open source LLM community

## Contact

- **Issues**: [GitHub Issues](https://github.com/cyzus/worldreasoner/issues)
- **Discussions**: [GitHub Discussions](https://github.com/cyzus/worldreasoner/discussions)
- **Email**: [contact@worldreasoner.ai]

---

**Status**: 🔄 Active Development | **Version**: 0.1.0 | **Last Updated**: October 2024
