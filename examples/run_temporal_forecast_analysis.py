"""
Temporal forecast analysis - analyze how forecast accuracy changes over time.

This script runs forecasts on a single question at multiple simulated dates,
showing how accuracy and confidence evolve as more context becomes available.

This is useful for understanding:
- How much does additional context improve forecasts?
- At what point does the LLM have "enough" information?
- How does confidence change over time?
- When does the model "figure out" the answer?

Prerequisites:
1. Set up config/local.yaml with LLM API keys
2. Have a resolved question in the database (with ground_truth)
3. MCP server running (default: http://127.0.0.1:8110/mcp)

Usage:
    # Analyze temporal progression for a specific question
    python examples/run_temporal_forecast_analysis.py --question-id q_tech_20251117_003

    # Use specific model
    python examples/run_temporal_forecast_analysis.py --question-id q_tech_20251117_003 --model gpt-4

    # Customize number of forecast points (default: 5)
    python examples/run_temporal_forecast_analysis.py --question-id q_tech_20251117_003 --num-points 10

    # Save results to JSON
    python examples/run_temporal_forecast_analysis.py --question-id q_tech_20251117_003 --output results.json

    # Skip visualization generation
    python examples/run_temporal_forecast_analysis.py --question-id q_tech_20251117_003 --no-viz
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple

from src.core.database import GenericDatabase
from src.domain.models import Question, Forecast
from src.domain.models.event import Event
from src.domain.models.article import Article
from src.agents.factory import AgentFactory
from src.config import get_config
from src.domain.evaluation import ForecastEvaluator
from src.utils.logging import logger


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze temporal forecast progression for a single question"
    )

    # Question selection (required)
    parser.add_argument(
        '--question-id',
        type=str,
        required=True,
        help='Question ID to analyze'
    )

    # Database
    parser.add_argument(
        '--db',
        type=str,
        default='worldreasoner.db',
        help='Path to database file (default: worldreasoner.db)'
    )

    # Temporal configuration
    parser.add_argument(
        '--knowledge-cutoff',
        type=str,
        default='2024-05-01',
        help='LLM training cutoff date (YYYY-MM-DD, default: 2024-05-01)'
    )

    parser.add_argument(
        '--num-points',
        type=int,
        default=5,
        help='Number of forecast points to generate (default: 5)'
    )

    parser.add_argument(
        '--min-context-items',
        type=int,
        default=2,
        help='Minimum context items needed for first forecast (default: 2)'
    )

    # Agent configuration
    parser.add_argument(
        '--max-steps',
        type=int,
        default=15,
        help='Maximum agent steps (default: 15)'
    )

    parser.add_argument(
        '--model',
        type=str,
        default=None,
        help='Override LLM model (e.g., gpt-4, claude-sonnet-4)'
    )

    parser.add_argument(
        '--mode',
        default='container',
        choices=['knowledge_only', 'container', 'real_time'],
        help='Forecasting mode (default: container)'
    )

    # Output control
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Save results to JSON file (default: temporal_analysis/<question_id>.json)'
    )

    parser.add_argument(
        '--no-viz',
        action='store_true',
        help='Skip visualization generation'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output'
    )

    return parser.parse_args()


def ensure_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC if naive).

    Args:
        dt: Datetime to check

    Returns:
        Timezone-aware datetime
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_context_timeline(
    question: Question,
    db: GenericDatabase
) -> List[Tuple[datetime, int, str]]:
    """Get timeline of when context items become available.

    Args:
        question: Question to analyze
        db: Database instance

    Returns:
        List of (timestamp, cumulative_count, item_type) tuples, sorted by time
    """
    timeline = []

    # Get all related events via question.related_event_ids
    if question.related_event_ids:
        for event_id in question.related_event_ids:
            event = db.get(Event, event_id)
            if event and event.occurred_date:
                timeline.append((ensure_aware(event.occurred_date), 'event', event.id))

    # Get target event if it exists
    if question.target_event_id:
        event = db.get(Event, question.target_event_id)
        if event and event.occurred_date:
            timeline.append((ensure_aware(event.occurred_date), 'event', event.id))

    # Get all articles and filter for those related to this question
    all_articles = db.get_many(Article)
    question_articles = [
        a for a in all_articles
        if 'related_question_ids' in a.metadata
        and question.id in a.metadata['related_question_ids']
    ]

    for article in question_articles:
        if article.published_date:
            timeline.append((ensure_aware(article.published_date), 'article', article.id))

    # Sort by timestamp
    timeline.sort(key=lambda x: x[0])

    # Add cumulative counts
    result = []
    for i, (timestamp, item_type, item_id) in enumerate(timeline):
        cumulative_count = i + 1
        result.append((timestamp, cumulative_count, item_type))

    return result


def calculate_forecast_points(
    question: Question,
    db: GenericDatabase,
    num_points: int,
    min_context_items: int
) -> List[Dict[str, Any]]:
    """Calculate optimal forecast points along the timeline.

    Args:
        question: Question to analyze
        db: Database instance
        num_points: Number of forecast points to generate
        min_context_items: Minimum context items for first forecast

    Returns:
        List of forecast point dictionaries with simulated_date and context_count
    """
    # Get context timeline
    timeline = get_context_timeline(question, db)

    if len(timeline) < min_context_items:
        raise ValueError(
            f"Question {question.id} has only {len(timeline)} context items, "
            f"but {min_context_items} required"
        )

    # Filter to events before resolution
    valid_timeline = [
        (ts, count, item_type) for ts, count, item_type in timeline
        if ts < question.resolution_date
    ]

    if len(valid_timeline) < min_context_items:
        raise ValueError(
            f"Question {question.id} has only {len(valid_timeline)} context items "
            f"before resolution, but {min_context_items} required"
        )

    # Calculate forecast points
    forecast_points = []

    # Find indices where we have enough context
    valid_indices = [i for i in range(len(valid_timeline)) if valid_timeline[i][1] >= min_context_items]

    if not valid_indices:
        raise ValueError(f"No valid forecast points found with {min_context_items}+ context items")

    # Distribute forecast points evenly across valid timeline
    if num_points <= len(valid_indices):
        # Use evenly spaced points
        step = len(valid_indices) // num_points
        selected_indices = [valid_indices[i * step] for i in range(num_points)]
    else:
        # Use all available points
        selected_indices = valid_indices
        logger.warning(
            f"Requested {num_points} points but only {len(valid_indices)} available. "
            f"Using all {len(valid_indices)} points."
        )

    # Create forecast points
    for idx in selected_indices:
        timestamp, context_count, item_type = valid_timeline[idx]
        forecast_points.append({
            'simulated_date': timestamp,
            'context_count': context_count,
            'days_before_resolution': (question.resolution_date - timestamp).days
        })

    return forecast_points


def run_single_temporal_forecast(
    question: Question,
    simulated_date: datetime,
    context_count: int,
    db: GenericDatabase,
    config,
    args,
    evaluator: ForecastEvaluator
) -> Dict[str, Any]:
    """Run forecast at a specific point in time.

    Args:
        question: Question to forecast
        simulated_date: Simulated current date
        context_count: Number of context items available at this time
        db: Database instance
        config: Configuration object
        args: Command line arguments
        evaluator: ForecastEvaluator instance

    Returns:
        Dict with forecast results and evaluation
    """
    try:
        if args.verbose:
            print(f"\n  Simulated Date: {simulated_date.date()}")
            print(f"  Context Available: {context_count} items")

        # Create agent
        agent = AgentFactory.create_forecast_agent(
            question=question,
            simulated_date=simulated_date.isoformat(),
            knowledge_cutoff=args.knowledge_cutoff,
            config=config,
            max_steps=args.max_steps,
            mode=args.mode
        )

        # Run agent
        result = agent.run(
            "Use the get_question tool to see what you need to forecast, then try to answer it."
        )

        # Get the forecast that was just submitted
        # Filter by timestamp to get only forecasts created in this run
        all_forecasts = db.get_many(Forecast, filters={'question_id': question.id})

        # Find most recent forecast (created in last few seconds)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
        recent_forecasts = [
            f for f in all_forecasts
            if f.timestamp > recent_cutoff
        ]

        if not recent_forecasts:
            logger.warning(f"No recent forecast found for {question.id}")
            return {
                'simulated_date': simulated_date.isoformat(),
                'context_count': context_count,
                'status': 'error',
                'error': 'No forecast created'
            }

        # Get most recent
        forecast = max(recent_forecasts, key=lambda f: f.timestamp)

        # Evaluate immediately
        evaluation = evaluator.evaluate_forecast(forecast, question)

        if args.verbose:
            status = "CORRECT" if evaluation.is_correct else "INCORRECT"
            print(f"  Result: {status}")
            print(f"  Confidence: {evaluation.confidence:.1%}")
            if evaluation.brier_score is not None:
                print(f"  Brier Score: {evaluation.brier_score:.4f}")

        return {
            'simulated_date': simulated_date.isoformat(),
            'context_count': context_count,
            'days_before_resolution': (question.resolution_date - simulated_date).days,
            'forecast_id': forecast.id,
            'status': 'success',
            'evaluation': {
                'is_correct': evaluation.is_correct,
                'accuracy': evaluation.accuracy,
                'brier_score': evaluation.brier_score,
                'log_score': evaluation.log_score,
                'confidence': evaluation.confidence,
                'prediction': evaluation.prediction,
                'ground_truth': evaluation.ground_truth,
            },
            'metadata': evaluation.evaluation_metadata
        }

    except Exception as e:
        logger.error(f"Error in temporal forecast at {simulated_date}: {e}", exc_info=True)
        return {
            'simulated_date': simulated_date.isoformat(),
            'context_count': context_count,
            'status': 'error',
            'error': str(e)
        }


def print_header(title: str, width: int = 80):
    """Print a formatted header."""
    print("=" * width)
    print(title)
    print("=" * width)


def print_results_summary(results: List[Dict[str, Any]]):
    """Print summary of temporal forecast results.

    Args:
        results: List of temporal forecast results
    """
    print_header("TEMPORAL FORECAST ANALYSIS RESULTS")

    successful = [r for r in results if r['status'] == 'success']

    if not successful:
        print("\nNo successful forecasts to analyze!")
        return

    print(f"\nTotal Forecast Points: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(results) - len(successful)}")

    print("\n" + "-" * 80)
    print(f"{'Date':<12} {'Context':<10} {'Days Left':<12} {'Correct':<10} {'Confidence':<12} {'Brier':<10}")
    print("-" * 80)

    for result in results:
        if result['status'] != 'success':
            date_str = result['simulated_date'][:10]
            print(f"{date_str:<12} {'N/A':<10} {'N/A':<12} {'ERROR':<10} {'N/A':<12} {'N/A':<10}")
            continue

        date_str = result['simulated_date'][:10]
        context = f"{result['context_count']} items"
        days_left = f"{result['days_before_resolution']} days"
        correct = "YES" if result['evaluation']['is_correct'] else "NO"
        confidence = f"{result['evaluation']['confidence']:.1%}"
        brier = f"{result['evaluation']['brier_score']:.4f}" if result['evaluation']['brier_score'] is not None else "N/A"

        print(f"{date_str:<12} {context:<10} {days_left:<12} {correct:<10} {confidence:<12} {brier:<10}")

    print("-" * 80)

    # Calculate progression metrics
    if len(successful) > 1:
        first = successful[0]
        last = successful[-1]

        print("\nProgression Analysis:")
        print(f"  Context Growth: {first['context_count']} -> {last['context_count']} items")
        print(f"  Confidence Change: {first['evaluation']['confidence']:.1%} -> {last['evaluation']['confidence']:.1%}")

        if first['evaluation']['brier_score'] and last['evaluation']['brier_score']:
            brier_change = last['evaluation']['brier_score'] - first['evaluation']['brier_score']
            direction = "improved" if brier_change < 0 else "worsened"
            print(f"  Brier Score Change: {brier_change:+.4f} ({direction})")

    print("\n" + "=" * 80)


def generate_visualization(
    results: List[Dict[str, Any]],
    question: Question,
    output_path: Path
):
    """Generate visualization of temporal progression.

    Args:
        results: List of temporal forecast results
        question: Question analyzed
        output_path: Path to save figure
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
    except ImportError:
        print("WARNING: matplotlib not installed. Skipping visualization.")
        print("Install with: uv sync --group viz")
        return

    successful = [r for r in results if r['status'] == 'success']
    if len(successful) < 2:
        print("WARNING: Need at least 2 successful forecasts for visualization")
        return

    # Extract data
    dates = [datetime.fromisoformat(r['simulated_date']) for r in successful]
    context_counts = [r['context_count'] for r in successful]
    confidences = [r['evaluation']['confidence'] for r in successful]
    is_correct = [r['evaluation']['is_correct'] for r in successful]
    brier_scores = [r['evaluation']['brier_score'] for r in successful if r['evaluation']['brier_score'] is not None]

    # Create figure with subplots
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10))

    # Plot 1: Context availability over time
    ax1.plot(dates, context_counts, marker='o', linewidth=2, markersize=8, color='#3498db')
    ax1.fill_between(dates, context_counts, alpha=0.3, color='#3498db')
    ax1.set_ylabel('Context Items Available', fontsize=11)
    ax1.set_title(f'Temporal Forecast Progression: {question.id}', fontsize=13, fontweight='bold')
    ax1.grid(alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))

    # Plot 2: Confidence over time (color by correctness)
    colors = ['#2ecc71' if correct else '#e74c3c' for correct in is_correct]
    ax2.scatter(dates, confidences, c=colors, s=100, alpha=0.7, edgecolors='black', linewidth=1)
    ax2.plot(dates, confidences, linewidth=2, alpha=0.5, color='#7f8c8d')
    ax2.set_ylabel('Forecast Confidence', fontsize=11)
    ax2.set_ylim([0, 1.05])
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#2ecc71', label='Correct'),
        Patch(facecolor='#e74c3c', label='Incorrect')
    ]
    ax2.legend(handles=legend_elements, loc='upper right')

    # Plot 3: Brier score over time (if available)
    if brier_scores and len(brier_scores) > 1:
        ax3.plot(dates[:len(brier_scores)], brier_scores, marker='s', linewidth=2, markersize=8, color='#e67e22')
        ax3.fill_between(dates[:len(brier_scores)], brier_scores, alpha=0.3, color='#e67e22')
        ax3.set_ylabel('Brier Score (lower=better)', fontsize=11)
        ax3.set_xlabel('Simulated Date', fontsize=11)
        ax3.grid(alpha=0.3)
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    else:
        ax3.text(0.5, 0.5, 'Insufficient Brier Score Data',
                ha='center', va='center', transform=ax3.transAxes, fontsize=12)
        ax3.set_xlabel('Simulated Date', fontsize=11)

    # Rotate x-axis labels
    for ax in [ax1, ax2, ax3]:
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    plt.tight_layout()

    # Save figure
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_path}")
    plt.close()


def main():
    """Main entry point."""
    args = parse_args()

    print_header("TEMPORAL FORECAST ANALYSIS - Single Question Progression")

    # Load configuration
    config = get_config()
    if args.model:
        config.llm.model = args.model
        logger.info(f"Using model: {args.model}")

    # Initialize database
    db = GenericDatabase(args.db)

    # Load question
    question = db.get(Question, args.question_id)
    if not question:
        print(f"\nERROR: Question {args.question_id} not found in database")
        return

    if question.ground_truth is None:
        print(f"\nERROR: Question {args.question_id} is not resolved (no ground truth)")
        print("This analysis requires a resolved question for evaluation")
        return

    print(f"\nQuestion: {question.question_text}")
    print(f"Resolution Date: {question.resolution_date.date()}")
    print(f"Ground Truth: {question.ground_truth}")

    # Calculate forecast points
    print(f"\nCalculating {args.num_points} forecast points along timeline...")
    try:
        forecast_points = calculate_forecast_points(
            question=question,
            db=db,
            num_points=args.num_points,
            min_context_items=args.min_context_items
        )
    except ValueError as e:
        print(f"\nERROR: {e}")
        return

    print(f"Generated {len(forecast_points)} forecast points")

    # Initialize evaluator
    evaluator = ForecastEvaluator(db_path=args.db)

    # Run forecasts at each point
    print(f"\nRunning forecasts at {len(forecast_points)} temporal points...")
    print("This may take several minutes.\n")

    results = []
    for i, point in enumerate(forecast_points, 1):
        print(f"[{i}/{len(forecast_points)}] Point {i}:")

        result = run_single_temporal_forecast(
            question=question,
            simulated_date=point['simulated_date'],
            context_count=point['context_count'],
            db=db,
            config=config,
            args=args,
            evaluator=evaluator
        )
        results.append(result)

    # Print summary
    print()
    print_results_summary(results)

    # Save results to JSON
    output_data = {
        'analysis_info': {
            'question_id': args.question_id,
            'question_text': question.question_text,
            'resolution_date': question.resolution_date.isoformat(),
            'ground_truth': question.ground_truth,
            'model': args.model or config.llm.model,
            'knowledge_cutoff': args.knowledge_cutoff,
            'num_points': len(results),
            'mode': args.mode
        },
        'results': results
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = Path('temporal_analysis')
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{args.question_id}.json"

    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")

    # Generate visualization
    if not args.no_viz:
        viz_path = output_path.with_suffix('.png')
        generate_visualization(results, question, viz_path)

    print("\nTemporal analysis complete!")


if __name__ == "__main__":
    main()
