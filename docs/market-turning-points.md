# Market Analysis: Turning Points & Lead Changes

This document explains how turning points and lead changes are detected in Polymarket price curves and how they're used in the evidence pipeline.

## Overview

The system analyzes price curves to detect two types of significant market events:

1. **Turning Points**: Moments where sentiment shifted significantly - a **peak** (price went up then reversed down) or a **trough** (price went down then reversed up). These often correspond to important news events that changed market perception.

2. **Lead Changes**: Moments when the market's prediction flipped - when the price crossed the 50% threshold, indicating the favored outcome changed. These are the most critical events to investigate as they represent a fundamental shift in market consensus.

## Turning Points Detection

Turning points can be detected using two methods, selected via the `method` parameter:

| Method | Key | Description |
|--------|-----|-------------|
| **PELT/BIC** (default) | `"pelt_bic"` | Statistical changepoint detection using the PELT algorithm with a BIC-style penalty. More robust for noisy or irregular data. |
| **Local Heuristic** | `"local"` | Sliding-window peak/trough detection. Simpler, purely geometric approach. |

Both methods share the same reversal verification, significance calculation, time-gap filtering, and output format. They differ only in **how candidate turning points are identified**.

---

### Method 1: PELT/BIC (Default)

This method uses the [PELT](https://centre-borelli.github.io/ruptures-docs/) (Pruned Exact Linear Time) changepoint detection algorithm to find **regime boundaries** — points where the underlying price level shifts — and then extracts peaks and troughs around those boundaries.

#### How It Works

```
1. Convert prices to a 1-D signal
2. Estimate noise level (robust MAD-based σ estimate)
3. Compute BIC-style penalty: penalty = scale × ln(n) × σ²
4. Run PELT with L2 (mean-shift) cost model to find changepoints
5. For each changepoint boundary:
   a. Open a window [boundary - lookback, boundary + lookahead]
   b. Find the local peak and trough within the window
   c. Apply reversal verification and significance checks
6. Apply time-gap filtering and sort by significance
```

#### Noise Estimation

A robust noise estimate is computed from first-differences using the Median Absolute Deviation (MAD):

```python
diffs = np.diff(prices)
mad = np.median(np.abs(diffs - np.median(diffs)))
sigma = mad / 0.6745  # Scale to match Gaussian std dev
```

Falls back to standard deviation if MAD is zero (constant price segments).

#### BIC-Style Penalty

The penalty controls how many changepoints are detected — higher penalty → fewer, more significant changepoints:

```python
penalty = pelt_penalty_scale × ln(n_points) × sigma²
```

- `pelt_penalty_scale` (default: 1.0) is a user-tunable multiplier
- The `ln(n)` term is the BIC complexity penalty that scales with data size
- `sigma²` normalizes by the data's noise level

#### Peak/Trough Extraction Around Boundaries

For each PELT changepoint boundary, a window is opened and the highest (peak candidate) and lowest (trough candidate) prices within that window are found. The winner is whichever has the higher significance, provided it passes the reversal and minimum-significance checks.

#### Fallback

If the `ruptures` library is not installed, the method automatically falls back to the local heuristic detector.

#### PELT-Specific Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pelt_min_segment_points` | 5 | Minimum number of data points per regime segment |
| `pelt_jump` | 1 | Speed/precision tradeoff (higher = faster but coarser) |
| `pelt_penalty_scale` | 1.0 | Multiplier for BIC penalty (higher = fewer changepoints) |

---

### Method 2: Local Heuristic

The original geometric detector that scans through price history looking for local maxima (peaks) and local minima (troughs) using sliding windows.

#### How It Works

```
For each point P at index i:
  1. Get prices in lookback window (points before P)
  2. Get prices in lookahead window (points after P)
  3. Check if P is a local maximum or minimum
  4. Verify it's a TRUE reversal (direction actually changed)
  5. Calculate significance based on magnitude of the swing
```

#### Local Extremum Detection

**Peak (Local Maximum):**
```python
is_peak = (
    current_price >= max(lookback_prices) AND
    current_price >= max(lookahead_prices)
)
```

**Trough (Local Minimum):**
```python
is_trough = (
    current_price <= min(lookback_prices) AND
    current_price <= min(lookahead_prices)
)
```

---

### Shared Logic (Both Methods)

#### Window Selection

```python
lookback_window = 5   # Points to look back (adaptive for sparse data)
lookahead_window = 5  # Points to look ahead (adaptive for sparse data)
```

For sparse data (few price points), windows automatically shrink:
```python
effective_window = min(default_window, max(2, (n_points - 1) // 3))
```

#### Reversal Verification

A peak/trough must be a TRUE reversal, not just a local extremum in a continuing trend:

**For Peaks:**
- `change_before` must be positive (price rose to reach the peak)
- `change_after` must be negative (price fell after the peak)

**For Troughs:**
- `change_before` must be negative (price fell to reach the trough)
- `change_after` must be positive (price rose after the trough)

```python
change_before = (current_price - anchor_left_price) * 100   # in percentage points
change_after  = (anchor_right_price - current_price) * 100  # in percentage points
```

#### Significance Calculation

Significance measures how "important" the turning point is:

```python
significance = abs(change_before) + abs(change_after)
```

This is the **total swing** — how much the price moved to reach the point plus how much it moved after.

**Example:**
- Price rises 15pp to reach a peak, then falls 12pp after → Significance = 15 + 12 = **27**

#### Minimum Threshold

```python
min_change_pct = 5.0  # Default: 5 percentage points total swing
```

#### Time Gap Filtering

To avoid detecting multiple turning points in rapid succession:

```python
min_time_between_points_hours = 6.0

# If too close to the previous turning point, keep whichever has higher significance
```

#### Final Sorting

Results are sorted by significance (descending):

```python
turning_points.sort(key=lambda x: x["significance"], reverse=True)
```

## Output Format

Each turning point includes:

```python
{
    "timestamp": 1735689600,      # Unix timestamp (seconds)
    "price": 0.225,               # Price at turning point (0-1 scale)
    "type": "trough",             # "peak" or "trough"
    "change_before": -16.5,       # Price change leading to this point (pp)
    "change_after": 10.5,         # Price change after this point (pp)
    "significance": 27.0          # Total swing magnitude (pp)
}
```

## Visual Example

```
Price
 70% |        * Peak
     |       /  \
 50% |      /    \        *
     |     /      \      / \
 30% |    /        \    /   \
     |   /          \  /
 10% |  *            *
     |  Start     Trough      Time
```

In this example:
- **Peak** at 70%: rose ~40pp, fell ~40pp → significance ≈ 80
- **Trough** at 10%: fell ~60pp, rose ~20pp → significance ≈ 80

## Sharp Movements Detection

In addition to turning points, the system also detects **sharp movements** - rapid price changes within a time window:

```python
min_change_pct = 10.0   # Minimum 10pp change
window_hours = 24.0     # Within 24 hours
```

These capture sudden market reactions that may not be full reversals.

## Lead Changes Detection

**Lead changes** are moments when the market's prediction flipped - when the price crossed the 50% threshold, indicating a change in which outcome is favored. These are often the most significant events to investigate, as they represent a fundamental shift in market consensus.

### Algorithm

The algorithm scans through price history detecting threshold crossings:

```python
def detect_lead_changes(
    price_history: List[Dict],
    threshold: float = 0.5,
    min_time_between_changes_hours: float = 1.0,
) -> List[Dict]:
```

#### Detection Logic

```
For each consecutive pair of prices (prev, curr):
  1. Check if price crossed the threshold
  2. Determine direction: "above" (Yes became favored) or "below" (No became favored)
  3. Calculate time spent in previous state
  4. Filter out rapid oscillations (within min_time_between_changes_hours)
```

#### Threshold Crossing Detection

```python
crossed_above = prev_price < threshold and curr_price >= threshold
crossed_below = prev_price >= threshold and curr_price < threshold

if crossed_above:
    direction = "above"  # "Yes" outcome became favored
elif crossed_below:
    direction = "below"  # "No" outcome became favored
```

#### Time in Previous State

For context, the algorithm also calculates how long the market was in the previous state before the flip:

```python
time_in_previous_state_hours = (current_timestamp - last_cross_timestamp) / 3600
```

This helps identify whether the flip was a brief oscillation or a sustained change in sentiment.

### Output Format

Each lead change includes:

```python
{
    "timestamp": 1735689600,              # Unix timestamp (seconds)
    "price": 0.52,                        # Price at crossing (0-1 scale)
    "previous_price": 0.48,               # Price before crossing
    "direction": "above",                 # "above" or "below"
    "time_in_previous_state_hours": 48.5  # Hours in previous state (optional)
}
```

### Visual Example

```
Price
 70% |
     |           *---*
 50% |----*--X-------X----*----  <- Threshold (50%)
     |   /      \   /      \
 30% |  *        *-*        *
     |                         Time
         ^       ^
         |       |
    Lead change  Lead change
    (above)      (below)
```

In this example:
- First **X**: Price crossed above 50% → "Yes" became favored
- Second **X**: Price crossed below 50% → "No" became favored

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | 0.5 | Price level that determines "leading" outcome |
| `min_time_between_changes_hours` | 1.0 | Minimum gap to filter oscillations |

### Why Lead Changes Matter

Lead changes are prioritized over turning points in the evidence pipeline because:

1. **Clear signal**: The market's prediction actually flipped, not just shifted
2. **Actionable**: Easier to search for "what changed the market's mind"
3. **High impact**: Usually caused by significant news or events
4. **Binary clarity**: For Yes/No markets, lead changes are unambiguous

## Integration with Evidence Pipeline

When processing Polymarket questions, market analysis data is:

1. **Fetched** from price history via `analyze_price_curve()`
2. **Injected** into the agent prompt with dates and magnitudes
3. **Used** as priority dates for evidence collection

### Priority Hierarchy

Lead changes are treated as **CRITICAL** dates, while turning points are **PRIORITY** dates:

1. **Lead Changes (Critical)**: Market prediction flipped - highest priority for investigation
2. **Turning Points (Priority)**: Significant sentiment shifts - secondary priority

### Example Prompt Sections

**Lead Changes:**
```
LEAD CHANGES (when market prediction flipped):
These are moments when the favored outcome changed. CRITICAL events to investigate:
- 2026-01-15 14:30: 'Yes' became favored (crossed above 50%: 45.2% -> 52.1%) [was in previous state for 72.5h]
- 2026-01-20 09:15: 'No' became favored (crossed below 50%: 51.3% -> 47.8%) [was in previous state for 114.8h]

CRITICAL DATES (lead changes - market prediction flipped): 2026-01-15, 2026-01-20
These are the MOST IMPORTANT dates - find what news caused the market to flip its prediction.
```

**Turning Points:**
```
TURNING POINTS (significant price reversals):
These are moments when market sentiment shifted significantly:
- TROUGH on 2026-01-01 00:00: price dropped 16.5pp then recovered 10.5pp (significance: 27.0)

PRIORITY DATES (from turning points): 2026-01-01
Search for news around these dates - they mark significant sentiment shifts.
```

## API Endpoints

### Get Price History with Turning Points

```
GET /api/questions/{question_id}/price_history?include_turning_points=true&min_turning_point_change=5.0
```

### Get Market Analysis (Turning Points + Lead Changes)

```
GET /api/questions/{question_id}/price_turning_points?min_change_pct=5.0&create_events=false
```

**Response includes:**
```json
{
    "turning_points": [...],
    "sharp_movements": [...],
    "lead_changes": [...],
    "curve_summary": {
        "min_price": 0.15,
        "max_price": 0.72,
        "price_range": 0.57,
        "start_price": 0.35,
        "end_price": 0.65,
        "total_change": 0.30
    }
}
```

Set `create_events=true` to persist turning points as Event records in the database.

## Configuration Parameters

### Turning Points

| Parameter | Default | Description |
|-----------|---------|-------------|
| `method` | `"pelt_bic"` | Detection method: `"pelt_bic"` (statistical) or `"local"` (heuristic) |
| `min_change_pct` | 5.0 | Minimum total swing (pp) for a turning point |
| `lookback_window` | 5 | Points to look back (adaptive) |
| `lookahead_window` | 5 | Points to look ahead (adaptive) |
| `min_time_between_points_hours` | 6.0 | Minimum gap between turning points |
| `pelt_min_segment_points` | 5 | Min data points per regime segment (PELT only) |
| `pelt_jump` | 1 | Speed/precision tradeoff (PELT only) |
| `pelt_penalty_scale` | 1.0 | BIC penalty multiplier — higher = fewer changepoints (PELT only) |

### Lead Changes

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | 0.5 | Price level for lead determination |
| `min_time_between_changes_hours` | 1.0 | Minimum gap to filter oscillations |

## Limitations

1. **Sparse data**: Markets with very few price points (<10) may not detect all turning points
2. **Noise sensitivity**: Low thresholds may detect insignificant fluctuations
3. **Hindsight only**: Algorithm needs data after the turning point to confirm the reversal
4. **Single outcome**: Currently analyzes the primary outcome (first token) only
5. **PELT dependency**: The `pelt_bic` method requires the `ruptures` and `numpy` packages; falls back to `local` if not installed
