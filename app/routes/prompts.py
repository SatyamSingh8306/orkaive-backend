"""Prompt template versioning routes (admin-only).

A small CRUD over the prompt registry. Requires the standard JWT auth;
in production, layer an admin check on top.

GET    /api/prompts                  list template names
GET    /api/prompts/{name}           list versions + active pointer
GET    /api/prompts/{name}/active    active body
GET    /api/prompts/{name}/{version} specific version body
POST   /api/prompts                  create a new version
POST   /api/prompts/{name}/activate  flip the active pointer
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.routes.auth import get_current_user
from app.schemas.prompt import (
    PromptActivateRequest,
    PromptTemplate,
    PromptUpsertRequest,
    PromptVersion,
)
from app.schemas.user import UserResponse
from app.services.prompt_registry import get_prompt_registry

logger = get_logger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("", response_model=list[str])
async def list_templates(_user: UserResponse = Depends(get_current_user)) -> list[str]:
    return await get_prompt_registry().list_templates()


@router.get("/{name}/versions", response_model=list[int])
async def list_versions(name: str, _user: UserResponse = Depends(get_current_user)) -> list[int]:
    versions = await get_prompt_registry().list_versions(name)
    if not versions:
        # The registry may be empty for a fresh install; that's a 404, not a 500.
        raise HTTPException(status_code=404, detail=f"no versions for prompt {name!r}")
    return versions


@router.get("/{name}/active")
async def get_active(name: str, _user: UserResponse = Depends(get_current_user)) -> dict:
    body = await get_prompt_registry().get_active(name)
    return {"name": name, "body": body}


@router.get("/{name}/{version}")
async def get_version(
    name: str,
    version: int,
    _user: UserResponse = Depends(get_current_user),
) -> dict:
    body = await get_prompt_registry().get_version(name, version)
    if body is None:
        raise HTTPException(
            status_code=404, detail=f"prompt {name!r} version {version} not found"
        )
    return {"name": name, "version": version, "body": body}


@router.post("", response_model=PromptVersion, status_code=status.HTTP_201_CREATED)
async def create_version(
    payload: PromptUpsertRequest,
    _user: UserResponse = Depends(get_current_user),
) -> PromptVersion:
    registry = get_prompt_registry()
    new_version = await registry.create_version(
        name=payload.name,
        body=payload.body,
        description=payload.description,
        created_by=_user.email,
    )
    return PromptVersion(
        name=payload.name,
        version=new_version,
        body=payload.body,
        description=payload.description,
        created_by=_user.email,
        is_active=True,  # create_version auto-activates the first version
    )


@router.post("/{name}/activate", response_model=PromptTemplate)
async def activate(
    name: str,
    payload: PromptActivateRequest,
    _user: UserResponse = Depends(get_current_user),
) -> PromptTemplate:
    if payload.name != name:
        raise HTTPException(
            status_code=400,
            detail=f"path name {name!r} does not match body name {payload.name!r}",
        )
    try:
        await get_prompt_registry().activate(name, payload.version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return PromptTemplate(name=name, active_version=payload.version)
