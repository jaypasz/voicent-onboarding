"""Reminders for clients who have gone quiet.

An onboarding is stalled when it is active, reminders aren't paused, the client has steps left, and nothing has happened
for the template's `nudge_after_days` (counted from the last client or admin activity, or the last reminder, whichever is
later). Each contact is reminded about their own open steps; steps nobody is assigned to go to the first contact. One
channel per contact: a text if they agreed to texts and it isn't night where they are, otherwise an email. After
`nudge_max` automatic reminders with no response, it stops and flags the onboarding for Jay.

Every reminder carries a fresh magic link (links are stored only as hashes, so an old one can't be sent again). A link
for a reminder that failed is revoked straight away.
"""
from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from . import magic_link
from . import models as m
from .config import Settings, valid_timezone
from .errors import Conflict
from .notify import Notifier, to_e164

SKIPPED_NO_WAY = "There's no email address or consented phone number to reach them on."


@dataclass
class Outcome:
    contact: str
    status: str  # sent | failed | skipped (can't reach them) | later (will be tried again) | would_send (dry run)
    channel: str | None = None
    reason: str = ""


@dataclass
class Summary:
    enabled: bool = True
    considered: int = 0
    sent: int = 0
    failed: int = 0
    flagged: int = 0
    details: list[str] = field(default_factory=list)


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def in_quiet_hours(now: dt.datetime, tz_name: str, start: int, end: int, fallback: str = "America/New_York") -> bool:
    """Is it night where the client is? start/end are local hours; a window like 21 to 8 wraps midnight."""
    local = _aware(now).astimezone(ZoneInfo(tz_name if valid_timezone(tz_name) else fallback))
    h = local.hour
    return (h >= start or h < end) if start > end else (start <= h < end)


def open_steps(ob: m.Onboarding, contact: m.Contact, primary: m.Contact | None) -> list[m.Step]:
    """Client steps still to do that belong to this contact. Unassigned ones belong to the first contact."""
    out = []
    for s in ob.steps:
        if s.visibility != "client" or s.status not in ("pending", "in_progress"):
            continue
        if s.assignee_contact_id == contact.id or (s.assignee_contact_id is None and primary is not None and contact.id == primary.id):
            out.append(s)
    return out


def build_message(settings: Settings, contact: m.Contact, steps: list[m.Step], url: str) -> dict:
    first = (contact.name.split() or ["there"])[0]
    n = len(steps)
    brand = settings.brand_name
    nxt = steps[0].title
    left = f"{n} step{'s' if n != 1 else ''} left"
    sms = f"{brand}: Hi {first}, you have {left} in your onboarding. Next up: {nxt[:60]}. Continue here: {url} Reply STOP to opt out."
    subject = f"Your onboarding with {brand}: {left}"
    text = (
        f"Hi {first},\n\nYou have {left} in your onboarding with {brand}. The next one is \"{nxt}\".\n\n"
        f"Pick up where you left off: {url}\n\nThis link is just for you, so please don't forward it.\n"
        f"If you'd rather not get these reminders, reply to this email and say so.\n"
    )
    e = html.escape
    page = (
        f"<p>Hi {e(first)},</p><p>You have {e(left)} in your onboarding with {e(brand)}. The next one is <strong>{e(nxt)}</strong>.</p>"
        f'<p><a href="{e(url)}" style="display:inline-block;padding:12px 20px;background:#0b5cff;color:#fff;text-decoration:none;border-radius:8px;font-weight:600">Continue your onboarding</a></p>'
        f"<p>This link is just for you, so please don't forward it. If you'd rather not get these reminders, reply to this email and say so.</p>"
    )
    return {"sms": sms, "subject": subject, "text": text, "html": page}


def _channels(settings: Settings, contact: m.Contact, quiet: bool, manual: bool) -> tuple[list[tuple[str, str]], list[str]]:
    """The ways to reach this contact right now (in order of preference), and why any were left out."""
    chans: list[tuple[str, str]] = []
    why: list[str] = []
    if settings.sms_enabled and contact.phone:
        e164 = to_e164(contact.phone)
        if not contact.sms_consent:
            why.append("no recorded consent to text them")
        elif e164 is None:
            why.append("their phone number isn't one we can text")
        elif quiet:
            why.append("it's night where they are")
        else:
            chans.append(("sms", e164))
    if settings.email_enabled and contact.email:
        if quiet and not manual:
            why.append("it's night where they are")
        else:
            chans.append(("email", contact.email))
    return chans, why


def _recently_failed(db: Session, ob: m.Onboarding, contact: m.Contact, now: dt.datetime, hours: int) -> bool:
    last = db.scalar(
        select(m.Nudge).where(m.Nudge.onboarding_id == ob.id, m.Nudge.contact_id == contact.id).order_by(m.Nudge.created_at.desc(), m.Nudge.round.desc()).limit(1)
    )
    return bool(last and last.status == "failed" and _aware(last.created_at) > now - dt.timedelta(hours=hours))


def _nudge_contact(db, settings, notifier, ob, client, contact, steps, round_no, now, manual, dry_run, app_url) -> Outcome:
    quiet = in_quiet_hours(now, client.timezone, settings.nudge_quiet_start, settings.nudge_quiet_end, settings.default_timezone)
    chans, why = _channels(settings, contact, quiet, manual)
    if not chans:
        later = bool(why) and all("night" in w for w in why)
        return Outcome(contact.name, "later" if later else "skipped", reason=("; ".join(why).capitalize() + ".") if why else SKIPPED_NO_WAY)
    if not manual and _recently_failed(db, ob, contact, now, settings.nudge_retry_hours):
        return Outcome(contact.name, "later", reason="A recent attempt failed. Trying again later.")
    if dry_run:
        return Outcome(contact.name, "would_send", channel=chans[0][0])

    last_reason = ""
    for channel, address in chans:
        row = m.Nudge(org_id=ob.org_id, onboarding_id=ob.id, contact_id=contact.id, channel=channel, round=round_no, template="manual" if manual else "stalled", status="queued", created_at=now)
        try:
            with db.begin_nested():  # if another run already took this slot, the unique constraint refuses it
                db.add(row)
                db.flush()
        except IntegrityError:
            return Outcome(contact.name, "later", channel=channel, reason="Another run is already reminding them.")
        raw, link = magic_link.issue_link(db, settings, ob.org_id, ob.id, contact.id)
        msg = build_message(settings, contact, steps, f"{app_url}/c/{raw}")
        result = notifier.send_sms(address, msg["sms"]) if channel == "sms" else notifier.send_email(address, msg["subject"], msg["text"], msg["html"])
        if result.ok:
            row.status, row.sent_at = "sent", now
            db.flush()
            return Outcome(contact.name, "sent", channel=channel)
        row.status, row.error = "failed", result.reason[:300]
        link.revoked_at = now  # nobody received this link
        if result.opted_out:
            contact.sms_consent, contact.sms_consent_at = False, None
            contact.sms_consent_source = f"replied STOP ({now.date().isoformat()})"
        last_reason = result.reason
        db.flush()
    return Outcome(contact.name, "failed", channel=chans[-1][0], reason=last_reason)


def nudge_onboarding(db: Session, settings: Settings, notifier: Notifier, ob: m.Onboarding, now: dt.datetime, *, manual: bool, dry_run: bool = False) -> list[Outcome]:
    """Remind the contacts of one onboarding. Manual sends ignore the stall timer, the cap and the pause switch, but never the texting rules."""
    client = db.get(m.Client, ob.client_id)
    contacts = list(db.scalars(select(m.Contact).where(m.Contact.client_id == ob.client_id, m.Contact.org_id == ob.org_id).order_by(m.Contact.created_at)))
    primary = contacts[0] if contacts else None
    round_no = (db.scalar(select(func.max(m.Nudge.round)).where(m.Nudge.onboarding_id == ob.id)) or 0) + 1
    app_url = settings.app_url
    outcomes = []
    for c in contacts:
        steps = open_steps(ob, c, primary)
        if steps:
            outcomes.append(_nudge_contact(db, settings, notifier, ob, client, c, steps, round_no, now, manual, dry_run, app_url))
    return outcomes


def remind_now(db: Session, settings: Settings, notifier: Notifier, ob: m.Onboarding, now: dt.datetime | None = None) -> list[Outcome]:
    """Jay presses "Send a reminder now"."""
    if not settings.reminders_enabled:
        raise Conflict("Reminders aren't switched on yet. Set APP_URL and either Twilio or Resend on the server.")
    if ob.status != "active":
        raise Conflict("Only an active onboarding can be reminded.")
    return nudge_onboarding(db, settings, notifier, ob, now or dt.datetime.now(dt.timezone.utc), manual=True)


def _stalled(db: Session, settings: Settings, ob: m.Onboarding, now: dt.datetime) -> bool:
    days = int(ob.document.get("nudge_after_days") or 3)
    last_sent = db.scalar(select(func.max(m.Nudge.sent_at)).where(m.Nudge.onboarding_id == ob.id, m.Nudge.status == "sent"))
    touch = max(_aware(ob.last_activity_at), _aware(last_sent)) if last_sent else _aware(ob.last_activity_at)
    return now - touch >= dt.timedelta(days=days)


def run_nudges(sm: sessionmaker, settings: Settings, notifier: Notifier, now: dt.datetime | None = None, dry_run: bool = False) -> Summary:
    """One pass over every active onboarding. Each is its own transaction, so one failure never undoes another."""
    summary = Summary(enabled=settings.reminders_enabled)
    if not summary.enabled:
        return summary
    now = now or dt.datetime.now(dt.timezone.utc)
    with sm() as db:
        ids = list(db.scalars(select(m.Onboarding.id).where(m.Onboarding.status == "active", m.Onboarding.nudges_paused.is_(False))))
    for oid in ids:
        with sm() as db:
            ob = db.get(m.Onboarding, oid)
            if ob is None or ob.status != "active" or ob.nudges_paused or not _stalled(db, settings, ob, now):
                continue
            if not any(s.visibility == "client" and s.status in ("pending", "in_progress") for s in ob.steps):
                continue  # the client has nothing left to do
            rounds = db.scalar(select(func.count(func.distinct(m.Nudge.round))).where(m.Nudge.onboarding_id == ob.id, m.Nudge.template == "stalled", m.Nudge.status == "sent")) or 0
            if rounds >= settings.nudge_max:
                if ob.attention != "nudges_exhausted":
                    ob.attention = "nudges_exhausted"
                    summary.flagged += 1
                    summary.details.append(f"{ob.title}: no reply after {rounds} reminders")
                db.commit()
                continue
            summary.considered += 1
            outcomes = nudge_onboarding(db, settings, notifier, ob, now, manual=False, dry_run=dry_run)
            sent = [o for o in outcomes if o.status in ("sent", "would_send")]
            summary.sent += len(sent)
            summary.failed += sum(1 for o in outcomes if o.status == "failed")
            summary.details += [f"{ob.title}: {o.contact} - {o.status}{(' by ' + o.channel) if o.channel else ''}{(' (' + o.reason + ')') if o.reason else ''}" for o in outcomes]
            if not dry_run:
                if outcomes and all(o.status == "skipped" for o in outcomes) and ob.attention != "unreachable":
                    ob.attention = "unreachable"
                    summary.flagged += 1
                elif sent and ob.attention == "unreachable":
                    ob.attention = None
            db.commit()
    return summary
