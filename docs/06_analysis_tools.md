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

## 6.3 Shared Infrastructure

Both inspectors rely on the following shared components:

| Component | Location | Description |
|-----------|----------|-------------|
| `TemporalFilterService.get_evidence_window` | `src/core/temporal.py` | Computes the evidence window from `resolution_date` and `estimated_start_time` |
| `InspectorReportBuilder` | `src/tools/inspectors/formatting.py` | Builds all text output sections: bar charts, key-value pairs, metrics tables, gap lists |
| `GraphVisualizer` | `src/analysis/graph_visualization.py` | ASCII tree rendering, DFS depth calculation, causal chain enumeration |

The evidence window defines the time range `[estimated_start_time, resolution_date - 1s]` within which all articles and events must fall to be counted toward quality scores. Evidence outside this window is excluded from scoring.

---

*For CLI commands to invoke the inspectors, see [Appendix A](appendix/A_cli_reference.md). For the evidence criteria thresholds used by the pipeline, see [Section 3.2](03_evidence_pipeline.md#32-evidence-criteria).*
