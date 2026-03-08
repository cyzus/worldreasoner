"""Reporting utilities for forecast evaluation."""

from typing import Dict, Any
from src.domain.evaluation.evaluator import EvaluationResult


def print_header(title: str, width: int = 80):
    """Print a formatted header."""
    print("=" * width)
    print(title)
    print("=" * width)


def print_evaluation_result(result: EvaluationResult, verbose: bool = False):
    """Print a single evaluation result.

    Args:
        result: EvaluationResult object
        verbose: Whether to show detailed information
    """
    status = "CORRECT" if result.is_correct else "INCORRECT"
    print(f"\\nForecast {result.forecast_id}: {status}")
    print(f"  Question: {result.question_id}")
    print(f"  Prediction: {result.prediction} (confidence: {result.confidence:.2%})")
    print(f"  Ground Truth: {result.ground_truth}")
    print(f"  Accuracy: {result.accuracy}")

    if result.brier_score is not None:
        print(f"  Brier Score: {result.brier_score:.4f} (lower is better)")

    if result.log_score is not None:
        print(f"  Log Score: {result.log_score:.4f} (higher is better)")

    if verbose and result.evaluation_metadata:
        print("  Metadata:")
        for key, value in result.evaluation_metadata.items():
            print(f"    {key}: {value}")


def print_summary_report(report: Dict[str, Any]):
    """Print a summary evaluation report.

    Args:
        report: Report dict from ForecastEvaluator.generate_evaluation_report()
    """
    print_header("EVALUATION SUMMARY")

    print(f"\\nTotal Forecasts Evaluated: {report['total_forecasts']}")
    print(f"Overall Accuracy: {report['overall_accuracy']:.2%}")

    if report.get("avg_brier_score") is not None:
        print(f"Average Brier Score: {report['avg_brier_score']:.4f} (lower is better)")

    if report.get("avg_log_score") is not None:
        print(f"Average Log Score: {report['avg_log_score']:.4f} (higher is better)")

    # By question type
    if report.get("by_question_type"):
        print("\\nBreakdown by Question Type:")
        print("-" * 60)
        for qtype, stats in report["by_question_type"].items():
            print(f"\\n{qtype.upper()}:")
            print(f"  Count: {stats['count']}")
            print(f"  Accuracy: {stats['accuracy']:.2%}")
            if stats.get("avg_brier_score") is not None:
                print(f"  Avg Brier Score: {stats['avg_brier_score']:.4f}")

    # Calibration
    if report.get("calibration"):
        cal = report["calibration"]
        print("\\nCalibration Analysis (Boolean Questions):")
        print("-" * 60)
        print(f"Mean Calibration Error: {cal['mean_calibration_error']:.4f}")

    print("\\n" + "=" * 80)


def print_benchmark_report(report: Dict[str, Any]):
    """Print benchmark report to console.

    Args:
        report: Report dictionary
    """
    print_header("BENCHMARK EVALUATION RESULTS")

    # Model information
    if "model_info" in report:
        print("\\nModel Configuration:")
        print("-" * 60)
        model_info = report["model_info"]
        print(f"  Model: {model_info.get('model', 'Unknown')}")
        print(f"  Max Steps: {model_info.get('max_steps', 'N/A')}")

    # Execution info
    if "benchmark_info" in report:
        print("\\nExecution Info:")
        print("-" * 60)
        bench_info = report["benchmark_info"]
        print(f"  Duration: {bench_info.get('duration_seconds', 0):.1f} seconds")

    # Results
    if "results" in report:
        print("\\nResults:")
        print("-" * 60)
        results = report["results"]
        print(f"  Total Questions: {results.get('total_questions', 0)}")
        print(f"  Successful: {results.get('successful', 0)}")
        print(f"  Failed: {results.get('failed', 0)}")

        if results.get("successful", 0) > 0:
            print(f"\\n  Overall Accuracy: {results.get('overall_accuracy', 0):.2%}")
            if results.get("avg_brier_score") is not None:
                print(f"  Average Brier Score: {results['avg_brier_score']:.4f}")

    print("\\n" + "=" * 80)
