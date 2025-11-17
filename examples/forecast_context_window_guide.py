"""Comprehensive guide to forecast context windows.

This script demonstrates:
1. How to calculate valid forecast windows
2. How different thresholds affect the window
3. How to validate and suggest simulated dates
4. Integration with smolagents
"""

from datetime import datetime, timezone
from src.core.database import GenericDatabase
from src.domain.models import Question


def main():
    # Initialize database
    db = GenericDatabase("worldreasoner.db")

    # Get questions
    questions = db.get_many(Question, filters={})

    # Find a question with good context for demonstration
    demo_question = None
    for q in questions:
        try:
            # Look for questions with at least 5 context items
            window = q.get_forecast_context_window(db=db, min_context_items=5)
            demo_question = q
            break
        except ValueError:
            continue

    if not demo_question:
        print("No suitable questions found with sufficient context")
        return

    print("="*80)
    print("FORECAST CONTEXT WINDOW - COMPREHENSIVE GUIDE")
    print("="*80)
    print(f"\nQuestion: {demo_question.question_text}")
    print(f"Resolution date: {demo_question.resolution_date.date()}")

    # =========================================================================
    # PART 1: Understanding Different Threshold Strategies
    # =========================================================================
    print(f"\n{'='*80}")
    print("PART 1: HOW THRESHOLDS AFFECT THE FORECAST WINDOW")
    print(f"{'='*80}")
    print("\nA threshold determines how many context items (articles/events) you need")
    print("before you can start forecasting. Higher threshold = more info, shorter window.")

    print(f"\n{'Threshold':<12} {'Window Opens':<20} {'Days Available':<15} {'Strategy'}")
    print("-"*80)

    thresholds_to_test = [
        (1, "Most aggressive - Start ASAP"),
        (3, "Balanced (DEFAULT)"),
        (5, "Conservative - Wait for more info"),
        (10, "Very conservative"),
    ]

    windows_by_threshold = {}
    for threshold, description in thresholds_to_test:
        try:
            start, end = demo_question.get_forecast_context_window(
                db=db,
                min_context_items=threshold
            )
            days = (end - start).days
            windows_by_threshold[threshold] = (start, end, days)

            marker = " ← DEFAULT" if threshold == 3 else ""
            print(f"{threshold:<12} {start.date()!s:<20} {days:<15} {description}{marker}")
        except ValueError:
            print(f"{threshold:<12} {'N/A':<20} {'N/A':<15} {description} (not enough context)")

    # =========================================================================
    # PART 2: Using the Default Threshold (Recommended)
    # =========================================================================
    print(f"\n{'='*80}")
    print("PART 2: USING THE DEFAULT THRESHOLD (min_context_items=3)")
    print(f"{'='*80}")

    try:
        # Get window with default threshold
        window_start, window_end = demo_question.get_forecast_context_window(db=db)
        days_available = (window_end - window_start).days

        print(f"\nForecast Window:")
        print(f"  Opens:      {window_start.date()} (when 3rd context item available)")
        print(f"  Closes:     {window_end.date()} (before resolution)")
        print(f"  Duration:   {days_available} days")

        # Get suggested dates
        suggested_7d = demo_question.suggest_simulated_date(
            db=db,
            offset_days_before_resolution=7
        )
        suggested_14d = demo_question.suggest_simulated_date(
            db=db,
            offset_days_before_resolution=14
        )

        print(f"\nSuggested Simulated Dates:")
        print(f"  7 days before resolution:  {suggested_7d.date()}")
        print(f"  14 days before resolution: {suggested_14d.date()}")

        # =====================================================================
        # PART 3: Validation Examples
        # =====================================================================
        print(f"\n{'='*80}")
        print("PART 3: VALIDATING SIMULATED DATES")
        print(f"{'='*80}")

        test_dates = [
            (window_start, "Window start (earliest valid)"),
            (suggested_7d, "Suggested (7 days before)"),
            (window_end, "Window end (too late!)"),
        ]

        print(f"\n{'Date':<15} {'Status':<12} {'Notes'}")
        print("-"*80)
        for test_date, description in test_dates:
            valid, error = demo_question.validate_simulated_date(test_date, db=db)
            status = "[VALID]" if valid else "[INVALID]"

            if valid:
                print(f"{test_date.date()!s:<15} {status:<12} {description}")
            else:
                print(f"{test_date.date()!s:<15} {status:<12} {description}")
                print(f"{'':>15} {'':>12} Error: {error}")

    except ValueError as e:
        print(f"\nError calculating window: {e}")
        print("This may indicate a data quality issue (e.g., context after resolution)")

    # =========================================================================
    # PART 4: Code Examples for Integration
    # =========================================================================
    print(f"\n{'='*80}")
    print("PART 4: CODE EXAMPLES FOR YOUR FORECASTING AGENT")
    print(f"{'='*80}")

    print("""
# -------------------------------------------------------------------------
# Example 1: Basic usage (recommended for most cases)
# -------------------------------------------------------------------------
from src.core.database import GenericDatabase
from src.domain.models import Question

db = GenericDatabase("worldreasoner.db")
question = db.get(Question, "q_tech_20251115_001_33f3eedc")

# Get suggested simulated date (uses min_context_items=3 by default)
simulated_date = question.suggest_simulated_date(db=db)

# Use in smolagents MCP server
mcp_server_parameters = [{
    "url": "http://127.0.0.1:8110/mcp",
    "headers": {
        "X-Question-ID": question.id,
        "X-Simulated-Date": simulated_date.isoformat(),
    }
}]

# -------------------------------------------------------------------------
# Example 2: Custom threshold for different scenarios
# -------------------------------------------------------------------------

# Aggressive: Quick response with minimal context
simulated_date_quick = question.suggest_simulated_date(
    db=db,
    min_context_items=1  # Start as soon as any context exists
)

# Conservative: Wait for comprehensive context
simulated_date_thorough = question.suggest_simulated_date(
    db=db,
    min_context_items=5  # Need 5 articles/events before forecasting
)

# -------------------------------------------------------------------------
# Example 3: Manual validation before forecasting
# -------------------------------------------------------------------------
from datetime import datetime, timezone

# Propose a specific date
candidate_date = datetime(2025, 11, 3, tzinfo=timezone.utc)

# Validate it
valid, error = question.validate_simulated_date(candidate_date, db=db)

if not valid:
    print(f"Invalid simulated date: {error}")
    # Get valid window
    start, end = question.get_forecast_context_window(db=db)
    print(f"Valid window: [{start.date()}, {end.date()})")
    # Use suggested date instead
    candidate_date = question.suggest_simulated_date(db=db)

# -------------------------------------------------------------------------
# Example 4: Batch processing multiple questions
# -------------------------------------------------------------------------
questions = db.get_many(Question)

for question in questions:
    try:
        # Calculate window
        start, end = question.get_forecast_context_window(db=db)

        # Get suggested date
        simulated_date = question.suggest_simulated_date(db=db)

        print(f"Question {question.id}")
        print(f"  Window: [{start.date()}, {end.date()})")
        print(f"  Suggested: {simulated_date.date()}")

    except ValueError as e:
        print(f"Question {question.id}: Error - {e}")
        continue
""")

    # =========================================================================
    # PART 5: Choosing the Right Threshold
    # =========================================================================
    print(f"\n{'='*80}")
    print("PART 5: CHOOSING THE RIGHT THRESHOLD FOR YOUR USE CASE")
    print(f"{'='*80}")

    print("""
+-------------------------------------------------------------------------+
| THRESHOLD SELECTION GUIDE                                               |
+-------------------------------------------------------------------------+
|                                                                         |
| min_context_items=1 (Most Aggressive)                                  |
|   + Longest forecast window                                            |
|   + Good for: Rapid response, early signals                            |
|   - Risk: May lack sufficient context                                  |
|                                                                         |
| min_context_items=3 (DEFAULT - Balanced)                               |
|   + Reasonable forecast window                                         |
|   + Sufficient context for informed forecasting                        |
|   + Good for: Most use cases, benchmarking                             |
|                                                                         |
| min_context_items=5 (Conservative)                                     |
|   + More comprehensive context                                         |
|   + Good for: High-stakes decisions, thorough analysis                 |
|   - Risk: Shorter forecast window, may exclude some questions          |
|                                                                         |
| min_context_items=10+ (Very Conservative)                              |
|   + Maximum context available                                          |
|   - Risk: Very short or no forecast window                             |
|   - May not be achievable for many questions                           |
|                                                                         |
+-------------------------------------------------------------------------+

Recommendation: Start with the default (3) and adjust based on your needs.
""")


if __name__ == "__main__":
    main()
