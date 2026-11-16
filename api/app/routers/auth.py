"""Signed-in teachers: recorded at sign-in by the web, and their account details."""

import asyncio
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, StringConstraints

from app import users
from app.auth import CurrentPrincipal, storage_unavailable

router = APIRouter(tags=["auth"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
GoogleName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class User(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None
    created_at: datetime


class GoogleSignIn(BaseModel):
    """What the web read from Google's verified ID token (KSE domain already checked)."""

    google_sub: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
    first_name: GoogleName = ""
    last_name: GoogleName = ""
    avatar_url: Annotated[str, StringConstraints(max_length=2000)] | None = None


class NamesUpdate(BaseModel):
    first_name: Name
    last_name: Name


@router.post("/auth/sync", response_model=User)
async def sync_user(body: GoogleSignIn, principal: CurrentPrincipal) -> dict[str, Any]:
    """Only the web's server calls this, when a teacher signs in."""
    if principal.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the web app records sign-ins")
    with storage_unavailable():
        return await asyncio.to_thread(
            users.upsert_from_google,
            body.google_sub,
            body.email,
            body.first_name,
            body.last_name,
            body.avatar_url,
        )


@router.get("/me", response_model=User)
async def get_me(principal: CurrentPrincipal) -> dict[str, Any]:
    with storage_unavailable():
        user = await asyncio.to_thread(users.get_user, principal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again")
    return user


@router.patch("/me", response_model=User)
async def update_me(body: NamesUpdate, principal: CurrentPrincipal) -> dict[str, Any]:
    with storage_unavailable():
        user = await asyncio.to_thread(
            users.update_names, principal.user_id, body.first_name, body.last_name
        )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again")
    return user
