#!/usr/bin/env python3
"""Example: external agent forecasting via the WorldReasoner MCP server.

Shows how any Python agent can connect to the MCP forecasting server,
use its tools to gather evidence and reason causally, then submit a forecast
and retrieve the evaluation score.

Prerequisites:
    1. WorldReasoner backend running:
         uv run worldreasoner --reload
    2. MCP forecasting server running:
         uv run worldreasoner-mcp-forecast --port 8110
    3. A question in the database (see examples/forecast_custom_question.py)

Usage:
    uv run python examples/external_agent_forecast.py --question-id <id>
    uv run python examples/external_agent_forecast.py --question-id <id> --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent

MCP_BASE = "http://localhost:8110"
API_BASE = "http://localhost:8300/api"


# ── MCP client ────────────────────────────────────────────────────────────────

class MCPClient:
    """Minimal MCP streamable-HTTP client for the WorldReasoner forecasting server."""

    def __init__(self, base_url: str, question_id: str, simulated_date: str, knowledge_cutoff: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-Question-ID": question_id,
            "X-Simulated-Date": simulated_date,
        }
        if knowledge_cutoff:
            self.headers["X-Knowledge-Cutoff"] = knowledge_cutoff
        self._session_id: str | None = None

    def call(self, tool: str, **kwargs) -> dict:
        """Call an MCP tool and return its result."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": kwargs,
            },
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{self.base_url}/mcp",
                json=payload,
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()

        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")

        result = data.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}


# ── Simple agent loop ─────────────────────────────────────────────────────────

def run_forecast(client: MCPClient, dry_run: bool = False) -> dict:
    """
    A simple agent loop that:
      1. Reads the question
      2. Searches for relevant articles
      3. Identifies key events
      4. Creates causal links
      5. Submits a forecast

    In a real agent, steps 2-5 would be driven by an LLM. Here we use
    deterministic logic to show the API surface clearly.
    """

    # Step 1 — get question context
    print("\n[1] Getting question...")
    q = client.call("get_question")
    print(f"    Question: {q.get('question_text', '')[:80]}")
    print(f"    Resolution: {q.get('resolution_date', '')[:10]}")
    print(f"    Simulated date: {q.get('simulated_date', '')[:10]}")

    if q.get("error"):
        raise RuntimeError(f"get_question failed: {q['error']}")

    question_text = q.get("question_text", "")

    # Step 2 — search for articles
    print("\n[2] Searching for relevant articles...")
    search_result = client.call(
        "temporal_search_articles",
        query=question_text[:100],
        max_results=5,
    )
    articles = search_result.get("articles", [])
    print(f"    Found {len(articles)} articles")
    for a in articles[:3]:
        print(f"    • [{a.get('published_date','')[:10]}] {a.get('title','')[:70]}")

    if not articles:
        print("    [WARN] No articles found — proceeding with knowledge-only forecast")

    # Step 3 — identify key events from top articles
    print("\n[3] Identifying causal events...")
    event_ids: list[str] = []

    if articles and not dry_run:
        # In a real agent an LLM would read each article and extract events.
        # Here we create one example event from the first article.
        first = articles[0]
        event_result = client.call(
            "identify_forecast_event",
            title=f"Development: {first.get('title', 'Event')[:60]}",
            description=f"Based on article published {first.get('published_date','')[:10]}",
            occurred_date=first.get("published_date", "")[:10] or None,
            domain=q.get("domain", "economics"),
            source_article_ids=[first.get("id")] if first.get("id") else [],
        )
        event_id = event_result.get("event_id")
        if event_id:
            event_ids.append(event_id)
            print(f"    Created event: {event_id}")
        if event_result.get("error"):
            print(f"    [WARN] Event creation: {event_result['error']}")
    else:
        print("    (skipped — dry run or no articles)")

    # Step 4 — inspect the graph
    print("\n[4] Inspecting reasoning graph...")
    graph = client.call("inspect_forecast_graph")
    print(f"    Events: {graph.get('event_count', 0)}")
    print(f"    Edges:  {graph.get('edge_count', 0)}")
    print(f"    Depth:  {graph.get('max_depth', 0)}")

    # Step 5 — submit forecast
    # In a real agent, an LLM would reason over the gathered evidence and
    # produce a calibrated probability. Here we use a placeholder.
    print("\n[5] Submitting forecast...")

    if dry_run:
        prediction = True
        confidence = 0.65
        reasoning = "[DRY RUN] Example forecast — replace with LLM-generated reasoning."
        print(f"    [DRY RUN] Would submit: prediction={prediction}, confidence={confidence:.0%}")
        return {
            "dry_run": True,
            "prediction": prediction,
            "confidence": confidence,
            "articles_found": len(articles),
            "events_created": len(event_ids),
        }

    forecast_result = client.call(
        "submit_forecast",
        prediction=True,          # Replace with LLM decision
        confidence=0.65,          # Replace with LLM probability
        reasoning=(
            "Based on the available evidence and historical Fed behavior, "
            "a rate cut before end of 2025 appears more likely than not."
        ),
        articles_accessed=[a.get("id") for a in articles if a.get("id")],
    )

    forecast_id = forecast_result.get("forecast_id")
    print(f"    Forecast ID: {forecast_id}")
    print(f"    Prediction:  {forecast_result.get('prediction')}")
    print(f"    Confidence:  {forecast_result.get('confidence', 0):.0%}")

    return forecast_result


# ── Evaluation ────────────────────────────────────────────────────────────────

def get_evaluation(question_id: str) -> dict | None:
    """Fetch accuracy/Brier score for the question from the REST API."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{API_BASE}/questions/{question_id}/forecasts")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question-id", required=True, help="Question ID in the database")
    parser.add_argument(
        "--simulated-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"),
        help="Simulated 'today' for temporal access control (ISO format)",
    )
    parser.add_argument(
        "--knowledge-cutoff",
        default=None,
        help="Agent's training cutoff date (ISO format, optional)",
    )
    parser.add_argument("--mcp-url", default=MCP_BASE, help="MCP server base URL")
    parser.add_argument("--dry-run", action="store_true", help="Skip writes, just show what would happen")
    args = parser.parse_args()

    print(f"WorldReasoner External Agent Example")
    print(f"  Question ID:    {args.question_id}")
    print(f"  Simulated date: {args.simulated_date}")
    print(f"  MCP server:     {args.mcp_url}")
    print(f"  Dry run:        {args.dry_run}")

    client = MCPClient(
        base_url=args.mcp_url,
        question_id=args.question_id,
        simulated_date=args.simulated_date,
        knowledge_cutoff=args.knowledge_cutoff,
    )

    try:
        result = run_forecast(client, dry_run=args.dry_run)
    except httpx.ConnectError:
        print(f"\n[ERROR] Cannot connect to MCP server at {args.mcp_url}")
        print("  Start it with:  uv run worldreasoner-mcp-forecast --port 8110")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    print("\n── Summary ──────────────────────────────────────────────────")
    for k, v in result.items():
        print(f"  {k}: {v}")

    print("\n── To evaluate after resolution ──────────────────────────────")
    print(f"  uv run wr db update question {args.question_id} ground_truth true")
    print(f"  uv run wr benchmark evaluate --db worldreasoner.db")


if __name__ == "__main__":
    main()
