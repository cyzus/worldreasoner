#!/usr/bin/env python3
"""End-to-end example: add a custom question, collect evidence, run a forecast, evaluate.

This script demonstrates the full WorldReasoner pipeline for a single question:
  1. Add the question to the database
  2. Collect evidence (articles + causal explanation)
  3. Build the causal graph
  4. Run a forecast with an LLM agent (via CLI subprocess for simplicity)
  5. Print the result and score it if ground truth is known

Usage:
    uv run python examples/forecast_custom_question.py
    uv run python examples/forecast_custom_question.py --db my.db --no-evidence

Requirements:
    - LLM API keys configured in config/config.yaml
    - Run from the repo root
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Question definition ───────────────────────────────────────────────────────

EXAMPLE_QUESTION = {
    "question_text": "Will the US Federal Reserve cut interest rates at least once before the end of 2025?",
    "question_type": "binary",
    "domain": "economics",
    "source": "manual",
    "resolution_date": "2025-12-31T23:59:59Z",
    # Set ground_truth once the question resolves. None = unresolved.
    "ground_truth": None,
    # Options only needed for multiple-choice questions
    "options": None,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a CLI command, streaming output, returning the result."""
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if check and result.returncode != 0:
        print(f"[ERROR] Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    return result


def run_json(cmd: list[str]) -> dict:
    """Run a CLI command that outputs JSON, return parsed result."""
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}")
        sys.exit(result.returncode)
    return json.loads(result.stdout)


# ── Main pipeline ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="worldreasoner.db", help="Database path")
    parser.add_argument("--model", default=None, help="LLM model (default: from config)")
    parser.add_argument("--mode", default="container",
                        choices=["knowledge_only", "container", "real_time"],
                        help="Forecast mode")
    parser.add_argument("--no-evidence", action="store_true",
                        help="Skip evidence collection (use if already collected)")
    parser.add_argument("--no-graph", action="store_true",
                        help="Skip graph building")
    parser.add_argument("--question-id", default=None,
                        help="Use an existing question ID instead of adding a new one")
    args = parser.parse_args()

    wr = ["uv", "run", "wr", "--db", args.db] if "--db" not in ["uv"] else ["uv", "run", "wr"]

    # ── Step 1: Add question ──────────────────────────────────────────────────
    if args.question_id:
        question_id = args.question_id
        print(f"\n[Step 1] Using existing question: {question_id}")
    else:
        print("\n[Step 1] Adding question to database...")
        from src.core.database import GenericDatabase
        from src.domain.models import Question

        db = GenericDatabase(args.db)
        q = Question(
            id=f"manual_{uuid.uuid4().hex[:8]}",
            question_text=EXAMPLE_QUESTION["question_text"],
            question_type=EXAMPLE_QUESTION["question_type"],
            domain=EXAMPLE_QUESTION["domain"],
            source=EXAMPLE_QUESTION["source"],
            resolution_date=datetime.fromisoformat(
                EXAMPLE_QUESTION["resolution_date"].replace("Z", "+00:00")
            ),
            ground_truth=EXAMPLE_QUESTION["ground_truth"],
            options=EXAMPLE_QUESTION["options"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.save(q)
        question_id = q.id
        print(f"  Created question: {question_id}")
        print(f"  Text: {q.question_text}")

    # ── Step 2: Collect evidence ──────────────────────────────────────────────
    if not args.no_evidence:
        print(f"\n[Step 2] Collecting evidence for {question_id}...")
        print("  (This scrapes news articles and builds a causal NL explanation.)")
        print("  (May take 1–5 minutes depending on model and article availability.)")
        run(["uv", "run", "wr", "evidence", "run", "-q", question_id, "--db", args.db])
    else:
        print(f"\n[Step 2] Skipping evidence collection (--no-evidence)")

    # ── Step 3: Build causal graph ────────────────────────────────────────────
    if not args.no_graph:
        print(f"\n[Step 3] Building causal graph for {question_id}...")
        build_result = run(
            ["uv", "run", "wr", "graph", "build", "-q", question_id, "--db", args.db, "--json"],
            check=False,
        )
        if build_result.returncode != 0:
            print("  [WARN] Graph build failed — forecast will proceed without causal tools")

        # Audit the graph
        run(
            ["uv", "run", "wr", "graph", "audit", "-q", question_id, "--db", args.db],
            check=False,
        )
    else:
        print(f"\n[Step 3] Skipping graph build (--no-graph)")

    # ── Step 4: Run forecast ──────────────────────────────────────────────────
    print(f"\n[Step 4] Running forecast...")
    print(f"  Mode:  {args.mode}")
    print(f"  Model: {args.model or 'default (from config)'}")

    forecast_cmd = [
        "uv", "run", "wr", "forecast", "run",
        "-q", question_id,
        "--db", args.db,
        "--mode", args.mode,
        "--slot", "mid",
        "--json",  # machine-readable, no interactive confirm
    ]
    if args.model:
        forecast_cmd += ["--model", args.model]
    if args.mode in ("container", "real_time"):
        forecast_cmd += ["--enable-causal-tools"]

    result = run_json(forecast_cmd)

    print("\n── Forecast result ──────────────────────────────────────────")
    print(f"  Forecast ID:  {result.get('forecast_id', 'N/A')}")
    print(f"  Prediction:   {result.get('prediction', 'N/A')}")
    confidence = result.get('confidence')
    if confidence is not None:
        print(f"  Confidence:   {confidence:.0%}")
    if result.get('error'):
        print(f"  [ERROR] {result['error']}")

    # ── Step 5: Evaluate ──────────────────────────────────────────────────────
    ground_truth = EXAMPLE_QUESTION["ground_truth"]
    if ground_truth is not None and confidence is not None:
        prediction = result.get("prediction")
        correct = str(prediction).lower() in (str(ground_truth).lower(), "yes" if ground_truth is True else "no")
        brier = (confidence - (1.0 if ground_truth else 0.0)) ** 2

        print("\n── Evaluation ───────────────────────────────────────────────")
        print(f"  Ground truth: {ground_truth}")
        print(f"  Correct:      {'✓' if correct else '✗'}")
        print(f"  Brier score:  {brier:.4f}  (0 = perfect, 1 = worst)")
    else:
        print("\n── Evaluation ───────────────────────────────────────────────")
        print("  Ground truth not yet set — question is unresolved.")
        print(f"  Once resolved, update with:")
        print(f"    uv run wr db update question {question_id} ground_truth <true|false>")
        print(f"  Then score with:")
        print(f"    uv run wr benchmark evaluate --db {args.db}")

    print("\n── Next steps ───────────────────────────────────────────────")
    print(f"  View in dashboard:    uv run worldreasoner --reload")
    print(f"  Question ID:          {question_id}")
    print(f"  Inspect evidence:     uv run wr db show question {question_id} --db {args.db}")
    print(f"  Compare conditions:   uv run wr benchmark run -q {question_id} -c vanilla_llm -c worldreasoner --db {args.db}")


if __name__ == "__main__":
    main()
