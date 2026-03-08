"""Example: Visualize benchmarks.

Generates plots from auto-benchmark JSON results (autobench_*.json).
Also supports legacy benchmark_*.json files.

Usage:
    python examples/visualize_benchmarks.py
    python examples/visualize_benchmarks.py --output benchmarks/figures/results.png
    python examples/visualize_benchmarks.py --metric brier
    python examples/visualize_benchmarks.py --table
"""

import argparse
from pathlib import Path
from examples.benchmark_visualization import BenchmarkVisualizer


def main():
    parser = argparse.ArgumentParser(description="Visualize benchmark results")
    parser.add_argument(
        "--benchmarks-dir", default="benchmarks", help="Input directory"
    )
    parser.add_argument("--output", help="Output file path for figure (optional)")
    parser.add_argument(
        "--metric",
        choices=["accuracy", "brier", "all"],
        default="all",
        help="Which metric to plot (default: all)",
    )
    parser.add_argument(
        "--table", action="store_true", help="Print text summary table instead of plot"
    )
    args = parser.parse_args()

    viz = BenchmarkVisualizer(Path(args.benchmarks_dir))
    df = viz.load_data()

    if df.empty:
        print("No benchmark data found.")
        return

    autobench_count = len(df[df["format"] == "autobench"])
    legacy_count = len(df[df["format"] == "legacy"])
    print(f"Loaded {len(df)} results ({autobench_count} autobench, {legacy_count} legacy)")

    if args.table:
        viz.print_summary_table(df)
        return

    output = Path(args.output) if args.output else None

    if args.metric == "accuracy":
        viz.plot_accuracy_comparison(df, output_path=output)
    elif args.metric == "brier":
        viz.plot_brier_comparison(df, output_path=output)
    else:
        viz.plot_multi_metric(df, output_path=output)

    if not output:
        import matplotlib.pyplot as plt

        plt.show()
    else:
        print(f"Saved to {output}")


if __name__ == "__main__":
    main()
