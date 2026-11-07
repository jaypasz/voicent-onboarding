"""Keep the AIOS board in step with each onboarding. One-way: onboarding to AIOS, never back.

Each onboarding becomes one AIOS project (its id is `onb-<onboarding id>`, so creating it twice is harmless) with one task
per step. Client steps read "Waiting on client: ..." until they are done; internal steps are Jay's own tasks. When a client
acts, a one-line comment is added to the task.

What goes out is only titles, statuses, dates and one-line summaries, passed through redact(). Never a form answer, an uploaded
file, an account name beyond what the client typed as a label, or a link token.

It works by reconciling, not by replaying events: compare what we know with what AIOS was last told, and fix the difference.
That makes it safe to run twice, and safe to run after a failure. IDs are saved after every call so a crash can't make
duplicates; if a reply was lost, the task is found again by its link before another is created. A change that lands while
a sync is running is never lost: `sync_version` goes up on every change and `synced_version` only moves to the version a pass
actually read.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from . import models as m
from .aios import AiosClient, AiosError
from .config import Settings
from .redact import redact

log = logging.getLogger("uvicorn.error")

STEP_TO_TASK = {"pending": "todo", "in_progress": "doing", "done": "done", "skipped": "done"}
ONBOARDING_TO_PROJECT = {"active": "active", "paused": "paused", "completed": "done", "archived": "paused"}
FAILURE_LOG_EVERY = dt.timedelta(minutes=30)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass
class SyncResult:
    ok: bool
    state: str  # synced | skipped | busy | failed | off
    message: str = ""
    changes: int = 0


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def project_id(ob: m.Onboarding) -> str:
    return f"onb-{ob.id}"


def step_link(settings: Settings, ob: m.Onboarding, step: m.Step) -> str:
    """Where Jay lands from the task. Also how a task is recognised again if the reply to creating it was lost."""
    return f"{settings.app_url}/onboardings/{ob.id}#step-{step.key}"[:300]


def task_title(step: m.Step) -> str:
    waiting = step.visibility == "client" and step.status not in ("done", "skipped")
    return (f"Waiting on client: {step.title}" if waiting else step.title)[:200]


def task_notes(ob: m.Onboarding, step: m.Step, assignee: str | None) -> str:
    d = next((x for x in ob.document["steps"] if x["key"] == step.key), {})
    parts = [d.get("description", "")]
    if step.visibility == "client" and assignee:
        parts.append(f"For: {assignee}")
    checklist = (d.get("config") or {}).get("checklist") or []
    if step.visibility == "internal" and checklist:
        parts.append("Checklist:\n" + "\n".join(f"- {c}" for c in checklist))
    if step.status == "skipped":
        parts.append("Skipped.")
    return redact("\n\n".join(p for p in parts if p))[:8000]


def due_date(step: m.Step) -> str | None:
    return _aware(step.due_at).astimezone(ZoneInfo("America/New_York")).date().isoformat() if step.due_at else None


def summary_line(step: m.Step, response: m.Response) -> str:
    """One line about what a client just did. Deliberately never contains their answers."""
    d = response.data
    if step.type == "approval":
        if d.get("decision") == "approved":
            return "Client approved this."
        return redact(f'Client asked for changes: "{str(d.get("comment", ""))[:200]}"')
    if step.type == "connect":
        return redact(f"Client connected the account ({str(d.get('account_label', ''))[:80]}).") if d.get("status") == "connected" else "Client asked for help with this."
    if step.type == "book_call":
        return "Client booked the call." if d.get("booked") else "Client hasn't booked the call yet."
    if step.type == "upload":
        n = len(d.get("file_ids", []))
        return f"Client uploaded {n} file{'s' if n != 1 else ''}." if n else "Client had nothing to upload."
    return "Client filled this in."


def _log(db: Session, ob: m.Onboarding, action: str, status: str, detail: str) -> None:
    if status == "failed":  # don't write the same failure every few minutes
        last = db.scalar(select(m.SyncLog).where(m.SyncLog.onboarding_id == ob.id, m.SyncLog.target == "aios").order_by(m.SyncLog.created_at.desc()).limit(1))
        if last and last.status == "failed" and last.detail == detail[:300] and _aware(last.created_at) > dt.datetime.now(dt.timezone.utc) - FAILURE_LOG_EVERY:
            return
    db.add(m.SyncLog(org_id=ob.org_id, onboarding_id=ob.id, target="aios", action=action, status=status, detail=detail[:300]))


def _reconcile(db: Session, settings: Settings, aios: AiosClient, org_id: str, onboarding_id: str) -> SyncResult:
    ob = db.scalar(select(m.Onboarding).where(m.Onboarding.id == onboarding_id, m.Onboarding.org_id == org_id))
    if ob is None:
        return SyncResult(False, "failed", "Onboarding not found.")
    if ob.status == "draft":
        return SyncResult(True, "skipped", "Not sent yet, so there is nothing to sync.")
    version = ob.sync_version
    client = db.get(m.Client, ob.client_id)
    names = {c.id: c.name for c in db.scalars(select(m.Contact).where(m.Contact.client_id == ob.client_id, m.Contact.org_id == org_id))}
    pid, changes = project_id(ob), 0
    try:
        wanted = ONBOARDING_TO_PROJECT[ob.status]
        if not ob.aios_project_id:
            aios.create_project({
                "id": pid, "name": redact(f"Onboarding: {client.name}")[:200], "track": "other", "status": wanted,
                "goal": redact(f"Client onboarding from the template '{ob.document['name']}'.")[:2000], "plan": f"{settings.app_url}/onboardings/{ob.id}"[:300],
            })
            ob.aios_project_id, ob.aios_status = pid, wanted
            db.commit()
            changes += 1
        elif ob.aios_status != wanted:
            aios.patch_project(pid, {"status": wanted})
            ob.aios_status = wanted
            db.commit()
            changes += 1

        existing: dict[str, dict] | None = None
        for s in ob.steps:
            desired = STEP_TO_TASK[s.status]
            assignee = names.get(s.assignee_contact_id) if s.assignee_contact_id else None
            if not s.aios_task_id:
                if existing is None:  # one lookup per pass: finds a task whose creation reply was lost
                    existing = {t["link"]: t for t in aios.list_tasks(pid) if t.get("link")}
                found = existing.get(step_link(settings, ob, s))
                if found:
                    s.aios_task_id, s.aios_status = found["id"], found.get("status")
                else:
                    body = {"title": task_title(s), "status": desired, "track": "other", "priority": "normal", "project_id": pid,
                            "date": due_date(s), "link": step_link(settings, ob, s), "notes": task_notes(ob, s, assignee)}
                    s.aios_task_id, s.aios_status = aios.create_task(body)["id"], desired
                db.commit()
                changes += 1
            if s.aios_status != desired:
                aios.patch_task(s.aios_task_id, {"status": desired, "title": task_title(s), "notes": task_notes(ob, s, assignee)})
                s.aios_status = desired
                db.commit()
                changes += 1
            last = s.responses[-1] if s.responses else None
            if last and last.revision > s.aios_comment_revision:
                if last.submitted_by.startswith("contact:"):  # Jay already knows what Jay did
                    aios.add_comment(s.aios_task_id, summary_line(s, last))
                    changes += 1
                s.aios_comment_revision = last.revision
                db.commit()

        db.execute(update(m.Onboarding).where(m.Onboarding.id == ob.id, m.Onboarding.synced_version < version).values(synced_version=version))
        if changes:
            _log(db, ob, "sync", "ok", f"Sent {changes} change{'s' if changes != 1 else ''} to AIOS.")
        db.commit()
        return SyncResult(True, "synced", "AIOS is up to date.", changes)
    except AiosError as e:
        db.rollback()
        _log(db, ob, "sync", "failed", e.message)
        db.commit()
        return SyncResult(False, "failed", e.message, changes)


def sync_onboarding(sm: sessionmaker, settings: Settings, org_id: str, onboarding_id: str, aios: AiosClient | None = None) -> SyncResult:
    """Bring AIOS in line with one onboarding. Never raises: a sync problem must not reach the client or the admin's click."""
    if not settings.aios_sync_enabled:
        return SyncResult(True, "off", "AIOS sync isn't switched on.")
    lock = _lock_for(onboarding_id)
    if not lock.acquire(blocking=False):
        return SyncResult(True, "busy", "A sync is already running.")
    try:
        with sm() as db:
            return _reconcile(db, settings, aios or AiosClient(settings), org_id, onboarding_id)
    except Exception:  # noqa: BLE001 - nothing here may escape into a request or the job loop
        log.error("AIOS sync failed for onboarding %s", onboarding_id, exc_info=True)
        return SyncResult(False, "failed", "Something unexpected went wrong while syncing. See the server logs.")
    finally:
        lock.release()


def kick(request, background, org_id: str, onboarding_id: str) -> None:
    """After a change: sync this onboarding once the response has gone. If that doesn't happen (restart, AIOS down), the
    periodic pass finds it by its version number. A no-op when AIOS sync is off."""
    st = request.app.state
    if st.settings.aios_sync_enabled:
        background.add_task(sync_onboarding, st.sessionmaker, st.settings, org_id, onboarding_id, st.aios)


def sync_dirty(sm: sessionmaker, settings: Settings, aios: AiosClient | None = None, limit: int = 25) -> dict:
    """The periodic pass: every sent onboarding whose version has moved since the last sync."""
    if not settings.aios_sync_enabled:
        return {"enabled": False, "synced": 0, "failed": 0}
    with sm() as db:
        todo = list(db.execute(select(m.Onboarding.org_id, m.Onboarding.id).where(m.Onboarding.status != "draft", m.Onboarding.sync_version > m.Onboarding.synced_version).limit(limit)))
    out = {"enabled": True, "synced": 0, "failed": 0}
    for org_id, oid in todo:
        r = sync_onboarding(sm, settings, org_id, oid, aios)
        out["synced" if r.ok else "failed"] += 1
    return out


def status_for(db: Session, settings: Settings, ob: m.Onboarding) -> dict:
    """What the admin page shows about AIOS for one onboarding."""
    rows = list(db.scalars(select(m.SyncLog).where(m.SyncLog.onboarding_id == ob.id, m.SyncLog.target == "aios").order_by(m.SyncLog.created_at.desc()).limit(5)))
    if not settings.aios_sync_enabled:
        state = "off"
    elif ob.status == "draft":
        state = "not_sent"
    elif ob.synced_version >= ob.sync_version and ob.aios_project_id:
        state = "synced"
    elif rows and rows[0].status == "failed":
        state = "failing"
    else:
        state = "pending"
    return {
        "enabled": settings.aios_sync_enabled, "state": state, "project_id": ob.aios_project_id,
        "log": [{"at": r.created_at, "status": r.status, "detail": r.detail} for r in rows],
    }
