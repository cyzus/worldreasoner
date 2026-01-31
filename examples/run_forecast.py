"""Example: Run a single forecast.

Demonstrates running the forecast agent on a question.
"""

import argparse
import tempfile
import os
from src.core.database import GenericDatabase
from src.domain.models import Question
from src.config import get_config
from src.agents.factory import AgentFactory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-id", help="Existing question ID")
    parser.add_argument("--db", default=":memory:", help="Database path")
    args = parser.parse_args()

    # Handle :memory: with temp file
    db_path = args.db
    cleanup_db = False
    if args.db == ":memory:":
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cleanup_db = True
        print(f"Using temp DB: {db_path}")

    db = GenericDatabase(db_path)
    db.initialize_all_tables()
    
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
            question_type=QuestionType.BINARY,
            source="example",
            difficulty=3,
            domain=Domain.TECH,
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
        mode="container", # or knowledge_only
        simulated_date="2024-01-01",
        knowledge_cutoff="2024-01-01"
    )
    
    print(f"Forecasting: {question.question_text}")
    print("-" * 50)
    result = agent.run("Make a forecast")
    print(result)

    if cleanup_db and os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except:
            pass
if __name__ == "__main__":
    main()
