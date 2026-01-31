"""Example: Run a single forecast.

Demonstrates running the forecast agent on a question.
"""

import argparse
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.config import get_config
from src.agents.factory import AgentFactory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-id", help="Existing question ID")
    parser.add_argument("--db", default=":memory:", help="Database path")
    args = parser.parse_args()

    db = GenericDatabase(args.db)
    
    if args.question_id:
        question = db.get(Question, args.question_id)
    else:
        # Realistic mock question from worldreasoner.db
        print("Note: Using demo question (copied from real DB).")
        from src.domain.models import QuestionType, Domain
        from datetime import datetime, timezone
        question = Question(
            id="q_tech_20251117_003",
            question_text="Will GPT-5 be released by OpenAI before the end of 2025?",
            question_type=QuestionType.BOOLEAN,
            domain=Domain.TECHNOLOGY,
            resolution_date=datetime(2025, 12, 20, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc)
        )
        db.save(Question, question)

    if not question:
        print("Question not found.")
        return

    # Run Agent
    factory = AgentFactory()
    agent = factory.create_forecast_agent(
        question=question,
        config=get_config(),
        mode="container" # or knowledge_only
    )
    
    print(f"Forecasting: {question.question_text}")
    print("-" * 50)
    result = agent.run("Make a forecast")
    print(result)

if __name__ == "__main__":
    main()
