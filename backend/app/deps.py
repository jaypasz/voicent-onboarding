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


READS = {"GET", "HEAD", "OPTIONS"}


def _resolve_org(request: Request, actor: Actor, db: Session, viewers_may_write: bool) -> str:
    """The org this admin request acts for, and who is acting, for the audit trail (audit.py)."""
    from . import audit

    org = _which_org(request, actor, db, viewers_may_write)
    member = db.get(m.OrgMember, request.state.member_id) if request.state.member_id else None
    label = (member.name or member.email) if member and (member.name or member.email) else actor.label
    audit.acting(db, audit.Who("team", request.state.member_id or actor.id, label if actor.kind != "service" else f"{label} (service)"))
    return org


def _which_org(request: Request, actor: Actor, db: Session, viewers_may_write: bool) -> str:
    """The org this admin request acts for. A person acts for the orgs they belong to; nobody reaches another org's rows.

    - user: their memberships (copied from Voicent-App when tenancy is on, see tenancy.py, plus any made by seed). With
      several, X-Org-Id picks one. A Voicent superuser may pick any org with X-Org-Id, as an admin there.
      Their role is kept on request.state.role; a viewer can look but not change anything.
    - local (AUTH_DISABLED, development only): a single "local" org, created on first use.
    - service: X-Org-Id, or the only org when there is exactly one.
    """
    from . import tenancy

    wanted = request.headers.get("X-Org-Id")
    if actor.kind == "user":
        acc = tenancy.access_for(db, getattr(request.app.state, "directory", None), actor.id, actor.label)
        request.state.superuser = acc.superuser
        if wanted and acc.superuser and wanted not in acc.orgs:
            if not db.scalar(select(m.Org.id).where(m.Org.id == wanted)):
                raise HTTPException(404, "Organization not found.")
            org, role = wanted, "admin"
        elif not acc.orgs:
            if acc.superuser:
                raise HTTPException(400, "Choose an organization to work in.")
            raise HTTPException(403, "Your account isn't a member of any organization.")
        elif wanted in acc.orgs:
            org, role = wanted, acc.orgs[wanted]
        elif len(acc.orgs) == 1:
            org, role = next(iter(acc.orgs.items()))
        else:
            raise HTTPException(400, "You belong to several organizations; send X-Org-Id.")
        request.state.role = role
        request.state.member_id = db.scalar(select(m.OrgMember.id).where(m.OrgMember.org_id == org, m.OrgMember.auth_user_id == actor.id))
        if request.method not in READS and role == "viewer" and not viewers_may_write:
            raise HTTPException(403, "Your role lets you look but not change anything here.")
        return org
    request.state.role, request.state.superuser, request.state.member_id = "admin", actor.kind == "local", None
    if actor.kind == "local":
        from . import services

        return services.get_or_create_org(db, "Local", "local").id
    if wanted:
        if not db.scalar(select(m.Org.id).where(m.Org.id == wanted)):
            raise HTTPException(404, "Organization not found.")
        return wanted
    ids = list(db.scalars(select(m.Org.id)))
    if len(ids) != 1:
        raise HTTPException(400, "Send X-Org-Id: there isn't exactly one organization.")
    return ids[0]


def current_org(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")) -> str:
    return _resolve_org(request, actor, db, viewers_may_write=False)


def self_org(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")) -> str:
    """For what is a person's own (their notifications and their email preference): a viewer may change these too."""
    return _resolve_org(request, actor, db, viewers_may_write=True)


def admin_org(request: Request, org: str = Depends(current_org)) -> str:
    """For settings only an org's admins may change (its brand and senders)."""
    if request.state.role != "admin":
        raise HTTPException(403, "Only an admin of this organization can change that.")
    return org


Db = Depends(get_db, scope="function")
Auth = Depends(current_actor)
Org = Depends(current_org)
AdminOrg = Depends(admin_org)
SelfOrg = Depends(self_org)

__all__ = ["Actor", "AdminOrg", "Auth", "Db", "Org", "SelfOrg", "Session"]


# ---------------------------------------------------------------- the client side

def portal_ctx(request: Request, db: Session = Depends(get_db, scope="function")):
    """The client behind a portal session token. Every failure is the same 401, so nothing is learned from it."""
    from . import portal

    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    ctx = portal.build_ctx(db, request.app.state.settings, token) if token else None
    if ctx is None:
        raise HTTPException(401, portal.UNAVAILABLE, headers={"WWW-Authenticate": "Bearer"})
    from . import audit

    audit.acting(db, audit.Who("client", ctx.contact.id, ctx.contact.name))
    return ctx


def limit_writes(request: Request, ctx) -> None:
    """At most N portal writes a minute per link. Keyed on the link, which a caller can't spoof."""
    limiter = request.app.state.limit_writes
    if not limiter.allow(ctx.link.id):
        raise HTTPException(429, "Too many requests. Try again in a minute.", headers={"Retry-After": str(limiter.retry_after(ctx.link.id))})


PortalCtx = Depends(portal_ctx)
