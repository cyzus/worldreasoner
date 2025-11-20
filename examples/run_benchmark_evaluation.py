"""
Benchmark evaluation script - runs forecasts on all questions and generates summary.

This script:
1. Finds all resolved questions in the database
2. Runs the forecast agent on each question
3. Evaluates each forecast immediately
4. Generates a comprehensive summary report with LLM model info

Prerequisites:
1. Set up config/local.yaml with LLM API keys
2. Have resolved questions in the database (with ground_truth)
3. MCP server running (default: http://127.0.0.1:8110/mcp)

Usage:
    # Run benchmark on all resolved questions
    python examples/run_benchmark_evaluation.py

    # Use specific model
    python examples/run_benchmark_evaluation.py --model gpt-4

    # Custom knowledge cutoff and offset
    python examples/run_benchmark_evaluation.py --knowledge-cutoff 2024-05-01 --offset-days 7

    # Save detailed results to JSON
    python examples/run_benchmark_evaluation.py --output benchmark_results.json

    # Limit number of questions (for testing)
    python examples/run_benchmark_evaluation.py --max-questions 5

The script will generate a summary showing:
- Overall accuracy, Brier score, log score
- Breakdown by question type
- Breakdown by difficulty level
- Calibration analysis
- Model information
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from src.core.database import GenericDatabase
from src.domain.models import Question, Forecast
from src.agents.factory import AgentFactory
from src.config import get_config
from src.domain.evaluation import ForecastEvaluator
from src.utils.logging import logger


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run benchmark evaluation on all resolved questions"
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
        '--min-context-items',
        type=int,
        default=3,
        help='Minimum context items needed before forecasting (default: 3)'
    )

    parser.add_argument(
        '--offset-days',
        type=int,
        default=0,
        help='Days before resolution to simulate forecast (default: 0)'
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
        help='Override LLM model (e.g., gpt-4, claude-sonnet-4, gemini-pro)'
    )

    parser.add_argument(
        '--knowledge-only',
        action='store_true',
        help='Disable research tools (only allow get_question and submit_forecast). Tests inherent LLM knowledge without external information.'
    )

    # Execution control
    parser.add_argument(
        '--max-questions',
        type=int,
        default=None,
        help='Maximum number of questions to evaluate (default: all)'
    )

    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip questions that already have forecasts'
    )

    # Output control
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Override default output path (default: benchmarks/benchmark_<timestamp>_<model>.json)'
    )

    parser.add_argument(
        '--no-save',
        action='store_true',
        help='Do not save JSON report (only print to console)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output for each forecast'
    )

    return parser.parse_args()


def print_header(title: str, width: int = 80):
    """Print a formatted header."""
    print("=" * width)
    print(title)
    print("=" * width)


def get_resolved_questions(db: GenericDatabase, min_context_items: int = 3) -> List[Question]:
    """Get all resolved questions with sufficient context.

    Args:
        db: Database instance
        min_context_items: Minimum context items required

    Returns:
        List of resolved questions with sufficient context
    """
    all_questions = db.get_many(Question)

    # Filter for resolved questions with ground truth
    resolved = []
    for question in all_questions:
        if question.ground_truth is None:
            continue

        # Check if question has sufficient context
        try:
            window_start, window_end = question.get_forecast_context_window(
                db=db,
                min_context_items=min_context_items
            )
            resolved.append(question)
        except ValueError:
            # Question doesn't have enough context, skip
            logger.debug(f"Skipping question {question.id}: insufficient context")
            continue

    return resolved


def check_existing_forecast(db: GenericDatabase, question_id: str) -> bool:
    """Check if a forecast already exists for this question.

    Args:
        db: Database instance
        question_id: Question ID to check

    Returns:
        True if forecast exists
    """
    forecasts = db.get_many(Forecast, filters={'question_id': question_id})
    return len(forecasts) > 0


def run_single_forecast(
    question: Question,
    db: GenericDatabase,
    config,
    args,
    evaluator: ForecastEvaluator
) -> Dict[str, Any]:
    """Run forecast on a single question and evaluate.

    Args:
        question: Question to forecast
        db: Database instance
        config: Configuration object
        args: Command line arguments
        evaluator: ForecastEvaluator instance

    Returns:
        Dict with forecast results and evaluation
    """
    try:
        # Prepare forecast
        forecast_setup = question.prepare_forecast(
            db=db,
            offset_days_before_resolution=args.offset_days,
            min_context_items=args.min_context_items
        )

        if args.verbose:
            print(f"\nQuestion: {question.id}")
            print(f"  Text: {question.question_text[:100]}...")
            print(f"  Type: {question.question_type.value}")
            print(f"  Simulated Date: {forecast_setup['simulated_date'].date()}")

        # Create agent
        agent = AgentFactory.create_forecast_agent(
            question=question,
            simulated_date=forecast_setup['simulated_date'].isoformat(),
            knowledge_cutoff=args.knowledge_cutoff,
            config=config,
            max_steps=args.max_steps,
            knowledge_only=args.knowledge_only
        )

        # Run agent
        result = agent.run(
            "Use the get_question tool to see what you need to forecast, then try to answer it."
        )

        # Get the forecast that was just submitted
        forecasts = db.get_many(Forecast, filters={'question_id': question.id})
        if not forecasts:
            logger.warning(f"No forecast found for question {question.id}")
            return {
                'question_id': question.id,
                'status': 'error',
                'error': 'No forecast created'
            }

        # Get most recent forecast
        forecast = max(forecasts, key=lambda f: f.timestamp)

        # Evaluate immediately
        evaluation = evaluator.evaluate_forecast(forecast, question)

        # Update forecast with evaluation
        evaluator.update_forecast_with_evaluation(forecast, evaluation)

        if args.verbose:
            status = "CORRECT" if evaluation.is_correct else "INCORRECT"
            print(f"  Result: {status}")
            brier_str = f"{evaluation.brier_score:.4f}" if evaluation.brier_score is not None else "N/A"
            print(f"  Brier Score: {brier_str}")

        return {
            'question_id': question.id,
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
        logger.error(f"Error forecasting question {question.id}: {e}", exc_info=True)
        return {
            'question_id': question.id,
            'status': 'error',
            'error': str(e)
        }


def generate_benchmark_report(
    results: List[Dict[str, Any]],
    config,
    args,
    start_time: datetime,
    end_time: datetime
) -> Dict[str, Any]:
    """Generate comprehensive benchmark report.

    Args:
        results: List of forecast results
        config: Configuration object
        args: Command line arguments
        start_time: When benchmark started
        end_time: When benchmark ended

    Returns:
        Comprehensive report dictionary
    """
    # Filter successful results
    successful = [r for r in results if r['status'] == 'success']
    failed = [r for r in results if r['status'] == 'error']

    if not successful:
        return {
            'total_questions': len(results),
            'successful': 0,
            'failed': len(failed),
            'message': 'No successful forecasts to evaluate'
        }

    # Overall metrics
    correct_count = sum(1 for r in successful if r['evaluation']['is_correct'])
    accuracy = correct_count / len(successful) if successful else 0.0

    brier_scores = [r['evaluation']['brier_score'] for r in successful
                    if r['evaluation']['brier_score'] is not None]
    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

    log_scores = [r['evaluation']['log_score'] for r in successful
                  if r['evaluation']['log_score'] is not None]
    avg_log = sum(log_scores) / len(log_scores) if log_scores else None

    # By question type
    by_type = {}
    for result in successful:
        # Get question from metadata
        q_id = result['question_id']
        # We need to group by type - store in metadata during run
        # For now, we'll aggregate all

    # Model information
    model_info = {
        'model': args.model or config.llm.model,
        'max_steps': args.max_steps,
        'knowledge_cutoff': args.knowledge_cutoff,
        'offset_days': args.offset_days,
        'min_context_items': args.min_context_items,
        'knowledge_only': args.knowledge_only
    }

    # Execution info
    duration = (end_time - start_time).total_seconds()

    report = {
        'benchmark_info': {
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'questions_per_minute': (len(results) / duration * 60) if duration > 0 else 0
        },
        'model_info': model_info,
        'results': {
            'total_questions': len(results),
            'successful': len(successful),
            'failed': len(failed),
            'overall_accuracy': accuracy,
            'avg_brier_score': avg_brier,
            'avg_log_score': avg_log
        },
        'detailed_results': results if args.verbose else None
    }

    return report


def print_benchmark_report(report: Dict[str, Any]):
    """Print benchmark report to console.

    Args:
        report: Report dictionary from generate_benchmark_report
    """
    print_header("BENCHMARK EVALUATION RESULTS")

    # Model information
    print("\nModel Configuration:")
    print("-" * 60)
    model_info = report['model_info']
    print(f"  Model: {model_info['model']}")
    print(f"  Max Steps: {model_info['max_steps']}")
    print(f"  Knowledge Cutoff: {model_info['knowledge_cutoff']}")
    print(f"  Forecast Offset: {model_info['offset_days']} days before resolution")
    print(f"  Min Context Items: {model_info['min_context_items']}")

    # Knowledge-only mode indicator
    if model_info.get('knowledge_only'):
        print(f"  Mode: KNOWLEDGE-ONLY (no research tools - testing inherent knowledge)")
    else:
        print(f"  Mode: FULL (with research tools - temporal_search_articles, fetch_article)")

    # Execution info
    print("\nExecution Info:")
    print("-" * 60)
    bench_info = report['benchmark_info']
    print(f"  Duration: {bench_info['duration_seconds']:.1f} seconds")
    print(f"  Throughput: {bench_info['questions_per_minute']:.2f} questions/minute")
    print(f"  Timestamp: {bench_info['timestamp']}")

    # Results
    print("\nResults:")
    print("-" * 60)
    results = report['results']
    print(f"  Total Questions: {results['total_questions']}")
    print(f"  Successful: {results['successful']}")
    print(f"  Failed: {results['failed']}")

    if results['successful'] > 0:
        print(f"\n  Overall Accuracy: {results['overall_accuracy']:.2%}")
        if results['avg_brier_score'] is not None:
            print(f"  Average Brier Score: {results['avg_brier_score']:.4f} (lower is better)")
        if results['avg_log_score'] is not None:
            print(f"  Average Log Score: {results['avg_log_score']:.4f} (higher is better)")

    print("\n" + "=" * 80)


def main():
    """Main entry point."""
    args = parse_args()

    print_header("BENCHMARK EVALUATION - Forecasting All Resolved Questions")

    # Load configuration
    config = get_config()

    # Override model if specified
    if args.model:
        config.llm.model = args.model
        logger.info(f"Using model: {args.model}")

    # Initialize database
    db = GenericDatabase(args.db)

    # Get resolved questions
    print("\nFinding resolved questions...")
    resolved_questions = get_resolved_questions(db, args.min_context_items)

    print(f"Found {len(resolved_questions)} resolved questions with sufficient context")

    if not resolved_questions:
        print("\nNo resolved questions found!")
        print("Questions need:")
        print(f"  - ground_truth set (not None)")
        print(f"  - At least {args.min_context_items} context items (articles/events)")
        return

    # Filter by existing forecasts if requested
    if args.skip_existing:
        questions_to_run = [
            q for q in resolved_questions
            if not check_existing_forecast(db, q.id)
        ]
        skipped = len(resolved_questions) - len(questions_to_run)
        print(f"Skipping {skipped} questions with existing forecasts")
        resolved_questions = questions_to_run

    # Limit number of questions if requested
    if args.max_questions:
        resolved_questions = resolved_questions[:args.max_questions]
        print(f"Limited to {len(resolved_questions)} questions")

    if not resolved_questions:
        print("\nNo questions to evaluate!")
        return

    # Initialize evaluator
    evaluator = ForecastEvaluator(db_path=args.db)

    # Run benchmark
    print(f"\nRunning benchmark on {len(resolved_questions)} questions...")
    print("This may take several minutes depending on the number of questions.")
    print()

    start_time = datetime.now(timezone.utc)
    results = []

    for i, question in enumerate(resolved_questions, 1):
        print(f"[{i}/{len(resolved_questions)}] Processing {question.id}...")

        result = run_single_forecast(
            question=question,
            db=db,
            config=config,
            args=args,
            evaluator=evaluator
        )
        results.append(result)

    end_time = datetime.now(timezone.utc)

    # Generate report
    report = generate_benchmark_report(
        results=results,
        config=config,
        args=args,
        start_time=start_time,
        end_time=end_time
    )

    # Print report
    print()
    print_benchmark_report(report)

    # Save to file (unless --no-save specified)
    if not args.no_save:
        # Determine output path
        if args.output:
            output_path = Path(args.output)
        else:
            # Auto-generate filename: benchmarks/benchmark_<timestamp>_<model>.json
            benchmarks_dir = Path('benchmarks')
            benchmarks_dir.mkdir(exist_ok=True)

            timestamp = end_time.strftime('%Y%m%d_%H%M%S')
            model_name = report['model_info']['model'].replace('/', '_')
            filename = f"benchmark_{timestamp}_{model_name}.json"
            output_path = benchmarks_dir / filename

        # Save report
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nDetailed results saved to: {output_path}")

    # Summary
    print("\nBenchmark complete!")
    successful = report['results']['successful']
    total = report['results']['total_questions']
    print(f"Successfully evaluated {successful}/{total} questions")


if __name__ == "__main__":
    main()
