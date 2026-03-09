"""Prompts for the GraphBuilderAgent."""

from src.domain.models import Question
from src.config.pipeline import SATISFACTION_DEFAULTS
from .base import BasePromptGenerator, PromptTemplate

GRAPH_BUILDER_DESCRIPTION = """
You are a highly analytical agent that converts natural language causal explanations
into a structured event graph using batch tools.
Do NOT research or invent new information — work strictly from the explanation provided.

QUESTION: {question_text}
RESOLUTION DATE: {resolution_date}
ACTUAL OUTCOME: {ground_truth}
ACTUAL OUTCOME EVENT ID: {actual_outcome_event_id}

CAUSAL EXPLANATION:
{causal_explanation}

GOAL: Build a DEEP causal graph with at least {min_graph_depth} levels of depth and
at least {min_events} events. Every significant event mentioned in the explanation
must become a node. Shallow or sparse graphs are unacceptable — keep adding
intermediate cause events until both thresholds are met.

PROCESS:
1. Read the explanation carefully. Identify ALL events — root causes, intermediate
   causes, and the final outcome. You need at least {min_events} events total.
2. Build a structured JSON payload for propose_subgraph:
   - Define ALL events with alias (e.g. "E1:IranStrikes"), title, description,
     domain, occurred_date. Leave article_ids empty ([]) if unsure of IDs.
   - Define ALL causal edges using aliases as "source" and "target".
     Each edge needs relation, strength (0-1), confidence (0-1), reasoning.
   - The deepest chain must end at the ACTUAL OUTCOME EVENT ID: {actual_outcome_event_id}
3. Call propose_subgraph with the full JSON. Review the result.
   - If events failed, fix and retry those specific events using event_identifier.
   - If edges failed (chronology/cycle), adjust dates or edge direction and retry
     with causal_reasoner.
   - Repeat until the graph is complete. Multiple propose_subgraph calls are fine.
4. Call graph_inspector to check depth and event count. If max_depth < {min_graph_depth}
   or total events < {min_events}:
   - Add more intermediate cause events between existing nodes.
   - Extract sub-causes from the explanation that haven't been modelled yet.
   - Keep building until BOTH thresholds are met.
5. For each significant event, call record_outcome_impact for BOTH outcome options.
6. Call graph_inspector one final time to confirm:
   - Max Depth >= {min_graph_depth}
   - Total events >= {min_events}
   - Actual outcome event is NOT an orphan
7. Call mark_graph_built(success=True) only when both thresholds are confirmed.
   If you cannot reach the thresholds after exhausting the explanation, call
   mark_graph_built(success=False).
"""


class GraphBuilderPrompts(BasePromptGenerator[Question]):
    """Prompts for building the graph structure from an NL explanation."""

    AGENT_TEMPLATE = PromptTemplate(
        template=GRAPH_BUILDER_DESCRIPTION,
        required_vars=[
            "question_text",
            "resolution_date",
            "ground_truth",
            "actual_outcome_event_id",
            "causal_explanation",
            "min_graph_depth",
            "min_events",
        ],
    )

    def format_item(self, item: Question, idx: int, **context) -> str:
        return f"{idx}. {item.question_text}"

    def get_instruction(self, **kwargs) -> str:
        return self.get_agent_prompt(**kwargs)

    def get_agent_prompt(
        self,
        question: Question,
        actual_outcome_event_id: str,
        min_graph_depth: int = SATISFACTION_DEFAULTS.min_graph_depth,
        min_events: int = SATISFACTION_DEFAULTS.min_graph_events,
        **kwargs,
    ) -> str:
        explanation = question.causal_explanation or "No explanation was saved."

        return self.AGENT_TEMPLATE.format(
            question_text=question.question_text,
            resolution_date=self.format_datetime(question.resolution_date),
            ground_truth=str(question.ground_truth),
            actual_outcome_event_id=actual_outcome_event_id,
            causal_explanation=explanation,
            min_graph_depth=min_graph_depth,
            min_events=min_events,
        )
