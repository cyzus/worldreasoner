# WorldReasoner: AI-Powered Forecasting with Temporal Evidence Control

## Abstract

WorldReasoner is a forecasting research platform that evaluates how AI language models perform on real-world prediction tasks when given structured access to temporally-filtered evidence. The system addresses core limitations of LLMs as forecasters — including training data cutoffs and the absence of causal structure — by providing a temporal gateway that simulates a controlled "past" for each question, paired with an evidence pipeline that collects, structures, and quality-scores articles and causal event graphs. Benchmarking is conducted across six experimental conditions ranging from pure knowledge recall to full evidence-augmented reasoning, measured against a 300-question dataset sourced from Polymarket and news pipelines. The platform is designed as a rigorous ablation testbed suitable for comparing frontier models and forecasting architectures.

---

## Documentation

| Section | File | Description |
|---------|------|-------------|
| **1. Introduction** | [01_introduction.md](01_introduction.md) | Background, problem statement, system overview, key contributions |
| **2. Data Collection** | [02_data_collection.md](02_data_collection.md) | Polymarket API, codebase integration, dataset composition |
| **3. Evidence Pipeline** | [03_evidence_pipeline.md](03_evidence_pipeline.md) | Article collection, event graphs, market price analysis |
| **4. Forecasting** | [04_forecasting.md](04_forecasting.md) | MCP server, temporal gateway, context window management |
| **5. Evaluation** | [05_evaluation.md](05_evaluation.md) | Metrics, experimental conditions, benchmarking guide |
| **6. Analysis Tools** | [06_analysis_tools.md](06_analysis_tools.md) | Graph inspector, article inspector, quality scoring |
| **Appendix A: CLI Reference** | [appendix/A_cli_reference.md](appendix/A_cli_reference.md) | Complete `wr` command reference |

---

## Quick Start

```bash
# Install dependencies
uv pip install -e .

# Collect questions from Polymarket
wr question goal

# Run evidence pipeline
wr evidence run --sample 20

# Build causal graphs
wr graph build --limit 20

# Auto-review events
wr evidence auto-review -y

# Run baseline benchmark
wr benchmark run -c vanilla_llm -n 10 -y

# Run full WorldReasoner benchmark
wr benchmark run -c worldreasoner -y

# Visualize results
python examples/visualize_benchmarks.py
```

For the full CLI reference, see [Appendix A](appendix/A_cli_reference.md).
