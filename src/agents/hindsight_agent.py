from typing import Optional

from src.agents.base import BaseAgent
from src.config import Config, get_config
from smolagents import CodeAgent, LiteLLMModel
from src.tools import (
    # Evidence
    ArticleCollectorTool,
    WebFetchTool,
    WebSearchTool,
    # Inspector
    ArticleInspectorTool,
    GraphInspectorTool,
    # NL Explanation
    SaveExplanationTool,
)
from src.pipelines.prompts.hindsight_causal_analysis import (
    EVIDENCE_AGENT_DESCRIPTION,
)


class HindsightAgent(BaseAgent):
    """Manager agent for building deep causal explanations with hindsight.

    This agent orchestrates:
    1. Evidence collection (delegated to Evidence Agent)
    2. Writing a natural-language causal explanation (save_explanation)

    The GraphBuilderAgent converts the saved explanation into a structured
    graph asynchronously.
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

        managed_agents = [evidence_agent]

        # Manager tools: coordination + save explanation
        tools = tools + [
            GraphInspectorTool(db_path=db_path, question_id=question_id),
            ArticleInspectorTool(db_path=db_path, question_id=question_id),
            SaveExplanationTool(db_path=db_path, question_id=question_id),
        ]

        super().__init__(
            config=config,
            tools=tools,
            max_steps=max_steps,
            is_code=is_code,
            managed_agents=managed_agents,
        )
