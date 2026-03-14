# Section 3: Evidence Pipeline

This section describes how evidence is collected, structured, and quality-validated for each forecasting question. It also covers the market price analysis module that identifies significant price curve events from Polymarket CLOB data.

---

## 3.1 Pipeline Overview

The evidence pipeline runs in three stages:

1. **Article Collection** — News articles are gathered from web search and RSS feeds, filtered to the question's evidence window (from `estimated_start_time` to just before `resolution_date`).
2. **Event Graph Construction** — Articles are synthesized into structured causal events (`Event` records) connected by `CausalHypothesis` links, forming a directed acyclic graph from root causes to the outcome event.
3. **Event Review** — Collected events are reviewed (manually or by LLM auto-review) to verify quality and accuracy before forecasting.

```bash
# Stage 1: Collect articles and events
wr evidence run --db experiment.db --sample 20

# Stage 2: Build causal graphs from events
wr graph build --db experiment.db --limit 20

# Stage 3a: Manual review (interactive)
wr evidence review --db experiment.db

# Stage 3b: Auto-review with LLM (recommended for scale)
wr evidence auto-review --db experiment.db -y
```

---

## 3.2 Evidence Criteria

The following minimum thresholds define acceptable evidence for a question to proceed to forecasting:

**Article Collection:**
- At least 20 articles
- Articles from unique (diverse) sources — single-source collections are penalized
- Temporal coverage across the evidence window — articles should be distributed over time, not clustered

**Event Graph:**
- At least 10 events
- Temporal coverage across the evidence window
- Graph depth of at least 3 levels (root causes → intermediate events → outcome)

These criteria are enforced by the auto-review system and surfaced by the inspector tools (see [Section 6](06_analysis_tools.md)).

Custom thresholds can be specified:
```bash
wr evidence auto-review --min-events 15 --min-depth 4 --db experiment.db
```

---

## 3.3 Market Price Analysis

For questions sourced from Polymarket, the system can analyze the CLOB price history to identify significant market events. This analysis complements article-based evidence by pinpointing *when* the market's belief shifted, providing temporal anchors for article search.

Two types of market events are detected: **turning points** (significant sentiment reversals) and **lead changes** (prediction flips across the 50% threshold).

### 3.3.1 Turning Points

Turning points are moments where price sentiment shifted significantly — a **peak** (price rose then reversed downward) or a **trough** (price fell then reversed upward). Two detection methods are available:

| Method | Key | Description |
|--------|-----|-------------|
| **PELT/BIC** (default) | `"pelt_bic"` | Statistical changepoint detection using the PELT algorithm with a BIC-style penalty. More robust for noisy or irregular data. |
| **Local Heuristic** | `"local"` | Sliding-window peak/trough detection. Simpler, purely geometric approach. |

Both methods share the same reversal verification, significance calculation, time-gap filtering, and output format. They differ only in how candidate turning points are identified.

#### Method 1: PELT/BIC (Default)

Uses the PELT (Pruned Exact Linear Time) changepoint detection algorithm to find **regime boundaries** — points where the underlying price level shifts — then extracts peaks and troughs around those boundaries.

**Algorithm:**
```
1. Convert prices to a 1-D signal
2. Estimate noise level (robust MAD-based sigma estimate)
3. Compute BIC-style penalty: penalty = scale * ln(n) * sigma^2
4. Run PELT with L2 (mean-shift) cost model to find changepoints
5. For each changepoint boundary:
   a. Open a window [boundary - lookback, boundary + lookahead]
   b. Find local peak and trough within the window
   c. Apply reversal verification and significance checks
6. Apply time-gap filtering and sort by significance
```

**Noise Estimation (MAD-based):**

A robust noise estimate is computed from first-differences using the Median Absolute Deviation:

```python
diffs = np.diff(prices)
mad = np.median(np.abs(diffs - np.median(diffs)))
sigma = mad / 0.6745  # Scale to match Gaussian std dev
```

Falls back to standard deviation if MAD is zero (constant price segments).

**BIC-Style Penalty:**

The penalty controls how many changepoints are detected — higher penalty yields fewer, more significant changepoints:

```python
penalty = pelt_penalty_scale * ln(n_points) * sigma**2
```

- `pelt_penalty_scale` (default: 1.0) is a user-tunable multiplier
- The `ln(n)` term is the BIC complexity penalty scaling with data size
- `sigma**2` normalizes by the data's noise level

**Peak/Trough Extraction:**

For each PELT changepoint boundary, a window is opened and the highest (peak candidate) and lowest (trough candidate) prices within that window are found. The candidate with higher significance is selected, provided it passes reversal and minimum-significance checks.

**Fallback:** If the `ruptures` library is not installed, the method automatically falls back to the local heuristic detector.

**PELT-Specific Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pelt_min_segment_points` | 5 | Minimum number of data points per regime segment |
| `pelt_jump` | 1 | Speed/precision tradeoff (higher = faster but coarser) |
| `pelt_penalty_scale` | 1.0 | BIC penalty multiplier — higher = fewer changepoints |

#### Method 2: Local Heuristic

The geometric detector scans through price history looking for local maxima (peaks) and local minima (troughs) using sliding windows.

**Algorithm:**
```
For each point P at index i:
  1. Get prices in lookback window (points before P)
  2. Get prices in lookahead window (points after P)
  3. Check if P is a local maximum or minimum
  4. Verify it is a TRUE reversal (direction actually changed)
  5. Calculate significance based on the magnitude of the swing
```

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

#### Shared Logic (Both Methods)

**Window Selection:**
```python
lookback_window = 5   # Points to look back (adaptive for sparse data)
lookahead_window = 5  # Points to look ahead (adaptive for sparse data)
```

For sparse data, windows automatically shrink:
```python
effective_window = min(default_window, max(2, (n_points - 1) // 3))
```

**Reversal Verification:**

A peak or trough must be a true reversal, not just a local extremum in a continuing trend.

For peaks:
- `change_before` must be positive (price rose to reach the peak)
- `change_after` must be negative (price fell after the peak)

For troughs:
- `change_before` must be negative (price fell to reach the trough)
- `change_after` must be positive (price rose after the trough)

```python
change_before = (current_price - anchor_left_price) * 100   # in percentage points
change_after  = (anchor_right_price - current_price) * 100  # in percentage points
```

**Significance Calculation:**

```python
significance = abs(change_before) + abs(change_after)
```

Significance is the total swing — how much the price moved to reach the point plus how much it moved after. Example: price rises 15 pp to a peak, then falls 12 pp → significance = 27.

**Minimum Threshold:**
```python
min_change_pct = 5.0  # Default: 5 percentage points total swing
```

**Time Gap Filtering:**
```python
min_time_between_points_hours = 6.0

# If two turning points are too close, keep whichever has higher significance
```

**Sorting:** Results are sorted by significance descending.

**Visual Example:**
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
- Peak at 70%: rose ~40 pp, fell ~40 pp → significance ≈ 80
- Trough at 10%: fell ~60 pp, rose ~20 pp → significance ≈ 80

### 3.3.2 Lead Changes Detection

Lead changes are moments when the market's prediction flipped — when the price crossed the 50% threshold, indicating a change in which outcome is favored. These are treated as the most critical events in the evidence pipeline, as they represent a fundamental shift in market consensus.

**Algorithm:**

```python
def detect_lead_changes(
    price_history: List[Dict],
    threshold: float = 0.5,
    min_time_between_changes_hours: float = 1.0,
) -> List[Dict]:
```

**Detection Logic:**
```
For each consecutive pair of prices (prev, curr):
  1. Check if price crossed the threshold
  2. Determine direction: "above" (Yes became favored) or "below" (No became favored)
  3. Calculate time spent in previous state
  4. Filter out rapid oscillations (within min_time_between_changes_hours)
```

**Threshold Crossing:**
```python
crossed_above = prev_price < threshold and curr_price >= threshold
crossed_below = prev_price >= threshold and curr_price < threshold

if crossed_above:
    direction = "above"  # "Yes" outcome became favored
elif crossed_below:
    direction = "below"  # "No" outcome became favored
```

**Time in Previous State:**
```python
time_in_previous_state_hours = (current_timestamp - last_cross_timestamp) / 3600
```

This contextualizes whether a flip is a brief oscillation or a sustained sentiment change.

**Why Lead Changes Matter:**
1. **Clear signal**: The market's prediction actually flipped, not just shifted.
2. **Actionable**: Easier to search for "what changed the market's mind."
3. **High impact**: Usually caused by significant news events.
4. **Binary clarity**: For Yes/No markets, lead changes are unambiguous.

### 3.3.3 Output Formats

**Turning Point Record:**
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

**Lead Change Record:**
```python
{
    "timestamp": 1735689600,              # Unix timestamp (seconds)
    "price": 0.52,                        # Price at crossing (0-1 scale)
    "previous_price": 0.48,               # Price before crossing
    "direction": "above",                 # "above" or "below"
    "time_in_previous_state_hours": 48.5  # Hours spent in previous state
}
```

**Full API Response:**
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

### 3.3.4 Integration with Evidence Pipeline

When processing Polymarket questions, market analysis data is:
1. **Fetched** from price history via `analyze_price_curve()`
2. **Injected** into the agent prompt with dates and magnitudes
3. **Used** as priority dates for evidence collection

**Priority Hierarchy:**

| Priority Level | Event Type | Description |
|---------------|-----------|-------------|
| **CRITICAL** | Lead Changes | Market prediction flipped — highest priority for investigation |
| **PRIORITY** | Turning Points | Significant sentiment shifts — secondary priority |

**Example Prompt Injection:**

Lead changes section:

```
LEAD CHANGES (when market prediction flipped):
These are moments when the favored outcome changed. CRITICAL events to investigate:
- 2026-01-15 14:30: 'Yes' became favored (crossed above 50%: 45.2% -> 52.1%) [was in previous state for 72.5h]
- 2026-01-20 09:15: 'No' became favored (crossed below 50%: 51.3% -> 47.8%) [was in previous state for 114.8h]

CRITICAL DATES (lead changes - market prediction flipped): 2026-01-15, 2026-01-20
These are the MOST IMPORTANT dates - find what news caused the market to flip its prediction.
```

Turning points section:

```
TURNING POINTS (significant price reversals):
These are moments when market sentiment shifted significantly:
- TROUGH on 2026-01-01 00:00: price dropped 16.5pp then recovered 10.5pp (significance: 27.0)

PRIORITY DATES (from turning points): 2026-01-01
Search for news around these dates - they mark significant sentiment shifts.
```

### 3.3.5 API Endpoints

**Get price history with optional turning points:**
```
GET /api/questions/{question_id}/price_history?include_turning_points=true&min_turning_point_change=5.0
```

**Get full market analysis (turning points + lead changes):**
```
GET /api/questions/{question_id}/price_turning_points?min_change_pct=5.0&create_events=false
```

Set `create_events=true` to persist detected turning points as `Event` records in the database.

### 3.3.6 Configuration Parameters

**Turning Points:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `method` | `"pelt_bic"` | Detection method: `"pelt_bic"` or `"local"` |
| `min_change_pct` | 5.0 | Minimum total swing (pp) for a turning point |
| `lookback_window` | 5 | Points to look back (adaptive) |
| `lookahead_window` | 5 | Points to look ahead (adaptive) |
| `min_time_between_points_hours` | 6.0 | Minimum gap between turning points |
| `pelt_min_segment_points` | 5 | Min data points per regime segment (PELT only) |
| `pelt_jump` | 1 | Speed/precision tradeoff (PELT only) |
| `pelt_penalty_scale` | 1.0 | BIC penalty multiplier (PELT only) |

**Lead Changes:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | 0.5 | Price level for lead determination |
| `min_time_between_changes_hours` | 1.0 | Minimum gap to filter rapid oscillations |

### 3.3.7 Limitations

1. **Sparse data**: Markets with fewer than 10 price points may miss turning points.
2. **Noise sensitivity**: Low `min_change_pct` thresholds may detect insignificant fluctuations.
3. **Hindsight only**: The algorithm requires data *after* the turning point to confirm the reversal; it cannot identify turning points in real-time.
4. **Single outcome**: Currently analyzes the primary outcome (first token) only.
5. **PELT dependency**: The `pelt_bic` method requires `ruptures` and `numpy`; falls back to `local` if not installed.

---

## 3.4 Event Review

After evidence collection, all events in the graph are reviewed to verify accuracy and relevance before they are made available to the forecasting agent.

**Manual review (interactive):**
```bash
wr evidence review --db experiment.db
wr evidence review -q q_abc123 --db experiment.db
wr evidence review --status all --summary
```

**Auto-review with LLM (recommended for scale):**
```bash
wr evidence auto-review --db experiment.db
wr evidence auto-review --db experiment.db --sample 5
wr evidence auto-review -y                          # Skip confirmation
wr evidence auto-review --skip-criteria             # Skip quality criteria checks
wr evidence auto-review -m gpt-5                    # Use specific model
wr evidence auto-review --min-events 15 --min-depth 4  # Custom thresholds
```

**View rejected events:**
```bash
wr evidence list-rejected --db experiment.db
wr evidence list-rejected -n 20
wr evidence list-rejected -v
wr evidence list-rejected -e evt_123abc
```

**Reset review status:**
```bash
wr evidence reset --db experiment.db          # Reset all to pending
wr evidence reset --status rejected           # Reset only rejected events
wr evidence reset -q q_abc123                 # Reset for specific question
```

---

*For details on how evidence quality is scored and visualized, see [Section 6](06_analysis_tools.md). For how the evidence is used during forecasting, see [Section 4](04_forecasting.md).*
