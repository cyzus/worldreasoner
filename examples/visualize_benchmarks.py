"""
Benchmark visualization script - creates comparative figures from all benchmark results.

This script:
1. Loads all benchmark JSON files from benchmarks/
2. Extracts key metrics (accuracy, Brier score, log score)
3. Generates comparison visualizations:
   - Model performance comparison
   - Knowledge-only vs Full mode comparison
   - Performance over time
   - Metric distributions

Prerequisites:
- Benchmark results in benchmarks/ directory
- Visualization dependencies (install via: uv sync --group viz)

Usage:
    # Generate all visualizations
    python examples/visualize_benchmarks.py

    # Save to custom output directory
    python examples/visualize_benchmarks.py --output-dir figures/

    # Generate specific plot types
    python examples/visualize_benchmarks.py --plots accuracy brier

    # Show interactive plots instead of saving
    python examples/visualize_benchmarks.py --show
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import sys

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import pandas as pd
    import numpy as np
except ImportError:
    print("ERROR: Required packages not installed.")
    print("Please install: pip install matplotlib pandas numpy")
    sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate visualizations from benchmark results"
    )

    parser.add_argument(
        '--benchmarks-dir',
        type=str,
        default='benchmarks',
        help='Directory containing benchmark JSON files (default: benchmarks)'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        default='benchmarks/figures',
        help='Output directory for figures (default: benchmarks/figures)'
    )

    parser.add_argument(
        '--plots',
        nargs='+',
        choices=['accuracy', 'brier', 'log_score', 'mode_comparison', 'timeline', 'all'],
        default=['all'],
        help='Which plots to generate (default: all)'
    )

    parser.add_argument(
        '--show',
        action='store_true',
        help='Show interactive plots instead of saving to files'
    )

    parser.add_argument(
        '--dpi',
        type=int,
        default=150,
        help='DPI for saved figures (default: 150)'
    )

    return parser.parse_args()


def load_benchmark_files(benchmarks_dir: Path) -> List[Dict[str, Any]]:
    """Load all benchmark JSON files from directory.

    Args:
        benchmarks_dir: Directory containing benchmark files

    Returns:
        List of benchmark data dictionaries
    """
    benchmark_files = sorted(benchmarks_dir.glob('benchmark_*.json'))

    if not benchmark_files:
        print(f"WARNING: No benchmark files found in {benchmarks_dir}")
        return []

    benchmarks = []
    for filepath in benchmark_files:
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                data['_filename'] = filepath.name
                benchmarks.append(data)
        except Exception as e:
            print(f"WARNING: Error loading {filepath.name}: {e}")
            continue

    print(f"Loaded {len(benchmarks)} benchmark files")
    return benchmarks


def extract_dataframe(benchmarks: List[Dict[str, Any]]) -> pd.DataFrame:
    """Extract key metrics into a pandas DataFrame.

    Args:
        benchmarks: List of benchmark dictionaries

    Returns:
        DataFrame with flattened metrics
    """
    records = []
    for bench in benchmarks:
        # Skip benchmarks with no successful results
        if bench['results']['successful'] == 0:
            continue

        record = {
            # Model info
            'model': bench['model_info']['model'],
            'max_steps': bench['model_info']['max_steps'],
            'knowledge_cutoff': bench['model_info']['knowledge_cutoff'],
            'offset_days': bench['model_info']['offset_days'],
            'min_context_items': bench['model_info']['min_context_items'],
            # Support both old knowledge_only and new mode fields
            'mode': bench['model_info'].get('mode') or ('knowledge_only' if bench['model_info'].get('knowledge_only') else 'container'),
            'mode_label': bench['model_info'].get('mode', 'Knowledge-Only' if bench['model_info'].get('knowledge_only') else 'Container').title(),

            # Results
            'total_questions': bench['results']['total_questions'],
            'successful': bench['results']['successful'],
            'failed': bench['results']['failed'],
            'accuracy': bench['results']['overall_accuracy'],
            'brier_score': bench['results'].get('avg_brier_score'),
            'log_score': bench['results'].get('avg_log_score'),

            # Benchmark info
            'timestamp': datetime.fromisoformat(bench['benchmark_info']['timestamp']),
            'duration_seconds': bench['benchmark_info']['duration_seconds'],
            'questions_per_minute': bench['benchmark_info']['questions_per_minute'],

            # Metadata
            'filename': bench['_filename']
        }
        records.append(record)

    return pd.DataFrame(records)


def plot_model_accuracy_comparison(df: pd.DataFrame, output_path: Path = None):
    """Create bar chart comparing accuracy across models.

    Args:
        df: DataFrame with benchmark data
        output_path: Optional path to save figure
    """
    # Group by model and mode, take most recent run
    grouped = df.sort_values('timestamp').groupby(['model', 'mode']).tail(1)

    # Sort by accuracy
    grouped = grouped.sort_values('accuracy', ascending=True)

    fig, ax = plt.subplots(figsize=(12, max(6, len(grouped) * 0.4)))

    # Create labels with mode
    labels = [f"{row['model']}\n({row['mode']})" for _, row in grouped.iterrows()]

    # Color by mode
    colors = ['#3498db' if mode == 'Full' else '#e74c3c'
              for mode in grouped['mode']]

    bars = ax.barh(range(len(grouped)), grouped['accuracy'] * 100, color=colors)

    ax.set_yticks(range(len(grouped)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel('Accuracy (%)', fontsize=11)
    ax.set_title('Model Accuracy Comparison (Most Recent Run)', fontsize=13, fontweight='bold')
    ax.grid(axis='x', alpha=0.3)

    # Add value labels
    for i, (bar, acc) in enumerate(zip(bars, grouped['accuracy'])):
        ax.text(acc * 100 + 1, i, f'{acc*100:.1f}%',
                va='center', fontsize=9)

    # Add legend
    full_patch = mpatches.Patch(color='#3498db', label='Full Mode (with research)')
    knowledge_patch = mpatches.Patch(color='#e74c3c', label='Knowledge-Only Mode')
    ax.legend(handles=[full_patch, knowledge_patch], loc='lower right')

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=args.dpi, bbox_inches='tight')
        print(f"Saved: {output_path}")

    return fig


def plot_brier_score_comparison(df: pd.DataFrame, output_path: Path = None):
    """Create bar chart comparing Brier scores across models.

    Args:
        df: DataFrame with benchmark data
        output_path: Optional path to save figure
    """
    # Filter out None values
    df_clean = df[df['brier_score'].notna()].copy()

    if len(df_clean) == 0:
        print("WARNING: No Brier score data available")
        return None

    # Group by model and mode, take most recent run
    grouped = df_clean.sort_values('timestamp').groupby(['model', 'mode']).tail(1)

    # Sort by Brier score (lower is better)
    grouped = grouped.sort_values('brier_score', ascending=False)

    fig, ax = plt.subplots(figsize=(12, max(6, len(grouped) * 0.4)))

    labels = [f"{row['model']}\n({row['mode']})" for _, row in grouped.iterrows()]
    colors = ['#3498db' if mode == 'Full' else '#e74c3c'
              for mode in grouped['mode']]

    bars = ax.barh(range(len(grouped)), grouped['brier_score'], color=colors)

    ax.set_yticks(range(len(grouped)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel('Brier Score (lower is better)', fontsize=11)
    ax.set_title('Model Brier Score Comparison (Most Recent Run)', fontsize=13, fontweight='bold')
    ax.grid(axis='x', alpha=0.3)

    # Add value labels
    for i, (bar, score) in enumerate(zip(bars, grouped['brier_score'])):
        ax.text(score + 0.01, i, f'{score:.4f}',
                va='center', fontsize=9)

    # Add legend
    full_patch = mpatches.Patch(color='#3498db', label='Full Mode (with research)')
    knowledge_patch = mpatches.Patch(color='#e74c3c', label='Knowledge-Only Mode')
    ax.legend(handles=[full_patch, knowledge_patch], loc='lower right')

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=args.dpi, bbox_inches='tight')
        print(f"Saved: {output_path}")

    return fig


def plot_mode_comparison(df: pd.DataFrame, output_path: Path = None):
    """Create side-by-side comparison of Full vs Knowledge-Only modes.

    Args:
        df: DataFrame with benchmark data
        output_path: Optional path to save figure
    """
    # Find models that have both modes
    models_with_both = []
    for model in df['model'].unique():
        model_df = df[df['model'] == model]
        modes = set(model_df['mode'])
        if 'Full' in modes and 'Knowledge-Only' in modes:
            models_with_both.append(model)

    if not models_with_both:
        print("WARNING: No models found with both Full and Knowledge-Only modes")
        return None

    # Get most recent run for each model+mode combination
    comparison_data = []
    for model in models_with_both:
        model_df = df[df['model'] == model]
        for mode in ['Full', 'Knowledge-Only']:
            mode_df = model_df[model_df['mode'] == mode].sort_values('timestamp')
            if len(mode_df) > 0:
                latest = mode_df.iloc[-1]
                comparison_data.append({
                    'model': model,
                    'mode': mode,
                    'accuracy': latest['accuracy'],
                    'brier_score': latest['brier_score']
                })

    comp_df = pd.DataFrame(comparison_data)

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, max(6, len(models_with_both) * 0.6)))

    # Plot accuracy comparison
    for i, model in enumerate(models_with_both):
        model_data = comp_df[comp_df['model'] == model]
        full = model_data[model_data['mode'] == 'Full']['accuracy'].values[0]
        knowledge = model_data[model_data['mode'] == 'Knowledge-Only']['accuracy'].values[0]

        ax1.barh(i - 0.2, full * 100, 0.4, label='Full' if i == 0 else '', color='#3498db')
        ax1.barh(i + 0.2, knowledge * 100, 0.4, label='Knowledge-Only' if i == 0 else '', color='#e74c3c')

        # Add difference annotation
        diff = (full - knowledge) * 100
        ax1.text(max(full, knowledge) * 100 + 2, i, f'+{diff:.1f}%' if diff > 0 else f'{diff:.1f}%',
                va='center', fontsize=8, color='green' if diff > 0 else 'red')

    ax1.set_yticks(range(len(models_with_both)))
    ax1.set_yticklabels(models_with_both, fontsize=9)
    ax1.set_xlabel('Accuracy (%)', fontsize=11)
    ax1.set_title('Accuracy: Full vs Knowledge-Only', fontsize=12, fontweight='bold')
    ax1.legend()
    ax1.grid(axis='x', alpha=0.3)

    # Plot Brier score comparison (if available)
    has_brier = comp_df['brier_score'].notna().any()
    if has_brier:
        for i, model in enumerate(models_with_both):
            model_data = comp_df[comp_df['model'] == model]
            full_brier = model_data[model_data['mode'] == 'Full']['brier_score'].values[0]
            knowledge_brier = model_data[model_data['mode'] == 'Knowledge-Only']['brier_score'].values[0]

            if pd.notna(full_brier) and pd.notna(knowledge_brier):
                ax2.barh(i - 0.2, full_brier, 0.4, color='#3498db')
                ax2.barh(i + 0.2, knowledge_brier, 0.4, color='#e74c3c')

                # Add difference (negative is better for Brier)
                diff = full_brier - knowledge_brier
                ax2.text(max(full_brier, knowledge_brier) + 0.01, i,
                        f'{diff:.4f}',
                        va='center', fontsize=8,
                        color='red' if diff > 0 else 'green')

        ax2.set_yticks(range(len(models_with_both)))
        ax2.set_yticklabels(models_with_both, fontsize=9)
        ax2.set_xlabel('Brier Score (lower is better)', fontsize=11)
        ax2.set_title('Brier Score: Full vs Knowledge-Only', fontsize=12, fontweight='bold')
        ax2.grid(axis='x', alpha=0.3)
    else:
        ax2.text(0.5, 0.5, 'No Brier Score Data Available',
                ha='center', va='center', transform=ax2.transAxes, fontsize=12)
        ax2.set_xticks([])
        ax2.set_yticks([])

    plt.suptitle('Research Impact: Full Mode vs Knowledge-Only Mode',
                fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=args.dpi, bbox_inches='tight')
        print(f"Saved: {output_path}")

    return fig


def plot_performance_timeline(df: pd.DataFrame, output_path: Path = None):
    """Create timeline showing performance evolution.

    Args:
        df: DataFrame with benchmark data
        output_path: Optional path to save figure
    """
    if len(df) < 2:
        print("WARNING: Need at least 2 benchmark runs for timeline")
        return None

    # Sort by timestamp
    df_sorted = df.sort_values('timestamp')

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot accuracy over time
    for model in df_sorted['model'].unique():
        model_df = df_sorted[df_sorted['model'] == model]
        for mode in model_df['mode'].unique():
            mode_df = model_df[model_df['mode'] == mode]
            label = f"{model} ({mode})"
            marker = 'o' if mode == 'Full' else 's'
            ax1.plot(mode_df['timestamp'], mode_df['accuracy'] * 100,
                    marker=marker, label=label, markersize=6, linewidth=2)

    ax1.set_ylabel('Accuracy (%)', fontsize=11)
    ax1.set_title('Model Performance Over Time', fontsize=13, fontweight='bold')
    ax1.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=8)
    ax1.grid(alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)

    # Plot Brier score over time (if available)
    has_brier = df_sorted['brier_score'].notna().any()
    if has_brier:
        for model in df_sorted['model'].unique():
            model_df = df_sorted[df_sorted['model'] == model]
            for mode in model_df['mode'].unique():
                mode_df = model_df[model_df['mode'] == mode]
                mode_df = mode_df[mode_df['brier_score'].notna()]
                if len(mode_df) > 0:
                    label = f"{model} ({mode})"
                    marker = 'o' if mode == 'Full' else 's'
                    ax2.plot(mode_df['timestamp'], mode_df['brier_score'],
                            marker=marker, label=label, markersize=6, linewidth=2)

        ax2.set_ylabel('Brier Score (lower is better)', fontsize=11)
        ax2.set_xlabel('Date', fontsize=11)
        ax2.set_title('Brier Score Over Time', fontsize=13, fontweight='bold')
        ax2.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=8)
        ax2.grid(alpha=0.3)
        ax2.tick_params(axis='x', rotation=45)
    else:
        ax2.text(0.5, 0.5, 'No Brier Score Data Available',
                ha='center', va='center', transform=ax2.transAxes, fontsize=12)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=args.dpi, bbox_inches='tight')
        print(f"Saved: {output_path}")

    return fig


def plot_log_score_comparison(df: pd.DataFrame, output_path: Path = None):
    """Create bar chart comparing log scores across models.

    Args:
        df: DataFrame with benchmark data
        output_path: Optional path to save figure
    """
    # Filter out None values
    df_clean = df[df['log_score'].notna()].copy()

    if len(df_clean) == 0:
        print("WARNING: No log score data available")
        return None

    # Group by model and mode, take most recent run
    grouped = df_clean.sort_values('timestamp').groupby(['model', 'mode']).tail(1)

    # Sort by log score (higher is better)
    grouped = grouped.sort_values('log_score', ascending=True)

    fig, ax = plt.subplots(figsize=(12, max(6, len(grouped) * 0.4)))

    labels = [f"{row['model']}\n({row['mode']})" for _, row in grouped.iterrows()]
    colors = ['#3498db' if mode == 'Full' else '#e74c3c'
              for mode in grouped['mode']]

    bars = ax.barh(range(len(grouped)), grouped['log_score'], color=colors)

    ax.set_yticks(range(len(grouped)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel('Log Score (higher is better)', fontsize=11)
    ax.set_title('Model Log Score Comparison (Most Recent Run)', fontsize=13, fontweight='bold')
    ax.grid(axis='x', alpha=0.3)

    # Add value labels
    for i, (bar, score) in enumerate(zip(bars, grouped['log_score'])):
        offset = 0.05 if score < 0 else -0.05
        ha = 'left' if score < 0 else 'right'
        ax.text(score + offset, i, f'{score:.4f}',
                va='center', ha=ha, fontsize=9)

    # Add legend
    full_patch = mpatches.Patch(color='#3498db', label='Full Mode (with research)')
    knowledge_patch = mpatches.Patch(color='#e74c3c', label='Knowledge-Only Mode')
    ax.legend(handles=[full_patch, knowledge_patch], loc='lower right')

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=args.dpi, bbox_inches='tight')
        print(f"Saved: {output_path}")

    return fig


def print_summary_statistics(df: pd.DataFrame):
    """Print summary statistics to console.

    Args:
        df: DataFrame with benchmark data
    """
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY STATISTICS")
    print("=" * 80)

    print(f"\nTotal benchmark runs: {len(df)}")
    print(f"Unique models: {df['model'].nunique()}")
    print(f"Date range: {df['timestamp'].min().date()} to {df['timestamp'].max().date()}")

    print("\nOverall Statistics:")
    print(f"  Mean Accuracy: {df['accuracy'].mean():.2%}")
    print(f"  Std Accuracy:  {df['accuracy'].std():.2%}")
    if df['brier_score'].notna().any():
        print(f"  Mean Brier:    {df['brier_score'].mean():.4f}")
        print(f"  Std Brier:     {df['brier_score'].std():.4f}")

    print("\nBy Mode:")
    for mode in df['mode'].unique():
        mode_df = df[df['mode'] == mode]
        print(f"  {mode}:")
        print(f"    Runs: {len(mode_df)}")
        print(f"    Mean Accuracy: {mode_df['accuracy'].mean():.2%}")
        if mode_df['brier_score'].notna().any():
            print(f"    Mean Brier: {mode_df['brier_score'].mean():.4f}")

    print("\nTop 3 Best Performing (by accuracy):")
    top3 = df.nlargest(3, 'accuracy')
    for i, (_, row) in enumerate(top3.iterrows(), 1):
        print(f"  {i}. {row['model']} ({row['mode']}): {row['accuracy']:.2%}")

    print("\n" + "=" * 80 + "\n")


def main():
    """Main entry point."""
    global args
    args = parse_args()

    # Load benchmark files
    benchmarks_dir = Path(args.benchmarks_dir)
    if not benchmarks_dir.exists():
        print(f"ERROR: Benchmarks directory not found: {benchmarks_dir}")
        sys.exit(1)

    benchmarks = load_benchmark_files(benchmarks_dir)

    if not benchmarks:
        print("No benchmark data to visualize!")
        sys.exit(1)

    # Extract DataFrame
    df = extract_dataframe(benchmarks)

    if len(df) == 0:
        print("No valid benchmark data found!")
        sys.exit(1)

    # Print summary
    print_summary_statistics(df)

    # Determine which plots to create
    plot_types = args.plots
    if 'all' in plot_types:
        plot_types = ['accuracy', 'brier', 'log_score', 'mode_comparison', 'timeline']

    # Create output directory if saving
    if not args.show:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Saving figures to: {output_dir}\n")

    # Generate plots
    figures = []

    if 'accuracy' in plot_types:
        print("Generating accuracy comparison...")
        output_path = None if args.show else output_dir / 'accuracy_comparison.png'
        fig = plot_model_accuracy_comparison(df, output_path)
        if fig:
            figures.append(fig)

    if 'brier' in plot_types:
        print("Generating Brier score comparison...")
        output_path = None if args.show else output_dir / 'brier_score_comparison.png'
        fig = plot_brier_score_comparison(df, output_path)
        if fig:
            figures.append(fig)

    if 'log_score' in plot_types:
        print("Generating log score comparison...")
        output_path = None if args.show else output_dir / 'log_score_comparison.png'
        fig = plot_log_score_comparison(df, output_path)
        if fig:
            figures.append(fig)

    if 'mode_comparison' in plot_types:
        print("Generating mode comparison...")
        output_path = None if args.show else output_dir / 'mode_comparison.png'
        fig = plot_mode_comparison(df, output_path)
        if fig:
            figures.append(fig)

    if 'timeline' in plot_types:
        print("Generating performance timeline...")
        output_path = None if args.show else output_dir / 'performance_timeline.png'
        fig = plot_performance_timeline(df, output_path)
        if fig:
            figures.append(fig)

    # Show plots if requested
    if args.show:
        print("\nDisplaying interactive plots...")
        plt.show()
    else:
        print(f"\nGenerated {len(figures)} visualizations in {output_dir}")

    print("\nVisualization complete!")


if __name__ == "__main__":
    main()
