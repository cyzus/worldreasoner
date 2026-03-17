#!/bin/bash
# Run evidence collection for MOFE dataset
#
# Usage:
#   bash scripts/run_evidence_mofe.sh test      # Test with 5 questions
#   bash scripts/run_evidence_mofe.sh all        # Process all 109 questions
#   bash scripts/run_evidence_mofe.sh domain politics  # Process specific domain

set -euo pipefail
cd "$(dirname "$0")/.."

DB="mofe_polymarket_curated.db"
MODE="${1:-test}"

source .env 2>/dev/null || true

if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo "ERROR: GEMINI_API_KEY not set. Add it to .env"
    exit 1
fi

echo "================================================"
echo "  MOFE Evidence Collection"
echo "  DB: $DB"
echo "  Mode: $MODE"
echo "  Model: gemini-3-pro (evidence)"
echo "================================================"

case "$MODE" in
    test)
        echo "Running test batch: 3 random questions..."
        echo "y" | wr evidence run \
            --db "$DB" \
            --resolved \
            --sample 3
        ;;
    all)
        echo "Running all questions (this will take hours)..."
        echo "y" | wr evidence run \
            --db "$DB" \
            --resolved \
            --limit 200
        ;;
    domain)
        DOMAIN="${2:-politics}"
        echo "Running domain: $DOMAIN"
        echo "y" | wr evidence run \
            --db "$DB" \
            --resolved \
            --domain "$DOMAIN"
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Usage: $0 {test|all|domain <name>}"
        exit 1
        ;;
esac

echo ""
echo "Evidence collection complete."
echo "Run 'python -m mofe.pipeline.diagnose_data --db external/worldreasoner/$DB' to verify."
