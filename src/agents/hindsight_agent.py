from typing import Optional

from src.agents.base import BaseAgent
from src.config import Config, get_config
from smolagents import CodeAgent, LiteLLMModel
from src.tools import (ArticleRetrievalTool, ArticleCollectorTool,
                       WebFetchTool, WebSearchTool,
                       EventDetailsTool, EventIdentifierTool,
                       CausalReasonerTool, GraphInspectorTool,
                       ArticleInspectorTool, QuestionArticlesTool)


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
                ArticleInspectorTool(db_path=db_path, question_id=question_id),  # Check coverage
                WebFetchTool(),
                WebSearchTool(),
            ],
            max_steps=15,
            stream_outputs=True,
            additional_authorized_imports=["json"], # Allow json imports in code agent
            name="evidence_collector",
            description="""Specialist agent for collecting evidence articles.

            Uses adaptive search strategies:
            - Try multiple search queries if initial results are insufficient
            - Broaden time windows if needed
            - Fetch and analyze article content
            - Make sure all the articles collected are published BEFORE the resolution date
            - Use article_collector to save relevant articles to the database
            - Use article_inspector to check timeline coverage and identify gaps
            - If gaps exist, collect more articles from those time periods

            IMPORTANT: After collecting, report back the article IDs in this format:
            "Collected articles: [art_xxx, art_yyy, art_zzz]"

            This allows the causal_analyzer to link events to evidence."""
        )

        # Causal analysis specialist (event creation, graph building, depth evaluation)
        # Tools get question_id for provenance tracking
        causal_agent = CodeAgent(
            model=llm_model,
            tools=[
                QuestionArticlesTool(db_path=db_path, question_id=question_id),  # Get articles for this question
                EventIdentifierTool(db_path=db_path, question_id=question_id),  # Provenance-aware
                EventDetailsTool(db_path=db_path),
                CausalReasonerTool(db_path=db_path, question_id=question_id),  # Provenance-aware
                GraphInspectorTool(db_path=db_path, question_id=question_id),  # Provenance-aware
                ArticleRetrievalTool(db_path=db_path),
                ArticleInspectorTool(db_path=db_path, question_id=question_id),  # Check coverage
            ],
            max_steps=30,  # More steps for iterative graph building
            stream_outputs=True,
            additional_authorized_imports=["json"], # Allow json imports in code agent
            name="causal_analyzer",
            description="""Specialist agent for building deep causal graphs.

            CRITICAL: Build DEEP multi-level causal chains, not just direct links!

            FIRST STEP - Get article IDs:
            Call get_question_articles to get all articles
            collected for this question. Save the article_ids list - you MUST use
            these when creating events and causal links!

            Process:
            1. Call get_question_articles to get article IDs
            2. If target_event_id is provided, use EventDetailsTool to understand it
            3. Create events using event_identifier with source_article_ids from step 1
            4. For each cause, ask "What caused THIS?" and create intermediate events
            5. Use causal_reasoner with evidence_article_ids from step 1
            6. Use graph_inspector to check depth - iterate if < 2 levels

            IMPORTANT:
            - Always pass source_article_ids when creating events
            - Always pass evidence_article_ids when creating causal links
            - All chains must connect to the target event

            Your goal: Create causal graphs with depth >= 3 levels, properly linked to evidence."""
        )

        managed_agents = [evidence_agent, causal_agent]

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
            managed_agents=managed_agents
        )
        