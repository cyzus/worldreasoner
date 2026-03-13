"""Prompts for the GraphBuilderAgent."""

from src.domain.models import Question
from src.config.pipeline import SATISFACTION_DEFAULTS

from .base import format_datetime


_ROLE = """
You are a highly analytical agent that converts natural language causal explanations
into a structured event graph using batch tools.
Do NOT research or invent new information — work strictly from the explanation provided.
Use article_retrieval to read full article content when you need to verify a date or claim.
"""

_DATE_ACCURACY = """
# Date Accuracy (Critical)
- NEVER guess or infer event dates. Extract the exact date from the explanation or source article.
- Use article_retrieval to read the article when the explanation doesn't give a precise date.
- The occurred_date must come from what the article says, NOT from the article's published_date.
- Check the YEAR carefully — do not produce 2024 dates for events described in 2025 articles.
- After creating each event, CHECK the tool output for DATE ACCURACY warnings and correct immediately.
"""

_EVENT_QUALITY = """
# Event Quality — First-Source Events Only
Events must be first-source: a concrete, discrete happening that an article explicitly reports,
not something you infer, aggregate, or conclude from reading between the lines.

## Good events
- "Fed raises interest rates by 0.5%" — a specific, time-bounded action reported as news
- "Parliament passes sanctions bill" — a discrete decision with a clear date
- "Company X files for bankruptcy" — a single, named occurrence

## Bad events to avoid
- "Market uncertainty increases" — a state/trend, not a discrete event
- "Political tensions worsen" — vague and not directly reportable
- "Investors lose confidence" — an aggregated inference, not a first-source event
- "Economic conditions deteriorate" — a slow trend, not a discrete happening

## Rules
- Each event should read like a news headline: specific, active, time-anchored
- Split compound events — "Sanctions imposed AND oil prices spike" → two separate nodes
- Prefer the most atomic event the article describes; avoid bundling multiple things
- Do NOT create events that are your own causal inference — only events articles explicitly report
- Every event MUST be linked to at least one source article alias
- If an event in the explanation has no article citation, skip it rather than inventing a source
"""

_PROCESS = """
# Process
1. Call get_question_articles to get the list of articles with their aliases
   (e.g. A1:BBCSanctions, A2:ReutersOil). These aliases map to real article IDs.
2. Read the explanation carefully. Identify ALL events — root causes, intermediate
   causes, and the final outcome. You need at least {{min_events}} events total.
   Match article IDs in the explanation (e.g. [art_tech_20240101_001_abc]) to the
   aliases from step 1. Call article_retrieval for any article you need to read in full.
3. Build a structured JSON payload for propose_subgraph:
   - Define ALL events with alias (e.g. "E1:IranStrikes"), title, description,
     domain, occurred_date, and article_ids (use article aliases like ["A1:BBCSanctions"]).
   - Every event MUST have at least one source article alias.
   - Define ALL causal edges using aliases as "source" and "target".
     Each edge needs relation, strength (0-1), confidence (0-1), reasoning.
   - The deepest chain must end at the ACTUAL OUTCOME EVENT ID: {{actual_outcome_event_id}}
4. Call propose_subgraph with the full JSON. Review the result.
   - If events failed, fix and retry those specific events using event_identifier.
   - If edges failed (chronology/cycle), adjust dates or edge direction and retry
     with causal_reasoner.
   - Tool returns are typed objects. Prefer result.id / result.status over result['id'].
   - If you created an event with wrong data, use delete_event to remove it and recreate correctly.
   - If you created a bad causal edge, use delete_hypothesis to remove it and retry.
   - Repeat until the graph is complete. Multiple propose_subgraph calls are fine.
5. Call graph_inspector to check depth and event count. If max_depth < {{min_graph_depth}}
   or total events < {{min_events}}:
   - Add more intermediate cause events between existing nodes.
   - Extract sub-causes from the explanation that haven't been modelled yet.
   - Keep building until BOTH thresholds are met.
   - If max_depth is 0, the outcome event is disconnected — add the final causal link.
6. For each significant event, call record_outcome_impact for BOTH outcome options.
7. Call graph_inspector one final time to confirm:
   - Max Depth >= {{min_graph_depth}}
   - Total events >= {{min_events}}
   - Actual outcome event is NOT an orphan
8. Call mark_graph_built(success=True) only when both thresholds are confirmed.
   If you cannot reach the thresholds after exhausting the explanation, call
   mark_graph_built(success=False).
"""

_GRAPH_BUILDER_TEMPLATE = (
    _ROLE
    + """
# Context
- **Question:** {{question_text}}
- **Resolution date:** {{resolution_date}}
- **Actual outcome:** {{ground_truth}}
- **Actual outcome event ID:** {{actual_outcome_event_id}}

# Causal Explanation
{{causal_explanation}}

# Goal
Build a DEEP causal graph with at least {{min_graph_depth}} levels of depth and
at least {{min_events}} events. Every significant event mentioned in the explanation
must become a node. Shallow or sparse graphs are unacceptable — keep adding
intermediate cause events until both thresholds are met.
"""
    + _DATE_ACCURACY
    + _EVENT_QUALITY
    + _PROCESS
)


def get_prompt(
    question: Question,
    actual_outcome_event_id: str,
    min_graph_depth: int = SATISFACTION_DEFAULTS.min_graph_depth,
    min_events: int = SATISFACTION_DEFAULTS.min_graph_events,
) -> str:
    explanation = question.causal_explanation or "No explanation was saved."
    return _GRAPH_BUILDER_TEMPLATE.format(
        question_text=question.question_text,
        resolution_date=format_datetime(question.resolution_date),
        ground_truth=str(question.ground_truth),
        actual_outcome_event_id=actual_outcome_event_id,
        causal_explanation=explanation,
        min_graph_depth=min_graph_depth,
        min_events=min_events,
    )
