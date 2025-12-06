from typing import Optional

from src.agents.base import BaseAgent
from src.config import Config, get_config
from smolagents import CodeAgent, LiteLLMModel
from src.tools import (ArticleRetrievalTool, ArticleCollectorTool,
                       WebFetchTool, WebSearchTool,
                       EventDetailsTool, EventIdentifierTool,
                       CausalReasonerTool, GraphInspectorTool)


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
            **config.llm.model_dump(exclude={"model", "embedding_model"})
        )

        # Evidence gathering specialist (web search, article collection)
        # Tools get question_id for provenance tracking
        evidence_agent = CodeAgent(
            model=llm_model,
            tools=[
                ArticleCollectorTool(db_path=db_path, question_id=question_id),  # Provenance-aware
                WebFetchTool(),
                WebSearchTool(),
            ],
            max_steps=15,
            stream_outputs=True,
            name="evidence_collector",
            description="""Specialist agent for collecting evidence articles.

            Uses adaptive search strategies:
            - Try multiple search queries if initial results are insufficient
            - Broaden time windows if needed
            - Fetch and analyze article content
            - Finally, you MUST use the collector tool to save relevant articles to the database

            Returns detailed evidence including article ids for causal analysis."""
        )

        # Causal analysis specialist (event creation, graph building, depth evaluation)
        # Tools get question_id for provenance tracking
        causal_agent = CodeAgent(
            model=llm_model,
            tools=[
                EventIdentifierTool(db_path=db_path, question_id=question_id),  # Provenance-aware
                EventDetailsTool(db_path=db_path),
                CausalReasonerTool(db_path=db_path, question_id=question_id),  # Provenance-aware
                GraphInspectorTool(db_path=db_path),
                ArticleRetrievalTool(db_path=db_path)
            ],
            max_steps=30,  # More steps for iterative graph building
            stream_outputs=True,
            name="causal_analyzer",
            description="""Specialist agent for building deep causal graphs.

            CRITICAL: Build DEEP multi-level causal chains, not just direct links!

            Process:
            1. If target_event_id is provided, use EventDetailsTool to understand it
            2. Identify immediate causes (level 1) that lead to the target
            3. For each cause, ask "What caused THIS?" and create intermediate events (level 2+)
            4. Use graph_inspector to check depth - iterate if < 2 levels
            5. Build causal chains: Root → Intermediate → Immediate → TARGET

            IMPORTANT: All causal chains must ultimately connect to the target event!
            Use causal_reasoner with the correct target_event_id for final-stage links.

            All events and hypotheses are automatically saved to database.

            Your goal: Create causal graphs with depth >= 3 levels."""
        )

        managed_agents = [evidence_agent, causal_agent]

        # Manager tools (high-level coordination)
        tools = tools + [
            GraphInspectorTool(db_path=db_path)
        ]

        super().__init__(
            config=config,
            tools=tools,
            max_steps=max_steps,
            is_code=is_code,
            managed_agents=managed_agents
        )
        