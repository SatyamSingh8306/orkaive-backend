"""Prompt template schema + registry docs.

A `PromptVersion` is one immutable version of one named prompt. A
`PromptTemplate` is the (name, active_version) pair that the rest of
the app uses to look up the right body.

Why versioning?

  * We can A/B test router prompts against eval cases
    (`eval/test_orchestrator.py`) without redeploying.
  * A bad prompt can be rolled back by flipping `active_version` to
    the previous known-good id.
  * Prompts are auditable: the version log shows what the router was
    being told on 2026-07-12 at 14:30 UTC.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PromptVersion(BaseModel):
    """An immutable prompt body, identified by (name, version)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=128)
    version: int = Field(..., ge=1)
    body: str = Field(..., min_length=1)
    description: str = Field("", max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow(), alias="createdAt")
    created_by: Optional[str] = Field(default=None, alias="createdBy")
    is_active: bool = Field(default=False, alias="isActive")


class PromptTemplate(BaseModel):
    """A named prompt template, with one currently-active version."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=128)
    active_version: int = Field(..., ge=1, alias="activeVersion")
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow(), alias="updatedAt")


class PromptUpsertRequest(BaseModel):
    """API: create a new version of a named prompt."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=128)
    body: str = Field(..., min_length=1)
    description: str = Field("", max_length=500)


class PromptActivateRequest(BaseModel):
    """API: flip the active version for a named prompt."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    version: int = Field(..., ge=1)
