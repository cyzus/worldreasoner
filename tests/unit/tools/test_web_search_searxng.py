"""SearXNG request configuration tests."""

from unittest.mock import Mock

from src.tools.collectors.web_search import WebSearchTool


def test_structured_search_passes_configured_engine_allowlist(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SEARXNG_BASE_URL", "http://127.0.0.1:2077")
    monkeypatch.setenv("SEARXNG_ENGINES", "duckduckgo,bing,google")
    response = Mock()
    response.status_code = 200
    response.text = '{"results": []}'
    response.raise_for_status.return_value = None
    client = Mock()
    client.get.return_value = response
    monkeypatch.setattr(
        "src.tools.collectors.web_search.httpx.Client",
        lambda **_: client,
    )

    tool = WebSearchTool()
    assert tool._get_structured_results("test query") == []

    client.get.assert_called_once_with(
        "/search",
        params={
            "q": "test query",
            "format": "json",
            "page": 1,
            "engines": "duckduckgo,bing,google",
        },
    )
