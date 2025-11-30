"""Unit tests for WebFetchTool."""

import pytest
import asyncio
from src.tools import WebFetchTool


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
    
    @pytest.mark.asyncio
    async def test_web_fetch_multiple_urls(self):
        """Test fetching from multiple different URLs to verify robustness."""
        tool = WebFetchTool()
        
        # Test URLs with different characteristics
        test_urls = [
            {
                "url": "https://www.example.com",
                "expected_title_contains": "Example Domain",
                "description": "Simple example site"
            },
            {
                "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
                "expected_title_contains": "Artificial intelligence",
                "description": "Wikipedia article"
            },
            {
                "url": "https://www.python.org",
                "expected_title_contains": "Python",
                "description": "Python.org homepage"
            },
            {
                "url": "https://github.com",
                "expected_title_contains": "GitHub",
                "description": "GitHub homepage"
            }
        ]
        
        import json
        results = []
        
        for test_case in test_urls:
            result_json = await tool.forward_async(test_case["url"], timeout=30)
            result = json.loads(result_json)
            results.append(result)
            
            # Verify basic structure
            assert "success" in result, f"Missing 'success' for {test_case['description']}"
            assert "url" in result, f"Missing 'url' for {test_case['description']}"
            assert result["url"] == test_case["url"], f"URL mismatch for {test_case['description']}"
            
            # If fetch succeeded, verify content
            if result["success"]:
                assert "title" in result, f"Missing 'title' for {test_case['description']}"
                assert "markdown" in result, f"Missing 'markdown' for {test_case['description']}"
                assert len(result["markdown"]) > 0, f"Empty markdown for {test_case['description']}"
                
                # Check if expected title content is present (case-insensitive)
                assert test_case["expected_title_contains"].lower() in result["title"].lower(), \
                    f"Expected title to contain '{test_case['expected_title_contains']}' for {test_case['description']}, got: {result['title']}"
            else:
                # If it failed, should have an error message
                assert "error" in result and result["error"] is not None, \
                    f"Failed fetch should have error message for {test_case['description']}"
        
        # Verify we got results for all URLs
        assert len(results) == len(test_urls), "Should have results for all test URLs"
        
        # At least one should succeed (example.com is very reliable)
        success_count = sum(1 for r in results if r["success"])
        assert success_count >= 1, "At least one URL should fetch successfully"
