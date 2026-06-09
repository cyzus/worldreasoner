# WorldReasoner: Temporal Forecasting Benchmark for LLMs

WorldReasoner evaluates how AI language models perform on real-world prediction tasks when given structured, temporally-filtered evidence. The system addresses core limitations of LLMs as forecasters — training data cutoffs and lack of causal structure — by providing a temporal gateway that simulates a controlled "past" for each question, paired with an evidence pipeline that collects, structures, and quality-scores articles and causal event graphs. Benchmarking is conducted across six experimental conditions ranging from pure knowledge recall to full evidence-augmented reasoning, evaluated against a 120-question curated dataset sourced from Polymarket.

---

## Documentation

| Section | File | Description |
|---------|------|-------------|
| **1. Introduction** | [01_introduction.md](01_introduction.md) | Background, problem statement, system overview |
| **2. Data Collection** | [02_data_collection.md](02_data_collection.md) | Polymarket API, dataset composition |
| **3. Evidence Pipeline** | [03_evidence_pipeline.md](03_evidence_pipeline.md) | Article collection, event graphs, quality scoring |
| **4. Forecasting** | [04_forecasting.md](04_forecasting.md) | MCP server, temporal gateway, context management |
| **5. Evaluation** | [05_evaluation.md](05_evaluation.md) | Metrics, conditions, contamination filtering, benchmark guide |
| **6. Analysis Tools** | [06_analysis_tools.md](06_analysis_tools.md) | Graph inspector, article inspector |
| **Metrics** | [metrics.md](metrics.md) | Accuracy, Brier score, log score definitions |
| **Appendix A: CLI** | [appendix/A_cli_reference.md](appendix/A_cli_reference.md) | Complete `wr` command reference |

---

## Quick Start

```bash
# Install
uv sync && uv run playwright install
cp config/config.example.yaml config/config.yaml  # add API keys

# Collect and process questions
uv run wr question collect
uv run wr evidence run -q <question_id>
uv run wr graph build -q <question_id>

# Run a benchmark
uv run wr benchmark run -c vanilla_llm -n 10           # quick test
uv run wr benchmark run -c worldreasoner --question-ids include_ids.txt

# Score results (contamination-filtered, matches paper)
uv run wr benchmark evaluate \
  --db combined.db \
  --include-ids include_ids.txt \
  --filter-knowledge-leakage

# Research dashboard
uv run worldreasoner --reload &
cd frontend && npm run dev   # → http://localhost:5173
```

For the full CLI reference: `wr --help` or [Appendix A](appendix/A_cli_reference.md).

For paper figure reproduction: [scripts/README.md](../scripts/README.md).
