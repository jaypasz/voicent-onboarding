"""What a client may see and do. Everything here is scoped to one link: one onboarding, one contact.

The rule that matters most: a client never receives an internal step, an internal comment, the raw template
document, or any count that would reveal how many internal steps exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import magic_link
from . import models as m
from . import services
from .config import Settings
from .errors import Conflict, Forbidden, Invalid, NotFound
from .storage import Storage, UploadsOff, check_upload_request, storage_path
from .steps import registry

UNAVAILABLE = "This link isn't available. Ask for a new one."
VISIBLE_STATUSES = ("active", "paused", "completed")  # a draft or archived onboarding looks like a dead link
MAX_ISSUED_FACTOR = 4


@dataclass
class Ctx:
    link: m.MagicLink
    onboarding: m.Onboarding
    contact: m.Contact


def build_ctx(db: Session, settings: Settings, token: str) -> Ctx | None:
    link = magic_link.link_from_session(db, settings, token)
    return _ctx(db, link)


def build_ctx_from_link(db: Session, raw: str) -> Ctx | None:
    return _ctx(db, magic_link.find_usable_link(db, raw))


def _ctx(db: Session, link: m.MagicLink | None) -> Ctx | None:
    if link is None:
        return None
    ob, contact = db.get(m.Onboarding, link.onboarding_id), db.get(m.Contact, link.contact_id)
    if not ob or not contact or ob.org_id != link.org_id or contact.org_id != link.org_id or ob.status not in VISIBLE_STATUSES:
        return None
    return Ctx(link, ob, contact)


# ---------------------------------------------------------------- what is visible and writable

def _visible(ob: m.Onboarding, step: m.Step, contact: m.Contact) -> bool:
    if step.visibility != "client":
        return False
    if ob.layout == "focus" and step.assignee_contact_id not in (None, contact.id):
        return False  # in the focus layout a client only sees their own steps
    return True


def _can_write(ob: m.Onboarding, step: m.Step, contact: m.Contact) -> bool:
    return ob.status == "active" and step.visibility == "client" and step.assignee_contact_id in (None, contact.id)


def _doc_step(ob: m.Onboarding, key: str) -> dict:
    return next(d for d in ob.document["steps"] if d["key"] == key)


def step_view(db: Session, ctx: Ctx, step: m.Step) -> dict:
    ob, contact = ctx.onboarding, ctx.contact
    d = _doc_step(ob, step.key)
    last = step.responses[-1] if step.responses else None
    assignee = db.get(m.Contact, step.assignee_contact_id) if step.assignee_contact_id else None
    return {
        "key": step.key, "type": step.type, "title": step.title, "description": d["description"], "section": step.section,
        "position": step.position, "status": step.status, "due_at": step.due_at, "config": d["config"],
        "assignee": {"id": assignee.id, "name": assignee.name, "is_you": assignee.id == contact.id} if assignee else None,
        "can_write": _can_write(ob, step, contact),
        "response": last.data if last else None,
        "files": [{"id": f.id, "name": f.name, "size": f.size} for f in step.files],
        "comments": [
            {"id": c.id, "author_kind": c.author_kind, "author_label": c.author_label, "body": c.body, "created_at": c.created_at}
            for c in step.comments if c.client_visible
        ],
    }


def onboarding_view(db: Session, ctx: Ctx) -> dict:
    ob, contact = ctx.onboarding, ctx.contact
    steps = [s for s in ob.steps if _visible(ob, s, contact)]
    live = [s for s in steps if s.status != "skipped"]
    used = {s.section for s in steps if s.section}
    client = db.get(m.Client, ob.client_id)
    return {
        "title": ob.title, "layout": ob.layout, "status": ob.status, "client_name": client.name if client else "",
        "contact": {"id": contact.id, "name": contact.name},
        "sections": [sec for sec in ob.document["sections"] if sec["key"] in used],
        "progress": {"done": sum(1 for s in live if s.status == "done"), "total": len(live)},
        "steps": [step_view(db, ctx, s) for s in steps],
    }


# ---------------------------------------------------------------- what a client may do

def _find(ctx: Ctx, key: str) -> m.Step:
    step = next((s for s in ctx.onboarding.steps if s.key == key), None)
    if step is None or not _visible(ctx.onboarding, step, ctx.contact):
        raise NotFound("Step not found.")  # the same answer for a step that doesn't exist and one that isn't theirs to see
    return step


def _writable(ctx: Ctx, step: m.Step) -> None:
    if ctx.onboarding.status != "active":
        raise Conflict("This onboarding isn't accepting changes right now.")
    if not _can_write(ctx.onboarding, step, ctx.contact):
        raise Forbidden("This step is assigned to someone else.")


def submit(db: Session, ctx: Ctx, key: str, data, storage: Storage | None) -> dict:
    step = _find(ctx, key)
    _writable(ctx, step)
    services.submit_step(db, ctx.link.org_id, ctx.onboarding.id, key, data, submitted_by=f"contact:{ctx.contact.id}", actor_kind="client", storage=storage)
    return step_view(db, ctx, step)


def comment(db: Session, ctx: Ctx, key: str, body: str) -> dict:
    step = _find(ctx, key)
    _writable(ctx, step)
    c = services.add_comment(db, ctx.link.org_id, ctx.onboarding.id, key, body=body, author_kind="client", author_label=ctx.contact.name)
    return {"id": c.id, "author_kind": c.author_kind, "author_label": c.author_label, "body": c.body, "created_at": c.created_at}


def upload_url(db: Session, ctx: Ctx, key: str, *, name: str, size: int, content_type: str, storage: Storage | None) -> dict:
    step = _find(ctx, key)
    _writable(ctx, step)
    if step.type != "upload":
        raise Invalid("This step doesn't take files.")
    if storage is None:
        raise UploadsOff("File uploads aren't switched on yet.")
    config = _doc_step(ctx.onboarding, key)["config"]
    check_upload_request(config, name, size, content_type)
    if len(step.files) >= config.get("max_files", 5) * MAX_ISSUED_FACTOR:  # retries are fine; this only stops abuse
        raise Invalid("Too many uploads on this step. Ask for help if you're stuck.")
    path = storage_path(ctx.link.org_id, ctx.onboarding.id, step.id, name)
    target = storage.signed_upload(path)
    f = m.File(org_id=ctx.link.org_id, step_id=step.id, storage_path=path, name=name[:300], size=size, content_type=content_type)
    step.files.append(f)
    db.flush()
    return {"file_id": f.id, "upload_url": target["url"], "token": target["token"], "name": f.name}
