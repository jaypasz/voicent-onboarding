"""Telling the client when their steps change after sending.

Edits are batched: each one marks the onboarding "changed" and starts a quiet period (`CHANGE_NOTICE_DELAY_MINUTES`, 10 by
default); when the period passes with no further edit, the client gets ONE message listing what is different from what they
last saw. Edits that cancel out send nothing, and a save can be marked silent. Only what the client can see counts (steps with
visibility "client"); our internal steps never appear in a notice, and the notice carries step titles we wrote, never an answer
or a comment.

Same rules as reminders (nudges.py): a text only with recorded consent, never at night where the client is (texts or
automatic emails: the notice just waits), a fresh magic link per contact (a link for a failed send is revoked), and a contact
who replied STOP is recorded as having withdrawn consent. A notice is claimed with one conditional UPDATE, so it goes out once.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from . import branding, magic_link, nudges
from . import models as m
from .config import Settings
from .notify import Notifier

log = logging.getLogger("uvicorn.error")
MAX_LISTED = 5


def snapshot(document: dict) -> list[dict]:
    """What the client can see of the steps, in order: key, title and a fingerprint of everything that shapes the step."""
    out = []
    for d in document.get("steps", []):
        if d.get("visibility", "client") != "client":
            continue
        shape = {k: d.get(k) for k in ("type", "title", "description", "config", "assignee_role", "section")}
        out.append({"key": d["key"], "title": d.get("title", ""), "sig": hashlib.sha1(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()[:12]})
    return out


def diff(before: list[dict], after: list[dict]) -> dict:
    """What a client would notice. Titles are of steps we wrote."""
    b, a = {s["key"]: s for s in before}, {s["key"]: s for s in after}
    added = [s["title"] for s in after if s["key"] not in b]
    removed = [s["title"] for s in before if s["key"] not in a]
    changed = [s["title"] for s in after if s["key"] in b and b[s["key"]]["sig"] != s["sig"]]
    common = [s["key"] for s in before if s["key"] in a]
    reordered = common != [s["key"] for s in after if s["key"] in b]
    return {"added": added, "removed": removed, "changed": changed, "reordered": reordered}


def is_empty(d: dict) -> bool:
    return not (d["added"] or d["removed"] or d["changed"] or d["reordered"])


def note_edit(ob: m.Onboarding, before: list[dict], now: dt.datetime) -> None:
    """An admin edit of a sent onboarding that the client should hear about. The first edit of a batch remembers what the client
    saw; every edit restarts the quiet period."""
    if ob.client_seen_steps is None:
        ob.client_seen_steps = before
    ob.steps_changed_at = now


def pending(ob: m.Onboarding) -> bool:
    return ob.steps_changed_at is not None


def _listed(titles: list[str]) -> str:
    shown = ", ".join(f"“{t}”" for t in titles[:MAX_LISTED])
    return shown + (f" and {len(titles) - MAX_LISTED} more" if len(titles) > MAX_LISTED else "")


def summary_lines(d: dict) -> list[str]:
    lines = []
    if d["added"]:
        lines.append(f"New: {_listed(d['added'])}")
    if d["changed"]:
        lines.append(f"Updated: {_listed(d['changed'])}")
    if d["removed"]:
        lines.append(f"No longer needed: {_listed(d['removed'])}")
    if d["reordered"]:
        lines.append("The order of the steps changed")
    return lines


def build_message(contact: m.Contact, d: dict, url: str, brand: str) -> dict:
    first = (contact.name.split() or ["there"])[0]
    lines = summary_lines(d)
    n = len(lines)
    sms = f"{brand}: Hi {first}, your onboarding was updated ({'; '.join(lines)[:90]}). See what's new: {url} Reply STOP to opt out."
    subject = f"Your onboarding with {brand} was updated"
    text = (f"Hi {first},\n\nWe made {'a change' if n == 1 else 'some changes'} to your onboarding with {brand}:\n\n" + "\n".join(f"- {x}" for x in lines)
            + f"\n\nSee what's new: {url}\n\nThis link is just for you, so please don't forward it.\n")
    e = html.escape
    page = (f"<p>Hi {e(first)},</p><p>We made {'a change' if n == 1 else 'some changes'} to your onboarding with {e(brand)}:</p>"
            + "<ul>" + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ul>"
            + f'<p><a href="{e(url)}" style="display:inline-block;padding:12px 20px;background:#0b5cff;color:#fff;text-decoration:none;border-radius:8px;font-weight:600">See what\'s new</a></p>'
            + "<p>This link is just for you, so please don't forward it.</p>")
    return {"sms": sms, "subject": subject, "text": text, "html": page}


def _tell(db: Session, settings: Settings, notifier: Notifier, ob: m.Onboarding, d: dict, now: dt.datetime) -> int:
    """Send the notice to each contact with something to do. Returns how many were reached. A contact that can't be reached, or a send
    that fails, is logged and not retried: a failure must not loop, and the client sees the change in their portal anyway."""
    client = db.get(m.Client, ob.client_id)
    org = db.get(m.Org, ob.org_id)
    contacts = list(db.scalars(select(m.Contact).where(m.Contact.client_id == ob.client_id, m.Contact.org_id == ob.org_id).order_by(m.Contact.created_at)))
    primary = contacts[0] if contacts else None
    reached = 0
    for c in contacts:
        if not nudges.open_steps(ob, c, primary):
            continue
        chans, why = nudges._channels(settings, c, False, False)
        if not chans:
            log.info("Change notice: onboarding %s contact %s not reachable (%s)", ob.id, c.id, "; ".join(why) or "no address")
            continue
        for channel, address in chans:
            raw, link = magic_link.issue_link(db, settings, ob.org_id, ob.id, c.id)
            msg = build_message(c, d, f"{settings.app_url}/c/{raw}", branding.display_name(org, settings))
            if channel == "sms":
                result = notifier.send_sms(address, msg["sms"], sender=branding.sms_from(org, settings))
            else:
                result = notifier.send_email(address, msg["subject"], msg["text"], msg["html"], sender=branding.email_from(org, settings), reply_to=branding.reply_to(org))
            if result.ok:
                reached += 1
                break
            link.revoked_at = now  # nobody received this link
            if result.opted_out:
                c.sms_consent, c.sms_consent_at = False, None
                c.sms_consent_source = f"replied STOP ({now.date().isoformat()})"
            log.warning("Change notice: onboarding %s contact %s by %s failed: %s", ob.id, c.id, channel, result.reason)
    db.flush()
    return reached


def run_notices(sm: sessionmaker, settings: Settings, notifier: Notifier, now: dt.datetime | None = None) -> dict:
    """One pass: tell the clients whose steps changed and then sat quiet for the delay. Returns counts."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=settings.change_notice_delay_minutes)
    out = {"considered": 0, "sent": 0, "waiting": 0, "nothing_to_say": 0}
    with sm() as db:
        ids = list(db.scalars(select(m.Onboarding.id).where(m.Onboarding.steps_changed_at.is_not(None), m.Onboarding.status == "active")))
    for oid in ids:
        with sm() as db:
            ob = db.get(m.Onboarding, oid)
            if ob is None or ob.steps_changed_at is None:
                continue
            out["considered"] += 1
            seen = ob.steps_changed_at
            if nudges._aware(seen) > cutoff:
                out["waiting"] += 1  # still being edited
                continue
            client = db.get(m.Client, ob.client_id)
            if nudges.in_quiet_hours(now, client.timezone, settings.nudge_quiet_start, settings.nudge_quiet_end, settings.default_timezone):
                out["waiting"] += 1  # night where they are: it stays pending
                continue
            claimed = db.execute(update(m.Onboarding).where(m.Onboarding.id == oid, m.Onboarding.steps_changed_at == seen).values(steps_changed_at=None))
            if claimed.rowcount != 1:
                db.rollback()
                continue  # another run took it, or it was edited again meanwhile
            before = ob.client_seen_steps or []
            d = diff(before, snapshot(ob.document))
            ob.client_seen_steps = None
            if is_empty(d):
                out["nothing_to_say"] += 1
            else:
                _tell(db, settings, notifier, ob, d, now)
                out["sent"] += 1
            db.commit()
    return out
