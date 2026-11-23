"""Telling the client the next stage is open.

When a sign-off opens a stage (stages.py), the onboarding remembers which stages opened and when. After the same quiet period as
change notices (`CHANGE_NOTICE_DELAY_MINUTES`), so a sign-off withdrawn straight away sends nothing, each contact with something
to do in those stages gets ONE message naming the stage and their steps in it, with a fresh magic link. Several stages opened in
the meantime go out as one message.

The same rules as reminders and change notices (changes.tell): a text only with recorded consent, never at night where the client
is (the notice just waits), a link for a failed send is revoked, a STOP reply withdraws consent, and the notice is claimed with one
conditional UPDATE so it goes out once. Only step and stage titles we wrote go out, and only those the client can see.
"""
from __future__ import annotations

import datetime as dt
import html

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from . import changes, nudges, stages
from . import models as m
from .config import Settings
from .notify import Notifier

MAX_LISTED = 5


def note_opened(ob: m.Onboarding, keys: list[str], now: dt.datetime) -> None:
    """A sign-off opened these stages. Each new one restarts the quiet period, so a run of sign-offs makes one message."""
    if not keys:
        return
    ob.stage_opened_keys = list(dict.fromkeys([*(ob.stage_opened_keys or []), *keys]))
    ob.stage_opened_at = now


def forget_locked(ob: m.Onboarding) -> None:
    """After a sign-off is withdrawn: a stage that is locked again is no news. With nothing left, nothing is sent."""
    if not ob.stage_opened_keys:
        return
    locked = {st.key for st in stages.stages(ob) if st.state == "locked"}
    keep = [k for k in ob.stage_opened_keys if k not in locked]
    ob.stage_opened_keys = keep or None
    if not keep:
        ob.stage_opened_at = None


def pending(ob: m.Onboarding) -> bool:
    return ob.stage_opened_at is not None


def _waiting(ob: m.Onboarding, keys: list[str], contact: m.Contact, primary: m.Contact | None) -> list[m.Step]:
    """This contact's open client steps in the stages that opened."""
    return [s for s in nudges.open_steps(ob, contact, primary) if s.section in keys]


def _listed(titles: list[str]) -> str:
    shown = ", ".join(f"“{t}”" for t in titles[:MAX_LISTED])
    return shown + (f" and {len(titles) - MAX_LISTED} more" if len(titles) > MAX_LISTED else "")


def build_message(contact: m.Contact, stage_titles: list[str], steps: list[str], url: str, brand: str) -> dict:
    first = (contact.name.split() or ["there"])[0]
    part = "part" if len(stage_titles) == 1 else "parts"
    named = _listed(stage_titles)
    sms = f"{brand}: Hi {first}, the next {part} of your onboarding {'is' if len(stage_titles) == 1 else 'are'} ready: {named[:80]}. Pick up here: {url} Reply STOP to opt out."
    subject = f"The next {part} of your onboarding with {brand} {'is' if len(stage_titles) == 1 else 'are'} ready"
    text = (f"Hi {first},\n\nThanks for everything so far. We've reviewed it, and the next {part} of your onboarding with {brand} "
            f"{'is' if len(stage_titles) == 1 else 'are'} ready: {named}.\n\nWhat's waiting for you:\n"
            + "\n".join(f"- {t}" for t in steps[:MAX_LISTED]) + (f"\n- and {len(steps) - MAX_LISTED} more" if len(steps) > MAX_LISTED else "")
            + f"\n\nPick up where you left off: {url}\n\nThis link is just for you, so please don't forward it.\n")
    e = html.escape
    page = (f"<p>Hi {e(first)},</p><p>Thanks for everything so far. We've reviewed it, and the next {part} of your onboarding with {e(brand)} "
            f"{'is' if len(stage_titles) == 1 else 'are'} ready: {e(named)}.</p><p>What's waiting for you:</p>"
            + "<ul>" + "".join(f"<li>{e(t)}</li>" for t in steps[:MAX_LISTED]) + (f"<li>and {len(steps) - MAX_LISTED} more</li>" if len(steps) > MAX_LISTED else "") + "</ul>"
            + f'<p><a href="{e(url)}" style="display:inline-block;padding:12px 20px;background:#0b5cff;color:#fff;text-decoration:none;border-radius:8px;font-weight:600">Pick up where you left off</a></p>'
            + "<p>This link is just for you, so please don't forward it.</p>")
    return {"sms": sms, "subject": subject, "text": text, "html": page}


def run_notices(sm: sessionmaker, settings: Settings, notifier: Notifier, now: dt.datetime | None = None) -> dict:
    """One pass: tell the clients whose next stage opened and then stayed open for the delay. Returns counts."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=settings.change_notice_delay_minutes)
    out = {"considered": 0, "sent": 0, "waiting": 0, "nothing_to_say": 0}
    with sm() as db:
        ids = list(db.scalars(select(m.Onboarding.id).where(m.Onboarding.stage_opened_at.is_not(None), m.Onboarding.status == "active")))
    for oid in ids:
        with sm() as db:
            ob = db.get(m.Onboarding, oid)
            if ob is None or ob.stage_opened_at is None:
                continue
            out["considered"] += 1
            seen = ob.stage_opened_at
            if nudges._aware(seen) > cutoff:
                out["waiting"] += 1  # just signed off: give an undo the chance to cancel it
                continue
            client = db.get(m.Client, ob.client_id)
            if nudges.in_quiet_hours(now, client.timezone, settings.nudge_quiet_start, settings.nudge_quiet_end, settings.default_timezone):
                out["waiting"] += 1  # night where they are: it stays pending
                continue
            claimed = db.execute(update(m.Onboarding).where(m.Onboarding.id == oid, m.Onboarding.stage_opened_at == seen).values(stage_opened_at=None))
            if claimed.rowcount != 1:
                db.rollback()
                continue  # another run took it, or another stage opened meanwhile
            db.refresh(ob)
            opened = {st.key: st for st in stages.stages(ob) if st.key in (ob.stage_opened_keys or []) and st.state != "locked"}
            ob.stage_opened_keys = None
            keys = list(opened)
            primary = db.scalar(select(m.Contact).where(m.Contact.client_id == ob.client_id, m.Contact.org_id == ob.org_id).order_by(m.Contact.created_at).limit(1))

            def build(c: m.Contact, url: str, brand: str) -> dict:
                mine = _waiting(ob, keys, c, primary)
                return build_message(c, [opened[k].title for k in keys if any(s.section == k for s in mine)], [s.title for s in mine], url, brand)

            sent = changes.tell(db, settings, notifier, ob, now, what="Stage notice", wants=lambda c, p: bool(_waiting(ob, keys, c, p)), build=build) if keys else 0
            out["sent" if sent else "nothing_to_say"] += 1
            db.commit()
    return out
