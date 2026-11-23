"""The audit trail: who changed what, and when, for every change by our team, a client or the system.

Who is acting is put on the database session (`db.info["who"]`) by the code that knows: `deps._resolve_org` for our team,
`deps.portal_ctx` for a client, and each background job for itself. `record` reads it, so the rules in services.py don't
pass a person around. An entry is added to the same session as the change, so both are committed together or neither is.

What an entry may say: titles, names, statuses, dates, counts. Never an answer, a comment's text, a file's contents, a link
token or a provider's error text. Free text that reaches a summary (a file name, an account label) goes through redact().

Entries are never changed or deleted by the app: the ORM refuses both (`_refuse`), and no route offers either.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session

from . import models as m
from .redact import redact


@dataclass(frozen=True)
class Who:
    kind: str  # team | client | system
    id: str | None
    label: str


SYSTEM = Who("system", None, "System")


def system(label: str) -> Who:
    """A background job acting on its own: "Reminders", "Change notices", "Voicent-App delivery"."""
    return Who("system", None, label)


def acting(db: Session, who: Who) -> None:
    db.info["who"] = who


def who(db: Session) -> Who:
    return db.info.get("who") or SYSTEM


def record(db: Session, org_id: str, action: str, summary: str, *, onboarding: m.Onboarding | None = None,
           client_id: str | None = None, step_key: str = "", details: dict | None = None, by: Who | None = None,
           at: dt.datetime | None = None) -> m.AuditEvent:
    actor = by or who(db)
    row = m.AuditEvent(
        org_id=org_id, actor_kind=actor.kind, actor_id=actor.id, actor_label=actor.label[:200], action=action,
        onboarding_id=onboarding.id if onboarding is not None else None,
        client_id=client_id or (onboarding.client_id if onboarding is not None else None),
        step_key=step_key, summary=redact(summary)[:500], details=details or {},
        at=at or dt.datetime.now(dt.timezone.utc),  # when it was recorded, so entries of one request keep their order
    )
    db.add(row)
    return row


def for_onboarding(db: Session, org_id: str, ob: m.Onboarding, *, limit: int = 100, before: dt.datetime | None = None) -> list[m.AuditEvent]:
    """This onboarding's trail, newest first, with changes to its client that aren't tied to any onboarding (a contact's
    consent, being marked paying) mixed in."""
    q = select(m.AuditEvent).where(
        m.AuditEvent.org_id == org_id,
        or_(m.AuditEvent.onboarding_id == ob.id, (m.AuditEvent.client_id == ob.client_id) & m.AuditEvent.onboarding_id.is_(None)),
    )
    if before is not None:
        q = q.where(m.AuditEvent.at < before)
    return list(db.scalars(q.order_by(m.AuditEvent.at.desc(), m.AuditEvent.id.desc()).limit(limit)))


@event.listens_for(Session, "before_flush")
def _refuse(session: Session, flush_context, instances) -> None:
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, m.AuditEvent):
            raise RuntimeError("Audit entries are never changed or deleted.")
