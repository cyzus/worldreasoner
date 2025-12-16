"""
CLI script to run forecasting with ForecastAgent.

This script demonstrates how to run the ForecastAgent to make predictions
about future outcomes with temporally-constrained context.

Prerequisites:
1. Set up config/local.yaml with LLM API keys
2. Have questions in the database (from Question Pipeline)
3. MCP server running (default: http://127.0.0.1:8110/mcp)

Usage:
    # Run with randomly selected question
    python examples/run_forecast_smolagents.py

    # Run with specific question ID
    python examples/run_forecast_smolagents.py --question-id q_tech_20251117_003_5c55a8f1

    # Specify custom database
    python examples/run_forecast_smolagents.py --db custom.db

    # Custom context thresholds
    python examples/run_forecast_smolagents.py --min-context-items 5 --offset-days 7

    # Custom knowledge cutoff date and verbose output
    python examples/run_forecast_smolagents.py --knowledge-cutoff 2024-05-01 --verbose

    # Skip immediate evaluation for resolved questions
    python examples/run_forecast_smolagents.py --no-evaluate

The agent automatically calculates valid forecast windows based on context availability
and ensures temporal consistency with knowledge cutoffs.

If the question is already resolved (has ground truth), the forecast will be
automatically evaluated and results displayed immediately.
"""

import argparse
from src.core.database import GenericDatabase
from src.domain.models import Question, Forecast
from src.agents.factory import AgentFactory
from src.config import get_config
from src.domain.evaluation import ForecastEvaluator


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run ForecastAgent for making temporally-aware predictions."
    )

    # Question selection
    parser.add_argument(
        '--question-id',
        type=str,
        default=None,
        help='Question ID to forecast (optional, randomly selects one if not provided)'
    )

    # Database configuration
    parser.add_argument(
        '--db',
        type=str,
        default='worldreasoner.db',
        help='Path to database file (default: worldreasoner.db)'
    )

    # Temporal configuration
    parser.add_argument(
        '--knowledge-cutoff',
        type=str,
        default='2024-05-01',
        help='LLM training cutoff date (YYYY-MM-DD, default: 2024-05-01)'
    )

    # Context window configuration
    parser.add_argument(
        '--min-context-items',
        type=int,
        default=3,
        help='Minimum context items needed before forecasting (default: 3)'
    )

    parser.add_argument(
        '--offset-days',
        type=int,
        default=0,
        help='Days before resolution to simulate forecast (default: 0)'
    )

    # Agent configuration
    parser.add_argument(
        '--max-steps',
        type=int,
        default=15,
        help='Maximum agent steps (default: 15)'
    )

    parser.add_argument(
        '--mode',
        type=str,
        choices=['knowledge_only', 'container', 'real_time'],
        default='container',
        help='Forecasting mode (default: container). knowledge_only=no research tools, container=temporal research, real_time=live information'
    )

    parser.add_argument(
        '--test-db',
        type=str,
        default=None,
        help='Path to test database for storing forecasts (optional)'
    )

    # Output control
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output'
    )

    # Evaluation control
    parser.add_argument(
        '--no-evaluate',
        action='store_true',
        help='Skip immediate evaluation even if question is resolved'
    )

    return parser.parse_args()


def select_random_question(db: GenericDatabase, min_context_items: int = 3) -> Question:
    """Randomly select a question with sufficient context for forecasting.

    Args:
        db: Database instance
        min_context_items: Minimum number of context items required

    Returns:
        Randomly selected Question

    Raises:
        ValueError: If no suitable questions found
    """
    import random

    # Get all questions
    all_questions = db.get_many(Question)

    if not all_questions:
        raise ValueError("No questions found in database")

    # Filter questions that have enough context
    suitable_questions = []
    for question in all_questions:
        try:
            # Try to get forecast window - will fail if insufficient context
            window_start, window_end = question.get_forecast_context_window(
                db=db,
                min_context_items=min_context_items
            )
            # If we got here, question has enough context
            suitable_questions.append(question)
        except ValueError:
            # Question doesn't have enough context, skip it
            continue

    if not suitable_questions:
        raise ValueError(
            f"No questions found with at least {min_context_items} context items. "
            f"Total questions in database: {len(all_questions)}"
        )

    selected = random.choice(suitable_questions)
    print(f"\n📋 Randomly selected question: {selected.id}")
    print(f"   Found {len(suitable_questions)} suitable questions out of {len(all_questions)} total\n")

    return selected


def print_header(title: str, width: int = 80):
    """Print a formatted header."""
    print("=" * width)
    print(title)
    print("=" * width)


def print_forecast_setup(question: Question, window_start, window_end, simulated_date, args):
    """Print forecast setup information."""
    print_header("FORECAST SETUP - AUTOMATIC CONTEXT WINDOW CALCULATION")

    print(f"\nQuestion: {question.question_text}")
    print(f"Resolution date: {question.resolution_date.date()}")

    days_available = (window_end - window_start).days

    print(f"\nValid Forecast Window:")
    print(f"  Opens:      {window_start.date()} (after {args.min_context_items} context items)")
    print(f"  Closes:     {window_end.date()} (before resolution)")
    print(f"  Duration:   {days_available} days")

    print(f"\nSimulated Date (auto-calculated):")
    print(f"  Using:      {simulated_date.date()}")
    print(f"  Strategy:   {args.offset_days} days before resolution")
    print(f"  Status:     VALID")


def print_ground_truth(question: Question):
    """Print ground truth information if available.

    Args:
        question: Question object to display ground truth for
    """
    print("\n" + "=" * 80)
    print("GROUND TRUTH (Actual Outcome)")
    print("=" * 80)

    if question.ground_truth is None:
        print("\nWARNING: Ground truth not available (question may not be resolved yet)")
        print(f"Resolution date: {question.resolution_date.date()}")
        return

    # Display ground truth
    outcome = "YES" if question.ground_truth else "NO"
    print(f"\nActual Outcome: {outcome}")

    if question.context:
        print(f"\nReason:")
        # Word wrap the reason for better readability
        import textwrap
        wrapped_reason = textwrap.fill(
            question.context,
            width=78,
            initial_indent="  ",
            subsequent_indent="  "
        )
        print(wrapped_reason)
    else:
        print("\nReason: Not provided")

    print("\n" + "=" * 80)


def get_latest_forecast(db: GenericDatabase, question_id: str) -> Forecast | None:
    """Get the most recently submitted forecast for a question.

    Args:
        db: Database instance
        question_id: Question ID to find forecast for

    Returns:
        Most recent Forecast or None if not found
    """
    all_forecasts = db.get_many(Forecast, filters={'question_id': question_id})
    if not all_forecasts:
        return None

    # Sort by timestamp descending
    all_forecasts.sort(key=lambda f: f.timestamp, reverse=True)
    return all_forecasts[0]


def evaluate_and_display_forecast(
    forecast: Forecast,
    question: Question,
    evaluator: ForecastEvaluator,
    update_db: bool = True
):
    """Evaluate a forecast and display the results.

    Args:
        forecast: Forecast to evaluate
        question: Question with ground truth
        evaluator: ForecastEvaluator instance
        update_db: Whether to update the forecast in the database
    """
    print("\n" + "=" * 80)
    print("IMMEDIATE EVALUATION (Question Already Resolved)")
    print("=" * 80)

    try:
        # Evaluate the forecast
        evaluation = evaluator.evaluate_forecast(forecast, question)

        # Display results
        status = "CORRECT" if evaluation.is_correct else "INCORRECT"
        print(f"\n{status}")
        print(f"\nYour Prediction: {evaluation.prediction} (confidence: {evaluation.confidence:.1%})")
        print(f"Actual Outcome:  {evaluation.ground_truth}")
        print(f"\nAccuracy: {evaluation.accuracy:.1%}")

        if evaluation.brier_score is not None:
            print(f"Brier Score: {evaluation.brier_score:.4f} (0=perfect, 1=worst)")

        if evaluation.log_score is not None:
            print(f"Log Score:   {evaluation.log_score:.4f} (higher is better)")

        # Show forecast horizon
        if evaluation.evaluation_metadata.get('forecast_horizon_days'):
            horizon = evaluation.evaluation_metadata['forecast_horizon_days']
            print(f"\nForecast Horizon: {horizon} days ahead")

        # Update database if requested
        if update_db:
            evaluator.update_forecast_with_evaluation(forecast, evaluation)
            print(f"\nEvaluation saved to database")

        print("\n" + "=" * 80)

    except Exception as e:
        print(f"\nERROR: Error evaluating forecast: {e}")
        import traceback
        traceback.print_exc()


def run_forecast(args):
    """Run the forecast agent with provided arguments.

    Args:
        args: Parsed command line arguments
    """
    # Load configuration
    config = get_config()
    # Load question from database
    db = GenericDatabase(args.db)

    # Get question - either by ID or random selection
    if args.question_id:
        question = db.get(Question, args.question_id)
        if not question:
            raise ValueError(f"Question {args.question_id} not found in database")
    else:
        # Randomly select a question with sufficient context
        question = select_random_question(db, min_context_items=args.min_context_items)

    # Prepare forecast - this handles all the complexity internally
    try:
        forecast_setup = question.prepare_forecast(
            db=db,
            offset_days_before_resolution=args.offset_days,
            min_context_items=args.min_context_items
        )

        # Print setup information
        if args.verbose:
            print_forecast_setup(
                question, 
                forecast_setup['window_start'], 
                forecast_setup['window_end'], 
                forecast_setup['simulated_date'], 
                args
            )

    except ValueError as e:
        print(f"\nERROR: {e}")
        print("\nThis may indicate:")
        print("  - Not enough context items in database")
        print("  - Evidence collected after resolution (data quality issue)")
        print("  - Question has no related events/articles")
        raise

    # Start forecast agent
    print_header("STARTING FORECAST AGENT")

    # Create agent using factory
    agent = AgentFactory.create_forecast_agent(
        question=question,
        simulated_date=forecast_setup['simulated_date'].isoformat(),
        knowledge_cutoff=args.knowledge_cutoff,
        config=config,
        db_path=args.test_db,
        mode=args.mode,
        max_steps=args.max_steps
    )

    # The agent now works in a temporally-constrained environment
    # - Knowledge cutoff: No info after LLM training date
    # - Simulated date: "Current time" for the forecast (auto-calculated)
    # - All tools automatically respect these temporal constraints

    print(f"\nKnowledge cutoff: {args.knowledge_cutoff}")
    print(f"Simulated date: {forecast_setup['simulated_date'].date()}")
    print(f"Max steps: {args.max_steps}\n")

    # Run the agent
    result = agent.run(
        "Use the get_question tool to see what you need to forecast, then try to answer it."
    )

    if args.verbose:
        print("\n" + "=" * 80)
        print("FORECAST RESULT")
        print("=" * 80)
        print(result)

    # Check if question is resolved and evaluate immediately if requested
    if question.ground_truth is not None and not args.no_evaluate:
        print("\nQuestion is already resolved - evaluating forecast immediately...")

        # Get the forecast that was just submitted
        forecast = get_latest_forecast(db, question.id)

        if forecast:
            # Initialize evaluator
            evaluator = ForecastEvaluator(db_path=args.db)

            # Evaluate and display results
            evaluate_and_display_forecast(
                forecast=forecast,
                question=question,
                evaluator=evaluator,
                update_db=True
            )
        else:
            print("WARNING: Could not find submitted forecast for evaluation")

    # Display ground truth if available (even if we already evaluated)
    if question.ground_truth is not None:
        print_ground_truth(question)


def main():
    """Main entry point."""
    args = parse_args()
    run_forecast(args)


if __name__ == "__main__":
    main()
