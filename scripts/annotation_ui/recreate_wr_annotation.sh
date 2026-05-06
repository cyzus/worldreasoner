#!/usr/bin/env bash
# Regenerate D:/workspace/wr-annotation from combined.db and the annotation UI source.
#
# Usage (from repo root):
#   bash scripts/annotation_ui/recreate_wr_annotation.sh           # reuse cached prices
#   bash scripts/annotation_ui/recreate_wr_annotation.sh --fetch   # refresh price history first
#   bash scripts/annotation_ui/recreate_wr_annotation.sh --overlap-only
#       # regenerate only annotation_data_ov*.js + manifest overlap section

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="d:/workspace/wr-annotation"
FETCH_FLAG="--no-fetch"
MODE="prolific"

for arg in "$@"; do
    [[ "$arg" == "--fetch" ]] && FETCH_FLAG=""
    [[ "$arg" == "--overlap-only" ]] && MODE="prolific-overlap-only"
done

cd "$REPO_ROOT"

if [[ "$MODE" == "prolific-overlap-only" ]]; then
    echo "=== Regenerating overlap sessions only ==="
else
    echo "=== Exporting prolific sessions ==="
fi
uv run python scripts/annotation_ui/export_data.py \
    --db combined.db \
    --mode "$MODE" \
    --output-dir "$OUTPUT_DIR" \
    --overlap-ids overlap.txt \
    --include-ids include_ids.txt \
    --questions-per-session 4 \
    $FETCH_FLAG

if [[ "$MODE" != "prolific-overlap-only" ]]; then
    echo ""
    echo "=== Copying static files ==="
    cp "$SCRIPT_DIR/index.html"              "$OUTPUT_DIR/index.html"
    cp "$SCRIPT_DIR/annotation_guideline.md" "$OUTPUT_DIR/annotation_guideline.md"
    echo "  index.html"
    echo "  annotation_guideline.md"
fi

echo ""
echo "=== Done — $OUTPUT_DIR is ready to push ==="
