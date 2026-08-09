# WORLDREASONER Dataset v2 Pipeline

## Current Release State

- `data/versions/v1/worldreasoner.db` is an immutable SQLite snapshot of
  `combined_new.db`.
- `data/versions/v2_0/worldreasoner.db` is the working v2.0 release.
- Both releases contain the same 345 question IDs.
- v2.0 retains the original article and event rows and stores all quality-pass
  outputs in separate, versioned tables.

The database files are ignored by Git. Each release directory contains a
tracked `manifest.json` with checksums, object counts, provenance, and the code
revision.

The first live smoke test processed two articles and two event-source pairs with
Gemini 3.1 Pro for cleanup/extraction and Gemini 3.5 Flash for independent
verification. It confirmed resumable batches, visible-text traceability, cleanup
fidelity recording, and append-only repair proposals. These records validate the
pipeline mechanics but are too few to estimate pass accuracy.

## Passes

### 1. Deterministic article preparation

`ArticleNormalizer` unwraps serialized crawler responses, normalizes encoding
and line endings, calculates content hashes, detects exact duplicates, and flags
empty, short, consent-leading, truncated, very long, link-heavy, and raw-HTML
captures. It does not rewrite substantive text.

```powershell
wr dataset normalize-articles
```

### 2. Human-readable Markdown

`ArticleMarkdownCleaner` removes page furniture in bounded chunks while
instructing the model to preserve claims, names, dates, numbers, quotations,
uncertainty, and negation. The cleaned Markdown is stored beside the normalized
snapshot rather than replacing it.

```powershell
wr dataset clean-articles --limit 10 --model <model-id> --allow-model-content
```

This command sends stored article text to the configured model endpoint. Confirm
provider terms and dataset handling policy before passing the required
acknowledgement flag. Run a small reviewed pilot before processing every cited
article.

### 3. Exact event evidence extraction

`EventEvidenceExtractor` asks pass A for verbatim supporting, contradicting, and
date passages. Every returned passage must occur in the preserved snapshot under
versioned Markdown-visible normalization. Untraceable passages cannot proceed as
valid evidence.

### 4. Independent event verification

`EventEvidenceVerifier` gives pass B only the event and traceable passages, not
pass A's verdict or rationale. It separately labels source support, date
validity, and entity match, then proposes `accept`, `revise`, `relink`, `reject`,
or `defer_unverifiable`.

```powershell
wr dataset validate-events --limit 10 \
  --verifier-model <different-model-id> \
  --allow-model-content
```

Validation writes append-only extraction, verification, and repair records. It
does not silently mutate the benchmark event.

## Construction-Pipeline Integration

The deterministic pass can run as an optional post-collection hook:

```python
db = GenericDatabase("data/versions/v2_0/worldreasoner.db")
quality = EvidenceQualityService(db, dataset_version="v2.0")
collector = ArticleCollectorTool(db=db, quality_processor=quality)
```

LLM cleanup and grounding remain explicit asynchronous stages. This keeps web
collection inexpensive and makes model, prompt, retry, and human-review policy
independently configurable.

## Next Execution Step

1. Review a stratified pilot of 30-50 flagged and clean article records.
2. Run Markdown cleanup on that pilot and compare it with the preserved snapshot.
3. Run two-model event grounding on 50-100 event-source pairs.
4. Measure pass precision against blinded human labels before scaling.
5. Process all official KER nodes, adjudicate high-impact disagreements, and
   freeze v2.0 metric eligibility.
