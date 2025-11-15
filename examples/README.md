# WorldReasoner Examples

Example scripts demonstrating WorldReasoner functionality.


## Pipeline Examples

### Question Pipeline (`run_question_pipeline.py`)

Generate forecast questions from news sources.

```bash
python examples/run_question_pipeline.py
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
# Generate questions (auto-indexes articles after completion)
python examples/run_question_pipeline.py

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

### Available Embedding Models

All models via [LiteLLM](https://docs.litellm.ai/docs/embedding/supported_embedding):
