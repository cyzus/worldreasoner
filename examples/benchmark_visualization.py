"""Benchmark visualization utilities.

Supports the auto-benchmark format (autobench_*.json) produced by
`wr benchmark run`, which contains multiple conditions × models per file.
Also supports the legacy single-model format (benchmark_*.json) for
backward compatibility.
"""

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

    # Condition display order (cheapest → most expensive)
    CONDITION_ORDER = [
        "vanilla_llm",
        "structured_scenario",
        "search_enabled",
        "worldreasoner",
        "oracle",
    ]

    def __init__(self, benchmarks_dir: Path):
        if not pd:
            raise ImportError("pandas and matplotlib are required for visualization")
        self.benchmarks_dir = benchmarks_dir

    def load_data(self) -> pd.DataFrame:
        """Load all benchmark data into a single DataFrame.

        Handles both autobench_*.json (new) and benchmark_*.json (legacy) formats.
        Returns one row per (condition, model, run_id) combination.
        """
        records = []
        records.extend(self._load_autobench_files())
        records.extend(self._load_legacy_files())
        return pd.DataFrame(records)

    def _load_autobench_files(self) -> List[Dict[str, Any]]:
        """Load auto-benchmark files (autobench_*.json)."""
        files = sorted(self.benchmarks_dir.glob("autobench_*.json"))
        records = []

        for filepath in files:
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)

                info = data.get("auto_benchmark_info", {})
                run_id = info.get("run_id", filepath.stem)
                timestamp = info.get("timestamp", "")
                ts = datetime.fromisoformat(timestamp) if timestamp else None
                duration = info.get("duration_seconds", 0)

                for cond_name, model_results in data.get("condition_results", {}).items():
                    for model_name, result in model_results.items():
                        successful = result.get("successful", 0)
                        total = result.get("total_questions", 0)

                        records.append({
                            "run_id": run_id,
                            "condition": cond_name,
                            "display_name": result.get("display_name", cond_name),
                            "model": model_name,
                            "accuracy": result.get("accuracy", 0.0),
                            "brier_score": result.get("avg_brier_score"),
                            "log_score": result.get("avg_log_score"),
                            "successful": successful,
                            "failed": result.get("failed", 0),
                            "total_questions": total,
                            "timestamp": ts,
                            "duration_seconds": duration,
                            "filename": filepath.name,
                            "format": "autobench",
                        })
            except Exception as e:
                print(f"Error loading {filepath}: {e}")

        return records

    def _load_legacy_files(self) -> List[Dict[str, Any]]:
        """Load legacy benchmark files (benchmark_*.json)."""
        files = sorted(self.benchmarks_dir.glob("benchmark_*.json"))
        records = []

        for filepath in files:
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)

                results = data.get("results", {})
                if results.get("successful", 0) == 0:
                    continue

                model_info = data.get("model_info", {})
                bench_info = data.get("benchmark_info", {})
                ts_str = bench_info.get("timestamp", "")
                ts = datetime.fromisoformat(ts_str) if ts_str else None

                records.append({
                    "run_id": filepath.stem,
                    "condition": model_info.get("mode", "container"),
                    "display_name": model_info.get("mode", "container"),
                    "model": model_info.get("model", "unknown"),
                    "accuracy": results.get("overall_accuracy", 0.0),
                    "brier_score": results.get("avg_brier_score"),
                    "log_score": results.get("avg_log_score"),
                    "successful": results.get("successful", 0),
                    "failed": results.get("failed", 0),
                    "total_questions": results.get("total", 0),
                    "timestamp": ts,
                    "duration_seconds": 0,
                    "filename": filepath.name,
                    "format": "legacy",
                })
            except Exception as e:
                print(f"Error loading {filepath}: {e}")

        return records

    def latest_run(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter to only the latest run per (condition, model)."""
        if df.empty:
            return df
        return (
            df.sort_values("timestamp")
            .groupby(["condition", "model"], as_index=False)
            .tail(1)
        )

    def plot_accuracy_comparison(
        self,
        df: pd.DataFrame,
        output_path: Optional[Path] = None,
        latest_only: bool = True,
    ):
        """Bar chart comparing accuracy across conditions, grouped by model.

        Args:
            df: DataFrame from load_data()
            output_path: If set, save figure instead of showing
            latest_only: If True, use only the most recent run per (condition, model)
        """
        if df.empty:
            print("No data to plot.")
            return None

        data = self.latest_run(df) if latest_only else df

        models = sorted(data["model"].unique())
        conditions = [c for c in self.CONDITION_ORDER if c in data["condition"].values]

        fig, ax = plt.subplots(figsize=(max(10, len(conditions) * 2), 6))

        bar_width = 0.8 / max(len(models), 1)
        x = np.arange(len(conditions))
        colors = plt.cm.Set2(np.linspace(0, 1, max(len(models), 1)))

        for i, model in enumerate(models):
            model_data = data[data["model"] == model]
            accuracies = []
            for cond in conditions:
                row = model_data[model_data["condition"] == cond]
                accuracies.append(row["accuracy"].values[0] * 100 if len(row) > 0 else 0)

            bars = ax.bar(
                x + i * bar_width - (len(models) - 1) * bar_width / 2,
                accuracies,
                bar_width,
                label=model,
                color=colors[i],
            )
            for bar, acc in zip(bars, accuracies):
                if acc > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.5,
                        f"{acc:.1f}%",
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )

        display_names = []
        for c in conditions:
            row = data[data["condition"] == c]
            display_names.append(row["display_name"].values[0] if len(row) > 0 else c)

        ax.set_xticks(x)
        ax.set_xticklabels(display_names, rotation=15, ha="right")
        ax.set_ylabel("Accuracy (%)")
        ax.set_title("Forecast Accuracy by Condition")
        ax.legend(title="Model", loc="upper left")
        ax.set_ylim(0, 105)
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()
        if output_path:
            plt.savefig(output_path, dpi=150)
        return fig

    def plot_brier_comparison(
        self,
        df: pd.DataFrame,
        output_path: Optional[Path] = None,
        latest_only: bool = True,
    ):
        """Bar chart comparing Brier scores across conditions.

        Lower Brier score is better, so bars grow downward from 1.0.
        """
        if df.empty:
            print("No data to plot.")
            return None

        data = self.latest_run(df) if latest_only else df
        # Only rows with Brier scores
        data = data[data["brier_score"].notna()]
        if data.empty:
            print("No Brier score data available.")
            return None

        models = sorted(data["model"].unique())
        conditions = [c for c in self.CONDITION_ORDER if c in data["condition"].values]

        fig, ax = plt.subplots(figsize=(max(10, len(conditions) * 2), 6))

        bar_width = 0.8 / max(len(models), 1)
        x = np.arange(len(conditions))
        colors = plt.cm.Set2(np.linspace(0, 1, max(len(models), 1)))

        for i, model in enumerate(models):
            model_data = data[data["model"] == model]
            scores = []
            for cond in conditions:
                row = model_data[model_data["condition"] == cond]
                scores.append(row["brier_score"].values[0] if len(row) > 0 else float("nan"))

            bars = ax.bar(
                x + i * bar_width - (len(models) - 1) * bar_width / 2,
                scores,
                bar_width,
                label=model,
                color=colors[i],
            )
            for bar, score in zip(bars, scores):
                if not np.isnan(score):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.01,
                        f"{score:.3f}",
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )

        display_names = []
        for c in conditions:
            row = data[data["condition"] == c]
            display_names.append(row["display_name"].values[0] if len(row) > 0 else c)

        ax.set_xticks(x)
        ax.set_xticklabels(display_names, rotation=15, ha="right")
        ax.set_ylabel("Brier Score (lower is better)")
        ax.set_title("Forecast Brier Score by Condition")
        ax.legend(title="Model", loc="upper right")
        ax.set_ylim(0, 1.05)
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()
        if output_path:
            plt.savefig(output_path, dpi=150)
        return fig

    def plot_multi_metric(
        self,
        df: pd.DataFrame,
        output_path: Optional[Path] = None,
        latest_only: bool = True,
    ):
        """Side-by-side subplots for accuracy, Brier, and log score."""
        if df.empty:
            print("No data to plot.")
            return None

        data = self.latest_run(df) if latest_only else df
        models = sorted(data["model"].unique())
        conditions = [c for c in self.CONDITION_ORDER if c in data["condition"].values]

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))

        bar_width = 0.8 / max(len(models), 1)
        x = np.arange(len(conditions))
        colors = plt.cm.Set2(np.linspace(0, 1, max(len(models), 1)))

        display_names = []
        for c in conditions:
            row = data[data["condition"] == c]
            display_names.append(row["display_name"].values[0] if len(row) > 0 else c)

        metrics = [
            ("accuracy", "Accuracy (%)", lambda v: v * 100, (0, 105)),
            ("brier_score", "Brier Score (lower=better)", lambda v: v, (0, 1.05)),
            ("log_score", "Log Score (higher=better)", lambda v: v, None),
        ]

        for ax, (col, ylabel, transform, ylim) in zip(axes, metrics):
            for i, model in enumerate(models):
                model_data = data[data["model"] == model]
                values = []
                for cond in conditions:
                    row = model_data[model_data["condition"] == cond]
                    if len(row) > 0 and pd.notna(row[col].values[0]):
                        values.append(transform(row[col].values[0]))
                    else:
                        values.append(float("nan"))

                ax.bar(
                    x + i * bar_width - (len(models) - 1) * bar_width / 2,
                    values,
                    bar_width,
                    label=model,
                    color=colors[i],
                )

            ax.set_xticks(x)
            ax.set_xticklabels(display_names, rotation=20, ha="right", fontsize=8)
            ax.set_ylabel(ylabel)
            ax.set_title(ylabel.split("(")[0].strip())
            ax.grid(axis="y", alpha=0.3)
            if ylim:
                ax.set_ylim(*ylim)

        axes[0].legend(title="Model", loc="upper left", fontsize=7)
        fig.suptitle("Forecast Evaluation — All Metrics", fontsize=14, y=1.02)
        plt.tight_layout()
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
        return fig

    def print_summary_table(self, df: pd.DataFrame, latest_only: bool = True):
        """Print a text summary table to stdout."""
        data = self.latest_run(df) if latest_only else df
        if data.empty:
            print("No data.")
            return

        # Sort by condition order, then model
        cond_order = {c: i for i, c in enumerate(self.CONDITION_ORDER)}
        data = data.copy()
        data["_order"] = data["condition"].map(lambda c: cond_order.get(c, 99))
        data = data.sort_values(["_order", "model"])

        print(f"\n{'Condition':<25} {'Model':<35} {'Acc':>6} {'Brier':>7} {'Log':>8} {'N':>5}")
        print("-" * 90)
        for _, row in data.iterrows():
            brier = f"{row['brier_score']:.4f}" if pd.notna(row["brier_score"]) else "  N/A"
            log = f"{row['log_score']:.4f}" if pd.notna(row["log_score"]) else "     N/A"
            print(
                f"{row['display_name']:<25} {row['model']:<35} "
                f"{row['accuracy']*100:>5.1f}% {brier:>7} {log:>8} "
                f"{row['successful']:>5}"
            )
