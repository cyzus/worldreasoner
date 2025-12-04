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

    def __init__(self, config: Config = None, tools: list = [], max_steps: int = 30,
                 is_code: bool = True, db_path: str = "worldreasoner.db"):

        # Initialize config and model first (needed for managed agents)
        if config is None:
            config = get_config()

        llm_model = LiteLLMModel(
            model_id=config.llm.model,
            **config.llm.model_dump(exclude={"model", "embedding_model"})
        )

        # Evidence gathering specialist (web search, article collection)
        evidence_agent = CodeAgent(
            model=llm_model,
            tools=[
                ArticleCollectorTool(db_path=db_path),  # Persist articles to DB
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
            - Articles are automatically saved to database when collected

            Returns detailed evidence including article ids for causal analysis."""
        )

        # Causal analysis specialist (event creation, graph building, depth evaluation)
        causal_agent = CodeAgent(
            model=llm_model,
            tools=[
                EventIdentifierTool(db_path=db_path),  # Persist events to DB
                EventDetailsTool(db_path=db_path),  # Get details about existing events
                CausalReasonerTool(db_path=db_path),  # Persist hypotheses to DB
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
            2. Otherwise, create target event for the question using event_identifier
            3. Identify immediate causes (level 1) that lead to the target
            4. For each cause, ask "What caused THIS?" and create intermediate events (level 2+)
            5. Use graph_inspector to check depth - iterate if < 2 levels
            6. Build causal chains: Root → Intermediate → Immediate → TARGET
            
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
        