"""Example: Visualize benchmarks.

Generates plots from benchmark JSON results.
"""

import argparse
from pathlib import Path
from src.utils.benchmark_visualization import BenchmarkVisualizer

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmarks-dir", default="benchmarks", help="Input directory")
    parser.add_argument("--output", help="Output file path (optional)")
    args = parser.parse_args()

    viz = BenchmarkVisualizer(Path(args.benchmarks_dir))
    df = viz.load_data()
    
    if df.empty:
        print("No benchmark data found.")
        return

    print(f"Loaded {len(df)} runs.")
    
    # Plot
    output = Path(args.output) if args.output else None
    viz.plot_accuracy_comparison(df, output_path=output)
    
    if not output:
        import matplotlib.pyplot as plt
        plt.show()
    else:
        print(f"Saved to {output}")

if __name__ == "__main__":
    main()
