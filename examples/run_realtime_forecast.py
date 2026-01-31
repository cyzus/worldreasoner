"""Example: Real-time forecasting.

Runs a forecast using the 'real_time' mode which enables full web access.
"""

import argparse
from datetime import datetime, timezone
from src.config import get_config
from src.core.database import GenericDatabase
from src.domain.models import Question, QuestionType, Domain
from src.agents.forecast_agent import ForecastAgent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", help="Question text (optional)")
    parser.add_argument("--question-id", help="Use existing question from DB")
    parser.add_argument("--db", default=":memory:", help="Database path")
    args = parser.parse_args()

    db = GenericDatabase(args.db)

    if args.question_id:
        question = db.get(Question, args.question_id)
    elif args.query:
        # Create ad-hoc question from query
        question = Question(
            id="rt_adhoc",
            question_text=args.query,
            question_type=QuestionType.BOOLEAN,
            domain=Domain.GENERAL,
            resolution_date=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    else:
        # Default demo question
        print("Note: Using demo question.")
        question = Question(
            id="q_tech_20251117_003",
            question_text="Will GPT-5 be released by OpenAI before the end of 2025?",
            question_type=QuestionType.BOOLEAN,
            domain=Domain.TECHNOLOGY,
            resolution_date=datetime(2025, 12, 20, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc)
        )
        # We don't save to DB unless needed, but for agent compat it's often safer or neutral
    
    if not question:
        print("No question specified.")
        return

    # Initialize Agent
    agent = ForecastAgent(
        question=question,
        simulated_date=datetime.now(timezone.utc).isoformat(),
        knowledge_cutoff=get_config().llm.knowledge_cutoff,
        config=get_config(),
        mode="real_time", # Enables web access
        db_path=args.db
    )

    print(f"Real-time Forecast: {question.question_text}")
    print("-" * 50)
    result = agent.run(f"Forecast: {question.question_text}")
    print(result)

if __name__ == "__main__":
    main()
