from typing import Optional
from datetime import datetime

from src.agents.base import BaseAgent, create_llm_model, _uses_structured_outputs
from src.config import Config, get_config
from smolagents import CodeAgent
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
        if config is None:
            config = get_config()

        self.question_id = question_id
        self.target_event_id = target_event_id

        llm_model = create_llm_model(config)

        date_instructions = (
            f"Today's date is {datetime.now().strftime('%Y-%m-%d')}. "
            "All question resolution dates and evidence windows are in the past. "
            "Search the web normally — do NOT skip searches assuming events are in the future."
        )

        # Evidence gathering specialist (web search, article collection)
        # Tools get question_id for provenance tracking
        evidence_agent_kwargs = dict(
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
            additional_authorized_imports=["json", "datetime", "typing"],
            name="evidence_collector",
            description=EVIDENCE_AGENT_DESCRIPTION,
            instructions=date_instructions,
        )
        if _uses_structured_outputs(llm_model.model_id):
            evidence_agent_kwargs["use_structured_outputs_internally"] = True
        evidence_agent = CodeAgent(**evidence_agent_kwargs)

        tools = tools + [
                ArticleCollectorTool(
                    db_path=db_path, question_id=question_id
                ),  # Provenance-aware
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
