"""HTTP tool executor.

Behaviour:
  * `headers` now come from a merged (secret + direct) dict — the
    orchestrator hands them in pre-merged.
  * Robust response handling: non-2xx responses return a structured
    error, JSON parsing is wrapped, and the agent gets a consistent
    shape regardless of what went wrong.
  * Exponential-backoff retry on transient failures (5xx, network
    errors). 4xx is NOT retried (client error, not transient).
  * Resolved-IP SSRF check: at request time, the resolved IP of the
    target host is checked against the private/loopback/link-local
    deny-list. This blocks DNS-rebinding attacks where a public hostname
    resolves to an internal IP.

LLM-facing description (`project_for_llm`) still strips operational
fields (URL, body, params) — unchanged.
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any, Optional

import httpx

from app.schemas.tool import HTTPMethod, ToolConfig, ToolForLLM, _is_blocked_host


# Status codes we retry. 4xx is a client error — retrying won't help.
_RETRYABLE_STATUS = frozenset({502, 503, 504, 429})
_MAX_RETRIES = 3
_BASE_BACKOFF = 0.5  # seconds; doubled per attempt


class HTTPExecutor:
    def __init__(
        self,
        method: HTTPMethod,
        url: str,
        headers: Optional[dict[str, str]] = None,
        query_params: Optional[dict[str, Any]] = None,
        body: Optional[Any] = None,
        timeout: int = 30,
        allow_internal_urls: bool = False,
        max_retries: int = _MAX_RETRIES,
    ):
        self.method = method.upper() if isinstance(method, str) else method
        self.url = url
        # CRITICAL: don't silently fall back to {} — be explicit
        self.headers = dict(headers) if headers else {}
        self.query_params = query_params or {}
        self.body = body
        self.timeout = timeout
        self.allow_internal_urls = allow_internal_urls
        self.max_retries = max(0, max_retries)

    async def __call__(
        self,
        query: Optional[dict[str, Any]] = None,
        body: Optional[Any] = None,
        focus_query: Optional[str] = None,
    ) -> dict[str, Any]:
        params = {**self.query_params, **(query or {})}
        json_body = body if body is not None else self.body

        # Resolved-IP SSRF check (defeats DNS rebinding to a private IP).
        ssrf_error = self._ssrf_check_resolved_ip()
        if ssrf_error:
            return {
                "status_code": 0,
                "error": ssrf_error,
                "response": None,
            }

        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,  # SSRF: don't chase redirects to private IPs
                ) as client:
                    response = await client.request(
                        method=self.method,
                        url=self.url,
                        headers=self.headers,
                        params=params,
                        json=json_body,
                    )
            except httpx.TimeoutException:
                last_error = f"request timed out after {self.timeout}s"
                await self._sleep_backoff(attempt)
                continue
            except httpx.RequestError as e:
                last_error = f"network error: {e}"
                await self._sleep_backoff(attempt)
                continue

            # Got a response — decide whether to retry.
            if response.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                last_error = f"HTTP {response.status_code} (will retry)"
                await self._sleep_backoff(attempt)
                continue

            return self._format_response(response, focus_query)

        # All retries exhausted.
        return {
            "status_code": 0,
            "error": last_error or "all retries failed",
            "response": None,
        }

    # ---------------------------------------------------------- internals

    def _format_response(
        self, response: httpx.Response, focus_query: Optional[str]
    ) -> dict[str, Any]:
        # Parse body safely. JSON content-type with malformed JSON falls
        # back to text rather than crashing the tool.
        content_type = response.headers.get("content-type", "")
        try:
            if "application/json" in content_type:
                try:
                    data = response.json()
                except (json.JSONDecodeError, ValueError):
                    data = response.text
            else:
                data = response.text
        except Exception as e:
            data = f"<failed to read response body: {e}>"

        # 4xx/5xx → return as a structured error so the agent can
        # react (and so we don't pretend it was a success).
        if response.status_code >= 400:
            return {
                "status_code": response.status_code,
                "error": f"HTTP {response.status_code}",
                "response": data,
            }

        # Optional summarization for large 2xx bodies.
        if focus_query:
            try:
                from app.services.text_summarizer import summarize_large_response

                data = summarize_large_response(data, focus_query)
            except Exception:
                # Summarization is best-effort, never fatal.
                pass

        return {"status_code": response.status_code, "response": data}

    async def _sleep_backoff(self, attempt: int) -> None:
        """Exponential backoff. attempt is 0-indexed."""
        if attempt >= self.max_retries:
            return
        await asyncio.sleep(_BASE_BACKOFF * (2 ** attempt))

    def _ssrf_check_resolved_ip(self) -> Optional[str]:
        """Resolve the URL's hostname and check the IP against the
        SSRF deny-list. Returns an error string or None.
        """
        if self.allow_internal_urls:
            return None

        from urllib.parse import urlparse

        parsed = urlparse(self.url)
        hostname = parsed.hostname
        if not hostname:
            return "url has no hostname"

        # Try to resolve. If DNS fails, let httpx surface the error
        # normally — we don't want to block legitimate tools when DNS
        # is just flaky.
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return None

        for family, _type, _proto, _canon, sockaddr in infos:
            ip_str = sockaddr[0]
            blocked, reason = _is_blocked_host(ip_str)
            if blocked:
                return f"tool url resolves to a blocked address: {reason}"
        return None


def build_executor(
    tool: ToolConfig,
    headers: Optional[dict[str, str]] = None,
) -> HTTPExecutor:
    """Build an `HTTPExecutor` for a validated `ToolConfig`.

    `headers` is the merged dict (secret + direct) produced by
    `tool_service.build_langchain_tool`.
    """
    return HTTPExecutor(
        method=tool.method,
        url=tool.url,
        headers=headers or {},
        query_params=tool.query_params,
        body=tool.body,
        timeout=tool.timeout,
        allow_internal_urls=tool.allow_internal_urls,
    )


def project_for_llm(tool: ToolConfig) -> ToolForLLM:
    """Build the LLM-facing description. NEVER includes headers, full URL,
    body, or any operational fields.
    """
    return ToolForLLM(
        name=tool.name,
        summary=tool.summary or f"{tool.method} request",
        method=tool.method,
        args_schema={
            "query": {"type": "object", "description": "Query parameters for the request"},
            "body": {"type": "object", "description": "Request body (for POST/PUT/PATCH)"},
            "focus_query": {
                "type": "string",
                "description": "Optional filter for the response. NOT sent to the server.",
            },
        },
    )
