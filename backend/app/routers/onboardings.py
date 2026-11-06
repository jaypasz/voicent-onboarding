from __future__ import annotations

from fastapi import APIRouter

from .. import services
from ..deps import Actor, Auth, Db, Org, Session
from ..schemas import CommentIn, NudgesIn, OnboardingIn, StepAnswerIn, comment_out, onboarding_detail, onboarding_summary, step_out

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


@router.post("/{onboarding_id}/send")
def send(onboarding_id: str, db: Session = Db, org: str = Org):
    return onboarding_detail(services.send_onboarding(db, org, onboarding_id))


@router.post("/{onboarding_id}/pause")
def pause(onboarding_id: str, db: Session = Db, org: str = Org):
    return onboarding_detail(services.set_onboarding_status(db, org, onboarding_id, "paused"))


@router.post("/{onboarding_id}/resume")
def resume(onboarding_id: str, db: Session = Db, org: str = Org):
    return onboarding_detail(services.set_onboarding_status(db, org, onboarding_id, "active"))


@router.post("/{onboarding_id}/archive")
def archive(onboarding_id: str, db: Session = Db, org: str = Org):
    return onboarding_detail(services.set_onboarding_status(db, org, onboarding_id, "archived"))


@router.put("/{onboarding_id}/nudges")
def nudges(onboarding_id: str, body: NudgesIn, db: Session = Db, org: str = Org):
    return onboarding_summary(services.set_nudges_paused(db, org, onboarding_id, body.paused))


@router.put("/{onboarding_id}/steps/{key}")
def submit(onboarding_id: str, key: str, body: StepAnswerIn, db: Session = Db, org: str = Org, actor: Actor = Auth):
    """Jay records an answer for a step (on a call, or an internal task)."""
    services.submit_step(db, org, onboarding_id, key, body.data, submitted_by=f"admin:{actor.label}", actor_kind="admin")
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/complete")
def complete(onboarding_id: str, key: str, db: Session = Db, org: str = Org):
    services.complete_step(db, org, onboarding_id, key)
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/skip")
def skip(onboarding_id: str, key: str, db: Session = Db, org: str = Org):
    services.skip_step(db, org, onboarding_id, key)
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/reopen")
def reopen(onboarding_id: str, key: str, db: Session = Db, org: str = Org):
    services.reopen_step(db, org, onboarding_id, key)
    return _step(db, org, onboarding_id, key)


@router.post("/{onboarding_id}/steps/{key}/comments", status_code=201)
def comment(onboarding_id: str, key: str, body: CommentIn, db: Session = Db, org: str = Org, actor: Actor = Auth):
    return comment_out(services.add_comment(db, org, onboarding_id, key, body=body.body, author_kind="admin", author_label=actor.label, client_visible=body.client_visible))
