"""Example: Run evidence retrieval with seeded data.

Demonstrates how to seed the database with articles and retrieve them using tools
or the HindsightAgent.
"""

import argparse
import tempfile
import os
import asyncio
import json
from datetime import datetime, timezone
from src.core.database import GenericDatabase
from src.agents.hindsight_agent import HindsightAgent
from src.domain.models import Question, QuestionType, Domain
from src.domain.outcome_event_service import OutcomeEventService
from src.pipelines.prompts.hindsight_causal_analysis import HindsightCausalAnalysisPrompts

async def run_evidence_demo(args):
    # Handle :memory: via tempfile for cross-instance sharing
    db_path = args.db
    cleanup_db = False
    if args.db == ":memory:":
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cleanup_db = True
        print(f"Using temp DB: {db_path}")

    db = GenericDatabase(db_path)
    db.initialize_all_tables()
    
    # 1. Seed Question (Real example from worldreasoner.db)
    question_id = "q_tech_20251220_001"
    question = Question(
        id=question_id,
        question_text="Will New York enact the RAISE Act to regulate AI by the end of 2025?",
        question_type=QuestionType.BINARY,
        source="news",
        difficulty=3,
        domain=Domain.TECH,
        resolution_date=datetime(2025, 12, 20, tzinfo=timezone.utc),
        ground_truth=True # "Yes" in DB
    )
    db.save(Question, question)

    print(f"Seeded Question: {question.question_text}")

    # 2. Auto-generate Outcome Events (User request: ensure outcome events are generated)
    print("\n--- Generating Outcome Events ---")
    outcome_service = OutcomeEventService(db)
    outcome_events = outcome_service.auto_create_outcome_events(question)
    print(f"Generated {len(outcome_events)} outcome events for analysis.")
    for evt in outcome_events:
        print(f"- {evt.title} ({evt.outcome_scenario})")

    # 2. Demonstrate Agent Usage (Correctly passing question_id)
    print("\n--- Running Hindsight Agent ---")
    # Ensure question_id is passed to HindsightAgent!
    agent = HindsightAgent(db_path=db_path, question_id=question_id)
    
    
    # Task: Use Default Prompt with Outcome Events
    prompts = HindsightCausalAnalysisPrompts()
    prompt = prompts.get_agent_prompt(
        question=question,
        min_evidence_articles=2,     # Set low for demo speed
        evidence_window_days=30,     # Look back 30 days
        min_graph_depth=2,           # Shallow graph for demo
        confidence_threshold=0.5,
        outcome_events=outcome_events
    )
    
    print("Using Default Prompt (Preview):")
    print(prompt[:200].replace('\n', ' ') + "...")
    
    result = await asyncio.to_thread(agent.run, prompt)
    print(result)

    if cleanup_db and os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except:
            pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=":memory:", help="Database path")
    args = parser.parse_args()
    
    asyncio.run(run_evidence_demo(args))

if __name__ == "__main__":
    main()
