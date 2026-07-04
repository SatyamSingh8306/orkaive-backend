"""Unit tests for `app.schemas.tool` (ToolConfig, ToolForLLM, SSRF helpers).

Locks down:
  * header validation (CR/LF rejection, type checks)
  * URL must be http(s)://
  * tool name whitespace rejection
  * _is_blocked_host deny-list (loopback, private, metadata, link-local)
  * assert_url_safe honours allow_internal_urls
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.tool import ToolConfig, _is_blocked_host, _BLOCKED_HOSTNAMES


def _tool(**overrides) -> ToolConfig:
    base = dict(
        workflowId="wf-1",
        nodeId="node-1",
        name="my_tool",
        url="https://api.example.com/v1/items",
    )
    base.update(overrides)
    return ToolConfig.model_validate(base)


class TestHeaderValidation:
    def test_accepts_plain_headers(self):
        t = _tool(headers={"Accept": "application/json", "X-Trace-Id": "abc-123"})
        assert t.headers == {"Accept": "application/json", "X-Trace-Id": "abc-123"}

    def test_rejects_crlf_in_value(self):
        with pytest.raises(ValidationError) as exc:
            _tool(headers={"X-Trace": "abc\r\nEvil-Header: x"})
        assert "line-break" in str(exc.value).lower()

    def test_rejects_lf_in_key(self):
        with pytest.raises(ValidationError):
            _tool(headers={"Bad\nKey": "v"})

    def test_rejects_non_string_values(self):
        with pytest.raises(ValidationError):
            _tool(headers={"X-Trace": 123})  # type: ignore[arg-type]

    def test_empty_headers_ok(self):
        assert _tool().headers == {}


class TestUrlValidation:
    def test_rejects_non_http_scheme(self):
        with pytest.raises(ValidationError):
            _tool(url="file:///etc/passwd")

    def test_accepts_http(self):
        assert _tool(url="http://api.example.com").url.startswith("http://")

    def test_accepts_https(self):
        assert _tool(url="https://api.example.com").url.startswith("https://")


class TestNameValidation:
    def test_rejects_whitespace(self):
        with pytest.raises(ValidationError):
            _tool(name="has space")

    def test_rejects_newline(self):
        with pytest.raises(ValidationError):
            _tool(name="bad\nname")


class TestBlockedHosts:
    @pytest.mark.parametrize("host", [
        "localhost",
        "127.0.0.1",
        "127.0.0.53",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # AWS IMDS
        "metadata.google.internal",
        "0.0.0.0",
        "::1",
    ])
    def test_blocked(self, host: str):
        blocked, reason = _is_blocked_host(host)
        assert blocked, f"{host} should be blocked, got reason={reason!r}"
        assert reason  # non-empty reason

    @pytest.mark.parametrize("host", [
        "api.example.com",
        "8.8.8.8",
        "1.1.1.1",
    ])
    def test_allowed(self, host: str):
        blocked, _ = _is_blocked_host(host)
        assert not blocked

    def test_ipv6_brackets_stripped(self):
        blocked, _ = _is_blocked_host("[::1]")
        assert blocked


class TestAssertUrlSafe:
    def test_blocks_private_ip_url(self):
        t = _tool(url="http://127.0.0.1/admin")
        with pytest.raises(ValueError, match="blocked"):
            t.assert_url_safe()

    def test_blocks_localhost_url(self):
        t = _tool(url="http://localhost/admin")
        with pytest.raises(ValueError, match="blocked"):
            t.assert_url_safe()

    def test_allows_public_url(self):
        t = _tool(url="https://api.example.com/v1")
        t.assert_url_safe()  # no raise

    def test_allow_internal_urls_skips_check(self):
        t = _tool(url="http://127.0.0.1/admin", allowInternalUrls=True)
        t.assert_url_safe()  # no raise

    def test_deny_list_holds_well_known_metadata(self):
        # sanity: the constant actually contains what we think it does
        assert "169.254.169.254" in _BLOCKED_HOSTNAMES
        assert "localhost" in _BLOCKED_HOSTNAMES
