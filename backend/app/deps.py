from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .auth import Actor, current_actor


def get_db(request: Request) -> Iterator[Session]:
    """One session per request. Commits when the handler finishes, rolls back if it raises.

    Every use is Depends(get_db, scope="function"): the commit happens as soon as the handler returns, BEFORE the response is
    sent and before any background task starts. With the default scope a background task (the AIOS sync) runs while the
    request's changes are still uncommitted and reads stale data. tests/test_aios_sync.py pins this on a real database."""
    db: Session = request.app.state.sessionmaker()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def current_org(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")) -> str:
    """The org this admin request acts for. A person acts for the org they belong to; nobody reaches another org's rows.

    - user: the org in org_members. No membership means 403.
    - local (AUTH_DISABLED, development only): a single "local" org, created on first use.
    - service: X-Org-Id, or the only org when there is exactly one.
    """
    if actor.kind == "user":
        orgs = list(db.scalars(select(m.OrgMember.org_id).where(m.OrgMember.auth_user_id == actor.id)))
        if not orgs:
            raise HTTPException(403, "Your account isn't a member of any organization.")
        if len(orgs) > 1:
            wanted = request.headers.get("X-Org-Id")
            if wanted not in orgs:
                raise HTTPException(400, "You belong to several organizations; send X-Org-Id.")
            return wanted
        return orgs[0]
    if actor.kind == "local":
        from . import services

        return services.get_or_create_org(db, "Local", "local").id
    wanted = request.headers.get("X-Org-Id")
    if wanted:
        if not db.scalar(select(m.Org.id).where(m.Org.id == wanted)):
            raise HTTPException(404, "Organization not found.")
        return wanted
    ids = list(db.scalars(select(m.Org.id)))
    if len(ids) != 1:
        raise HTTPException(400, "Send X-Org-Id: there isn't exactly one organization.")
    return ids[0]


Db = Depends(get_db, scope="function")
Auth = Depends(current_actor)
Org = Depends(current_org)

__all__ = ["Actor", "Auth", "Db", "Org", "Session"]


# ---------------------------------------------------------------- the client side

def portal_ctx(request: Request, db: Session = Depends(get_db, scope="function")):
    """The client behind a portal session token. Every failure is the same 401, so nothing is learned from it."""
    from . import portal

    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    ctx = portal.build_ctx(db, request.app.state.settings, token) if token else None
    if ctx is None:
        raise HTTPException(401, portal.UNAVAILABLE, headers={"WWW-Authenticate": "Bearer"})
    return ctx


def limit_writes(request: Request, ctx) -> None:
    """At most N portal writes a minute per link. Keyed on the link, which a caller can't spoof."""
    limiter = request.app.state.limit_writes
    if not limiter.allow(ctx.link.id):
        raise HTTPException(429, "Too many requests. Try again in a minute.", headers={"Retry-After": str(limiter.retry_after(ctx.link.id))})


PortalCtx = Depends(portal_ctx)
