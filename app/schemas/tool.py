"""Tool configuration schema (Pydantic v2).

`headers` are stored in MongoDB for non-sensitive cases (Accept,
Content-Type, User-Agent). For sensitive credentials, prefer
`authSecretRef` resolved via `app.services.secret_service` at
execution time.

URLs are validated against SSRF: private IPs, loopback, link-local, and
common metadata endpoints are blocked unless `allow_internal_urls=True`
is set on the tool (admin-only escape hatch for internal integrations).
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


# Hosts that must never be reached from a tool request.
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",   # GCP metadata
    "metadata.azure.com",          # Azure metadata
    "169.254.169.254",             # AWS / Azure IMDS (link-local)
})


def _is_blocked_host(hostname: str) -> tuple[bool, str]:
    """Return (blocked, reason). Empty hostname is not blocked here."""
    if not hostname:
        return False, ""
    lowered = hostname.lower().strip("[]")  # strip IPv6 brackets
    if lowered in _BLOCKED_HOSTNAMES:
        return True, f"hostname {lowered!r} is in the deny-list"
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return False, ""  # not an IP literal, OK
    if ip.is_loopback:
        return True, f"loopback IP {ip} is blocked (SSRF)"
    if ip.is_private:
        return True, f"private IP {ip} is blocked (SSRF)"
    if ip.is_link_local:
        return True, f"link-local IP {ip} is blocked (SSRF)"
    if ip.is_multicast:
        return True, f"multicast IP {ip} is blocked (SSRF)"
    if ip.is_reserved:
        return True, f"reserved IP {ip} is blocked (SSRF)"
    if ip.is_unspecified:
        return True, f"unspecified IP {ip} is blocked (SSRF)"
    return False, ""


class ToolConfig(BaseModel):
    """A single tool attached to a workflow node.

    Headers are stored in MongoDB for non-sensitive cases (Accept,
    Content-Type, User-Agent). For sensitive credentials (Authorization,
    API keys), prefer `authSecretRef` resolved via SecretService.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    workflow_id: str = Field(..., alias="workflowId")
    node_id: str = Field(..., alias="nodeId")
    name: str = Field(..., min_length=1, max_length=128)
    summary: str = Field("", max_length=500, description="LLM-readable description, max 500 chars")
    method: HTTPMethod = "GET"
    url: str = Field(..., min_length=1, max_length=2048)
    # HTTP headers. Stored in Mongo. Use authSecretRef for sensitive values.
    headers: dict[str, str] = Field(default_factory=dict, alias="headers")
    query_params: dict[str, Any] = Field(default_factory=dict, alias="queryParams")
    body: dict[str, Any] | None = None
    timeout: int = Field(30, ge=1, le=300)
    # Admin-only escape hatch: allow this tool to call internal URLs.
    # Default False blocks private/loopback/link-local IPs (SSRF).
    allow_internal_urls: bool = Field(default=False, alias="allowInternalUrls")
    # Auth secret reference — never the secret itself
    auth_secret_ref: str | None = Field(default=None, alias="authSecretRef")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("headers")
    @classmethod
    def _validate_headers(cls, v: dict[str, str]) -> dict[str, str]:
        """Validate header names and values. Prevent HTTP smuggling."""
        if not isinstance(v, dict):
            raise ValueError("headers must be a dict")
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("header keys and values must be strings")
            # Reject CR/LF (HTTP header injection / response splitting)
            if "\r" in key or "\n" in key or "\r" in value or "\n" in value:
                raise ValueError(
                    f"header {key!r} contains invalid line-break characters"
                )
        return v

    @field_validator("url")
    @classmethod
    def _url_must_be_http(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("tool url must start with http:// or https://")
        return v

    @field_validator("name")
    @classmethod
    def _name_safe(cls, v: str) -> str:
        if any(c in v for c in (" ", "\n", "\t")):
            raise ValueError("tool name must not contain whitespace")
        return v

    def assert_url_safe(self) -> None:
        """Runtime SSRF check. Call this at request time, NOT at config
        time, because DNS may have changed since the tool was created.

        Honours `allow_internal_urls` to opt out for internal integrations.
        """
        if self.allow_internal_urls:
            return
        parsed = urlparse(self.url)
        blocked, reason = _is_blocked_host(parsed.hostname or "")
        if blocked:
            raise ValueError(
                f"tool {self.name!r} url is blocked: {reason}. "
                "Set allowInternalUrls=true to override (admin-only)."
            )


class ToolForLLM(BaseModel):
    """The minimal, sanitized projection of a tool given to an LLM.

    Constructed by `ToolService.whitelist_for_llm`. Strips any operational
    details (URL, params, secrets) and returns only what the LLM needs to
    decide whether to call the tool and how.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    summary: str
    method: HTTPMethod
    args_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")
