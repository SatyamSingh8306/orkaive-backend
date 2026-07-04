"""Domain-specific exceptions.

These are translated to HTTP errors by the route layer; nothing outside
`app/routes/*` should catch `HTTPException` directly.
"""

from __future__ import annotations


class OrkaiveError(Exception):
    """Base class for domain errors."""

    code: str = "orkaive_error"
    http_status: int = 500


class NotFoundError(OrkaiveError):
    code = "not_found"
    http_status = 404


class ConflictNotFoundError(NotFoundError):
    """Raised when a conflict queryId is unknown or already resolved."""


class WorkflowNotFoundError(NotFoundError):
    """Raised when a workflow id is unknown."""


class ToolNotFoundError(NotFoundError):
    """Raised when a tool id is unknown."""


class ValidationError(OrkaiveError):
    code = "validation_error"
    http_status = 422


class ToolConfigError(ValidationError):
    """Raised when a tool configuration is invalid or unsafe."""


class WorkflowValidationError(ValidationError):
    """Raised when a workflow definition is invalid."""


class AuthError(OrkaiveError):
    code = "unauthenticated"
    http_status = 401


class AuthorizationError(OrkaiveError):
    code = "forbidden"
    http_status = 403


class UpstreamError(OrkaiveError):
    """Raised when an external service (LLM, Redis, Mongo) fails."""
    code = "upstream_error"
    http_status = 502
