from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import aios_sync, magic_link, models as m, services
from .. import nudges as reminders
from ..deps import Actor, Auth, Db, Org, Session
from ..errors import NotFound
from ..schemas import CommentIn, NudgesIn, OnboardingIn, StepAnswerIn, comment_out, onboarding_detail, onboarding_summary, step_out
from ..storage import UploadsOff

router = APIRouter(prefix="/onboardings", tags=["onboardings"])


def _step(db: Session, org: str, onboarding_id: str, key: str) -> dict:
    ob = services.get_onboarding(db, org, onboarding_id)
    return step_out(ob, next(s for s in ob.steps if s.key == key))


@router.get("")
def list_onboardings(status: str | None = None, client_id: str | None = None, db: Session = Db, org: str = Org):
    return [onboarding_summary(o) for o in services.list_onboardings(db, org, status, client_id)]


@router.post("", status_code=201)
def create(body: OnboardingIn, db: Session = Db, org: str = Org):
    return onboarding_detail(services.create_onboarding(db, org, client_id=body.client_id, template_id=body.template_id, title=body.title, version=body.version))


@router.get("/{onboarding_id}")
def get(onboarding_id: str, db: Session = Db, org: str = Org):
    return onboarding_detail(services.get_onboarding(db, org, onboarding_id))


class LinkIn(BaseModel):
    contact_id: str


class ExtendIn(BaseModel):
    days: int = Field(ge=1, le=365)


def _url(request: Request, raw: str) -> str:
    base = request.app.state.settings.app_url
    return f"{base}/c/{raw}"


def _link_out(link: m.MagicLink, contact_name: str = "") -> dict:
    return {"id": link.id, "contact_id": link.contact_id, "contact_name": contact_name, "expires_at": link.expires_at,
            "revoked_at": link.revoked_at, "last_used_at": link.last_used_at, "usable": magic_link.is_usable(link)}


@router.post("/{onboarding_id}/send")
def send(onboarding_id: str, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    """Start the onboarding and issue one link per contact. The links are in this response only; they can't be shown again."""
    ob = services.send_onboarding(db, org, onboarding_id)
    aios_sync.kick(request, background, org, ob.id)
    contacts = list(db.scalars(select(m.Contact).where(m.Contact.client_id == ob.client_id, m.Contact.org_id == org).order_by(m.Contact.created_at)))
    links = []
    for c in contacts:
        raw, link = magic_link.issue_link(db, request.app.state.settings, org, ob.id, c.id)
        links.append(_link_out(link, c.name) | {"url": _url(request, raw)})
    return onboarding_detail(ob) | {"links": links}


@router.get("/{onboarding_id}/links")
def list_links(onboarding_id: str, db: Session = Db, org: str = Org):
    services.get_onboarding(db, org, onboarding_id)
    names = {c.id: c.name for c in db.scalars(select(m.Contact).where(m.Contact.org_id == org))}
    return [_link_out(link, names.get(link.contact_id, "")) for link in magic_link.list_links(db, org, onboarding_id)]


@router.post("/{onboarding_id}/links", status_code=201)
def issue_link(onboarding_id: str, body: LinkIn, request: Request, db: Session = Db, org: str = Org):
    raw, link = magic_link.issue_link(db, request.app.state.settings, org, onboarding_id, body.contact_id)
    return _link_out(link) | {"url": _url(request, raw)}


@router.post("/{onboarding_id}/links/{link_id}/revoke")
def revoke_link(onboarding_id: str, link_id: str, db: Session = Db, org: str = Org):
    return _link_out(magic_link.revoke_link(db, org, onboarding_id, link_id))


@router.post("/{onboarding_id}/links/{link_id}/extend")
def extend_link(onboarding_id: str, link_id: str, body: ExtendIn, db: Session = Db, org: str = Org):
    return _link_out(magic_link.extend_link(db, org, onboarding_id, link_id, body.days))


@router.get("/{onboarding_id}/files/{file_id}/url")
def file_url(onboarding_id: str, file_id: str, request: Request, db: Session = Db, org: str = Org):
    """A short-lived download link for an uploaded file."""
    ob = services.get_onboarding(db, org, onboarding_id)
    f = db.scalar(select(m.File).join(m.Step, m.Step.id == m.File.step_id).where(m.File.id == file_id, m.File.org_id == org, m.Step.onboarding_id == ob.id))
    if not f:
        raise NotFound("File not found.")
    storage = request.app.state.storage
    if storage is None:
        raise UploadsOff("File uploads aren't switched on yet.")
    return {"name": f.name, "url": storage.signed_download(f.storage_path)}


@router.post("/{onboarding_id}/pause")
def pause(onboarding_id: str, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    aios_sync.kick(request, background, org, onboarding_id)
    return onboarding_detail(services.set_onboarding_status(db, org, onboarding_id, "paused"))


@router.post("/{onboarding_id}/resume")
def resume(onboarding_id: str, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    aios_sync.kick(request, background, org, onboarding_id)
    return onboarding_detail(services.set_onboarding_status(db, org, onboarding_id, "active"))


@router.post("/{onboarding_id}/archive")
def archive(onboarding_id: str, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    aios_sync.kick(request, background, org, onboarding_id)
    return onboarding_detail(services.set_onboarding_status(db, org, onboarding_id, "archived"))


@router.put("/{onboarding_id}/nudges")
def pause_reminders(onboarding_id: str, body: NudgesIn, db: Session = Db, org: str = Org):
    return onboarding_summary(services.set_nudges_paused(db, org, onboarding_id, body.paused))


@router.put("/{onboarding_id}/steps/{key}")
def submit(onboarding_id: str, key: str, body: StepAnswerIn, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org, actor: Actor = Auth):
    aios_sync.kick(request, background, org, onboarding_id)
    """Jay records an answer for a step (on a call, or an internal task)."""
    services.submit_step(db, org, onboarding_id, key, body.data, submitted_by=f"admin:{actor.label}", actor_kind="admin")
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/complete")
def complete(onboarding_id: str, key: str, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    aios_sync.kick(request, background, org, onboarding_id)
    services.complete_step(db, org, onboarding_id, key)
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/skip")
def skip(onboarding_id: str, key: str, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    aios_sync.kick(request, background, org, onboarding_id)
    services.skip_step(db, org, onboarding_id, key)
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/reopen")
def reopen(onboarding_id: str, key: str, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    aios_sync.kick(request, background, org, onboarding_id)
    services.reopen_step(db, org, onboarding_id, key)
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/comments", status_code=201)
def comment(onboarding_id: str, key: str, body: CommentIn, db: Session = Db, org: str = Org, actor: Actor = Auth):
    return comment_out(services.add_comment(db, org, onboarding_id, key, body=body.body, author_kind="admin", author_label=actor.label, client_visible=body.client_visible))


# ---------------------------------------------------------------- reminders and AIOS

@router.post("/{onboarding_id}/nudge")
def remind_now(onboarding_id: str, request: Request, db: Session = Db, org: str = Org):
    """Send a reminder to this onboarding's contacts now. Ignores the stall timer and the pause switch, never the texting rules."""
    st = request.app.state
    ob = services.get_onboarding(db, org, onboarding_id)
    results = [asdict(o) for o in reminders.remind_now(db, st.settings, st.notifier, ob, st.clock())]
    return {"results": results, "message": "" if results else "Nobody has any steps left to do."}


@router.get("/{onboarding_id}/nudges")
def reminder_history(onboarding_id: str, db: Session = Db, org: str = Org):
    services.get_onboarding(db, org, onboarding_id)
    names = {c.id: c.name for c in db.scalars(select(m.Contact).where(m.Contact.org_id == org))}
    rows = db.scalars(select(m.Nudge).where(m.Nudge.onboarding_id == onboarding_id, m.Nudge.org_id == org).order_by(m.Nudge.created_at.desc()).limit(50))
    return [{"id": n.id, "contact": names.get(n.contact_id, ""), "channel": n.channel, "status": n.status, "round": n.round, "kind": n.template,
             "at": n.sent_at or n.created_at, "error": n.error} for n in rows]


@router.get("/{onboarding_id}/sync")
def sync_status(onboarding_id: str, request: Request, db: Session = Db, org: str = Org):
    return aios_sync.status_for(db, request.app.state.settings, services.get_onboarding(db, org, onboarding_id))


@router.post("/{onboarding_id}/sync")
def sync_now(onboarding_id: str, request: Request, db: Session = Db, org: str = Org):
    """Sync this onboarding to AIOS right now and say how it went."""
    st = request.app.state
    services.get_onboarding(db, org, onboarding_id)
    db.commit()  # the sync reads in its own session, so what we've just seen must be saved first
    r = aios_sync.sync_onboarding(st.sessionmaker, st.settings, org, onboarding_id, st.aios)
    db.expire_all()
    return {"result": asdict(r)} | aios_sync.status_for(db, st.settings, services.get_onboarding(db, org, onboarding_id))
