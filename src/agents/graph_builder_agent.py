"""Graph builder agent for translating NL causal explanations into structured graphs."""

from smolagents import CodeAgent, Tool

from src.core.database import GenericDatabase
from src.core.alias_registry import AliasRegistry
from src.domain.models import Question

from src.tools import (
    ArticleRetrievalTool,
    EventIdentifierTool,
    CausalReasonerTool,
    GraphInspectorTool,
    RecordOutcomeImpactTool,
    DeleteEventTool,
    DeleteHypothesisTool,
)
from src.tools.generators.question_articles import QuestionArticlesTool
from src.tools.reasoning.propose_subgraph import ProposeSubgraphTool

from .factory import AgentFactory
from .base import _uses_structured_outputs


class MarkGraphBuiltTool(Tool):
    """Internal tool for the GraphBuilderAgent to mark its job as done."""

    name = "mark_graph_built"
    description = "Mark the graph as fully built and verified."
    inputs = {
        "success": {
            "type": "boolean",
            "description": "True if built successfully, False if unrecoverable errors",
        }
    }
    output_type = "string"

    def __init__(self, db_path: str, question_id: str):
        super().__init__()
        self.db = GenericDatabase(db_path)
        self.question_id = question_id

    def forward(self, success: bool) -> str:
        q = self.db.get(Question, self.question_id)
        if q:
            q.graph_built = success
            if not success:
                q.graph_build_error = "Agent marked graph build as failed."
            self.db.save(Question, q)
            return "Graph marked successfully."
        return "Question not found."


class GraphBuilderAgentFactory(AgentFactory):
    """Factory for the GraphBuilder Agent."""

    @classmethod
    def create(
        cls,
        model_id: str,
        temperature: float = 0.2,
        db_path: str = None,
        question_id: str = None,
        **kwargs,
    ) -> CodeAgent:
        """Create the graph builder agent with specialized graph batching tools."""

        # Instantiate base LLM model
        llm_model = cls._create_model(model_id, temperature)

        # Shared components
        alias_registry = AliasRegistry()

        # We need instances of base tools to pass to propose_subgraph
        evt_tool = EventIdentifierTool(
            db_path=db_path, question_id=question_id, alias_registry=alias_registry
        )
        reason_tool = CausalReasonerTool(
            db_path=db_path, question_id=question_id, alias_registry=alias_registry
        )

        tools = [
            QuestionArticlesTool(
                db_path=db_path,
                question_id=question_id,
                alias_registry=alias_registry,
            ),
            ArticleRetrievalTool(db_path=db_path),
            ProposeSubgraphTool(
                event_identifier_tool=evt_tool,
                causal_reasoner_tool=reason_tool,
                alias_registry=alias_registry,
                db_path=db_path,
                question_id=question_id,
            ),
            # Individual fallback tools using same alias registry
            evt_tool,
            reason_tool,
            RecordOutcomeImpactTool(db_path=db_path, question_id=question_id),
            GraphInspectorTool(db_path=db_path, question_id=question_id),
            DeleteEventTool(db_path=db_path),
            DeleteHypothesisTool(db_path=db_path),
            MarkGraphBuiltTool(db_path=db_path, question_id=question_id),
        ]

        agent_kwargs = dict(
            model=llm_model,
            tools=tools,
            max_steps=kwargs.get("max_steps", 30),
            additional_authorized_imports=["json", "datetime", "typing"],
        )
        if _uses_structured_outputs(llm_model.model_id):
            agent_kwargs["use_structured_outputs_internally"] = True
        agent = CodeAgent(**agent_kwargs)

        return agent
