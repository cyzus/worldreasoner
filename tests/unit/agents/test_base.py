"""Unit tests for agents."""

import pytest
from src.agents.base import BaseAgent
from src.agents.web_agent import WebAgent
from src.config import load_config


class TestBaseAgent:
    """Tests for BaseAgent."""

    def test_base_agent_initialization(self):
        """Test that BaseAgent initializes correctly."""
        agent = BaseAgent()

        assert agent is not None
        assert agent.config is not None
        assert agent.llm_model is not None
        assert agent.agent is not None

    def test_base_agent_with_custom_config(self):
        """Test BaseAgent initialization with custom config."""
        config = load_config()  # Loads from config.example.yaml + config.yaml
        agent = BaseAgent(config=config)

        assert agent.config == config
        assert agent.llm_model is not None

    @pytest.mark.asyncio
    @pytest.mark.integration
    def test_base_agent_run(self):
        """Test BaseAgent can run a simple prompt.

        This test makes actual API calls.
        """
        agent = BaseAgent()
        response = agent.run("Hello, how can you assist me today?")

        # Print response for inspection
        print(f"\n{'=' * 60}")
        print(f"BaseAgent Response: {response}")
        print(f"{'=' * 60}\n")

        assert response is not None
        assert isinstance(response, str)
        assert len(response) > 0


class TestWebAgent:
    """Tests for WebAgent."""

    def test_web_agent_initialization(self):
        """Test that WebAgent initializes correctly with web tools."""
        config = load_config()
        agent = WebAgent(config=config)

        assert agent is not None
        assert agent.config is not None
        assert (
            len(agent.agent.tools) >= 2
        )  # Should have WebSearchTool and VisitWebpageTool

    def test_web_agent_has_web_tools(self):
        """Test that WebAgent has the correct web tools."""
        config = load_config()
        agent = WebAgent(config=config)

        # Get tool names (tools might be objects or strings)
        tool_names = []
        for tool in agent.agent.tools:
            if hasattr(tool, "name"):
                tool_names.append(tool.name)
            elif isinstance(tool, str):
                tool_names.append(tool)

        # Print for debugging
        print(f"\nTool names: {tool_names}")
        print(f"Tools type: {type(agent.agent.tools)}")

        # Check that web tools are present
        assert len(agent.agent.tools) >= 2
        assert any(
            "web" in str(name).lower() or "search" in str(name).lower()
            for name in tool_names
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    def test_web_agent_run(self):
        """Test WebAgent can run a web search task.

        This test makes actual API calls and web requests.
        Mark as slow since it involves web scraping.
        """
        config = load_config()
        agent = WebAgent(config=config)
        response = agent.run("Find the latest news on climate change and summarize it.")

        # Print response for inspection
        print(f"\n{'=' * 60}")
        print(f"WebAgent Response: {response}")
        print(f"{'=' * 60}\n")

        assert response is not None
        assert isinstance(response, str)
        assert len(response) > 0
