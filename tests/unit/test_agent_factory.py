"""Unit tests for AgentFactory."""

import pytest
from src.agents.factory import AgentFactory
from src.agents.base import BaseAgent
from src.agents.web_agent import WebAgent
from smolagents import Tool


class DummyTool(Tool):
    """Dummy tool for testing."""

    name = "dummy"
    description = "A dummy tool"
    inputs = {}
    output_type = "string"

    def forward(self):
        return "dummy result"


class TestAgentFactory:
    """Tests for the AgentFactory class."""

    def test_create_web_agent_default(self):
        """Test creating a WebAgent with default settings."""
        agent = AgentFactory.create_web_agent()

        assert isinstance(agent, WebAgent)
        assert agent.agent is not None
        assert (
            len(agent.agent.tools) >= 2
        )  # Should have web_search and web_fetch at minimum

    def test_create_web_agent_with_custom_tools(self):
        """Test creating a WebAgent with custom tools."""
        dummy_tool = DummyTool()
        agent = AgentFactory.create_web_agent(tools=[dummy_tool])

        assert isinstance(agent, WebAgent)
        # Should have web tools + custom tool
        # Tools might be Tool objects or tool names (strings)
        tool_names = [
            tool.name if hasattr(tool, "name") else tool for tool in agent.agent.tools
        ]
        assert "dummy" in tool_names or any(
            "dummy" in str(t).lower() for t in agent.agent.tools
        )

    def test_create_web_agent_custom_max_steps(self):
        """Test creating a WebAgent with custom max_steps."""
        agent = AgentFactory.create_web_agent(max_steps=20)

        assert isinstance(agent, WebAgent)
        assert agent.agent.max_steps == 20

    def test_create_base_agent_default(self):
        """Test creating a BaseAgent with default settings."""
        agent = AgentFactory.create_base_agent()

        assert isinstance(agent, BaseAgent)
        assert agent.agent is not None

    def test_create_base_agent_with_tools(self):
        """Test creating a BaseAgent with custom tools."""
        dummy_tool = DummyTool()
        agent = AgentFactory.create_base_agent(tools=[dummy_tool])

        assert isinstance(agent, BaseAgent)
        # Tools might be Tool objects or tool names (strings)
        tool_names = [
            tool.name if hasattr(tool, "name") else tool for tool in agent.agent.tools
        ]
        assert "dummy" in tool_names or any(
            "dummy" in str(t).lower() for t in agent.agent.tools
        )

    def test_create_base_agent_custom_max_steps(self):
        """Test creating a BaseAgent with custom max_steps."""
        agent = AgentFactory.create_base_agent(max_steps=5)

        assert isinstance(agent, BaseAgent)
        assert agent.agent.max_steps == 5

    def test_create_agent_with_config_web(self):
        """Test dynamic agent creation with 'web' type."""
        agent = AgentFactory.create_agent_with_config(agent_type="web")

        assert isinstance(agent, WebAgent)

    def test_create_agent_with_config_base(self):
        """Test dynamic agent creation with 'base' type."""
        agent = AgentFactory.create_agent_with_config(agent_type="base")

        assert isinstance(agent, BaseAgent)

    def test_create_agent_with_config_invalid_type(self):
        """Test that invalid agent type raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            AgentFactory.create_agent_with_config(agent_type="invalid")

        assert "Unknown agent type" in str(excinfo.value)

    def test_create_agent_with_config_custom_params(self):
        """Test dynamic agent creation with custom parameters."""
        dummy_tool = DummyTool()
        agent = AgentFactory.create_agent_with_config(
            agent_type="base", tools=[dummy_tool], max_steps=7
        )

        assert isinstance(agent, BaseAgent)
        assert agent.agent.max_steps == 7
        # Tools might be Tool objects or tool names (strings)
        tool_names = [
            tool.name if hasattr(tool, "name") else tool for tool in agent.agent.tools
        ]
        assert "dummy" in tool_names or any(
            "dummy" in str(t).lower() for t in agent.agent.tools
        )
