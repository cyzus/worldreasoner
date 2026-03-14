# WorldReasoner Examples

For most tasks, use the `wr` CLI — see [Appendix A: CLI Reference](../docs/appendix/A_cli_reference.md).

The scripts in this directory are for specialized use cases not covered by the CLI.

## Visualization

### `visualize_benchmarks.py`
Generate charts from benchmark JSON results (accuracy, Brier score, log score).
```bash
python examples/visualize_benchmarks.py
python examples/visualize_benchmarks.py --metric accuracy
python examples/visualize_benchmarks.py --output benchmarks/figures/results.png
python examples/visualize_benchmarks.py --table  # text summary, no GUI
```
Reads `benchmarks/autobench_*.json` files produced by `wr benchmark run`.

## Temporal Analysis

### `run_temporal_forecast_analysis.py`
Analyze how forecast accuracy evolves as the resolution date approaches for a single question.
```bash
python examples/run_temporal_forecast_analysis.py --question-id <ID> --num-points 5
```
No CLI equivalent — use this for in-depth per-question temporal analysis.
