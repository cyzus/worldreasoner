"""Example: Evaluate forecasts.

This script demonstrates how to evaluate forecasts against ground truth.
It uses the reporting module to display results.
"""

import argparse
from src.core.database import GenericDatabase
from src.domain.models import Forecast, Question
from src.domain.evaluation.evaluator import ForecastEvaluator
from src.domain.evaluation.reporting import print_evaluation_result, print_summary_report

def main():
    parser = argparse.ArgumentParser(description="Evaluate forecasts")
    parser.add_argument("--db", default=":memory:", help="Database path (default: :memory:)")
    parser.add_argument("--forecast-id", help="Result to evaluate")
    args = parser.parse_args()

    db = GenericDatabase(args.db)
    evaluator = ForecastEvaluator(db.db_path)

    if args.forecast_id:
        # Evaluate single
        forecast = db.get(Forecast, args.forecast_id)
        if not forecast:
            print(f"Forecast {args.forecast_id} not found")
            return
            
        question = db.get(Question, forecast.question_id)
        result = evaluator.evaluate_forecast(forecast, question)
        print_evaluation_result(result, verbose=True)
    else:
        # Evaluate all
        results = evaluator.evaluate_all_resolved()
        if results:
            report = evaluator.generate_evaluation_report(results)
            print_summary_report(report)
        else:
            print("No resolved forecasts found to evaluate.")

if __name__ == "__main__":
    main()
