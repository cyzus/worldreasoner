# Section 6: Analysis Tools

This section documents the two inspector tools used to assess the quality of collected evidence before forecasting: `GraphInspectorTool` and `ArticleInspectorTool`. Both produce structured quality reports with numerical scores and actionable recommendations.

---

## 6.1 Graph Inspector (`GraphInspectorTool`)

**Source:** `src/tools/inspectors/graph_inspector.py`
**Analysis modules:** `src/analysis/graph_analysis.py`, `src/analysis/event_analysis.py`

The Graph Inspector evaluates the causal event graph associated with a question. It checks structural depth, temporal coverage, outcome impact coverage, and connectivity.

### Flow

1. Load all `CausalHypothesis` records tagged with `question_id`; return an empty-graph message if none exist.
2. Resolve the **target event** using this priority order: `is_actual_outcome` flag → first entry in `outcome_event_ids` → legacy `target_event_id` → inferred sink node.
3. Run `analyze_graph_structure` to compute depth, quality score, and leaf count.
4. Fetch all `Event` records referenced by hypotheses.
5. Filter events to the question's evidence window and run temporal analysis.
6. Detect **orphan events** — events linked to the question but absent from any hypothesis.
7. Fetch `EventOutcomeImpact` records and compute outcome impact coverage.
8. Build adjacency list; BFS to find subgraphs disconnected from the target.
9. Render all output sections.

### Output Sections

| Section | Contents |
|---------|----------|
| Relational Graph Structure | ASCII causal tree rendered from target up to root causes |
| Event Temporal Coverage | Monthly bar chart, gap list, quality metrics |
| Outcome Impact Analysis | Per-outcome positive/negative breakdown, missing impacts |
| Orphan Events | Disconnected events with fix instructions |
| Relational Chains | All root→target paths (depth, confidence, evidence count) |
| Graph Statistics | Event/hypothesis counts, depth score, quality score |
| Recommendation | Actionable guidance on depth, temporal coverage, impact coverage |

### Graph Quality Score (0–1)

Computed in `calculate_graph_quality` as a weighted combination of four components:

| Component | Weight | Formula |
|-----------|--------|---------|
| Depth | 40% | `min(max_depth / min_required_depth, 1.0)` — saturates at 3 levels by default |
| Confidence | 30% | Mean `hypothesis.confidence` across all hypotheses |
| Strength | 20% | Mean `hypothesis.strength` across all hypotheses |
| Evidence | 10% | Fraction of hypotheses with at least one `evidence_article_id` |

`max_depth` is the longest root→target path, found via DFS from the target event.

### Graph Recommendation

Threshold logic in `GraphVisualizer.get_recommendation`. All thresholds are sourced from `EvidenceSatisfactionConfig` (via `SATISFACTION_DEFAULTS`):

| Condition | Recommendation |
|-----------|---------------|
| `max_depth == 0` | No graph yet — start building |
| `max_depth < min_graph_depth - 1` | Too shallow — ask "What caused THIS?" for each cause |
| `max_depth < min_graph_depth` | Some depth — encourage going deeper |
| `max_depth >= min_graph_depth` and `quality < min_confidence` | Depth OK, but low quality — add evidence and improve confidence |
| All thresholds met | Good — graph ready for forecasting |

An additional **Events** recommendation fires when `event_count < min_graph_events`, reporting how many more events are needed.

### Temporal Quality Score (0–1)

Computed in `calculate_event_temporal_quality` from events within the evidence window.

**Gap Severity**

Summed penalties for gaps greater than 30 days between consecutive event dates. Each gap receives both an absolute penalty and a relative penalty; the larger of the two is used:

| Gap Size | Absolute Penalty |
|----------|-----------------|
| ≤60 days | 0.05 |
| 61–120 days | 0.10 |
| 121–180 days | 0.20 |
| >180 days | 0.30 |

Relative penalty: `min(gap_days / window_span × 0.5, 0.3)`. Total gap severity capped at 1.0.

**Early Gap Penalty**

If the first event lags behind `coverage_start`:

| Days Late | Penalty |
|-----------|---------|
| ≤30 | 0.05 |
| 31–90 | 0.15 |
| >90 | 0.25 |

**Distribution Score**

Coefficient of variation (CV) of monthly event counts:
```
distribution_score = max(0, 1 - CV / 3)
```
More lenient than articles since events are naturally sparse.

**Span Coverage Attenuation**

Gap severity is reduced when events cover most of the expected window:
```
span_coverage = min(event_span_days / expected_span_days, 1.0)
gap_severity  = gap_severity * max(1.0 - span_coverage * 0.4, 0.6)
```
At 100% span coverage the gap penalty is reduced by 40%; at 0% it is unchanged.

**Final Score:**
```
coverage_score = max(0, 1 - gap_severity - early_gap_penalty)
coverage_score = coverage_score * 0.7 + distribution_score * 0.3
temporal_score = coverage_score
```

Temporal recommendations fire when `temporal_score < 0.8`.

---

## 6.2 Article Inspector (`ArticleInspectorTool`)

**Source:** `src/tools/inspectors/article_inspector.py`
**Analysis module:** `src/analysis/article_analysis.py`

The Article Inspector evaluates the article collection for a question, checking volume, source diversity, and temporal coverage.

### Flow

1. Load `Question` record to get `resolution_date` and `estimated_start_time`.
2. Fetch all `Article` records for `question_id`.
3. Filter articles to the question's evidence window via `TemporalFilterService`.
4. Run `analyze_timeline`, `analyze_sources`, `identify_gaps`, and `calculate_quality`.
5. Render all output sections.

### Output Sections

| Section | Contents |
|---------|----------|
| Timeline Distribution | Monthly bar chart, coverage date range |
| Gaps | Time gaps >7 days between consecutive articles |
| Source Diversity | Unique sources/domains, top sources by article count |
| Coverage Quality | Scores for volume, diversity, coverage, distribution, gap severity |
| Recommendation | Actionable guidance on what to improve |

### Article Quality Score (0–1)

Weighted combination in `calculate_quality`:

| Component | Weight | Formula |
|-----------|--------|---------|
| Volume | 35% | `calculate_volume_score(count)` — see table below |
| Diversity | 25% | `calculate_diversity_score(unique_sources)` — see table below |
| Coverage | 40% | `(1 - gap_severity - early_gap_penalty) * 0.7 + distribution_score * 0.3` |

**Volume Score**

Saturates at `min_articles` (`EvidenceSatisfactionConfig.min_articles`, default 20):

| Article Count | Score |
|---------------|-------|
| ≥ `min_articles` | 1.0 |
| ≥ `min_articles / 2` | `0.5 + (count - half) * (0.5 / half)` |
| < `min_articles / 2` | `count * (0.5 / half)` |

**Diversity Score**

| Unique Sources | Score |
|----------------|-------|
| 1 | 0.1 |
| 2 | 0.3 |
| 3 | 0.5 |
| 4 | 0.7 |
| 5+ | `min(0.7 + (sources - 4) * 0.075, 1.0)` |

**Gap Severity**

Summed penalties for gaps greater than 7 days between consecutive articles. Each gap receives both an absolute and relative penalty; the larger is used:

| Gap Size | Absolute Penalty |
|----------|-----------------|
| ≤14 days | 0.05 |
| 15–30 days | 0.10 |
| 31–60 days | 0.20 |
| >60 days | 0.30 |

Relative penalty: `min(gap_days / window_span × 0.5, 0.3)`.

**Span Coverage Attenuation**

Same logic as events — gap severity is scaled down when articles span most of the expected window:
```
span_coverage = min(article_span_days / expected_span_days, 1.0)
gap_severity  = gap_severity * max(1.0 - span_coverage * 0.4, 0.6)
```

**Early Gap Penalty**

If the earliest article lags behind `coverage_start`:

| Days Late | Penalty |
|-----------|---------|
| ≤7 | 0.05 |
| 8–30 | 0.15 |
| >30 | 0.25 |

**Distribution Score**

CV of monthly article counts:
```
distribution_score = max(0, 1 - CV / 2)
```
Stricter than events (divisor of 2 vs. 3) since article distributions are expected to be more uniform.

### Article Recommendation

Recommendations fire when `quality.score < 0.8`:

- `volume_score < 0.5` → need more articles (aim for 5–10 minimum to start)
- `diversity_score < 0.6` → low source diversity — search different outlets
- any gap exists → reports the largest gap by date range with specific dates

---

## 6.3 Causal Pressure Trajectory

The **Causal Pressure Trajectory** is a time-series visualization of how evidence accumulated toward (or against) the resolved outcome as events occurred over time. It is displayed in the **Case Study View** under the "Evidence Accumulation" section, between the Causal Explanation and the Causal Events Table.

### Concept

Each event in the causal graph has a recorded `EventOutcomeImpact` toward the question's outcome event. This impact has three scalar attributes:

| Attribute | Range | Meaning |
|-----------|-------|---------|
| `impact_direction` | positive / negative / neutral / mixed | Which way the event pushed the outcome |
| `impact_magnitude` | [0, 1] | How strongly the event pushed |
| `confidence` | [0, 1] | How certain the system is of this assessment |

These are combined into a single **weighted contribution** per event:

```
contribution = sign(direction) × magnitude × confidence

where sign: positive → +1, negative → −1, neutral/mixed → 0
```

Events are then sorted by `occurred_date` and the contributions are accumulated into a running **cumulative pressure** signal:

```
cumulative_pressure(t) = Σ contribution_i   for all events i where occurred_date ≤ t
```

The result is a step function that rises as positive-direction events occur and falls as negative-direction events occur, giving an intuitive picture of how the causal evidence "tilted" over time.

### Outcome Selection

When a question has multiple outcome events (e.g. a `POSITIVE_RESOLUTION` and a `NEGATIVE_RESOLUTION` node), the trajectory targets the most relevant one using this priority order:

1. The outcome node flagged `is_actual_outcome = True`
2. The outcome node whose `outcome_scenario` matches `ground_truth` (e.g. `positive_resolution` for a "Yes" answer)
3. The first available outcome node

### Visualization

The chart is an SVG step chart rendered directly in the Case Study View:

| Element | Description |
|---------|-------------|
| **Step line** | Green if net pressure is positive, red if negative |
| **Shaded area** | Filled area between the step line and the zero baseline |
| **Colored dots** | One per event: green = positive, red = negative, purple = mixed, grey = neutral |
| **Hover tooltip** | Shows event title, date, direction, magnitude %, confidence %, individual `Δ` contribution, and market price at that moment |
| **Blue smooth line** | Polymarket price for the **actual outcome token** (right Y axis, 0–100%). Only shown for Polymarket questions. Token is selected by matching the actual outcome event node's title against `token_outcomes` labels (case-insensitive). Works for binary and MCQ questions without hardcoding. |
| **Dashed blue line at 50%** | Lead-change threshold on the price axis |
| **Yellow dashed line** | Resolution date |
| **Net label** | Final cumulative value (e.g. `+0.412`) displayed top-right |

### API Endpoint

The same trajectory can be fetched via the REST API for programmatic use:

```
GET /api/outcomes/{outcome_id}/trajectory
```

**Response:**
```json
{
    "outcome_event_id": "evt_outcome_yes_q123",
    "trajectory": [
        {
            "date": "2024-01-15T00:00:00+00:00",
            "event_id": "evt_abc",
            "event_title": "Fed raises interest rates",
            "direction": "positive",
            "magnitude": 0.7,
            "confidence": 0.85,
            "weighted_contribution": 0.595,
            "cumulative_pressure": 0.595
        },
        ...
    ],
    "summary": {
        "net_pressure": 0.412,
        "event_count": 7,
        "avg_confidence": 0.74,
        "dominant_direction": "positive"
    }
}
```

Events with no recorded `occurred_date` or `predicted_date` are excluded. Events are sorted chronologically before accumulation.

### Interpretation

| Net Pressure Range | Interpretation |
|--------------------|----------------|
| > +0.3 | Strong positive evidence accumulation toward this outcome |
| +0.1 to +0.3 | Moderate positive lean |
| −0.1 to +0.1 | Ambiguous or balanced evidence |
| −0.1 to −0.3 | Moderate negative evidence (events pushed away from this outcome) |
| < −0.3 | Strong evidence against this outcome |

Note that because `EventOutcomeImpact` assessments are made in **hindsight** (after the question has resolved), the cumulative pressure is biased toward the actual outcome — it reflects the explanatory power of the causal graph, not a prospective forecast.

---

## 6.4 Shared Infrastructure

Both inspectors rely on the following shared components:

| Component | Location | Description |
|-----------|----------|-------------|
| `TemporalFilterService.get_evidence_window` | `src/core/temporal.py` | Computes the evidence window from `resolution_date` and `estimated_start_time` |
| `InspectorReportBuilder` | `src/tools/inspectors/formatting.py` | Builds all text output sections: bar charts, key-value pairs, metrics tables, gap lists |
| `GraphVisualizer` | `src/analysis/graph_visualization.py` | ASCII tree rendering, DFS depth calculation, causal chain enumeration |

The evidence window defines the time range `[estimated_start_time, resolution_date - 1s]` within which all articles and events must fall to be counted toward quality scores. Evidence outside this window is excluded from scoring.

---

*For CLI commands to invoke the inspectors, see [Appendix A](appendix/A_cli_reference.md). For the evidence criteria thresholds used by the pipeline, see [Section 3.2](03_evidence_pipeline.md#32-evidence-criteria). For evaluation metrics used to score forecasts, see [Section 5](05_evaluation.md).*
