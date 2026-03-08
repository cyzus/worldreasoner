"""Prompts for the GraphBuilderAgent."""

from src.domain.models import Question
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

PROCESS:
1. Fetch the cited articles [art_id] from the explanation using article_retrieval
   to confirm the event dates and that the articles support the claim.
2. Build a structured JSON payload for propose_subgraph. 
   - Define all events with an alias (e.g. "E1:IranStrikes"), title, desc, domain, occurred_date, and article_ids.
   - Define all causal edges using the aliases as "source" and "target", plus relation type, strength (0-1), confidence (0-1), and reasoning.
   - Make sure your final edge points to the ACTUAL OUTCOME EVENT ID above as the target.
3. Call propose_subgraph ONCE with the full JSON structure.
4. Review the response. If any items failed (e.g., chronology or circular reasoning), 
   fix the subgraph JSON and retry the failed items, or use individual tools (event_identifier, causal_reasoner) to patch the gaps.
5. For each significant event, call record_outcome_impact for BOTH outcomes.
6. Call graph_inspector to verify:
   - Max Depth >= 1
   - Actual outcome event is NOT listed as an orphan
7. Call mark_graph_built to complete.
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
        **kwargs,
    ) -> str:

        explanation = question.causal_explanation or "No explanation was saved."

        return self.AGENT_TEMPLATE.format(
            question_text=question.question_text,
            resolution_date=self.format_datetime(question.resolution_date),
            ground_truth=str(question.ground_truth),
            actual_outcome_event_id=actual_outcome_event_id,
            causal_explanation=explanation,
        )
