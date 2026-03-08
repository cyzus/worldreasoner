from typing import Optional

from src.agents.base import BaseAgent
from src.config import Config, get_config
from smolagents import CodeAgent, LiteLLMModel
from src.tools import (
    # Evidence
    ArticleRetrievalTool,
    ArticleCollectorTool,
    WebFetchTool,
    WebSearchTool,
    # Graph and Reasoning
    EventDetailsTool,
    EventIdentifierTool,
    CausalReasonerTool,
    GraphInspectorTool,
    RecordOutcomeImpactTool,
    DeleteEventTool,
    DeleteHypothesisTool,
    # Inspector
    ArticleInspectorTool,
    QuestionArticlesTool,
    QuestionEventsTool,
)
from src.pipelines.prompts.hindsight_causal_analysis import (
    EVIDENCE_AGENT_DESCRIPTION,
    GRAPH_AGENT_DESCRIPTION,
)


class HindsightAgent(BaseAgent):
    """Manager agent for building deep causal explanations with hindsight.

    This agent orchestrates:
    1. Evidence collection (delegated to Evidence Agent)
    2. Deep causal graph building (delegated to Causal Analysis Agent)
    3. Quality evaluation and iteration
    """

    def __init__(
        self,
        config: Config = None,
        tools: list = [],
        max_steps: int = 30,
        is_code: bool = True,
        db_path: str = "worldreasoner.db",
        question_id: Optional[str] = None,
        target_event_id: Optional[str] = None,
    ):
        """Initialize the HindsightAgent.

        Args:
            config: Configuration object
            tools: Additional tools for the manager agent
            max_steps: Maximum steps for the manager agent
            is_code: Whether to use CodeAgent
            db_path: Path to the database
            question_id: Question ID for provenance tracking (passed to all tools)
            target_event_id: Target event ID for causal graph building
        """
        # Initialize config and model first (needed for managed agents)
        if config is None:
            config = get_config()

        self.question_id = question_id
        self.target_event_id = target_event_id

        llm_model = LiteLLMModel(
            model_id=config.llm.model,
            **config.llm.model_dump(
                exclude={"model", "embedding_model"}, exclude_none=True
            ),
        )

        # Evidence gathering specialist (web search, article collection)
        # Tools get question_id for provenance tracking
        evidence_agent = CodeAgent(
            model=llm_model,
            tools=[
                ArticleCollectorTool(
                    db_path=db_path, question_id=question_id
                ),  # Provenance-aware
                ArticleInspectorTool(
                    db_path=db_path, question_id=question_id
                ),  # Check coverage
                WebFetchTool(),
                WebSearchTool(
                    db_path=db_path, question_id=question_id
                ),  # Provenance-aware
            ],
            max_steps=15,
            stream_outputs=False,
            additional_authorized_imports=["json"],  # Allow json imports in code agent
            name="evidence_collector",
            description=EVIDENCE_AGENT_DESCRIPTION,
        )

        # Causal analysis specialist (event creation, graph building, depth evaluation)
        # Tools get question_id for provenance tracking
        _causal_agent = CodeAgent(
            model=llm_model,
            tools=[
                QuestionArticlesTool(
                    db_path=db_path, question_id=question_id
                ),  # Get articles for this question
                EventIdentifierTool(
                    db_path=db_path, question_id=question_id
                ),  # Provenance-aware
                EventDetailsTool(db_path=db_path),
                CausalReasonerTool(
                    db_path=db_path, question_id=question_id
                ),  # Provenance-aware
                GraphInspectorTool(
                    db_path=db_path, question_id=question_id
                ),  # Provenance-aware
                RecordOutcomeImpactTool(
                    db_path=db_path, question_id=question_id
                ),  # Record outcome impact natively
                DeleteEventTool(db_path=db_path),
                DeleteHypothesisTool(db_path=db_path),
                ArticleRetrievalTool(db_path=db_path),
                ArticleInspectorTool(
                    db_path=db_path, question_id=question_id
                ),  # Check coverage
                QuestionEventsTool(
                    db_path=db_path, question_id=question_id
                ),  # Get events and outcomes for this question
            ],
            max_steps=30,  # More steps for iterative graph building
            stream_outputs=False,
            additional_authorized_imports=["json"],  # Allow json imports in code agent
            name="causal_analyzer",
            description=GRAPH_AGENT_DESCRIPTION,
        )

        managed_agents = [evidence_agent]

        # Manager tools (high-level coordination)
        tools = tools + [
            GraphInspectorTool(db_path=db_path, question_id=question_id),
            ArticleInspectorTool(db_path=db_path, question_id=question_id),
        ]

        super().__init__(
            config=config,
            tools=tools,
            max_steps=max_steps,
            is_code=is_code,
            managed_agents=managed_agents,
        )
