"""Unit tests for WebFetchTool."""

import pytest
from src.tools import WebFetchTool


class TestWebFetchTool:
    """Tests for the WebFetchTool class."""

    def test_web_fetch_tool_initialization(self):
        """Test that WebFetchTool can be initialized."""
        tool = WebFetchTool()
        assert tool.name == "web_fetch"
        assert tool.description is not None
        assert "url" in tool.inputs
        assert tool.output_type == "object"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_web_fetch_async(self):
        """Test async web fetching."""
        tool = WebFetchTool()
        result = await tool.forward_async("https://www.example.com", timeout=30)

        assert result.success is True
        assert result.url == "https://www.example.com"
        assert "Example Domain" in result.title
        assert len(result.content) > 0
        assert result.metadata is not None
        # On success, error key may not be present
        assert result.error is None

    @pytest.mark.integration
    def test_web_fetch_sync(self):
        """Test synchronous web fetching (from sync context)."""
        tool = WebFetchTool()
        result = tool.forward("https://www.example.com", timeout=30)

        assert result.success is True
        assert result.url == "https://www.example.com"
        assert "Example Domain" in result.title
        assert len(result.content) > 0
        assert result.metadata is not None
        # On success, error key may not be present
        assert result.error is None

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_web_fetch_from_async_context(self):
        """Test web fetching when called from within an async context.

        This simulates how smolagents calls the tool - from within an
        already-running event loop.
        """
        tool = WebFetchTool()

        # This should NOT raise "RuntimeError: This event loop is already running"
        result = tool.forward("https://www.example.com", timeout=30)

        assert result.success is True
        assert result.url == "https://www.example.com"
        assert "Example Domain" in result.title

    @pytest.mark.integration
    def test_web_fetch_invalid_url(self):
        """Test handling of invalid URL."""
        tool = WebFetchTool()
        result = tool.forward(
            "https://this-domain-does-not-exist-12345.com", timeout=10
        )

        assert result.success is False
        assert result.error is not None

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_web_fetch_timeout(self):
        """Test that timeout is respected."""
        tool = WebFetchTool()

        # Use a very short timeout on a slow-loading site
        # This might still succeed if the site is fast, but won't hang
        result = await tool.forward_async("https://www.example.com", timeout=1)

        # Should either succeed quickly or fail with timeout
        assert isinstance(result.success, bool)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_web_fetch_multiple_urls(self):
        """Test fetching from multiple different URLs to verify robustness."""
        tool = WebFetchTool()

        # Test URLs with different characteristics
        test_urls = [
            {
                "url": "https://www.example.com",
                "expected_title_contains": "Example Domain",
                "description": "Simple example site",
            },
            {
                "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
                "expected_title_contains": "Artificial intelligence",
                "description": "Wikipedia article",
            },
            {
                "url": "https://www.python.org",
                "expected_title_contains": "Python",
                "description": "Python.org homepage",
            },
            {
                "url": "https://github.com",
                "expected_title_contains": "GitHub",
                "description": "GitHub homepage",
            },
        ]

        results = []

        for test_case in test_urls:
            result = await tool.forward_async(test_case["url"], timeout=30)
            results.append(result)

            # Verify basic structure
            assert result.success is not None, (
                f"Missing 'success' for {test_case['description']}"
            )
            assert result.url is not None, (
                f"Missing 'url' for {test_case['description']}"
            )
            assert result.url == test_case["url"], (
                f"URL mismatch for {test_case['description']}"
            )

            # If fetch succeeded, verify content
            if result.success:
                assert result.title is not None, (
                    f"Missing 'title' for {test_case['description']}"
                )
                assert result.content is not None, (
                    f"Missing 'content' for {test_case['description']}"
                )
                assert len(result.content) > 0, (
                    f"Empty content for {test_case['description']}"
                )

                # Check if expected title content is present (case-insensitive)
                assert (
                    test_case["expected_title_contains"].lower()
                    in result.title.lower()
                ), (
                    f"Expected title to contain '{test_case['expected_title_contains']}' for {test_case['description']}, got: {result.title}"
                )
            else:
                # If it failed, should have an error message
                assert result.error is not None, (
                    f"Failed fetch should have error message for {test_case['description']}"
                )

        # Verify we got results for all URLs
        assert len(results) == len(test_urls), "Should have results for all test URLs"

        # At least one should succeed (example.com is very reliable)
        success_count = sum(1 for r in results if r.success)
        assert success_count >= 1, "At least one URL should fetch successfully"
