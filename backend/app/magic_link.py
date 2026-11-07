"""A client's way in: a long random link token, exchanged for a short-lived portal session.

Only the SHA-256 of the token is stored; the raw token exists once, in the response that issued it. Every request
with a session token re-checks the link row, so revoking or expiring a link cuts off sessions at once.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import Settings
from .errors import Conflict, Invalid, NotFound

AUDIENCE = "portal"
ALG = "HS256"
MAX_EXTEND_DAYS = 365


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)  # SQLite hands back naive datetimes


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def is_usable(link: m.MagicLink, at: dt.datetime | None = None) -> bool:
    return link.revoked_at is None and _aware(link.expires_at) > (at or now())


# ---------------------------------------------------------------- admin side

def issue_link(db: Session, settings: Settings, org_id: str, onboarding_id: str, contact_id: str) -> tuple[str, m.MagicLink]:
    ob = db.scalar(select(m.Onboarding).where(m.Onboarding.id == onboarding_id, m.Onboarding.org_id == org_id))
    if not ob:
        raise NotFound("Onboarding not found.")
    contact = db.scalar(select(m.Contact).where(m.Contact.id == contact_id, m.Contact.org_id == org_id, m.Contact.client_id == ob.client_id))
    if not contact:
        raise NotFound("Contact not found for this client.")
    if ob.status == "archived":
        raise Conflict("This onboarding is archived.")
    raw = secrets.token_urlsafe(32)
    link = m.MagicLink(
        org_id=org_id, onboarding_id=ob.id, contact_id=contact.id, token_hash=hash_token(raw),
        expires_at=now() + dt.timedelta(days=settings.link_ttl_days),
    )
    db.add(link)
    db.flush()
    return raw, link


def list_links(db: Session, org_id: str, onboarding_id: str) -> list[m.MagicLink]:
    return list(db.scalars(select(m.MagicLink).where(m.MagicLink.org_id == org_id, m.MagicLink.onboarding_id == onboarding_id).order_by(m.MagicLink.created_at)))


def _link(db: Session, org_id: str, onboarding_id: str, link_id: str) -> m.MagicLink:
    link = db.scalar(select(m.MagicLink).where(m.MagicLink.id == link_id, m.MagicLink.org_id == org_id, m.MagicLink.onboarding_id == onboarding_id))
    if not link:
        raise NotFound("Link not found.")
    return link


def revoke_link(db: Session, org_id: str, onboarding_id: str, link_id: str) -> m.MagicLink:
    link = _link(db, org_id, onboarding_id, link_id)
    link.revoked_at = link.revoked_at or now()
    db.flush()
    return link


def extend_link(db: Session, org_id: str, onboarding_id: str, link_id: str, days: int) -> m.MagicLink:
    if not 1 <= days <= MAX_EXTEND_DAYS:
        raise Invalid(f"Extend by 1 to {MAX_EXTEND_DAYS} days.")
    link = _link(db, org_id, onboarding_id, link_id)
    if link.revoked_at is not None:
        raise Conflict("A revoked link can't be extended; issue a new one.")
    link.expires_at = max(_aware(link.expires_at), now()) + dt.timedelta(days=days)
    db.flush()
    return link


# ---------------------------------------------------------------- client side

def find_usable_link(db: Session, raw: str) -> m.MagicLink | None:
    """The link for a raw token, or None. Unknown, expired and revoked all look the same to the caller."""
    if not isinstance(raw, str) or not 16 <= len(raw) <= 200:
        return None
    link = db.scalar(select(m.MagicLink).where(m.MagicLink.token_hash == hash_token(raw)))
    return link if link and is_usable(link) else None


def issue_session(settings: Settings, link: m.MagicLink) -> tuple[str, int]:
    ttl = settings.session_ttl_minutes * 60
    claims = {"aud": AUDIENCE, "sub": link.id, "iat": int(now().timestamp()), "exp": int(now().timestamp()) + ttl}
    return jwt.encode(claims, settings.portal_key(), algorithm=ALG), ttl


def link_from_session(db: Session, settings: Settings, token: str) -> m.MagicLink | None:
    """The still-usable link behind a session token, or None for anything wrong with it."""
    try:
        claims = jwt.decode(token, settings.portal_key(), algorithms=[ALG], audience=AUDIENCE, options={"require": ["exp", "sub", "aud"]})
    except jwt.PyJWTError:
        return None
    link = db.get(m.MagicLink, str(claims["sub"]))
    return link if link and is_usable(link) else None
