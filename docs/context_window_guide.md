# Forecast Context Window Guide

## Overview

When making forecasts, the **simulated date** (when the forecast is made) must fall within a valid temporal window based on:

1. **Context availability**: All necessary background knowledge must exist
2. **Resolution timing**: Cannot forecast after the answer is known

This guide explains how to automatically derive valid forecast windows.

## The Problem

Consider this question:
```
"Will Disney and YouTube TV reach an agreement by November 15, 2025?"
```

**Context events** (prerequisite knowledge):
- Oct 31, 2025: Disney channels go dark on YouTube TV (1st article)
- Nov 3, 2025: Negotiations reported ongoing (2nd article)
- Nov 7, 2025: Latest update on dispute (3rd article)
- Nov 14, 2025: Final article before resolution

**Resolution**: Nov 15, 2025

**The Challenge**: When should the forecast window open?

### Approach 1: Wait for ALL context ❌
```
Window: [Nov 14, Nov 15) → Only 1 day to forecast!
```
Too restrictive - not useful for forecasting.

### Approach 2: Use minimum threshold ✅
```
min_context_items=3:
Window: [Nov 7, Nov 15) → 8 days to forecast
```
**Balanced** - have sufficient context, reasonable forecast period.

### Approach 3: Most aggressive
```
min_context_items=1:
Window: [Oct 31, Nov 15) → 15 days to forecast
```
Longer window, but may lack sufficient information.

**Valid forecast window with threshold=3**: `[Nov 7, 2025, Nov 15, 2025)`
- ✅ Can forecast on Nov 8 (have 3 context items)
- ❌ Cannot forecast on Nov 5 (only 2 context items)
- ❌ Cannot forecast on Nov 16 (already resolved)

## Implementation

### Main Function (Recommended)

**In `src/domain/models/question.py`:**

```python
def prepare_forecast(question, db=None, offset_days_before_resolution=0, min_context_items=3)
    """Get all forecast setup information in one call (hides complexity).

    Returns:
        dict with:
            - window_start: When forecasting window opens
            - window_end: When forecasting window closes
            - simulated_date: Suggested date to use
            - days_available: Number of days in forecast window
    """
```

**Recommended usage:**

```python
# Simple - everything in one call
setup = question.prepare_forecast(db=db, offset_days_before_resolution=7)
agent = ForecastAgent(question, simulated_date=setup['simulated_date'])
```

### Individual Helper Functions (Advanced)

For advanced users who need fine-grained control:

**In `src/domain/models/question_helpers.py`:**

```python
def calculate_forecast_context_window(question, db=None, min_context_items=3)
    """Calculate valid temporal window for forecasting."""

def validate_simulated_date(question, simulated_date, window_start, window_end)
    """Check if a date is within forecast window."""

def suggest_simulated_date(question, window_start, window_end, offset_days_before_resolution=7)
    """Suggest an appropriate simulated date within window."""
```

**Advanced usage (if you need manual control):**

```python
# Get valid forecast window manually
window_start, window_end = question.get_forecast_context_window(db=db, min_context_items=3)

# Validate a specific date
valid, error = question.validate_simulated_date(candidate_date, window_start, window_end)

# Get suggested date
simulated_date = question.suggest_simulated_date(window_start, window_end, offset_days_before_resolution=7)
```

## Usage Examples

### Example 1: Simple Automatic Setup (Recommended)

```python
from src.core.database import GenericDatabase
from src.domain.models import Question

db = GenericDatabase("worldreasoner.db")
question = db.get(Question, "q_tech_20251115_001_33f3eedc")

# Get everything in one call - no complexity!
setup = question.prepare_forecast(
    db=db,
    offset_days_before_resolution=7,  # 7 days before resolution
    min_context_items=3  # Default: need 3 context items
)

# Use the simulated date
print(f"Forecast window: {setup['window_start'].date()} to {setup['window_end'].date()}")
print(f"Using simulated date: {setup['simulated_date'].date()}")
print(f"Available: {setup['days_available']} days")

# Use in smolagents
mcp_server_parameters = [{
    "url": "http://127.0.0.1:8110/mcp",
    "headers": {
        "X-Question-ID": question.id,
        "X-Simulated-Date": setup['simulated_date'].isoformat(),
    }
}]
```

### Example 1b: Different Context Thresholds

```python
# Conservative: Wait for 5 context items
setup_conservative = question.prepare_forecast(db=db, min_context_items=5)

# Aggressive: Start with just 1 context item
setup_aggressive = question.prepare_forecast(db=db, min_context_items=1)

# Balanced: Default 3 items
setup_balanced = question.prepare_forecast(db=db)  # min_context_items=3 by default
```

### Example 2: Manual Control (Advanced)

```python
from datetime import datetime, timezone

# Get forecast window manually
window_start, window_end = question.get_forecast_context_window(db=db, min_context_items=3)

# Propose a specific date
candidate_date = datetime(2025, 11, 3, tzinfo=timezone.utc)

# Validate it
valid, error = question.validate_simulated_date(candidate_date, window_start, window_end)

if not valid:
    print(f"Invalid date: {error}")
    # Get valid window
    start, end = question.get_forecast_context_window(db=db)
    print(f"Valid window: [{start.date()}, {end.date()})")
```

### Example 3: Batch Processing

```python
# Process multiple questions with automatic date selection
questions = db.get_many(Question)

for question in questions:
    try:
        # Get suggested date
        simulated_date = question.suggest_simulated_date(db=db)

        print(f"Question: {question.id}")
        print(f"  Suggested date: {simulated_date.date()}")

    except ValueError as e:
        print(f"  Error: {e}")
        continue
```

## How It Works

### Context Detection

The function automatically finds prerequisite knowledge from:

1. **Related Events** (`question.related_event_ids`)
   - Events the question asks about
   - Uses `event.occurred_date`

2. **Evidence Articles** (`article.metadata['related_question_ids']`)
   - Articles tagged with this question
   - Uses `article.published_date`

3. **Fallback**: If no context found, uses 30 days before resolution

### Window Calculation

```python
# Collect all context dates from events and articles
context_dates = [event.occurred_date, article1.published_date, ...]

# Sort chronologically
sorted_dates = sorted(context_dates)

# Use the Nth date (where N = min_context_items)
if len(sorted_dates) >= min_context_items:
    window_start = sorted_dates[min_context_items - 1]  # 0-indexed
else:
    window_start = sorted_dates[-1]  # Use latest if fewer items

window_end = resolution_date - 1 second  # Before answer known
```

**Why not use max(all_context_dates)?**
- Would require waiting for the very last article
- Could result in forecast windows of 0-1 days
- Not practical for real forecasting scenarios

**Example with 5 articles**:
```
Articles published: [Mar 5, Jun 10, Aug 13, Oct 15, Oct 30]
Resolution: Oct 31

Threshold 1: Mar 5  → 239 days to forecast
Threshold 3: Aug 13 → 78 days to forecast (DEFAULT)
Threshold 5: Oct 30 → 1 day to forecast
Max (all):   Oct 30 → 1 day to forecast (same as threshold=5)
```

## Integration with MCP Server

The MCP forecasting server already uses headers to constrain knowledge:

```python
mcp_server_parameters = [{
    "url": "http://127.0.0.1:8110/mcp",
    "headers": {
        "X-Question-ID": question.id,
        "X-Knowledge-Cutoff": "2024-05-01",  # LLM training cutoff
        "X-Simulated-Date": simulated_date.isoformat()  # Now derived automatically!
    }
}]
```

**Key improvement**: Instead of manually setting `X-Simulated-Date`, derive it:

```python
simulated_date = question.suggest_simulated_date(db=db)
```

This ensures:
- ✅ All context is available
- ✅ Resolution hasn't occurred yet
- ✅ Consistent temporal constraints

## Data Quality Checks

The context window function also serves as a **data quality validator**:

```python
# If this raises ValueError, there's a data problem:
# - Evidence collected after resolution
# - Event dates inconsistent
# - Articles published before events they describe

try:
    window = question.get_forecast_context_window(db=db)
except ValueError as e:
    print(f"Data quality issue: {e}")
```

## Best Practices

1. **Always validate** simulated dates before forecasting
2. **Use suggested dates** for consistency across benchmarks
3. **Log the window** for each forecast for reproducibility
4. **Handle edge cases**: Some questions might not have context events
5. **Check data quality**: Invalid windows indicate data problems

## Future Enhancements

Potential improvements:

1. **Cache windows** in Question model for performance
2. **Support multiple forecasts** at different points in the window
3. **Confidence weighting** based on amount of available context
4. **Automatic window** in MCP server initialization
5. **Visualization** of temporal dependencies

## Quick Start

**Run the comprehensive demo:**
```bash
python examples/forecast_context_window_guide.py
```

This will show you:
- How thresholds affect the forecast window
- How to use the default threshold (recommended)
- How to validate simulated dates
- Code examples for integration
- Guidance on choosing the right threshold

## Files Modified

- `src/domain/models/question_helpers.py` - Core logic with threshold parameter
- `src/domain/models/question.py` - Convenience methods on Question model
- `examples/forecast_context_window_guide.py` - **Comprehensive demo script**
- `docs/context_window_guide.md` - This guide
