"""Factory for creating configured agents.

Centralizes agent creation to reduce boilerplate and ensure consistent configuration.
"""

from typing import List, Optional
from smolagents import Tool

from src.agents.base import BaseAgent, create_llm_model
from src.agents.web_agent import WebAgent
from src.config import Config, get_config
from src.domain.models.question import Question


class AgentFactory:
    """Factory for creating configured agents with standard settings.

    This factory provides a centralized way to create agents, ensuring
    consistent configuration across the application and reducing boilerplate
    in pipeline stages.

    Usage:
        # Create a web agent with custom tools
        agent = AgentFactory.create_web_agent(tools=[my_tool])

        # Create a base agent
        agent = AgentFactory.create_base_agent(tools=[analysis_tool])
    """

    @classmethod
    def _create_model(cls, model_id: str, temperature: float = 0.2):
        """Create a LiteLLMModel using global config settings."""
        config = get_config()
        return create_llm_model(config, model_id=model_id, temperature=temperature)

    @staticmethod
    def create_web_agent(
        tools: Optional[List[Tool]] = None,
        is_code: bool = False,
        config: Optional[Config] = None,
        max_steps: int = 15,
    ) -> WebAgent:
        """Create a WebAgent with standard configuration.

        WebAgents are specialized for web interactions and come pre-configured
        with web_search and web_fetch tools, plus any custom tools provided.

        Args:
            tools: Optional list of custom tools to add to the agent.
                   Web tools (WebSearchTool, WebFetchTool) are added automatically.
            config: Optional custom configuration. If not provided, uses global config.
            max_steps: Maximum number of steps the agent can take (default: 15).
                      WebAgents need more steps for search → fetch → collect workflows.

        Returns:
            Configured WebAgent instance

        Example:
            >>> collector_tool = ArticleCollectorTool(db_path="db.sqlite")
            >>> agent = AgentFactory.create_web_agent(tools=[collector_tool])
            >>> result = agent.run("Search for AI news articles")
        """
        app_config = config or get_config()
        return WebAgent(
            config=app_config, tools=tools, max_steps=max_steps, is_code=is_code
        )

    @staticmethod
    def create_base_agent(
        tools: Optional[List[Tool]] = None,
        is_code: bool = False,
        config: Optional[Config] = None,
        max_steps: int = 10,
    ) -> BaseAgent:
        """Create a BaseAgent with standard configuration.

        BaseAgents are general-purpose agents without pre-configured tools.
        Use these for analysis, reasoning, and structured data processing tasks.

        Args:
            tools: Optional list of tools to provide to the agent
            config: Optional custom configuration. If not provided, uses global config.
            max_steps: Maximum number of steps the agent can take (default: 10)

        Returns:
            Configured BaseAgent instance

        Example:
            >>> event_tool = EventIdentifierTool()
            >>> agent = AgentFactory.create_base_agent(tools=[event_tool])
            >>> result = agent.run("Analyze these articles for events")
        """
        app_config = config or get_config()
        return BaseAgent(
            config=app_config, tools=tools, max_steps=max_steps, is_code=is_code
        )

    @staticmethod
    def create_forecast_agent(
        question: Question,
        simulated_date: str,
        knowledge_cutoff: str,
        tools: Optional[List[Tool]] = None,
        config: Optional[Config] = None,
        db_path: str = None,
        mode: str = "container",
        enable_causal_tools: bool = False,
        max_steps: int = 15,
    ):
        """Create a ForecastAgent with standard configuration.

        ForecastAgents are specialized for forecasting tasks and require
        question context, simulated date, and knowledge cutoff information.
        They connect to MCP servers with custom headers for context.

        Args:
            question: The Question object containing forecast question details
            simulated_date: The simulated date for the forecast (ISO format)
            knowledge_cutoff: The knowledge cutoff date (ISO format)
            tools: Optional list of custom tools to add to the agent.
                   MCP tools are added automatically based on question context.
            config: Optional custom configuration. If not provided, uses global config.
            db_path: Path to test/forecast database (optional)
            mode: Forecasting mode - 'knowledge_only', 'container', or 'real_time' (default: 'container')
            enable_causal_tools: Whether to include causal reasoning tools (default: False)
            max_steps: Maximum number of steps the agent can take (default: 15)

        Returns:
            Configured ForecastAgent instance

        Example:
            >>> question = Question(id="q1", title="Will X happen?", ...)
            >>> agent = AgentFactory.create_forecast_agent(
            ...     question=question,
            ...     simulated_date="2024-01-01",
            ...     knowledge_cutoff="2023-12-31",
            ...     tools=[custom_tool]
            ... )
            >>> result = agent.run("Make a forecast")

            >>> # Knowledge-only mode (no research)
            >>> agent = AgentFactory.create_forecast_agent(
            ...     question=question,
            ...     simulated_date="2024-01-01",
            ...     knowledge_cutoff="2023-12-31",
            ...     mode="knowledge_only"
            ... )
        """
        from src.agents.forecast_agent import ForecastAgent

        app_config = config or get_config()
        return ForecastAgent(
            question=question,
            simulated_date=simulated_date,
            knowledge_cutoff=knowledge_cutoff,
            config=app_config,
            db_path=db_path,
            mode=mode,
            enable_causal_tools=enable_causal_tools,
            tools=tools,
            max_steps=max_steps,
        )

    @staticmethod
    def create_agent_with_config(
        agent_type: str,
        tools: Optional[List[Tool]] = None,
        config: Optional[Config] = None,
        max_steps: Optional[int] = None,
        is_code: bool = False,
        # Forecast-specific parameters
        question: Optional[Question] = None,
        simulated_date: Optional[str] = None,
        knowledge_cutoff: Optional[str] = None,
    ):
        """Create an agent based on string type identifier.

        Convenience method for dynamic agent creation based on configuration.

        Args:
            agent_type: Type of agent to create ("web", "base", or "forecast")
            tools: Optional list of tools
            config: Optional custom configuration
            max_steps: Optional max steps (uses defaults if not provided)
            question: Required for forecast agents - the Question object
            simulated_date: Required for forecast agents - simulated date (ISO format)
            knowledge_cutoff: Required for forecast agents - knowledge cutoff date (ISO format)

        Returns:
            Configured agent instance

        Raises:
            ValueError: If agent_type is not recognized or required parameters are missing

        Example:
            >>> # Create a web agent
            >>> agent = AgentFactory.create_agent_with_config(
            ...     agent_type="web",
            ...     tools=[my_tool]
            ... )
            >>> # Create a forecast agent
            >>> agent = AgentFactory.create_agent_with_config(
            ...     agent_type="forecast",
            ...     question=my_question,
            ...     simulated_date="2024-01-01",
            ...     knowledge_cutoff="2023-12-31"
            ... )
        """
        if agent_type == "web":
            kwargs = {"tools": tools, "config": config, "is_code": is_code}
            if max_steps is not None:
                kwargs["max_steps"] = max_steps
            return AgentFactory.create_web_agent(**kwargs)
        elif agent_type == "base":
            kwargs = {"tools": tools, "config": config, "is_code": is_code}
            if max_steps is not None:
                kwargs["max_steps"] = max_steps
            return AgentFactory.create_base_agent(**kwargs)
        elif agent_type == "forecast":
            # Validate required forecast parameters
            if question is None:
                raise ValueError("ForecastAgent requires 'question' parameter")
            if simulated_date is None:
                raise ValueError("ForecastAgent requires 'simulated_date' parameter")
            if knowledge_cutoff is None:
                raise ValueError("ForecastAgent requires 'knowledge_cutoff' parameter")

            kwargs = {
                "question": question,
                "simulated_date": simulated_date,
                "knowledge_cutoff": knowledge_cutoff,
                "tools": tools,
                "config": config,
            }
            if max_steps is not None:
                kwargs["max_steps"] = max_steps
            return AgentFactory.create_forecast_agent(**kwargs)
        else:
            raise ValueError(
                f"Unknown agent type: {agent_type}. "
                f"Must be 'web', 'base', or 'forecast'."
            )
