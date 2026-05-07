KNOWLEDGE_ONLY = """
Forecast the outcome of this question and submit your forecast.
Make reasonable forecasts based on your knowledge.
"""

REAL_TIME = """
Forecast the outcome of this question. Research if needed, then submit your forecast.
Make reasonable forecasts based on what you learn.
"""

CONTAINER = """
Forecast the outcome of this question. Research if needed, then submit your forecast.
The information you have access to might be limited due to the simulated date or evidence collection process.
Make reasonable forecasts nonetheless.
"""


def _format_question_block(question) -> str:
    """Format a Question object into a prompt-ready block."""
    lines = [
        "QUESTION TO FORECAST:",
        f"  ID: {question.id}",
        f"  Text: {question.question_text}",
        f"  Type: {question.question_type}",
    ]
    if question.options:
        lines.append(f"  Options: {', '.join(question.options)}")
    if question.quantity_unit:
        lines.append(f"  Unit: {question.quantity_unit}")
    lines.append("")
    return "\n".join(lines)

WITH_CAUSAL_TOOLS = """
CAUSAL REASONING WORKFLOW (Required — follow all steps):

STEP 1 — BUILD THE CAUSAL GRAPH
Option A (recommended — one call): Use propose_forecast_subgraph with a JSON object:
  {
    "events": [
      {"alias": "E1:RootCause", "title": "...", "description": "...", "domain": "politics", "occurred_date": "2024-01-01"},
      {"alias": "E2:Intermediate", "title": "...", "description": "...", "domain": "politics", "occurred_date": "2024-02-01"},
      {"alias": "E3:Outcome", "title": "...", "description": "...", "domain": "politics", "occurred_date": "2024-03-01"}
    ],
    "edges": [
      {"source": "E1:RootCause", "target": "E2:Intermediate", "relation": "causes", "strength": 0.8, "confidence": 0.7, "reasoning": "..."},
      {"source": "E2:Intermediate", "target": "E3:Outcome", "relation": "enables", "strength": 0.7, "confidence": 0.6, "reasoning": "..."}
    ]
  }

Option B (step-by-step): Call identify_forecast_event for each node, then call
create_forecast_causal_link for EVERY connection (root→intermediate, intermediate→outcome).

Include at least 3 events: root cause, intermediate event(s), and outcome.
For each edge provide: relation_type (causes|enables|prevents|correlates_with|conditional),
strength 0.0–1.0, confidence 0.0–1.0, and a mechanistic reasoning explanation.

STEP 2 — VERIFY WITH GRAPH INSPECTOR
Call inspect_forecast_graph and check:
- Hypotheses count ≥ 2 — if it shows 0, you skipped edges, go back and add them now
- max_depth ≥ 2 — if 0 or 1, add intermediate events and link them

STEP 3 — SUBMIT ONLY AFTER GRAPH IS COMPLETE
Do not submit your forecast until:
- At least 3 events are identified
- At least 2 causal links are created
- inspect_forecast_graph shows max_depth ≥ 2
"""


CONDITION_PREAMBLES = {
    "vanilla_llm": (
        "You are making a forecast based purely on your training knowledge. "
        "You do NOT have access to any external search tools or web browsing capabilities. "
        "Rely entirely on what you already know to make your prediction.\n\n"
    ),
    "structured_scenario": (
        "You have access to causal reasoning tools but no external search. "
        "Build a causal graph before forecasting: use propose_forecast_subgraph to batch-create "
        "at least 3 events and 2 edges in one call, then verify with inspect_forecast_graph. "
        "Do not submit until hypotheses ≥ 2.\n\n"
    ),
    "search_enabled": (
        "You have access to search and article retrieval tools. "
        "Use the search and article retrieval tools to gather relevant evidence "
        "before making your forecast. Focus on finding the most recent and relevant information.\n\n"
    ),
    "worldreasoner": (
        "You have access to both search tools and causal reasoning tools. "
        "First search for evidence, then build a causal graph using propose_forecast_subgraph "
        "(batch events+edges in one call), then verify with inspect_forecast_graph — "
        "must show hypotheses ≥ 2 and max_depth ≥ 2 before submitting.\n\n"
    ),
    "oracle": (
        "You have access to information very close to the question's resolution date. "
        "Search thoroughly for the most recent evidence, then build a causal graph using "
        "propose_forecast_subgraph (batch events+edges in one call), "
        "then verify with inspect_forecast_graph. Your goal is near-definitive evidence.\n\n"
    ),
    "real_time": (
        "You have access to live internet search tools (web_search, web_fetch). "
        "You MUST search the web to find the actual outcome of this question — "
        "it has already been resolved, so the answer is available online. "
        "Search for the question topic and resolution, find the definitive result, "
        "then submit your forecast with high confidence based on what you find.\n\n"
    ),
}


def get_forecast_instructions(
    mode: str,
    enable_causal_tools: bool,
    condition_name: str | None = None,
    question=None,
) -> str:
    """
    Generate forecast instructions based on mode and causal tool settings.

    Args:
        mode: Forecasting mode ("knowledge_only", "real_time", "container")
        enable_causal_tools: Whether causal reasoning tools are enabled
        condition_name: Optional condition name to prepend a condition-specific preamble
        question: Optional Question object to embed directly in the prompt (saves one agent step)
    """
    if mode == "knowledge_only":
        instructions = KNOWLEDGE_ONLY
    elif mode == "real_time":
        instructions = REAL_TIME
    else:
        instructions = CONTAINER
    if enable_causal_tools:
        instructions += "\n" + WITH_CAUSAL_TOOLS

    if condition_name and condition_name in CONDITION_PREAMBLES:
        instructions = CONDITION_PREAMBLES[condition_name] + instructions

    if question is not None:
        instructions = _format_question_block(question) + "\n" + instructions

    return instructions
