"""Web search.

Three backends:
  - duckduckgo  (no key, HTML scrape)
  - tavily      (high-quality search API; requires TAVILY_API_KEY)
  - serper      (Google via serper.dev; requires SERPER_API_KEY)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from backend.config import settings
from backend.core.logger import logger


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = ""


async def web_search(query: str, *, k: int = 6) -> list[SearchResult]:
    if not settings.search_enabled:
        return []
    backend = settings.search_backend.lower()
    try:
        if backend == "tavily" and settings.tavily_api_key:
            return await _tavily(query, k)
        if backend == "serper" and settings.serper_api_key:
            return await _serper(query, k)
        return await _duckduckgo(query, k)
    except Exception as exc:
        logger.warning(f"web_search failed ({backend}): {exc}")
        return []


# ------------------------------------------------------------- duckduckgo
async def _duckduckgo(query: str, k: int) -> list[SearchResult]:
    from bs4 import BeautifulSoup
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 Arajim-Jarvis"}) as c:
        r = await c.post("https://html.duckduckgo.com/html/",
                         data={"q": query})
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[SearchResult] = []
    for div in soup.select(".result")[:k]:
        title_a = div.select_one("a.result__a")
        snippet = div.select_one(".result__snippet")
        if not title_a:
            continue
        out.append(SearchResult(
            title=title_a.get_text(strip=True),
            url=title_a.get("href", ""),
            snippet=snippet.get_text(strip=True) if snippet else "",
            source="duckduckgo",
        ))
    return out


# ------------------------------------------------------------------- tavily
async def _tavily(query: str, k: int) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "max_results": k,
                "search_depth": "advanced",
            },
        )
    data = r.json()
    return [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", "")[:400],
            source="tavily",
        )
        for item in data.get("results", [])[:k]
    ]


# ------------------------------------------------------------------- serper
async def _serper(query: str, k: int) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"},
            json={"q": query, "num": k},
        )
    data = r.json()
    out: list[SearchResult] = []
    for item in (data.get("organic") or [])[:k]:
        out.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            source="serper",
        ))
    return out


async def fetch_clean(url: str, *, max_chars: int = 8_000) -> str:
    """Fetch a URL and return readable text."""
    from bs4 import BeautifulSoup
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 Arajim-Jarvis"}) as c:
            r = await c.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return text[:max_chars]
    except Exception as exc:
        logger.warning(f"fetch_clean({url}) failed: {exc}")
        return ""
