"""Tests for agent/tools/web_search.py (all external calls mocked)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mybot.agent.tools.web_search import WebSearchTool
from mybot.config.schema import WebSearchConfig


@pytest.fixture
def tool():
    return WebSearchTool()


class TestWebSearchSchema:
    def test_name(self, tool):
        assert tool.name == "web_search"

    def test_parameters_has_query(self, tool):
        assert "query" in tool.parameters["properties"]
        assert "query" in tool.parameters["required"]

    def test_to_schema_format(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "web_search"


class TestWebSearchProviderErrors:
    async def test_unknown_provider_returns_error(self):
        cfg = WebSearchConfig(provider="nonexistent_provider")
        tool = WebSearchTool(config=cfg)
        result = await tool.execute(query="test")
        assert "error" in result.lower()
        assert "nonexistent_provider" in result

    async def test_tavily_missing_key(self):
        cfg = WebSearchConfig(provider="tavily", api_key="")
        tool = WebSearchTool(config=cfg)
        result = await tool.execute(query="test")
        assert "error" in result.lower()
        assert "api_key" in result.lower() or "key" in result.lower()

    async def test_brave_missing_key(self):
        cfg = WebSearchConfig(provider="brave", api_key="")
        tool = WebSearchTool(config=cfg)
        result = await tool.execute(query="test")
        assert "error" in result.lower()

    async def test_kagi_missing_key(self):
        cfg = WebSearchConfig(provider="kagi", api_key="")
        tool = WebSearchTool(config=cfg)
        result = await tool.execute(query="test")
        assert "error" in result.lower()

    async def test_searxng_missing_base_url(self):
        cfg = WebSearchConfig(provider="searxng", base_url="")
        tool = WebSearchTool(config=cfg)
        result = await tool.execute(query="test")
        assert "error" in result.lower()


class TestDuckDuckGoSearch:
    async def test_results_formatted(self):
        # DDGS is imported locally inside _duckduckgo — patch at the source module
        fake_hits = [
            {"title": "Result One", "href": "https://example.com/1", "body": "Snippet one"},
            {"title": "Result Two", "href": "https://example.com/2", "body": "Snippet two"},
        ]
        with patch("ddgs.DDGS") as MockDDGS:
            instance = MockDDGS.return_value.__enter__.return_value
            instance.text.return_value = fake_hits
            tool = WebSearchTool()
            result = await tool.execute(query="test query")

        assert "Result One" in result
        assert "https://example.com/1" in result
        assert "Snippet one" in result
        assert "Result Two" in result

    async def test_empty_results(self):
        with patch("ddgs.DDGS") as MockDDGS:
            instance = MockDDGS.return_value.__enter__.return_value
            instance.text.return_value = []
            tool = WebSearchTool()
            result = await tool.execute(query="obscure query")

        assert "No results found" in result

    async def test_max_results_respected(self):
        fake_hits = [
            {"title": f"R{i}", "href": f"https://ex.com/{i}", "body": f"S{i}"}
            for i in range(10)
        ]
        captured = {}

        with patch("ddgs.DDGS") as MockDDGS:
            instance = MockDDGS.return_value.__enter__.return_value

            def fake_text(query, max_results):
                captured["max_results"] = max_results
                return fake_hits[:max_results]

            instance.text.side_effect = fake_text
            tool = WebSearchTool()
            await tool.execute(query="test", max_results=3)

        assert captured["max_results"] == 3


class TestTavilySearch:
    async def test_results_parsed(self):
        mock_response = {
            "results": [
                {"title": "T1", "url": "https://t.com/1", "content": "c1"},
                {"title": "T2", "url": "https://t.com/2", "content": "c2"},
            ]
        }
        cfg = WebSearchConfig(provider="tavily", api_key="test-key")
        tool = WebSearchTool(config=cfg)

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(tool, "_client", return_value=mock_client):
            result = await tool.execute(query="test")

        assert "T1" in result
        assert "https://t.com/1" in result


class TestBraveSearch:
    async def test_results_parsed(self):
        mock_response = {
            "web": {
                "results": [
                    {"title": "B1", "url": "https://b.com/1", "description": "d1"},
                ]
            }
        }
        cfg = WebSearchConfig(provider="brave", api_key="brave-key")
        tool = WebSearchTool(config=cfg)

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(tool, "_client", return_value=mock_client):
            result = await tool.execute(query="test")

        assert "B1" in result
        assert "https://b.com/1" in result
