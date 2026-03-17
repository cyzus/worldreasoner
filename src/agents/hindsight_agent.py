from typing import Optional
from datetime import datetime

from src.agents.base import BaseAgent
from src.config import Config, get_config
from smolagents import CodeAgent, LiteLLMModel
from src.tools import (
    # Evidence
    ArticleCollectorTool,
    ArticleRetrievalTool,
    WebFetchTool,
    WebSearchTool,
    # Inspector
    ArticleInspectorTool,
    GraphInspectorTool,
    # NL Explanation
    SaveExplanationTool,
)
from src.tools.generators.question_articles import QuestionArticlesTool
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

        evidence_model_id = config.llm.evidence_model or config.llm.model
        llm_model = LiteLLMModel(
            model_id=evidence_model_id,
            **config.llm.model_dump(
                exclude={"model", "embedding_model", "evidence_model"},
                exclude_none=True,
            ),
        )

        date_instructions = (
            f"Today's date is {datetime.now().strftime('%Y-%m-%d')}. "
            "All question resolution dates and evidence windows are in the past. "
            "Search the web normally — do NOT skip searches assuming events are in the future."
        )

        evidence_agent = CodeAgent(
            model=llm_model,
            tools=[
                ArticleCollectorTool(
                    db_path=db_path, question_id=question_id
                ),
                ArticleInspectorTool(
                    db_path=db_path, question_id=question_id
                ),
                WebFetchTool(),
                WebSearchTool(
                    db_path=db_path, question_id=question_id
                ),
            ],
            max_steps=15,
            stream_outputs=False,
            additional_authorized_imports=["json"],
            name="evidence_collector",
            description=EVIDENCE_AGENT_DESCRIPTION,
            instructions=date_instructions,
        )

        tools = tools + [
                ArticleCollectorTool(
                    db_path=db_path, question_id=question_id
                ),
                ArticleInspectorTool(
                    db_path=db_path, question_id=question_id
                ),  # Check coverage
                ArticleRetrievalTool(db_path=db_path),  # Read full article content
                # WebFetchTool(),
                # WebSearchTool(
                #     db_path=db_path, question_id=question_id
                # ),  # Provenance-aware
                SaveExplanationTool(db_path=db_path, question_id=question_id),
                QuestionArticlesTool(
                    db_path=db_path, question_id=question_id
                ),
        ]

        super().__init__(
            config=config,
            tools=tools,
            max_steps=max_steps,
            is_code=is_code,
            managed_agents=[evidence_agent],
            instructions=date_instructions,
        )
