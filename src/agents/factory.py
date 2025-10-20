"""Factory for creating configured agents.

Centralizes agent creation to reduce boilerplate and ensure consistent configuration.
"""

from typing import List, Optional
from smolagents import Tool

from src.agents.base import BaseAgent
from src.agents.web_agent import WebAgent
from src.utils.config import Config, get_config


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
    
    @staticmethod
    def create_web_agent(
        tools: Optional[List[Tool]] = None,
        config: Optional[Config] = None,
        max_steps: int = 15
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
        return WebAgent(config=app_config, tools=tools, max_steps=max_steps)
    
    @staticmethod
    def create_base_agent(
        tools: Optional[List[Tool]] = None,
        config: Optional[Config] = None,
        max_steps: int = 10
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
        return BaseAgent(config=app_config, tools=tools, max_steps=max_steps)
    
    @staticmethod
    def create_agent_with_config(
        agent_type: str,
        tools: Optional[List[Tool]] = None,
        config: Optional[Config] = None,
        max_steps: Optional[int] = None
    ):
        """Create an agent based on string type identifier.
        
        Convenience method for dynamic agent creation based on configuration.
        
        Args:
            agent_type: Type of agent to create ("web" or "base")
            tools: Optional list of tools
            config: Optional custom configuration
            max_steps: Optional max steps (uses defaults if not provided)
        
        Returns:
            Configured agent instance
        
        Raises:
            ValueError: If agent_type is not recognized
        
        Example:
            >>> agent = AgentFactory.create_agent_with_config(
            ...     agent_type="web",
            ...     tools=[my_tool]
            ... )
        """
        if agent_type == "web":
            kwargs = {"tools": tools, "config": config}
            if max_steps is not None:
                kwargs["max_steps"] = max_steps
            return AgentFactory.create_web_agent(**kwargs)
        elif agent_type == "base":
            kwargs = {"tools": tools, "config": config}
            if max_steps is not None:
                kwargs["max_steps"] = max_steps
            return AgentFactory.create_base_agent(**kwargs)
        else:
            raise ValueError(
                f"Unknown agent type: {agent_type}. "
                f"Must be 'web' or 'base'."
            )
