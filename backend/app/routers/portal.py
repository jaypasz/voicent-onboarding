"""The client's door. No admin auth here: a client holds a magic link, exchanged for a short-lived session token.

Nothing on this router takes an onboarding id. Which onboarding and which contact is decided by the token alone.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from .. import aios_sync, magic_link, portal
from ..deps import Db, PortalCtx, Session, limit_writes

router = APIRouter(prefix="/portal", tags=["portal"])


class ExchangeIn(BaseModel):
    token: str = Field(max_length=300)


class AnswerIn(BaseModel):
    data: Any


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class UploadIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    size: int = Field(ge=1)
    content_type: str = Field(max_length=100)


def _too_many(limiter, key: str) -> HTTPException:
    return HTTPException(429, "Too many requests. Try again in a minute.", headers={"Retry-After": str(limiter.retry_after(key))})


@router.post("/exchange")
def exchange(body: ExchangeIn, request: Request, db: Session = Db):
    """Swap a link token for a session. Unknown, expired, revoked and not-yet-live links all get the same 401."""
    st = request.app.state
    ip = request.client.host if request.client else "unknown"
    if not st.limit_exchange_ip.allow(ip):
        raise _too_many(st.limit_exchange_ip, ip)
    if not st.limit_exchange_all.allow("all"):
        raise _too_many(st.limit_exchange_all, "all")
    ctx = portal.build_ctx_from_link(db, body.token)
    if ctx is None:
        raise HTTPException(401, portal.UNAVAILABLE, headers={"WWW-Authenticate": "Bearer"})
    ctx.link.last_used_at = magic_link.now()
    session, ttl = magic_link.issue_session(st.settings, ctx.link)
    return {"session": session, "expires_in": ttl}


@router.post("/refresh")
def refresh(request: Request, ctx=PortalCtx):
    limit_writes(request, ctx)
    session, ttl = magic_link.issue_session(request.app.state.settings, ctx.link)
    return {"session": session, "expires_in": ttl}


@router.get("/onboarding")
def get_onboarding(db: Session = Db, ctx=PortalCtx):
    return portal.onboarding_view(db, ctx)


@router.put("/steps/{key}")
def submit(key: str, body: AnswerIn, request: Request, background: BackgroundTasks, db: Session = Db, ctx=PortalCtx):
    limit_writes(request, ctx)
    aios_sync.kick(request, background, ctx.link.org_id, ctx.onboarding.id)  # runs after the answer is saved and the response has gone
    return portal.submit(db, ctx, key, body.data, request.app.state.storage)


@router.post("/steps/{key}/comments", status_code=201)
def comment(key: str, body: CommentIn, request: Request, db: Session = Db, ctx=PortalCtx):
    limit_writes(request, ctx)
    return portal.comment(db, ctx, key, body.body)


@router.post("/steps/{key}/upload-url")
def upload_url(key: str, body: UploadIn, request: Request, db: Session = Db, ctx=PortalCtx):
    limit_writes(request, ctx)
    return portal.upload_url(db, ctx, key, name=body.name, size=body.size, content_type=body.content_type, storage=request.app.state.storage)
