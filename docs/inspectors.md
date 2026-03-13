# Inspector Tools

Reference for `graph_inspector` and `article_inspector` — their flow, scoring criteria, and output sections.

---

## Graph Inspector (`GraphInspectorTool`)

**Source:** `src/tools/inspectors/graph_inspector.py`
**Analysis:** `src/analysis/graph_analysis.py`, `src/analysis/event_analysis.py`

### Flow

1. Load all `CausalHypothesis` records tagged with `question_id`; return empty message if none.
2. Resolve the **target event** (priority: `is_actual_outcome` → first `outcome_event_ids` → legacy `target_event_id` → inferred sink node).
3. Run `analyze_graph_structure` → depth, quality score, leaf count.
4. Fetch all `Event` records referenced by hypotheses.
5. Filter events to the question's evidence window and run temporal analysis.
6. Detect **orphan events** — linked to the question but absent from any hypothesis.
7. Fetch `EventOutcomeImpact` records and compute outcome impact coverage.
8. Build adjacency list; BFS to find subgraphs disconnected from the target.
9. Render output sections (see below).

### Output Sections

| Section | Contents |
|---|---|
| Relational Graph Structure | ASCII causal tree from target up to root causes |
| Event Temporal Coverage | Monthly bar chart, gaps, quality metrics |
| Outcome Impact Analysis | Per-outcome positive/negative breakdown, missing impacts |
| Orphan Events | Disconnected events with fix instructions |
| Relational Chains | All root→target paths (depth, confidence, evidence count) |
| Graph Statistics | Event/hypothesis counts, depth score, quality score |
| Recommendation | Graph depth, temporal, and impact coverage guidance |

### Graph Quality Score (0–1)

Weighted combination computed in `calculate_graph_quality`:

| Component | Weight | Formula |
|---|---|---|
| Depth | 40% | `min(max_depth / min_required_depth, 1.0)` — saturates at 3 levels by default |
| Confidence | 30% | Mean `hypothesis.confidence` |
| Strength | 20% | Mean `hypothesis.strength` |
| Evidence | 10% | Fraction of hypotheses with ≥1 `evidence_article_id` |

**`max_depth`** = longest root→target path, found via DFS from the target event.

### Graph Recommendation

Threshold logic in `GraphVisualizer.get_recommendation`. All thresholds are sourced from `EvidenceSatisfactionConfig` (via `SATISFACTION_DEFAULTS`):

| Condition | Message |
|---|---|
| `max_depth == 0` | No graph yet |
| `max_depth < min_graph_depth - 1` | Too shallow — ask "What caused THIS?" for each cause |
| `max_depth < min_graph_depth` | Some depth — encourage going deeper |
| `max_depth >= min_graph_depth` and `quality < min_confidence` | Depth OK, but low quality — add evidence/confidence |
| otherwise | Good |

An additional **Events** recommendation fires when `event_count < min_graph_events`, reporting how many more events are needed.

### Temporal Quality Score (0–1)

Computed in `calculate_event_temporal_quality` from events within the evidence window.

**Gap severity** — summed penalties across gaps > 30 days between consecutive event dates:

| Gap size | Absolute penalty |
|---|---|
| ≤60 days | 0.05 |
| 61–120 days | 0.10 |
| 121–180 days | 0.20 |
| >180 days | 0.30 |

Each gap also gets a relative penalty: `min(gap_days / window_span × 0.5, 0.3)`. The larger of the two is used. Total capped at 1.0.

**Early gap penalty** — if the first event lags behind `coverage_start`:

| Days late | Penalty |
|---|---|
| ≤30 | 0.05 |
| 31–90 | 0.15 |
| >90 | 0.25 |

**Distribution score** — coefficient of variation (CV) of monthly event counts:
`score = max(0, 1 − CV/3)` — more lenient than articles since events are naturally sparse.

**Span coverage attenuation** — gap severity is reduced when events cover most of the expected window:
```
span_coverage = min(event_span_days / expected_span_days, 1.0)
gap_severity  = gap_severity × max(1.0 − span_coverage × 0.4, 0.6)
```
At 100% span coverage the gap penalty is reduced by 40%; at 0% it is unchanged.

**Final:**
```
coverage_score = max(0, 1 − gap_severity − early_gap_penalty)
coverage_score = coverage_score × 0.7 + distribution_score × 0.3
temporal_score = coverage_score
```

Temporal recommendation fires issues when `temporal_score < 0.8`.

---

## Article Inspector (`ArticleInspectorTool`)

**Source:** `src/tools/inspectors/article_inspector.py`
**Analysis:** `src/analysis/article_analysis.py`

### Flow

1. Load `Question` for `resolution_date` and `estimated_start_time`.
2. Fetch all `Article` records for `question_id`.
3. Filter articles to the question's evidence window via `TemporalFilterService`.
4. Run `analyze_timeline`, `analyze_sources`, `identify_gaps`, `calculate_quality`.
5. Render output sections.

### Output Sections

| Section | Contents |
|---|---|
| Timeline Distribution | Monthly bar chart, coverage range |
| Gaps | Time gaps > 7 days between consecutive articles |
| Source Diversity | Unique sources/domains, top sources by count |
| Coverage Quality | Scores for volume, diversity, coverage, distribution, gap severity |
| Recommendation | Actionable guidance |

### Article Quality Score (0–1)

Weighted combination in `calculate_quality`:

| Component | Weight | Formula |
|---|---|---|
| Volume | 35% | `calculate_volume_score(count)` — see table below |
| Diversity | 25% | `calculate_diversity_score(unique_sources)` — see table below |
| Coverage | 40% | `(1 − gap_severity − early_gap_penalty) × 0.7 + distribution_score × 0.3` |

**Volume score** — saturates at `min_articles` (`EvidenceSatisfactionConfig.min_articles`, default 20):

| Article count | Score |
|---|---|
| ≥ `min_articles` | 1.0 |
| ≥ `min_articles / 2` | `0.5 + (count − half) × (0.5 / half)` |
| < `min_articles / 2` | `count × (0.5 / half)` |

**Diversity score:**

| Unique sources | Score |
|---|---|
| 1 | 0.1 |
| 2 | 0.3 |
| 3 | 0.5 |
| 4 | 0.7 |
| 5+ | `min(0.7 + (sources − 4) × 0.075, 1.0)` |

**Gap severity** — summed penalties across gaps > 7 days between consecutive articles:

| Gap size | Absolute penalty |
|---|---|
| ≤14 days | 0.05 |
| 15–30 days | 0.10 |
| 31–60 days | 0.20 |
| >60 days | 0.30 |

Same relative penalty logic as events: `min(gap_days / window_span × 0.5, 0.3)`, max of the two per gap.

**Span coverage attenuation** — same logic as events: gap severity is scaled down when articles span most of the expected window:
```
span_coverage = min(article_span_days / expected_span_days, 1.0)
gap_severity  = gap_severity × max(1.0 − span_coverage × 0.4, 0.6)
```

**Early gap penalty** — if earliest article lags behind `coverage_start`:

| Days late | Penalty |
|---|---|
| ≤7 | 0.05 |
| 8–30 | 0.15 |
| >30 | 0.25 |

**Distribution score** — CV of monthly article counts:
`score = max(0, 1 − CV/2)` — stricter than events.

### Article Recommendation

Fires issues when `quality.score < 0.8`:
- `volume_score < 0.5` → need more articles (aim for 5–10)
- `diversity_score < 0.6` → low source diversity
- any gap exists → reports the largest gap by date range

---

## Shared Infrastructure

- **`TemporalFilterService.get_evidence_window`** — computes the evidence window from `resolution_date` and `estimated_start_time`.
- **`InspectorReportBuilder`** (`src/tools/inspectors/formatting.py`) — builds all text sections (bar charts, KV pairs, metrics, gap lists).
- **`GraphVisualizer`** (`src/analysis/graph_visualization.py`) — ASCII tree rendering, DFS depth calculation, causal chain enumeration.
