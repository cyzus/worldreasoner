# Annotation Specification

## 1. Available Data Fields

### From `questions` table

| Field | Column | Notes |
|---|---|---|
| Question text | `question_text` | Always present |
| Outcome | `ground_truth` | Always present for resolved questions |
| Background | `context` | May be null |
| Resolution criteria | `resolution_criteria` | May be null |
| Causal explanation | `causal_explanation` | Present for processed questions |
| Market close date | `resolution_date` | Always present for polymarket questions |
| Market open date | `estimated_start_time` | Only ~1/3 of polymarket questions have this; null otherwise |
| Source type | `source` | `"polymarket"` or `"news"` etc. |
| Market token IDs | `metadata.clob_token_ids` | Present for polymarket; used to fetch live price history |
| Current probability | `metadata.current_probability` | Snapshot at collection time |
| Market slug | `metadata.market_slug` | For constructing Polymarket URL |

### From `events` table

| Field | Column | Notes |
|---|---|---|
| Event date | `occurred_date` | May be null for some events |
| Is outcome | `is_outcome` | True → auto-approved, skip in annotation |
| Review status | `review_status` | `pending`, `approved`, `rejected` |
| Review note | `review_note` | `"Auto-approved (outcome event)"` → skip |
| Source article | `source_article_id` or `article_ids` | Used to fetch URL + snippet |

### From `event_outcome_impacts` table

| Field | Column | Notes |
|---|---|---|
| Impact direction | `impact_direction` | `positive`, `negative`, `neutral`, `mixed` |
| Impact magnitude | `impact_magnitude` | 0.0–1.0 |
| Confidence | `confidence` | 0.0–1.0 |
| Reasoning | `reasoning` | Full text explanation |
| Outcome event ID | `outcome_event_id` | Used to display what outcome is affected |

---

## 2. Event Selection Logic (for `export_data.py`)

### Step 1 — Hard exclusions (skip entirely)
- Events where `review_note == "Auto-approved (outcome event)"` — these are the outcome nodes, not annotated
- Events where `review_status == "rejected"` — already auto-rejected by LLM review

### Step 2 — Priority ordering (within remaining events)

The market window distinction drives two different annotation purposes:

- **In-market-window events** are the primary annotation target. These events occurred while Polymarket was actively pricing the outcome, so the market price chart provides an objective, real-time signal of whether an event was considered significant by the market. Annotators can directly verify whether the AI's claimed impact direction matches the observed price movement. This is the core signal for evaluating forecast-relevant causality.
- **Pre-market / non-market events** provide causal context but cannot be verified against market prices. They are annotated on causal logic alone and serve as background structure in the Hindsight Graph rather than direct forecast drivers.

Apply this sort before capping:

1. **Has impact analysis AND `occurred_date` is within market window** — highest priority
2. **Has impact analysis, outside market window** — second priority  
3. **No impact analysis, within market window** — third priority
4. **No impact analysis, outside market window** — lowest priority

**Market window definition:**
- Close: `resolution_date` (always available)
- Open: `estimated_start_time` if present; otherwise fall back to 90 days before `resolution_date`

**"Has impact analysis"** = a row exists in `event_outcome_impacts` for this `event_id`

### Step 3 — Cap at 10 events per question
If more than 10 remain after filtering, keep the top 10 by the priority order above. If still tied within a tier, subsample using the existing chronological stride.

---

## 3. UI Display Requirements

### Sidebar (Question Context)

| Element | Data source | Display notes |
|---|---|---|
| Question title | `question_text` | Large heading |
| Outcome badge | `ground_truth` | e.g., "Outcome: Yes" |
| Causal Explanation | `causal_explanation` | Markdown, scrollable box |
| Background | `context` | Markdown |
| Resolution Criteria | `resolution_criteria` | Highlighted box |
| **Market window** | `estimated_start_time` + `resolution_date` | Show as "Market: {open} → {close}". If `estimated_start_time` is null, show "Market: (estimated open) → {close}" with a note that open date is estimated |
| **Polymarket link** | `metadata.market_slug` | Link to `polymarket.com/event/{market_slug}` for in-context market verification |

### Event Card (Timeline)

| Element | Data source | Display notes |
|---|---|---|
| Date | `occurred_date` | Color-code: **blue** if within market window, **gray** if outside or unknown |
| **In-window badge** | Compare `occurred_date` to market window | Show "In Market Window" (blue) or "Pre-Market" (gray) |
| Title | `title` | Bold heading |
| Description | `description` | Body text |
| Source link | `source_url` from articles | "View Article" button; hidden if no URL |
| **Impact Analysis box** | `event_outcome_impacts` row | Show direction + magnitude + confidence + reasoning; hidden/muted if no row |
| **Reasoning assessment buttons** | — | 👍 / 👎 buttons; only visible when impact analysis is present |

### Impact Analysis Box Format

```
Affects: {outcome_event.title}
Impact: {direction} ({magnitude * 100}%) | Confidence: {confidence * 100}%

Reasoning:
{reasoning}
```

If no impact analysis row exists, show muted text: *"No impact assessment available for this event."* and hide the 👍/👎 buttons.

---

## 4. Annotation Actions

### Validity decision (required for all events)

| Action | Code | When to use |
|---|---|---|
| Approve | `approved` | Factually real, causally relevant |
| Reject: Hallucination | `rejected / Hallucination` | Fabricated event or dates |
| Reject: Noise | `rejected / Noise` | Real but causally irrelevant |
| Reject: Duplicate | `rejected / Duplicate` | Same occurrence already approved |
| Reject: Too Broad | `rejected / TooBroad` | Trend/period not a specific occurrence |
| Skip | `skipped` | Cannot verify from available source |

### Reasoning quality assessment (only when impact analysis is present)

| Assessment | `reasoning_status` value |
|---|---|
| 👍 Accurate Reasoning | `"accurate"` |
| 👎 Flawed Reasoning | `"flawed"` |

---

## 5. Data Pipeline: From DB to UI

### Source database
All annotation data comes from **`combined.db`** (not `worldreasoner.db`).

### Step 1 — Pre-fetch price history (run once)

Price history is **not stored** in the DB. It must be fetched from the Polymarket CLOB API using `metadata.clob_token_ids` and cached locally before running the export.

```bash
python scripts/annotation_ui/fetch_price_history.py --db combined.db
```

This writes `scripts/annotation_ui/price_cache.json` — a dict keyed by `question_id` containing:
- `history`: downsampled to ≤120 points `[{"t": unix_ts, "p": 0.0–1.0}, ...]`
- `turning_points`: movements >5pp
- `price_at_open`, `price_at_close`, `min_price`, `max_price`, `final_price`
- `fetched_at`: ISO timestamp

The cache is saved incrementally (after each question) so it survives interruptions. Re-run with `--force` to refresh stale data.

### Step 2 — Export to annotation_data.js

```bash
python scripts/annotation_ui/export_data.py --db combined.db
```


---

## 6. Annotator Capacity Planning

### Time estimates per event

| Event type | Estimated time | Basis |
|---|---|---|
| No impact analysis | ~1.5 min | Read title + description + source snippet, decide validity |
| Has impact analysis | ~3 min | + read reasoning, optionally verify against market chart, decide 👍/👎 |

Assuming ~84% of events have impact analysis (ratio from current data), per question with 10-cap:
**~26–27 min/question on average.**

---

### Phase 1 — Demo (58 questions, pipeline incomplete)

| Metric | Value |
|---|---|
| Annotatable questions | 58 (30 polymarket + 28 news) |
| Total events after 10-cap | ~579 |
| Total annotation effort | ~27 hrs |

| Setup | Questions/person | Hours/person |
|---|---|---|
| 2 annotators | 29 | ~13 hrs |
| **3 annotators** | 19–20 | **~9 hrs** ← recommended |
| 4 annotators | 14–15 | ~7 hrs |

---

### Phase 2 — Full dataset (346 questions, after pipeline completes)

Projecting from the current 84% impact ratio and 10-event cap:

| Metric | Estimate |
|---|---|
| Annotatable questions | 346 |
| Total events after 10-cap | ~3,460 |
| Events with impact analysis | ~2,900 (84%) |
| Total annotation effort | ~160 hrs |

| Setup | Questions/person | Hours/person | Notes |
|---|---|---|---|
| 3 annotators | 115 | ~53 hrs | Too heavy per person |
| **4 annotators** | 87 | **~40 hrs** | Feasible over 1–2 weeks |
| 5 annotators | 69 | ~32 hrs | Comfortable pace |
| 6 annotators | 58 | ~27 hrs | Parallel to demo phase load |

**Recommended for full dataset: 4–5 annotators**, with each person doing ~70–90 questions spread across sessions.

---

### Overlap set for Inter-Rater Reliability (IRR)

In both phases, assign a shared overlap set (same questions to all annotators) to measure agreement.

**Overlap size:** 10 questions (≈ 10% of demo set; scale to ~35 for full dataset).

Select overlap questions to maximize diversity:
- Equal split polymarket / news
- Mix of questions with and without price data
- At least 1 question with many high-confidence impact events
- At least 1 question with sparse or low-quality evidence

---

### Assignment structure (full dataset, 4 annotators + 35 overlap)

| Annotator | Unique questions | + Overlap | Total |
|---|---|---|---|
| A | 78 | 35 | 113 |
| B | 78 | 35 | 113 |
| C | 78 | 35 | 113 |
| D | 77 | 35 | 112 |

Estimated time per annotator: **~48 hrs** (including overlap set).

---

### UI requirements for annotator assignment

The export script and UI need to support **per-annotator partitioning**:

- `export_data.py` should accept `--annotator <name>` and `--total-annotators <N>` flags
- Questions are assigned by deterministic hash-based partitioning (not random shuffle per run) so assignments are stable across re-exports
- The overlap set question IDs are hard-coded or specified via `--overlap-ids <file>`
- Each annotator's export file is named `annotation_data_{annotator}.js`
- The export should include `"assigned_to": "<annotator>"` and `"is_overlap": bool` per question
