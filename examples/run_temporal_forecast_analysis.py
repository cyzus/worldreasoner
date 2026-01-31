"""Example: Temporal forecast analysis.

Analyzes how forecast accuracy changes as the resolution date approaches.
"""

import argparse
import json
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.config import get_config
from src.domain.evaluation.temporal import TemporalAnalyzer
from src.domain.evaluation.runner import BenchmarkRunner

def main():
    parser = argparse.ArgumentParser(description="Run temporal analysis")
    parser.add_argument("--question-id", required=True, help="Question ID")
    parser.add_argument("--db", default=":memory:", help="Database path")
    args = parser.parse_args()

    db = GenericDatabase(args.db)
    question = db.get(Question, args.question_id)
    
    if not question:
        print("Question not found")
        return

    # Calculate points
    analyzer = TemporalAnalyzer(db)
    points = analyzer.calculate_forecast_points(question)
    
    # Run forecasts
    runner = BenchmarkRunner(db, get_config())
    results = []
    
    print(f"Running forecasts at {len(points)} temporal points...")
    for point in points:
        result = runner.run_single_forecast(
            question=question,
            knowledge_cutoff="2024-05-01",
            offset_days=point["days_before_resolution"],
            verbose=True
        )
        result["simulated_date"] = point["simulated_date"]
        results.append(result)

    print(json.dumps(results, indent=2, default=str))

if __name__ == "__main__":
    main()
