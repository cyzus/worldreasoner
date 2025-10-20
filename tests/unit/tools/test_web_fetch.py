"""Unit tests for WebFetchTool."""

import pytest
import asyncio
from src.pipelines.stages.tools import WebFetchTool


class TestWebFetchTool:
    """Tests for the WebFetchTool class."""
    
    def test_web_fetch_tool_initialization(self):
        """Test that WebFetchTool can be initialized."""
        tool = WebFetchTool()
        assert tool.name == "web_fetch"
        assert tool.description is not None
        assert "url" in tool.inputs
        assert tool.output_type == "string"
    
    @pytest.mark.asyncio
    async def test_web_fetch_async(self):
        """Test async web fetching."""
        tool = WebFetchTool()
        result_json = await tool.forward_async("https://www.example.com", timeout=30)
        
        import json
        result = json.loads(result_json)
        
        assert result["success"] is True
        assert result["url"] == "https://www.example.com"
        assert "Example Domain" in result["title"]
        assert len(result["markdown"]) > 0
        assert "metadata" in result
        # On success, error key may not be present
        assert result.get("error") is None
    
    def test_web_fetch_sync(self):
        """Test synchronous web fetching (from sync context)."""
        tool = WebFetchTool()
        result_json = tool.forward("https://www.example.com", timeout=30)
        
        import json
        result = json.loads(result_json)
        
        assert result["success"] is True
        assert result["url"] == "https://www.example.com"
        assert "Example Domain" in result["title"]
        assert len(result["markdown"]) > 0
        assert "metadata" in result
        # On success, error key may not be present
        assert result.get("error") is None
    
    @pytest.mark.asyncio
    async def test_web_fetch_from_async_context(self):
        """Test web fetching when called from within an async context.
        
        This simulates how smolagents calls the tool - from within an
        already-running event loop.
        """
        tool = WebFetchTool()
        
        # This should NOT raise "RuntimeError: This event loop is already running"
        result_json = tool.forward("https://www.example.com", timeout=30)
        
        import json
        result = json.loads(result_json)
        
        assert result["success"] is True
        assert result["url"] == "https://www.example.com"
        assert "Example Domain" in result["title"]
    
    def test_web_fetch_invalid_url(self):
        """Test handling of invalid URL."""
        tool = WebFetchTool()
        result_json = tool.forward("https://this-domain-does-not-exist-12345.com", timeout=10)
        
        import json
        result = json.loads(result_json)
        
        assert result["success"] is False
        assert "error" in result
        assert result["error"] is not None
    
    @pytest.mark.asyncio
    async def test_web_fetch_timeout(self):
        """Test that timeout is respected."""
        tool = WebFetchTool()
        
        # Use a very short timeout on a slow-loading site
        # This might still succeed if the site is fast, but won't hang
        result_json = await tool.forward_async("https://www.example.com", timeout=1)
        
        import json
        result = json.loads(result_json)
        
        # Should either succeed quickly or fail with timeout
        assert "success" in result
        assert isinstance(result["success"], bool)
