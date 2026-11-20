"""Telling the team: who looks after what, and what just happened there.

A notification is a row for one team member, shown in the app. If they want it (OrgMember.notify_email) and email is set up,
it is also emailed. The text is our own wording: who did what, where. It never carries what a client typed, a file or a
link token; the email links to the onboarding page, which needs a login.

Sending follows the same rules as the other jobs: one conditional UPDATE claims each email, so two runs (a background task
and the timer) never send it twice. Provider errors are never shown.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from . import branding, models as m
from .config import Settings

log = logging.getLogger("uvicorn.error")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TEXT_MAX = 300
STALE = dt.timedelta(days=1)  # news older than this isn't worth an email any more


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def notify(db: Session, org_id: str, member_id: str | None, kind: str, text: str, *,
           onboarding_id: str | None = None, step_key: str = "", by_member_id: str | None = None) -> m.Notification | None:
    """One notification for one member of this org. Nothing for nobody, for someone outside the org, or for the person who
    did the thing themselves."""
    if not member_id or member_id == by_member_id:
        return None
    member = db.get(m.OrgMember, member_id)
    if member is None or member.org_id != org_id:
        return None
    wants_email = member.notify_email and bool(EMAIL.match(member.email or ""))  # whether email is set up is decided when sending
    n = m.Notification(org_id=org_id, member_id=member_id, kind=kind, text=text[:TEXT_MAX], onboarding_id=onboarding_id,
                       step_key=step_key, email_state="pending" if wants_email else "none")
    db.add(n)
    db.flush()
    return n


def contact_name(db: Session, submitted_by: str) -> str:
    if submitted_by.startswith("contact:"):
        c = db.get(m.Contact, submitted_by.split(":", 1)[1])
        if c:
            return c.name
    return "The client"


# ---------------------------------------------------------------- the events

def onboarding_owner_set(db, ob: m.Onboarding, by_member_id: str | None) -> None:
    notify(db, ob.org_id, ob.owner_member_id, "assigned_onboarding", f"You now look after “{ob.title}”.",
           onboarding_id=ob.id, by_member_id=by_member_id)


def step_assignee_set(db, ob: m.Onboarding, step: m.Step, by_member_id: str | None) -> None:
    notify(db, ob.org_id, step.team_assignee_id, "assigned_step", f"You're following up “{step.title}” in “{ob.title}”.",
           onboarding_id=ob.id, step_key=step.key, by_member_id=by_member_id)


def client_answered(db, ob: m.Onboarding, step: m.Step, submitted_by: str) -> None:
    """Whoever follows the step up hears about it; if nobody does, the onboarding's owner."""
    who = contact_name(db, submitted_by)
    notify(db, ob.org_id, step.team_assignee_id or ob.owner_member_id, "step_done", f"{who} answered “{step.title}” in “{ob.title}”.",
           onboarding_id=ob.id, step_key=step.key)


def onboarding_completed(db, ob: m.Onboarding) -> None:
    notify(db, ob.org_id, ob.owner_member_id, "completed", f"“{ob.title}” is finished.", onboarding_id=ob.id)


def client_gone_quiet(db, ob: m.Onboarding, rounds: int) -> None:
    notify(db, ob.org_id, ob.owner_member_id, "quiet",
           f"“{ob.title}”: no reply after {rounds} reminder{'s' if rounds != 1 else ''}. A call might help.", onboarding_id=ob.id)


# ---------------------------------------------------------------- reading them

def for_member(db: Session, org_id: str, member_id: str | None, unread_only: bool = False, limit: int = 50) -> tuple[list[m.Notification], int]:
    if not member_id:
        return [], 0
    base = select(m.Notification).where(m.Notification.org_id == org_id, m.Notification.member_id == member_id)
    unread = len(list(db.scalars(base.where(m.Notification.read_at.is_(None)).with_only_columns(m.Notification.id))))
    q = base.where(m.Notification.read_at.is_(None)) if unread_only else base
    return list(db.scalars(q.order_by(m.Notification.created_at.desc()).limit(limit))), unread


def mark_read(db: Session, org_id: str, member_id: str | None, ids: list[str] | None, now: dt.datetime) -> int:
    """Only ever the caller's own notifications."""
    if not member_id:
        return 0
    q = update(m.Notification).where(m.Notification.org_id == org_id, m.Notification.member_id == member_id, m.Notification.read_at.is_(None))
    if ids is not None:
        q = q.where(m.Notification.id.in_(ids))
    n = db.execute(q.values(read_at=now).execution_options(synchronize_session=False)).rowcount
    db.flush()
    return n


# ---------------------------------------------------------------- emailing them

def _email(settings: Settings, org: m.Org, n: m.Notification) -> tuple[str, str, str]:
    # the org goes in the link: someone in several orgs may be working in another one, and the onboarding is only found in its own
    link = f"{settings.app_url}/onboardings/{n.onboarding_id}?org={n.org_id}" if n.onboarding_id else settings.app_url
    name = branding.display_name(org, settings)
    text = f"{n.text}\n\nOpen it: {link}\n\nYou get these because you're on the {name} team. Turn them off on the Team page."
    page = (f"<p>{html.escape(n.text)}</p><p><a href=\"{html.escape(link)}\">Open it</a></p>"
            f"<p style=\"color:#666\">You get these because you're on the {html.escape(name)} team. Turn them off on the Team page.</p>")
    return n.text, text, page


def send_pending(sm: sessionmaker, settings: Settings, notifier, limit: int = 50) -> dict:
    """Email what is waiting. Never raises."""
    out = {"sent": 0, "failed": 0}
    if not (settings.email_enabled and settings.app_url):
        return out  # they wait; anything older than STALE when email is switched on is dropped, not sent late
    try:
        with sm() as db:
            ids = list(db.scalars(select(m.Notification.id).where(m.Notification.email_state == "pending").order_by(m.Notification.created_at).limit(limit)))
        for nid in ids:
            with sm() as db:
                claimed = db.execute(update(m.Notification).where(m.Notification.id == nid, m.Notification.email_state == "pending")
                                     .values(email_state="sending").execution_options(synchronize_session=False)).rowcount
                db.commit()
                if not claimed:
                    continue
                n = db.get(m.Notification, nid)
                member, org = db.get(m.OrgMember, n.member_id), db.get(m.Org, n.org_id)
                if not member or not member.notify_email or _aware(n.created_at) < _now() - STALE:
                    n.email_state = "none"
                    db.commit()
                    continue
                subject, text, page = _email(settings, org, n)
                r = notifier.send_email(member.email, subject, text, page, sender=branding.email_from(org, settings))
                n.email_state = "sent" if r.ok else "failed"
                out["sent" if r.ok else "failed"] += 1
                db.commit()
    except Exception:  # noqa: BLE001 - nothing here may escape into a request or the job loop
        log.error("Sending notification emails failed", exc_info=True)
    return out


def kick(request, background) -> None:
    """After a change that may have made notifications: email them once the response has gone (the timer catches the rest)."""
    st = request.app.state
    if st.settings.email_enabled:
        background.add_task(send_pending, st.sessionmaker, st.settings, st.notifier)
