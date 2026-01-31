"""Example: Deep causal analysis.

Demonstrates using the HindsightAgent to build causal graphs.
"""

import argparse
import asyncio
from src.core.database import GenericDatabase
from src.agents.hindsight_agent import HindsightAgent
from src.domain.models import Question, QuestionType, Domain
from src.pipelines.prompts import HindsightCausalAnalysisPrompts
from datetime import datetime, timezone

async def run_analysis(args):
    db = GenericDatabase(args.db)
    
    # Create or load question
    if args.question_id:
        question = db.get(Question, args.question_id)
    else:
        # Create dummy question: Using a historical event for causal analysis demo is often better
        # But we can stick to a recent one if preferred. 
        # Let's use the GPT-5 one but set it in the past for "hindsight" logic? 
        # Actually HindsightAgent usually works on past events.
        # Let's keep the Financial Crisis example as it's a perfect 'hindsight' candidate.
        print("Note: Using demo question (Historical event for Hindsight Analysis).")
        question = Question(
            id="q_hist_2008",
            question_text="Why did the 2008 financial crisis happen?",
            question_type=QuestionType.OPEN_ENDED,
            domain=Domain.ECONOMICS,
            resolution_date=datetime(2008, 9, 15, tzinfo=timezone.utc),
            ground_truth="Lehman Brothers collapse, subprime mortgage crisis, deregulation."
        )
        db.save(Question, question)

    if not question:
        print("Question not found.")
        return

    # Run Agent
    agent = HindsightAgent(db_path=args.db)
    prompts = HindsightCausalAnalysisPrompts()
    prompt = prompts.get_agent_prompt(question, min_graph_depth=2)
    
    print(f"Analyzing: {question.question_text}")
    print("-" * 50)
    result = await asyncio.to_thread(agent.run, prompt)
    print(result)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=":memory:", help="Database path")
    parser.add_argument("--question-id", help="Existing question ID")
    args = parser.parse_args()
    
    asyncio.run(run_analysis(args))

if __name__ == "__main__":
    main()
