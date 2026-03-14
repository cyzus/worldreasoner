# Section 1: Introduction

## 1.1 Background

Prediction markets such as [Polymarket](https://polymarket.com) provide a uniquely rigorous evaluation platform for forecasting systems. Prices on these markets represent crowd-aggregated probability estimates for real-world events, and outcomes are definitively resolved with verifiable ground truth. This makes them ideal for assessing whether an AI system can reason about the future better than collective human judgment.

Despite strong general reasoning capabilities, large language models (LLMs) face fundamental structural challenges as forecasters:

- **Knowledge cutoff**: LLMs have a fixed training data horizon. Any event after that date is invisible to the model without external retrieval.
- **No causal structure**: LLMs reason over flat text; they do not naturally build explicit cause-and-effect chains that trace *why* a market price moved or *what* will drive an outcome.
- **Information leakage risk**: Naive evaluation systems expose ground truth to the forecasting agent, invalidating results.
- **Calibration deficits**: Models often assign high confidence to wrong answers, producing poor Brier and log scores even when directionally correct.

## 1.2 System Overview

WorldReasoner addresses these limitations through three coordinated subsystems:

1. **Temporal Gateway** — An MCP (Model Context Protocol) server that acts as a strict information firewall. The agent is given a `simulated_date` and can only retrieve articles and events published before that date. Ground truth is withheld until evaluation time.

2. **Evidence Pipeline** — An automated pipeline that collects news articles/webpages, builds causal event graphs, and analyzes Polymarket price curves to identify significant turning points and lead changes. Evidence is quality-scored and reviewed before forecasting.

3. **Benchmarking Framework** — A structured evaluation harness supporting six experimental conditions (from pure LLM recall to full evidence-augmented reasoning) and four scoring metrics. Results are persisted as JSON and visualized as comparative charts.

## 1.3 Key Contributions

- A **temporally-isolated forecasting interface** that prevents leakage of future information to forecasting agents while still providing rich contextual evidence.
- A **market price analysis module** that extracts significant turning points and lead changes from Polymarket CLOB price curves using PELT/BIC changepoint detection and heuristic peak/trough algorithms.
- A **causal graph evidence structure** that organizes news events into root-to-outcome hypothesis chains, enabling agents to reason causally rather than from flat document retrieval.
- A **quality scoring system** for both article collections and event graphs, with temporal gap penalties and coverage metrics that flag insufficiently populated evidence windows.
- A **six-condition ablation benchmark** across multiple frontier models on a curated 300-question dataset spanning six domains and three time horizons.

## 1.4 Repository Structure

```
worldreasoner/
├── src/
│   ├── domain/              # Core business logic and data models
│   │   ├── models.py        # Question, Event, Article, Forecast
│   │   ├── evaluation/      # Metrics, conditions, ForecastEvaluator
│   │   └── services/        # QuestionService, TemporalGateway
│   ├── core/                # Infrastructure (database, temporal filtering)
│   ├── tools/               # Agent tools (inspectors, graph builder, search)
│   │   └── inspectors/      # GraphInspectorTool, ArticleInspectorTool
│   ├── pipelines/           # Collection and evidence pipelines
│   │   └── collection/      # PolymarketRunner, goal orchestrator
│   ├── integrations/        # External API clients
│   │   ├── polymarket_client.py   # Gamma API wrapper
│   │   └── polymarket.py          # CLOB price history + curve analysis
│   ├── api/                 # FastAPI backend
│   │   └── routes/          # questions.py, forecasts.py
│   └── mcp_forecasting_server.py  # MCP temporal gateway
├── examples/                # Benchmark scripts, visualization
│   ├── run_benchmark_evaluation.py
│   ├── visualize_benchmarks.py
│   └── evaluate_forecasts.py
├── scripts/                 # Dataset collection scripts
│   └── run_experiment_collection.py
├── config/                  # YAML configs (collection goals, LLM providers)
├── benchmarks/              # Output JSON from benchmark runs
├── tests/                   # Unit and integration tests
├── docs/                    # This documentation
└── migrations/              # Database schema migrations
```

## 1.5 Document Guide

The remaining sections of this documentation cover:

- **Section 2** — How questions are sourced from Polymarket and structured into the dataset.
- **Section 3** — How evidence (articles, events, market price signals) is collected and quality-scored.
- **Section 4** — How the MCP forecasting server provides temporally-filtered evidence to agents.
- **Section 5** — How benchmarks are run and results are measured.
- **Section 6** — How the inspector tools assess evidence quality.
- **Appendix A** — Complete CLI reference.
