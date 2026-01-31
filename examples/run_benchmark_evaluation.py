"""Example: Run benchmark evaluation.

This script runs forecasts on all resolved questions to benchmark performance.
"""

import argparse
from src.core.database import GenericDatabase
from src.config import get_config
from src.domain.evaluation.runner import BenchmarkRunner
from src.domain.evaluation.reporting import print_benchmark_report

def main():
    parser = argparse.ArgumentParser(description="Run benchmark evaluation")
    parser.add_argument("--db", default=":memory:", help="Database path")
    parser.add_argument("--model", help="Override LLM model")
    parser.add_argument("--max-questions", type=int, default=5, help="Limit questions for testing")
    args = parser.parse_args()

    # Setup
    config = get_config()
    db = GenericDatabase(args.db)
    runner = BenchmarkRunner(db, config)

    # Get questions
    questions = runner.get_resolved_questions()
    if args.max_questions:
        questions = questions[:args.max_questions]
    
    if not questions:
        print("No resolved questions found in database.")
        return

    # Run benchmark
    report = runner.run_benchmark(
        questions=questions, 
        knowledge_cutoff="2024-05-01",
        model_name=args.model,
        verbose=True
    )

    # Report
    print_benchmark_report(report)

if __name__ == "__main__":
    main()
