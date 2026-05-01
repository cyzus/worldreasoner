# Scripts

All scripts run from the repo root with `uv run python scripts/<name>.py`.

---

## Data pipeline

### `init_db.py`
Initialize or migrate the database schema for all registered models.
```bash
uv run python scripts/init_db.py
```

### `run_experiment_collection.py`
Collect questions from Polymarket and news sources into the database.
```bash
uv run python scripts/run_experiment_collection.py --db combined.db
uv run python scripts/run_experiment_collection.py --db combined.db --no-news   # Polymarket only
uv run python scripts/run_experiment_collection.py --db combined.db --dry-run   # show plan only
```

### `build_search_index.py`
Build or rebuild FTS5 and semantic search indexes after importing new articles.
```bash
uv run python scripts/build_search_index.py
```

### `fetch_knowledge_cutoff_date.py`
Fetch and cache LLM knowledge cutoff dates to a local JSON file.

---

## Database maintenance

### `cleanup.py`
Remove bad data from `combined.db`: fake example.com articles, invalid-content articles
(<500 chars), and exact-title duplicate events. Cascades to all referencing tables.
```bash
uv run python scripts/cleanup.py --db combined.db              # dry run (default)
uv run python scripts/cleanup.py --db combined.db --execute    # apply changes
```

### `cleanup_experiment_db.py`
Reclassify "general"-domain questions, remove low-quality micro-duration Bitcoin markets,
and report distribution against experiment targets.
```bash
uv run python scripts/cleanup_experiment_db.py --db combined.db --dry-run
uv run python scripts/cleanup_experiment_db.py --db combined.db
```

### `rerun_evidence.py`
Re-run the evidence + graph-builder pipelines for questions with too few unique source
articles (default: ≤2). Run after `cleanup.py` to avoid re-fetching bad sources.
```bash
uv run python scripts/rerun_evidence.py --db combined.db --dry-run
uv run python scripts/rerun_evidence.py --db combined.db
uv run python scripts/rerun_evidence.py --db combined.db --threshold 3   # stricter filter
uv run python scripts/rerun_evidence.py --db combined.db --ids q_id1 q_id2
```

---

## Prolific annotation study

### `select_prolific_questions.py`
Select high-quality questions for the Prolific study and write `include_ids.txt` and
`overlap.txt`. Balances domain distribution with a configurable per-domain cap.
```bash
uv run python scripts/select_prolific_questions.py --db combined.db --dry-run
uv run python scripts/select_prolific_questions.py --db combined.db
```
Key options: `--n 120`, `--min-score 0.8`, `--min-sources 3`, `--domain-cap 0.25`,
`--questions-per-session 4`, `--overlap-sessions 3`

### `annotation_ui/recreate_wr_annotation.sh`
Rebuild `D:/workspace/wr-annotation` from `combined.db` and the annotation UI source.
Run after `select_prolific_questions.py` updates `include_ids.txt`.
```bash
bash scripts/annotation_ui/recreate_wr_annotation.sh            # reuse cached prices
bash scripts/annotation_ui/recreate_wr_annotation.sh --fetch    # refresh price history
```

### `annotation_ui/export_data.py`
Export question data to `annotation_data_*.js` session files. Called by
`recreate_wr_annotation.sh`; can also be run directly.

### `annotation_ui/import_data.py`
Import completed annotation JSON files (downloaded from Google Drive) back into the
database.

---

## Recommended workflow

```
# 1. Collect questions
uv run python scripts/run_experiment_collection.py --db combined.db

# 2. Clean bad data
uv run python scripts/cleanup.py --db combined.db --execute

# 3. Re-run evidence for low-source questions
uv run python scripts/rerun_evidence.py --db combined.db

# 4. Select Prolific questions
uv run python scripts/select_prolific_questions.py --db combined.db

# 5. Build annotation study
bash scripts/annotation_ui/recreate_wr_annotation.sh
```
