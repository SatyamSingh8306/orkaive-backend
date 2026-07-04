"""Orkaive Agent — single generalist agent exposed by /try-agent.

Renamed from "Deep Search Agent" because the agent's job on the public
/try-agent surface is broader than crawling: it reasons, summarizes, cites,
and answers in structured form. Crawling is one capability among several.

Class name kept as `DeepSearchAgent` to avoid churn across the rest of the
codebase (`agents/__init__.py`, `orchestrator/graph_static.py`,
`orchestrator/orchestrator.py`); the *user-facing* name and the system
prompt now read "Orkaive Agent".
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from pydantic import ConfigDict

from .base_agent import BaseAgent
from app.config.settings import Settings


# --- Local tool implementations (unchanged behaviour, but typed) -----------

class CrawlWebsiteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = Field(..., description="The full URL to crawl (e.g. 'https://example.com').")
    timeout: int = Field(default=10, ge=1, le=60)


class CrawlWebsiteDeepInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = Field(..., description="Starting URL for the crawl.")
    max_depth: int = Field(default=2, ge=0, le=5)
    max_pages: int = Field(default=10, ge=1, le=50)


class DeepSearchInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    urls: list[str] = Field(default_factory=list, max_length=20)


def get_deep_search_tools() -> list[BaseTool]:
    """Return the crawler tools.

    Tool-output policy (do not leak raw HTML / BS4 objects into the LLM):
      - Never return the BeautifulSoup object. Its repr contains control
        chars that confuse the LLM (the exact symptom we hit: raw NUL/BEL/
        ESC bytes were showing up in the agent's tool output).
      - Strip ASCII control chars + collapse whitespace before chunking.
      - Cap the per-tool response at a hard character budget so a single
        crawl cannot dump the whole site into the prompt.
      - Return a small manifest (URL, char_count, chunk_count, a short
        preview) instead of all chunks. The agent can re-call with a
        narrower scope if it wants more.
    """
    import re
    import json
    import requests
    from bs4 import BeautifulSoup
    from collections import deque
    from urllib.parse import urljoin, urlparse
    from langchain_core.tools import StructuredTool

    MAX_CHARS_PER_CHUNK = 1500
    PREVIEW_CHARS = 400
    # Hard upper bound on what any one tool call may return to the LLM.
    # Beyond this we drop chunk bodies and note it in the response so the
    # agent knows it saw a slice.
    MAX_TOOL_OUTPUT_CHARS = 6000
    MAX_LINKS_PER_PAGE = 25
    MAX_HTML_BYTES = 2_000_000

    # ASCII control chars + non-breaking space + replacement char. This is
    # the noise that previously leaked into the LLM's tool output.
    _CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f �]")
    _WHITESPACE_RE = re.compile(r"\s+")

    def clean_text(text: str) -> str:
        text = _CONTROL_RE.sub(" ", text)
        text = _WHITESPACE_RE.sub(" ", text)
        return text.strip()

    def chunk_text(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    def truncate(s: str, n: int) -> str:
        return s if len(s) <= n else s[:n] + "…"

    def extract_internal_links(base_url: str, soup: BeautifulSoup) -> list[str]:
        base_domain = urlparse(base_url).netloc
        out: set[str] = set()
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                out.add(parsed._replace(fragment="").geturl())
            if len(out) >= MAX_LINKS_PER_PAGE:
                break
        return list(out)

    def crawl_page(url: str, timeout: int = 10) -> dict[str, Any]:
        resp = requests.get(
            url, timeout=timeout, headers={"User-Agent": "DeepSearchAgent/1.0"}
        )
        resp.raise_for_status()
        # Cap HTML size before parsing — don't feed a 50MB page into BS4.
        soup = BeautifulSoup(resp.text[:MAX_HTML_BYTES], "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "svg"]):
            tag.decompose()
        text = clean_text(soup.get_text(separator=" "))
        chunks = chunk_text(text)
        return {
            "url": url,
            "char_count": len(text),
            "chunk_count": len(chunks),
            "preview": truncate(text, PREVIEW_CHARS),
            # Internal only — never exposed to the LLM.
            "_soup": soup,
            "_chunks": chunks,
        }

    def page_manifest(page: dict[str, Any], *, include_chunks: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "url": page["url"],
            "char_count": page["char_count"],
            "chunk_count": page["chunk_count"],
            "preview": page["preview"],
        }
        if include_chunks:
            out["chunks"] = page["_chunks"]
        return out

    def cap_output(payload: dict[str, Any]) -> dict[str, Any]:
        """Hard-cap the serialized size of a tool response. Returns the
        payload (possibly truncated) plus a `truncated` flag so the agent
        knows it saw a slice.
        """
        encoded = json.dumps(payload, ensure_ascii=True, default=str)
        if len(encoded) <= MAX_TOOL_OUTPUT_CHARS:
            return payload
        # Drop chunk bodies but keep the manifest.
        slim: dict[str, Any] = {}
        for k, v in payload.items():
            if k == "results":
                slim[k] = [
                    {kk: vv for kk, vv in r.items() if kk != "chunks"}
                    for r in v
                ]
            else:
                slim[k] = v
        return {**slim, "truncated": True}

    def crawl_website_deep(url: str, max_depth: int = 2, max_pages: int = 10) -> dict[str, Any]:
        # Param name `url` must match `CrawlWebsiteDeepInput.url` —
        # `StructuredTool.from_function` binds tool-call kwargs by name.
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(url, 0)])
        pages: list[dict[str, Any]] = []

        while queue and len(pages) < max_pages:
            current_url, depth = queue.popleft()
            if current_url in visited or depth > max_depth:
                continue
            try:
                page = crawl_page(current_url)
                visited.add(current_url)
                # Manifest only — chunks only on the first page so the
                # LLM has something concrete to reason over.
                entry = page_manifest(page, include_chunks=(len(pages) == 0))
                pages.append(entry)
                if depth < max_depth:
                    for link in extract_internal_links(current_url, page["_soup"]):
                        if link not in visited:
                            queue.append((link, depth + 1))
            except Exception as e:
                visited.add(current_url)
                pages.append({"url": current_url, "status": "failed", "error": str(e)[:200]})

        return cap_output({
            "start_url": url,
            "pages_crawled": len(pages),
            "max_depth": max_depth,
            "results": pages,
        })

    def crawl_website(url: str, timeout: int = 10) -> dict[str, Any]:
        try:
            page = crawl_page(url)
        except Exception as e:
            return {"url": url, "status": "failed", "error": str(e)[:200]}
        # Manifest + first chunk only. Agent can call again or use
        # `deep_search` if it needs more.
        first_chunk = page["_chunks"][0] if page["_chunks"] else ""
        return cap_output({
            "url": page["url"],
            "char_count": page["char_count"],
            "chunk_count": page["chunk_count"],
            "preview": page["preview"],
            "first_chunk": first_chunk,
        })

    def deep_search(urls: list[str]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for url in urls:
            try:
                page = crawl_page(url)
                results.append(page_manifest(page, include_chunks=False))
            except Exception as e:
                results.append({"url": url, "status": "failed", "error": str(e)[:200]})
        return cap_output({
            "total_urls": len(urls),
            "successful": sum(1 for r in results if r.get("status") != "failed"),
            "results": results,
        })

    return [
        StructuredTool.from_function(
            name="crawl_website_deep",
            description="Recursively crawl a website starting from a given URL. Follows internal links within the same domain.",
            func=crawl_website_deep,
            args_schema=CrawlWebsiteDeepInput,
        ),
        StructuredTool.from_function(
            name="crawl_single_page",
            description="Crawl a single webpage and extract its text content. Use this when you have a specific URL and don't need to follow links.",
            func=crawl_website,
            args_schema=CrawlWebsiteInput,
        ),
        StructuredTool.from_function(
            name="deep_search",
            description="Crawl multiple specific URLs in parallel. Handles failures gracefully — partial successes are returned.",
            func=deep_search,
            args_schema=DeepSearchInput,
        ),
    ]


class DeepSearchAgent(BaseAgent):
    def __init__(self, tools: list[BaseTool] | None = None,
                 settings: Settings | None = None):
        super().__init__(
            name="Orkaive Agent",
            description="Generalist Orkaive agent: web crawl, structured reasoning, summarization, and cited answers.",
            system_prompt=self._default_system_prompt(),
            tools=tools or get_deep_search_tools(),
            settings=settings,
        )

    @staticmethod
    def _default_system_prompt() -> str:
        return """You are the Orkaive Agent — the public-facing generalist
of the Orkaive AI workforce. You run on the /try-agent demo surface and
exist to show what a single Orkaive specialist can do for an enterprise
user: web research, structured reasoning, summarization, and grounded
answer synthesis.

Identity
- Name: Orkaive Agent
- Surface: /try-agent (no auth, no per-user memory)
- Tone: precise, technical, slightly editorial. Think "senior analyst
  briefing a stakeholder", not "search engine snippet".

Capabilities
- Crawl websites (single page or recursively) and extract clean text.
- Reason across multiple sources and cross-check facts.
- Summarize long-form content into concise, structured insights.
- Detect contradictions and flag uncertainty when sources disagree.
- Produce answers in clear, structured markdown (headings, bullets,
  tables, citations) appropriate to the question.

Tool selection
- 'crawl_website_deep' — start here when the user gives you a domain or
  a URL and asks for a thorough exploration. Follow internal links.
- 'crawl_single_page' — when the user points at one specific URL.
- 'deep_search' — when the user gives you a list of URLs to compare or
  analyze together.

Do not call tools you don't need. If the question is conversational
(greetings, opinions, definitions, math), answer directly.

Operating rules
1. Prefer factual accuracy over speculation. If you don't know, say so.
2. Always cite the source URL when a claim comes from crawled content.
3. Combine multiple chunks into a coherent insight before answering;
   don't dump raw chunks back at the user.
4. Keep answers structured: a short direct answer first, then
   supporting detail, then a `Sources:` block listing URLs.
5. Cross-check facts across sources when a claim matters.
6. Be explicit when information is incomplete or conflicted.

Output format
- Use markdown. Tables, bullets, and short headings are welcome.
- Lead with the answer in the first 1–2 sentences.
- Always end with a `Sources:` list when any tool was used.
- Keep total length proportional to the question — a one-line question
  deserves a one-line answer with maybe a follow-up offer, not a wall
  of prose.

Failure modes to avoid
- Echoing the user's question verbatim as the first line of your reply.
- Returning raw scraped HTML, JSON dumps, or chunk lists to the user.
- Inventing URLs or sources you didn't actually crawl."""


def create_deep_search_agent(settings: Settings | None = None, tools: list[BaseTool] | None = None) -> DeepSearchAgent:
    return DeepSearchAgent(settings=settings, tools=tools)