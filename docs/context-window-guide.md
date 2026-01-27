# Forecast Context Window Guide

How to automatically derive the correct "simulated past" date for a forecast to ensure sufficient context without information leakage.

## The Problem

To forecast accurately, an agent needs:
1.  **Enough context**: Articles/events that have already happened.
2.  **Valid window**: Must be *before* the resolution date.

We calculate the optimal `simulated_date` by finding the point where sufficient context ($N$ items) became available.

## Implementation

### Recommended: Automatic Calculation

Use the `prepare_forecast` helper on the `Question` model.

```python
from src.core.database import GenericDatabase
from src.domain.models import Question

db = GenericDatabase("worldreasoner.db")
question = db.get(Question, "q_tech_20251115_001")

# Automatically calculates correct window based on available articles
setup = question.prepare_forecast(
    db=db,
    offset_days_before_resolution=7,  # Optional buffer
    min_context_items=3               # Wait until 3 articles exist
)

print(f"Simulated Date: {setup['simulated_date']}")
# > Simulated Date: 2024-11-08 (The date when the 3rd article was published)
```

### Integration with MCP

Pass the derived date to the MCP server headers:

```python
mcp_headers = {
    "X-Question-ID": question.id,
    "X-Simulated-Date": setup['simulated_date'].isoformat()
}
```

## How It Works

1.  Ids all events/articles related to the question.
2.  Sorts them chronologically.
3.  Sets `window_start` to the date of the $N$th item (`min_context_items`).
4.  Sets `window_end` to `resolution_date - 1 second`.

If `window_start > window_end`, the question is invalid (resolved before enough context existed).
