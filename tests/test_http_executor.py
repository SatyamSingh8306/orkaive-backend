"""Unit tests for `app.tools.http_executor` (HTTPExecutor).

Covers:
  * SSRF (literal + resolved IP) blocks private targets
  * retry on 5xx/429, no retry on 4xx
  * follow_redirects=False
  * headers are sent on the request
  * structured error shape on non-2xx
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.tools.http_executor import HTTPExecutor, project_for_llm
from app.schemas.tool import ToolConfig


def _tool(**overrides) -> ToolConfig:
    base = dict(
        workflowId="wf-1",
        nodeId="node-1",
        name="ping",
        url="https://api.example.com/ping",
    )
    base.update(overrides)
    return ToolConfig.model_validate(base)


def _mk_response(status: int, body, content_type="application/json") -> httpx.Response:
    """Build an httpx.Response without going through the network."""
    if isinstance(body, (dict, list)):
        raw = json.dumps(body).encode()
        content_type = content_type or "application/json"
    elif isinstance(body, str):
        raw = body.encode()
    elif isinstance(body, bytes):
        raw = body
    else:
        raw = str(body).encode()
    req = httpx.Request("GET", "https://api.example.com/ping")
    return httpx.Response(status_code=status, content=raw, headers={"content-type": content_type}, request=req)


class TestProjectForLlm:
    def test_strips_url_body_headers(self):
        t = _tool(url="https://secret.example.com/v1", headers={"X-Internal": "leak"})
        proj = project_for_llm(t)
        d = proj.model_dump()
        assert "url" not in d
        assert "body" not in d
        assert "headers" not in d
        assert d["name"] == "ping"
        assert d["method"] == "GET"
        # schema advertised to the LLM (use alias to match the wire format)
        d_alias = proj.model_dump(by_alias=True)
        assert "query" in d_alias["schema"]
        assert "body" in d_alias["schema"]
        assert "focus_query" in d_alias["schema"]


class TestSsrfCheck:
    async def test_blocks_localhost_by_name(self):
        ex = HTTPExecutor("GET", "http://localhost:8000/admin", max_retries=0)
        out = await ex()
        assert out["status_code"] == 0
        assert "blocked" in out["error"].lower()

    async def test_blocks_loopback_ip(self):
        ex = HTTPExecutor("GET", "http://127.0.0.1/", max_retries=0)
        out = await ex()
        assert out["status_code"] == 0
        assert "blocked" in out["error"].lower()

    async def test_allow_internal_urls_bypasses(self):
        ex = HTTPExecutor(
            "GET", "http://127.0.0.1/", allow_internal_urls=True, max_retries=0
        )
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(return_value=_mk_response(200, {"ok": True}))
            Client.return_value = client
            out = await ex()
        assert out["status_code"] == 200


class TestHeadersSent:
    async def test_merged_headers_passed_through(self):
        ex = HTTPExecutor(
            "GET",
            "https://api.example.com/ping",
            headers={"Authorization": "Bearer x", "X-Tenant": "t1"},
            max_retries=0,
        )
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            response = _mk_response(200, {"ok": True})
            client.request = AsyncMock(return_value=response)
            Client.return_value = client
            await ex()
            kwargs = client.request.await_args.kwargs
            assert kwargs["headers"]["Authorization"] == "Bearer x"
            assert kwargs["headers"]["X-Tenant"] == "t1"


class TestRetry:
    async def test_retries_503_then_succeeds(self):
        ex = HTTPExecutor("GET", "https://api.example.com/x", max_retries=2)
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(side_effect=[
                _mk_response(503, "down"),
                _mk_response(200, {"ok": True}),
            ])
            Client.return_value = client
            with patch("app.tools.http_executor.asyncio.sleep", new=AsyncMock()):
                out = await ex()
        assert out["status_code"] == 200
        assert client.request.await_count == 2

    async def test_no_retry_on_4xx(self):
        ex = HTTPExecutor("GET", "https://api.example.com/x", max_retries=3)
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(return_value=_mk_response(404, "missing"))
            Client.return_value = client
            out = await ex()
        assert out["status_code"] == 404
        # 4xx is NOT retried — exactly one call
        assert client.request.await_count == 1

    async def test_exhausts_retries_on_502(self):
        ex = HTTPExecutor("GET", "https://api.example.com/x", max_retries=2)
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(return_value=_mk_response(502, "bad gateway"))
            Client.return_value = client
            with patch("app.tools.http_executor.asyncio.sleep", new=AsyncMock()):
                out = await ex()
        # All attempts failed; final result is the last response, not a synthesized error
        assert out["status_code"] == 502
        assert client.request.await_count == 3  # initial + 2 retries

    async def test_retries_on_timeout(self):
        ex = HTTPExecutor("GET", "https://api.example.com/x", max_retries=1)
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(side_effect=[
                httpx.TimeoutException("slow"),
                _mk_response(200, {"ok": True}),
            ])
            Client.return_value = client
            with patch("app.tools.http_executor.asyncio.sleep", new=AsyncMock()):
                out = await ex()
        assert out["status_code"] == 200


class TestFollowRedirects:
    async def test_follow_redirects_disabled(self):
        ex = HTTPExecutor("GET", "https://api.example.com/x", max_retries=0)
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(return_value=_mk_response(200, {"ok": True}))
            Client.return_value = client
            await ex()
            Client.assert_called_once()
            kwargs = Client.call_args.kwargs
            # SSRF: must NOT chase redirects to private IPs
            assert kwargs.get("follow_redirects") is False


class TestResponseShape:
    async def test_json_response(self):
        ex = HTTPExecutor("GET", "https://api.example.com/x", max_retries=0)
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(return_value=_mk_response(200, {"hello": "world"}))
            Client.return_value = client
            out = await ex()
        assert out == {"status_code": 200, "response": {"hello": "world"}}

    async def test_4xx_returns_structured_error(self):
        ex = HTTPExecutor("GET", "https://api.example.com/x", max_retries=0)
        with patch("app.tools.http_executor.httpx.AsyncClient") as Client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.request = AsyncMock(return_value=_mk_response(403, {"err": "no"}))
            Client.return_value = client
            out = await ex()
        assert out["status_code"] == 403
        assert "error" in out
        assert out["response"] == {"err": "no"}
