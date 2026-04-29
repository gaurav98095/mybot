from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import httpx

from mybot.agent.tools.base import Tool
from mybot.config.schema import WebSearchConfig


@dataclass
class _Result:
    title: str
    url: str
    snippet: str


class WebSearchTool(Tool):
    def __init__(self, config: WebSearchConfig | None = None, proxy: str | None = None):
        self._cfg = config or WebSearchConfig()
        self._proxy = proxy

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web and return relevant results with titles, URLs, and snippets. "
            "Use for current events, documentation, news, or any topic needing up-to-date information."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": f"Number of results to return (default {self._cfg.max_results}).",
                    "default": self._cfg.max_results,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, max_results: int | None = None) -> str:
        n = max_results or self._cfg.max_results
        provider = self._cfg.provider.lower()
        dispatch = {
            "duckduckgo": self._duckduckgo,
            "tavily": self._tavily,
            "brave": self._brave,
            "searxng": self._searxng,
            "jina": self._jina,
            "kagi": self._kagi,
        }
        fn = dispatch.get(provider)
        if fn is None:
            return f"error: unsupported provider '{provider}'. Choose from: {', '.join(dispatch)}"

        try:
            results = await fn(query, n)
        except Exception as exc:
            return f"error: {exc}"

        if not results:
            return "No results found."

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.title}")
            lines.append(f"   URL: {r.url}")
            if r.snippet:
                lines.append(f"   {r.snippet}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _client(self) -> httpx.AsyncClient:
        kw: dict[str, Any] = {"timeout": self._cfg.timeout}
        if self._proxy:
            kw["proxy"] = self._proxy
        return httpx.AsyncClient(**kw)

    async def _duckduckgo(self, query: str, n: int) -> list[_Result]:
        from ddgs import DDGS

        def _sync() -> list[dict]:
            kw: dict[str, Any] = {"timeout": self._cfg.timeout}
            if self._proxy:
                kw["proxy"] = self._proxy
            with DDGS(**kw) as ddgs:
                return ddgs.text(query, max_results=n) or []

        hits = await asyncio.get_event_loop().run_in_executor(None, _sync)
        return [
            _Result(
                title=h.get("title", ""),
                url=h.get("href", ""),
                snippet=h.get("body", ""),
            )
            for h in hits
        ]

    async def _tavily(self, query: str, n: int) -> list[_Result]:
        if not self._cfg.api_key:
            raise ValueError("tavily provider requires api_key in config")
        async with self._client() as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": self._cfg.api_key, "query": query, "max_results": n},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            _Result(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in data.get("results", [])
        ]

    async def _brave(self, query: str, n: int) -> list[_Result]:
        if not self._cfg.api_key:
            raise ValueError("brave provider requires api_key in config")
        async with self._client() as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": n},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self._cfg.api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            _Result(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
            )
            for r in data.get("web", {}).get("results", [])
        ]

    async def _searxng(self, query: str, n: int) -> list[_Result]:
        base = self._cfg.base_url.rstrip("/")
        if not base:
            raise ValueError("searxng provider requires base_url in config")
        async with self._client() as client:
            resp = await client.get(
                f"{base}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general",
                    "language": "en",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            _Result(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in data.get("results", [])[:n]
        ]

    async def _jina(self, query: str, n: int) -> list[_Result]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "X-Return-Format": "json",
        }
        if self._cfg.api_key:
            headers["Authorization"] = f"Bearer {self._cfg.api_key}"
        async with self._client() as client:
            resp = await client.get(
                f"https://s.jina.ai/{quote_plus(query)}",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            _Result(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
            )
            for r in data.get("data", [])[:n]
        ]

    async def _kagi(self, query: str, n: int) -> list[_Result]:
        if not self._cfg.api_key:
            raise ValueError("kagi provider requires api_key in config")
        async with self._client() as client:
            resp = await client.get(
                "https://kagi.com/api/v0/search",
                params={"q": query, "limit": n},
                headers={"Authorization": f"Bot {self._cfg.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        items = [d for d in data.get("data", []) if d.get("t") == 0]
        return [
            _Result(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
            )
            for r in items[:n]
        ]
