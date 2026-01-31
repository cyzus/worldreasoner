"""Benchmark visualization utilities."""

from typing import List, Dict, Any, Optional
from pathlib import Path
import json
from datetime import datetime

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import pandas as pd
    import numpy as np
except ImportError:
    plt = None
    pd = None
    np = None

class BenchmarkVisualizer:
    """Visualizer for benchmark results."""

    def __init__(self, benchmarks_dir: Path):
        if not pd:
            raise ImportError("pandas and matplotlib are required for visualization")
        self.benchmarks_dir = benchmarks_dir

    def load_data(self) -> pd.DataFrame:
        """Load benchmark data into DataFrame."""
        files = sorted(self.benchmarks_dir.glob("benchmark_*.json"))
        records = []
        
        for filepath in files:
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                    
                if data["results"]["successful"] == 0:
                    continue
                    
                records.append({
                    "model": data["model_info"]["model"],
                    "mode": data["model_info"].get("mode", "container"),
                    "accuracy": data["results"]["overall_accuracy"],
                    "brier_score": data["results"].get("avg_brier_score"),
                    "timestamp": datetime.fromisoformat(data["benchmark_info"]["timestamp"]),
                    "filename": filepath.name
                })
            except Exception as e:
                print(f"Error loading {filepath}: {e}")
                
        return pd.DataFrame(records)

    def plot_accuracy_comparison(self, df: pd.DataFrame, output_path: Optional[Path] = None):
        """Plot accuracy comparison bar chart."""
        # Group by model/mode, take latest
        grouped = df.sort_values("timestamp").groupby(["model", "mode"]).tail(1)
        grouped = grouped.sort_values("accuracy", ascending=True)

        fig, ax = plt.subplots(figsize=(10, max(5, len(grouped) * 0.5)))
        
        labels = [f"{row['model']}\\n({row['mode']})" for _, row in grouped.iterrows()]
        bars = ax.barh(range(len(grouped)), grouped["accuracy"] * 100)
        
        ax.set_yticks(range(len(grouped)))
        ax.set_yticklabels(labels)
        ax.set_xlabel("Accuracy (%)")
        ax.set_title("Model Accuracy Comparison")
        ax.grid(axis="x", alpha=0.3)

        for i, (bar, acc) in enumerate(zip(bars, grouped["accuracy"])):
            ax.text(acc * 100 + 1, i, f"{acc*100:.1f}%", va="center")

        plt.tight_layout()
        if output_path:
            plt.savefig(output_path, dpi=150)
        return fig
