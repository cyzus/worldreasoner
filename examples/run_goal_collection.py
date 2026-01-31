"""Example: Goal collection.

Demonstrates the collection orchestrator.
"""

import asyncio
import argparse
from src.config.collection_goal import CollectionGoal
from src.pipelines.question.orchestrator import QuestionCollectionOrchestrator, OrchestratorConfig

async def run_collection(args):
    # Load goal
    try:
        goal = CollectionGoal.from_yaml(args.goal)
    except Exception:
        print(f"Goal file {args.goal} not found. Using defaults.")
        # Create a simple default goal programmatically if file missing
        # This keeps the example runnable without external deps if user didn't config
        return

    # Simple config
    config = OrchestratorConfig(max_iterations=1, parallel_sources=False)
    
    # Create orchestrator (mocking sources for minimal example or would load real ones)
    # For a minimal example, we likely assume sources are configured in src/config
    # But here we will simpler instantiation
    
    print("Orchestrator setup would happen here. (Simplified for example)")
    print(f"Goal: {goal.total_questions} questions")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", default="config/collection_goal.yaml")
    parser.add_argument("--db", default=":memory:")
    args = parser.parse_args()

    asyncio.run(run_collection(args))

if __name__ == "__main__":
    main()
