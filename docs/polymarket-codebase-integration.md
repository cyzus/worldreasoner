# Polymarket Client — Codebase Integration

**Date:** 2026-03-13

This document explains how `PolymarketClient` (`src/integrations/polymarket_client.py`) is used by the collection pipelines and the frontend/API layer.

---

## Two Separate Integration Modules

The codebase splits Polymarket access into two files:

| File | API Used | Purpose |
|---|---|---|
| `src/integrations/polymarket_client.py` | Gamma API | Fetches market/event metadata (questions, outcomes, tags, volumes) |
| `src/integrations/polymarket.py` | CLOB API | Fetches price timeseries, detects turning points and sharp movements |

`PolymarketClient` is only the Gamma API wrapper. The CLOB timeseries functions (`get_price_history_for_market`, `analyze_price_curve`) live in the other file and are used independently.

---

## PolymarketClient Methods

| Method | Endpoint | Used By |
|---|---|---|
| `fetch_events()` | `/events` | Pipeline bulk collection |
| `fetch_markets()` | `/markets` | Pipeline ground-truth collection |
| `search_markets()` | `/public-search` | Pipeline search collection + frontend search endpoint |
| `get_tag_id()` | `/tags/slug/{slug}` | Called internally by `fetch_markets()` to resolve slugs to numeric IDs; results cached per process |
| `call_api()` | (generic GET) | Internal helper used by `fetch_markets()` |

---

## Pipeline Usage — `PolymarketRunner`

**File:** `src/pipelines/collection/runner_polymarket.py`

`PolymarketRunner` is the pipeline's entry point for all Polymarket question collection. It owns a `PolymarketClient` instance and a `MarketParser`, and surfaces two collection modes.

### Mode 1: Bulk Collection (`collect()`)

Called by the orchestrator to fill the question database.

1. If `category_filter` is specified (a list of domain names), calls `fetch_events()` with a large pool (`count × 5` for active, `count × 20` for ground truth), then **filters client-side** by matching event tags against `DOMAIN_TO_TAG_SLUGS`:

   ```python
   DOMAIN_TO_TAG_SLUGS = {
       POLITICS: ["politics", "geopolitics", "elections"],
       FINANCE:  ["finance", "economy"],
       SPORTS:   ["sports"],
       TECH:     ["tech", "ai"],
       CULTURE:  ["entertainment", "music", "movies"],
       ...
   }
   ```

   This avoids any LLM categorization — domain assignment is purely tag-matching.

2. Without a category filter, calls `fetch_events()` directly for the full pool.

3. Each event is parsed by `_parse_event_structure()`:
   - **Single-market event** → binary (2 outcomes) or MCQ (>2 outcomes).
   - **Multi-market event** → aggregated into one MCQ, where each sub-market's `groupItemTitle` becomes an option. Volume and liquidity are summed across sub-markets. Ground truth is the sub-market whose outcome resolved `"Yes"`.
   - **Scalar markets** are skipped.

4. Each `MarketQuestion` is mapped to the domain `Question` model via `_map_to_question()`. Key fields preserved in `metadata`:
   - `clob_token_ids` — needed for price history fetching
   - `ground_truth` / `resolution_reasoning` — populated for resolved markets
   - `tags`, `market_slug`, `active`, `closed`

5. After mapping, the runner applies:
   - Early deduplication against `existing_question_ids`
   - Type and category filtering
   - Optional time-horizon post-filtering
   - Smart round-robin sampling across categories if `len(filtered) > count`

### Mode 2: Search Collection (`collect_from_search()`)

Called by the gap-filler with a keyword query.

- Calls `search_markets()` on `/public-search` with `events_status=resolved|active` and `sort=closed_time`.
- Parses the returned events the same way as Mode 1.

### `require_ground_truth` Flag

Controls which market state is fetched:

| Value | Markets fetched | Use case |
|---|---|---|
| `True` (default) | Closed/resolved markets with known outcomes | Building the question database for evaluation |
| `False` | Active/open markets | Live forecasting tasks |

---

## Frontend / API Usage

**File:** `src/api/routes/questions.py`

### `POST /questions/polymarket/search`

Directly instantiates `PolymarketClient` and calls `search_markets()`. Returns `events`, `tags`, and `profiles`. Used by the frontend's Polymarket search panel so users can browse and import markets by keyword before they go into the database.

Request parameters mirror `search_markets()` arguments: `query`, `limit_per_type`, `page`, `events_status` (`active`/`resolved`), `sort`, `presets`, `events_tag`.

### `POST /questions/preview`

Instantiates `PolymarketRunner` and calls `collect()` or `collect_from_search()` (depending on whether `search_query` is set). The result is returned to the user for review — nothing is saved yet. The user then calls `POST /questions/batch-save` to commit selected questions.

Key request fields:
- `source="polymarket"`
- `include_resolved` → sets `require_ground_truth` on the runner
- `domains` or `tags` → translated to `category_filter`
- `lookback_days` (default 730) → passed as `QualityRequirements.min_resolution_days`

### `GET /questions/{id}/price-history`

Loads a stored `Question` (must have `source="polymarket"`), reads `clob_token_ids` from its metadata, and calls `get_price_history_for_market()` from the CLOB module. Returns time-series data keyed by token ID, mapped to outcome labels.

Supported `interval` values: `all`, `max`, `1h`, `6h`, `1d`, `1w`.

Optionally includes curve analysis (`include_turning_points=true`): calls `analyze_price_curve()` to detect turning points, sharp movements, and lead changes.

### `GET /questions/{id}/price-analysis`

Similar to price-history but always runs full curve analysis via `analyze_question_price_curve()`.

---

## Data Flow

```
Frontend
    │
    ├── POST /questions/polymarket/search
    │       └── PolymarketClient.search_markets()  →  Gamma /public-search
    │
    ├── POST /questions/preview  (source="polymarket")
    │       └── PolymarketRunner
    │               ├── .collect()
    │               │     ├── PolymarketClient.fetch_events()  →  Gamma /events
    │               │     └── (category filter → client-side tag matching)
    │               └── .collect_from_search()
    │                     └── PolymarketClient.search_markets()  →  Gamma /public-search
    │
    └── GET /questions/{id}/price-history
            └── get_price_history_for_market()  →  CLOB timeseries API
                    (src/integrations/polymarket.py)
```

---

## Key Design Decisions

- **Bulk-fetch + local sort**: The `/events` `order` param triggers 422 errors for some sort keys, so the client always fetches a large batch and re-sorts locally by `volume24hr`.
- **No LLM categorization**: Domain assignment is done by tag-matching alone (`DOMAIN_TO_TAG_SLUGS`), which is fast and deterministic.
- **Tag ID cache**: `get_tag_id()` caches slug → numeric ID results in a class-level dict so repeated collection runs don't re-hit the tags endpoint.
- **Excluded tags**: Tag IDs `100639` and `102169` (platform earn products, not prediction markets) are always excluded from `fetch_events()` calls.
- **`clob_token_ids` in metadata**: Every question saved from Polymarket carries its CLOB token IDs so that price history can be fetched later without re-querying the Gamma API.
