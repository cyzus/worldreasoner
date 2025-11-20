"""
CLI script to evaluate forecasts against ground truth.

This script evaluates all forecasts for resolved questions and generates
an evaluation report with accuracy, Brier scores, and calibration metrics.

Prerequisites:
1. Forecasts in the database (from run_forecast_smolagents.py)
2. Questions with ground truth set (resolved questions)

Usage:
    # Evaluate all resolved forecasts and update database
    python examples/evaluate_forecasts.py

    # Evaluate without updating database (dry run)
    python examples/evaluate_forecasts.py --no-update

    # Use custom database
    python examples/evaluate_forecasts.py --db custom.db

    # Save report to JSON file
    python examples/evaluate_forecasts.py --output report.json

    # Evaluate specific forecast
    python examples/evaluate_forecasts.py --forecast-id fcst_123
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.domain.evaluation import ForecastEvaluator
from src.core.database import GenericDatabase
from src.domain.models import Forecast, Question
from src.utils.logging import logger


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Evaluate forecasts against ground truth for resolved questions."
    )

    parser.add_argument(
        '--db',
        type=str,
        default='worldreasoner.db',
        help='Path to database file (default: worldreasoner.db)'
    )

    parser.add_argument(
        '--forecast-id',
        type=str,
        default=None,
        help='Specific forecast ID to evaluate (optional, evaluates all if not provided)'
    )

    parser.add_argument(
        '--no-update',
        action='store_true',
        help='Do not update forecast records with evaluation results (dry run)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Save evaluation report to JSON file (optional)'
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


def print_evaluation_result(result, verbose: bool = False):
    """Print a single evaluation result.

    Args:
        result: EvaluationResult object
        verbose: Whether to show detailed information
    """
    status = "CORRECT" if result.is_correct else "INCORRECT"
    print(f"\nForecast {result.forecast_id}: {status}")
    print(f"  Question: {result.question_id}")
    print(f"  Prediction: {result.prediction} (confidence: {result.confidence:.2%})")
    print(f"  Ground Truth: {result.ground_truth}")
    print(f"  Accuracy: {result.accuracy}")

    if result.brier_score is not None:
        print(f"  Brier Score: {result.brier_score:.4f} (lower is better)")

    if result.log_score is not None:
        print(f"  Log Score: {result.log_score:.4f} (higher is better)")

    if verbose and result.evaluation_metadata:
        print(f"  Metadata:")
        for key, value in result.evaluation_metadata.items():
            print(f"    {key}: {value}")


def print_summary_report(report: dict):
    """Print a summary evaluation report.

    Args:
        report: Report dict from ForecastEvaluator.generate_evaluation_report()
    """
    print_header("EVALUATION SUMMARY")

    print(f"\nTotal Forecasts Evaluated: {report['total_forecasts']}")
    print(f"Overall Accuracy: {report['overall_accuracy']:.2%}")

    if report.get('avg_brier_score') is not None:
        print(f"Average Brier Score: {report['avg_brier_score']:.4f} (lower is better)")

    if report.get('avg_log_score') is not None:
        print(f"Average Log Score: {report['avg_log_score']:.4f} (higher is better)")

    # By question type
    if report.get('by_question_type'):
        print("\nBreakdown by Question Type:")
        print("-" * 60)
        for qtype, stats in report['by_question_type'].items():
            print(f"\n{qtype.upper()}:")
            print(f"  Count: {stats['count']}")
            print(f"  Accuracy: {stats['accuracy']:.2%}")
            if stats.get('avg_brier_score') is not None:
                print(f"  Avg Brier Score: {stats['avg_brier_score']:.4f}")
            if stats.get('avg_log_score') is not None:
                print(f"  Avg Log Score: {stats['avg_log_score']:.4f}")

    # Model information
    if report.get('model_info'):
        model_info = report['model_info']
        if model_info.get('models'):
            print("\nModel Performance:")
            print("-" * 60)
            print(f"Total Unique Models: {model_info['total_unique_models']}")
            print()
            for model_name, stats in model_info['models'].items():
                version_str = f" (v{stats['version']})" if stats.get('version') else ""
                print(f"{model_name}{version_str}:")
                print(f"  Forecasts: {stats['count']}")
                print(f"  Accuracy: {stats['accuracy']:.2%}")

    # Calibration
    if report.get('calibration'):
        cal = report['calibration']
        print("\nCalibration Analysis (Boolean Questions):")
        print("-" * 60)
        print(f"Mean Calibration Error: {cal['mean_calibration_error']:.4f}")

        if cal.get('bins'):
            print("\nConfidence Bins:")
            print(f"{'Range':<15} {'Count':<10} {'Accuracy':<12} {'Cal Error':<12}")
            print("-" * 60)
            for bin_data in cal['bins']:
                conf_range = bin_data['confidence_range']
                range_str = f"{conf_range[0]:.1f}-{conf_range[1]:.1f}"
                print(
                    f"{range_str:<15} "
                    f"{bin_data['count']:<10} "
                    f"{bin_data['accuracy']:.2%}{'':>7} "
                    f"{bin_data['calibration_error']:.4f}"
                )

    print("\n" + "=" * 80)


def evaluate_single_forecast(args, evaluator):
    """Evaluate a single forecast by ID.

    Args:
        args: Parsed command line arguments
        evaluator: ForecastEvaluator instance
    """
    db = GenericDatabase(args.db)

    # Get forecast
    forecast = db.get(Forecast, args.forecast_id)
    if not forecast:
        print(f"ERROR: Forecast {args.forecast_id} not found in database")
        return

    # Get question
    question = db.get(Question, forecast.question_id)
    if not question:
        print(f"ERROR: Question {forecast.question_id} not found in database")
        return

    # Check if resolved
    if not evaluator.is_question_resolved(question):
        print(f"ERROR: Question {forecast.question_id} is not resolved yet")
        print(f"   Ground truth: {question.ground_truth}")
        print(f"   Resolution date: {question.resolution_date}")
        return

    print_header(f"EVALUATING FORECAST: {args.forecast_id}")

    # Evaluate
    try:
        result = evaluator.evaluate_forecast(forecast, question)
        print_evaluation_result(result, verbose=True)

        # Update if requested
        if not args.no_update:
            evaluator.update_forecast_with_evaluation(forecast, result)
            print(f"\nForecast updated in database")

    except Exception as e:
        print(f"ERROR: Error evaluating forecast: {e}")
        logger.error(f"Error evaluating forecast {args.forecast_id}: {e}", exc_info=True)


def evaluate_all_forecasts(args, evaluator):
    """Evaluate all forecasts for resolved questions.

    Args:
        args: Parsed command line arguments
        evaluator: ForecastEvaluator instance
    """
    print_header("BATCH EVALUATION OF ALL RESOLVED FORECASTS")

    # Evaluate all
    update_forecasts = not args.no_update
    results = evaluator.evaluate_all_resolved(update_forecasts=update_forecasts)

    if not results:
        print("\nERROR: No forecasts to evaluate")
        print("   This could mean:")
        print("   - No forecasts in database")
        print("   - No questions have been resolved yet (ground_truth not set)")
        return

    # Print individual results if verbose
    if args.verbose:
        print("\nIndividual Results:")
        print("-" * 80)
        for result in results:
            print_evaluation_result(result, verbose=False)

    # Generate and print summary report
    report = evaluator.generate_evaluation_report(results)
    print()
    print_summary_report(report)

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {output_path}")

    # Status message
    if not args.no_update:
        print(f"\nUpdated {len(results)} forecast records in database")
    else:
        print(f"\nWARNING: Dry run - forecast records NOT updated (use without --no-update to save)")


def main():
    """Main entry point."""
    args = parse_args()

    # Initialize evaluator
    evaluator = ForecastEvaluator(db_path=args.db)

    # Evaluate single forecast or all
    if args.forecast_id:
        evaluate_single_forecast(args, evaluator)
    else:
        evaluate_all_forecasts(args, evaluator)


if __name__ == "__main__":
    main()
