# Section 2: Data Collection

This section describes how forecasting questions are sourced, the Polymarket API interfaces used, how the codebase integrates with those APIs, and the composition of the experiment dataset.

---

## 2.1 Question Sources

| Source | Collection Method | Primary Question Types |
|--------|-------------------|----------------------|
| Polymarket (Gamma API) | `PolymarketRunner.collect()` — bulk fetch from `/events` | Binary (Yes/No), MCQ |
| Polymarket (search) | `PolymarketRunner.collect_from_search()` — keyword search | Binary, MCQ |
| Polymarket (by identifier) | `PolymarketRunner.collect_by_identifiers()` — explicit slug/URL/id lookup | Binary, MCQ |
| Polymarket (ground-truth backfill) | `refresh_polymarket_ground_truth()` — re-fetch unresolved questions for resolved outcomes | Binary, MCQ |
| News pipeline | Goal-oriented orchestrator + web crawl | Quantity, Timeframe |

All questions are stored in a SQLite database (`worldreasoner.db` for development, `experiment.db` for the benchmark dataset). The goal-oriented orchestrator (`wr question goal`) runs both sources in parallel and tracks distribution gaps across domains, types, and time horizons.

---

## 2.2 Polymarket API Overview

Polymarket exposes two distinct API layers:

| API | Base URL | Purpose |
|-----|----------|---------|
| **Gamma API** | `https://gamma-api.polymarket.com` | Indexed on-chain data: market metadata, categories, volumes, tags, resolution outcomes |
| **CLOB API** | `https://clob.polymarket.com` | Order books, trade execution, real-time price timeseries |

WorldReasoner uses the Gamma API for question metadata and the CLOB API for price history and curve analysis. These are handled by separate modules (see Section 2.3.1).

### 2.2.1 Core Endpoints

The primary Gamma API endpoint is:

```http
GET https://gamma-api.polymarket.com/events
```

All markets (individual prediction questions) are nested under **Events** — an event is a top-level grouping that may contain one or more markets. Querying events directly is the most efficient strategy for bulk collection.

Key query parameters:

| Parameter | Values | Description |
|-----------|--------|-------------|
| `active` | `true` / `false` | Filter to currently tradeable events |
| `closed` | `true` / `false` | Filter to resolved/closed events |
| `limit` | integer | Maximum results per request |
| `offset` | integer | Pagination offset |
| `tag_slug` | string | Filter by category tag (e.g., `"politics"`, `"sports"`) |
| `tag_id` | integer | Filter by numeric tag ID |
| `slug` | string | Exact lookup by event URL slug |

### 2.2.2 Trending Events (Bulk-Fetch + Local Sort Pattern)

Trending activity is defined by two indicators:
- **`volume24hr`**: 24-hour trading volume — best indicator of current activity.
- **`liquidity`**: Depth of the market's liquidity pool.

The official API supports `order=volume_24hr` and `order=liquidity` parameters, but these trigger `422 Unprocessable Entity` errors for certain sort keys. The reliable pattern is **bulk-fetch + local sort**:

1. Fetch a large batch: `?active=true&closed=false&limit=100`
2. Sort the returned list locally by `volume24hr` (descending).
3. Truncate to the top N records.

```bash
# Fetch active events (sort applied client-side)
curl "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100"
```

### 2.2.3 Recently Resolved Events

To query events that have recently closed and been settled:

```bash
# Fetch recently closed events
curl "https://gamma-api.polymarket.com/events?closed=true&limit=50"
```

Sort the results client-side by `endDate` (descending) to get the most recently resolved events. The `endDate` field uses ISO 8601 format (e.g., `"2023-11-07T05:31:56Z"`).

### 2.2.4 Category Filtering via Tag Slugs

Each Polymarket event carries a `tags` array. Each tag has `id`, `label`, and `slug` fields. The `tag_slug` query parameter filters events to a specific category:

```http
GET https://gamma-api.polymarket.com/events?active=true&closed=false&tag_slug=crypto&limit=20
GET https://gamma-api.polymarket.com/events?active=true&closed=false&tag_slug=politics&limit=20
```

Based on analysis of approximately 1,000 active events, Polymarket market volume is concentrated in three dominant categories:

| Category | Volume Rank | Notes |
|----------|-------------|-------|
| Politics & Elections | 1st (dominant) | US elections, geopolitics, legislative outcomes; volume in billions USD |
| Sports | 2nd | Soccer, NBA/Basketball, tennis tournaments |
| Crypto & Tech | 3rd | Token price predictions, AI model releases, tech company events |

Note: A large "Earn 4%" category exists for platform yield products — this is excluded from collection (see Section 2.3.6).

### 2.2.5 Real-Time Trending Tag Discovery

To discover the most active tag slugs at any given moment — rather than relying on a static tag list — the following algorithm aggregates tags from the most active events:

**Algorithm:**
1. Fetch the 100–200 most active events (`events?active=true&limit=100`).
2. Iterate over each event; extract its `tags` array and accumulate `tag_slug` counts and volumes.
3. Sort by event count or total volume (descending).

```python
import urllib.request
import json
from collections import defaultdict

# Fetch the 100 most active events
url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100"

def get_realtime_tags():
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

            tag_counts = defaultdict(int)
            tag_volumes = defaultdict(float)

            # Aggregate tags from active events
            for event in data:
                volume = float(event.get('volume', 0))
                tags = event.get('tags', [])
                for tag in tags:
                    tag_slug = tag.get('slug', '')
                    if tag_slug:
                        tag_counts[tag_slug] += 1
                        tag_volumes[tag_slug] += volume

            # Rank by event count
            sorted_by_count = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            # Rank by total volume
            sorted_by_volume = sorted(tag_volumes.items(), key=lambda x: x[1], reverse=True)[:10]

            print("Top tag slugs by active market count:")
            for tag, count in sorted_by_count:
                print(f"  - {tag}: {count} active markets")

            print("\nTop tag slugs by total volume:")
            for tag, vol in sorted_by_volume:
                print(f"  - {tag}: ${vol:,.2f}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_realtime_tags()
```

This approach yields the tag slugs with the highest real-money participation, making them reliable as daily collection targets.

---

## 2.3 Codebase Integration

### 2.3.1 Module Overview

Polymarket access is split into two separate files with distinct responsibilities:

| File | API Used | Responsibility |
|------|----------|---------------|
| `src/integrations/polymarket_client.py` | Gamma API | Fetches market/event metadata (questions, outcomes, tags, volumes) |
| `src/integrations/polymarket.py` | CLOB API | Fetches price timeseries; detects turning points and sharp movements |

`PolymarketClient` is exclusively the Gamma API wrapper. CLOB timeseries functions (`get_price_history_for_market`, `analyze_price_curve`) reside in the separate module and are called independently for price history and curve analysis (see Section 3.3).

### 2.3.2 PolymarketClient Methods

| Method | Endpoint | Used By |
|--------|----------|---------|
| `fetch_events()` | `GET /events` | Pipeline bulk collection |
| `fetch_markets()` | `GET /markets` | Pipeline ground-truth collection |
| `search_markets()` | `GET /public-search` | Pipeline search collection + frontend search endpoint |
| `get_tag_id()` | `GET /tags/slug/{slug}` | Internal; resolves tag slugs to numeric IDs; results cached per process |
| `fetch_events_by_slug()` | `GET /events?slug=` | Identifier-based collection (resolve event by slug) |
| `fetch_event_by_id()` | `GET /events/{id}` | Identifier-based collection (resolve event by numeric id) |
| `fetch_markets_by_slug()` | `GET /markets?slug=` | Identifier-based collection (resolve market by slug) |
| `fetch_market_by_id()` | `GET /markets/{id}` | Identifier-based collection (resolve market by numeric id) |
| `call_api()` | (generic GET) | Internal helper used by `fetch_markets()` and the slug lookups |

### 2.3.3 PolymarketRunner

**File:** `src/pipelines/collection/runner_polymarket.py`

`PolymarketRunner` is the collection pipeline's entry point for all Polymarket question ingestion. It owns a `PolymarketClient` instance and a `MarketParser`, and exposes three collection modes.

**Mode 1: Bulk Collection (`collect()`)**

Called by the orchestrator to fill the question database.

1. If `category_filter` is specified (a list of domain names), calls `fetch_events()` with a large pool (`count × 5` for active markets, `count × 20` for ground-truth markets), then filters client-side by matching event tags against `DOMAIN_TO_TAG_SLUGS`:

   ```python
   DOMAIN_TO_TAG_SLUGS = {
       POLITICS: ["politics", "geopolitics", "elections"],
       FINANCE:  ["finance", "economy"],
       SPORTS:   ["sports"],
       TECH:     ["tech", "ai"],
       CULTURE:  ["entertainment", "music", "movies"],
   }
   ```

   Domain assignment is purely tag-matching — no LLM categorization.

2. Without a category filter, calls `fetch_events()` directly for the full pool.

3. Each event is parsed by `_parse_event_structure()`:
   - **Single-market event** → binary (2 outcomes) or MCQ (>2 outcomes).
   - **Multi-market event** → aggregated into one MCQ, where each sub-market's `groupItemTitle` becomes an option. Volume and liquidity are summed across sub-markets. Ground truth is the sub-market whose outcome resolved `"Yes"`.
   - **Scalar markets** are skipped.

4. Each `MarketQuestion` is mapped to the domain `Question` model via `_map_to_question()`. Key fields preserved in `metadata`:
   - `clob_token_ids` — needed for price history fetching
   - `ground_truth` / `resolution_reasoning` — populated for resolved markets
   - `tags`, `market_slug`, `active`, `closed`

5. Post-mapping steps: early deduplication, type and category filtering, optional time-horizon filtering, round-robin sampling across categories when supply exceeds quota.

**Mode 2: Search Collection (`collect_from_search()`)**

Called by the gap-filler with a keyword query. Calls `search_markets()` on `/public-search` with `events_status=resolved|active` and `sort=closed_time`. Parses returned events identically to Mode 1.

**Mode 3: Identifier Collection (`collect_by_identifiers()`)**

Fetches exactly the markets the caller names — no quality filtering, no target counts. Used by the `wr question add-polymarket` CLI command and by the ground-truth backfill (`refresh_polymarket_ground_truth()`, see Section 2.4 → Backfilling ground truth). Each identifier may be an event/market slug, a `polymarket.com` URL, or a numeric id. `_parse_identifier()` normalizes the input, then `_resolve_identifier_to_events()` tries, in order: event-by-slug → event-by-id → market-by-slug → market-by-id, wrapping a lone market in a synthetic single-market event. Resolved events are parsed by `_parse_event_structure()` and mapped via `_map_to_question()` — identical Question construction to Modes 1 and 2 (MCQ aggregation, ground-truth extraction, tag-based domain inference). Unresolvable identifiers are reported in `CollectionResult.error_message` without aborting the batch.

**`require_ground_truth` Flag**

| Value | Markets Fetched | Use Case |
|-------|----------------|---------|
| `True` (default) | Closed/resolved markets with known outcomes | Building evaluation dataset |
| `False` | Active/open markets | Live forecasting tasks |

### 2.3.4 Frontend API Endpoints

**File:** `src/api/routes/questions.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/questions/polymarket/search` | POST | Instantiates `PolymarketClient` directly; calls `search_markets()`. Returns `events`, `tags`, `profiles`. Used by frontend Polymarket search panel. |
| `/questions/preview` | POST | Instantiates `PolymarketRunner`; calls `collect()` or `collect_from_search()` (based on whether `search_query` is set). Returns preview for user review — nothing saved yet. |
| `/questions/batch-save` | POST | Commits user-selected questions from preview to the database. |
| `/questions/{id}/price-history` | GET | Reads `clob_token_ids` from question metadata; calls `get_price_history_for_market()`. Supports `interval` values: `all`, `max`, `1h`, `6h`, `1d`, `1w`. Optionally includes `analyze_price_curve()` results when `include_turning_points=true`. |
| `/questions/{id}/price-analysis` | GET | Always runs full curve analysis via `analyze_question_price_curve()`. |

Preview endpoint key request fields:
- `source="polymarket"`
- `include_resolved` → sets `require_ground_truth` on the runner
- `domains` or `tags` → translated to `category_filter`
- `lookback_days` (default 730) → passed as `QualityRequirements.min_resolution_days`

### 2.3.5 Data Flow

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

### 2.3.6 Key Design Decisions

- **Bulk-fetch + local sort**: The `/events` `order` parameter triggers `422` errors for some sort keys. The client always fetches a large batch and re-sorts locally by `volume24hr`.
- **No LLM categorization**: Domain assignment uses tag-matching alone (`DOMAIN_TO_TAG_SLUGS`), which is fast and deterministic.
- **Tag ID cache**: `get_tag_id()` caches slug → numeric ID results in a class-level dict, avoiding repeated hits to the tags endpoint across collection runs.
- **Excluded tags**: Tag IDs `100639` and `102169` (platform earn products, not prediction markets) are always excluded from `fetch_events()` calls.
- **`clob_token_ids` in metadata**: Every question saved from Polymarket carries its CLOB token IDs so price history can be fetched later without re-querying the Gamma API.

---

## 2.4 Dataset Composition

The experiment dataset (`experiment.db`) targets 300 high-quality resolved questions.

### Type Distribution

| Type | Target | Primary Source |
|------|--------|---------------|
| Binary (Yes/No) | 180 | Polymarket |
| MCQ | 60 | Polymarket + News |
| Quantity | 30 | News pipeline |
| Timeframe | 30 | News pipeline |

### Domain Distribution

| Domain | Target | Notes |
|--------|--------|-------|
| Finance | 50 | Markets, earnings, economy |
| Politics | 50 | Elections, policy, legislation |
| Sports | 50 | Events, tournaments, matches |
| Culture | 50 | Entertainment, arts, media |
| Climate | 50 | Environment, weather, policy |
| Health | 50 | Medical, healthcare, biotech |

### Time Horizon Distribution

Time horizon is computed as `resolution_date - estimated_start_time`. For Polymarket questions, `estimated_start_time` is the market's `startDate`.

| Horizon | Target | Day Range | Examples |
|---------|--------|-----------|---------|
| Short | 100 | 0–7 days | Weekly sports results, earnings reports |
| Medium | 100 | 7–90 days | Quarterly events, elections |
| Long | 100 | 90+ days | Annual outcomes, long-term policy |

### Collection Commands

**Config:** `config/collection_goal_experiment.yaml` | **DB:** `experiment.db`

Use `wr question goal` for most collection tasks:

```bash
# Full collection (Polymarket + News)
wr question goal --goal config/collection_goal_experiment.yaml --db experiment.db

# Polymarket only (faster, mostly binary/MCQ)
wr question goal --goal config/collection_goal_experiment.yaml --db experiment.db --no-news

# News only
wr question goal --goal config/collection_goal_experiment.yaml --db experiment.db --no-polymarket

# Run sources sequentially; skip auto-indexing
wr question goal --goal config/collection_goal_experiment.yaml --db experiment.db --sequential --skip-indexing
```

To add **specific, hand-picked** Polymarket questions (by slug, URL, or numeric id) rather than goal-driven collection, use `add-polymarket`:

```bash
# Add by event slug
wr question add-polymarket democratic-presidential-nominee-2028 --db combined.db

# Add by URL, or multiple identifiers at once
wr question add-polymarket https://polymarket.com/event/some-event slug-b 12345

# Resolve and preview without saving
wr question add-polymarket some-event-slug --dry-run
```

It fetches exactly what you name (no quality filtering or target counts) and skips questions already present in `--db`.

### Backfilling ground truth

A Polymarket question added while its market is still open is stored with `ground_truth=None`. Once that market resolves, backfill the outcome:

```bash
wr question refresh-polymarket --db combined.db
```

This re-fetches each stored Polymarket question that has no ground truth (matching by its saved `market_slug`, falling back to the market id in the question id), and copies over `ground_truth` / `resolution_reasoning` / `resolution_date` for any whose market has since resolved (`PolymarketRunner.collect_by_identifiers()` with `require_ground_truth=True`). It is idempotent — questions that already have ground truth, or whose markets are still open, are left untouched.

The API server runs this same backfill automatically on startup (set `POLYMARKET_REFRESH_ON_STARTUP=false` to disable). Nothing else re-resolves questions; there is no polling loop.

The following are only available via the script (no CLI equivalent):

```bash
# Preview the collection plan without running
python scripts/run_experiment_collection.py --dry-run

# Control max orchestration iterations (default: 3)
python scripts/run_experiment_collection.py --db experiment.db --max-iterations 5

# Export dataset summary to JSON
python scripts/run_experiment_collection.py --export dataset_summary.json
```

The orchestrator is resumable: re-running against the same `--db` file skips already-collected questions, focuses on distribution gaps, and accumulates results across runs.

---

*See [Section 3](03_evidence_pipeline.md) for how evidence is collected for these questions, and [Section 5](05_evaluation.md) for how they are used in the benchmark.*
