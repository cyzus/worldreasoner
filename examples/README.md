# WorldReasoner Examples

Example scripts demonstrating WorldReasoner functionality.


## Pipeline Examples

### Goal-Oriented Question Collection (`run_goal_collection.py`)

Collect forecast questions from multiple sources (Polymarket, news) until distribution goals are met.

```bash
python examples/run_goal_collection.py --goal config/collection_goal.yaml --db worldreasoner.db
```

### Evidence Pipeline (`run_evidence_pipeline.py`)

Build causal explanations using hindsight.

```bash
python examples/run_evidence_pipeline.py
```

### Forecasting with MCP (`run_forecast_smolagents.py`)

Run forecasting agents using the MCP server with temporal constraints.

```bash
# First, start the MCP server (in another terminal)
python -m src.mcp_forecasting_server

# Then run the agent
python examples/run_forecast_smolagents.py
```

### Quick Start

```bash
# Collect questions from multiple sources (auto-indexes articles after completion)
python examples/run_goal_collection.py --goal config/collection_goal.yaml --db worldreasoner.db

# Build evidence graph (auto-indexes articles after completion)
python examples/run_evidence_pipeline.py

# Run forecasting
python -m src.mcp_forecasting_server  # In one terminal
python examples/run_forecast_smolagents.py  # In another terminal
```

**Note:** Both pipelines automatically index articles for hybrid search after completion. To skip this behavior, use `--skip-indexing`.

## Hybrid Search

WorldReasoner uses a hybrid search approach combining:

1. **FTS5 Keyword Search** - Fast BM25 ranking for exact term matching
2. **Semantic Embeddings** - Via LiteLLM (OpenAI, Cohere, etc.) for meaning-based search
3. **Temporal Filtering** - Respects knowledge cutoff dates for forecasting

### Building the Search Index

**Auto-indexing:** Both question and evidence pipelines automatically index new articles after completion. You can skip this with `--skip-indexing`.

**Manual indexing:** Use the build script for initial setup or when changing embedding models:

```bash
# Index all articles with default model (from config.yaml: gemini/gemini-embedding-001)
python scripts/build_search_index.py

# Override with a different model
python scripts/build_search_index.py --model text-embedding-3-large

# Use via litellm proxy
python scripts/build_search_index.py --model litellm_proxy/text-embedding-3-small

# Rebuild from scratch
python scripts/build_search_index.py --rebuild
```

**Configuration:**
- Default embedding model is set in `config/config.yaml` under `llm.embedding_model`
- You can override it with the `--model` flag
- API keys should be in your `.env` file (e.g., `GOOGLE_API_KEY` for Gemini, `OPENAI_API_KEY` for OpenAI)

### Testing Search

Test the hybrid search with various queries:

```bash
python scripts/test_hybrid_search.py
```

This will run test queries comparing:
- Hybrid search (FTS5 + embeddings)
- Keyword-only search (FTS5)
- Semantic-only search (embeddings)

## Evaluation & Benchmarking

WorldReasoner provides comprehensive evaluation tools for analyzing forecast performance.

### Scripts Overview

| Script | Purpose | Key Use Case |
|--------|---------|--------------|
| `run_forecast_smolagents.py` | Single forecast with evaluation | Test a forecast on one question |
| `run_benchmark_evaluation.py` | Bulk forecasting on all questions | Compare model performance |
| `visualize_benchmarks.py` | Generate charts from benchmarks | Visualize model comparisons |
| `run_temporal_forecast_analysis.py` | Temporal progression analysis | Understand context impact |
| `evaluate_forecasts.py` | Evaluate existing forecasts | Post-hoc analysis |

### Single Question Forecast

```bash
# Run forecast on a specific question
python examples/run_forecast_smolagents.py --question-id q_tech_20251117_003

# With specific model
python examples/run_forecast_smolagents.py \
  --question-id q_tech_20251117_003 \
  --model gpt-4

# Knowledge-only mode (no research)
python examples/run_forecast_smolagents.py \
  --question-id q_tech_20251117_003 \
  --knowledge-only
```

### Full Benchmark Suite

```bash
# Run benchmarks on all resolved questions
python examples/run_benchmark_evaluation.py

# Compare different models
python examples/run_benchmark_evaluation.py --model gpt-4
python examples/run_benchmark_evaluation.py --model claude-sonnet-4

# Test knowledge-only mode
python examples/run_benchmark_evaluation.py --model gpt-4 --knowledge-only

# Visualize results
python examples/visualize_benchmarks.py
```

### Temporal Analysis

Understand how forecast quality changes as more context becomes available:

```bash
# Analyze temporal progression
python examples/run_temporal_forecast_analysis.py \
  --question-id q_politics_20251115_004_8352cfe8 \
  --num-points 5
```

**Output**: Shows how accuracy, confidence, and Brier score evolve over time as more articles/events become available.

### Visualization

Generate publication-quality comparative charts:

```bash
# Install visualization dependencies
uv sync --group viz

# Generate all visualizations
python examples/visualize_benchmarks.py

# Show interactive plots
python examples/visualize_benchmarks.py --show
```

**Generates:**
- Accuracy comparison across models
- Brier score comparison
- Full vs Knowledge-Only mode comparison
- Performance timeline

See [benchmarking.md](../docs/benchmarking.md) for complete documentation.

### Available Embedding Models

All models via [LiteLLM](https://docs.litellm.ai/docs/embedding/supported_embedding):
