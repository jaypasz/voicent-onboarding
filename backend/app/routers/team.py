from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field

from .. import models as m, notifications, services, tenancy
from ..deps import AdminOrg, Db, Org, SelfOrg, Session

router = APIRouter(tags=["team"])


def _member_out(row: m.OrgMember, me: str | None) -> dict:
    return {"id": row.id, "email": row.email, "name": row.name, "role": row.role, "source": row.source, "is_you": row.id == me,
            "notify_email": row.notify_email if row.id == me else None}


@router.get("/team")
def get_team(request: Request, db: Session = Db, org: str = Org):
    """Who can be given an onboarding or a step. A linked org's team is brought over from Voicent-App first."""
    o = services.get_org(db, org)
    in_sync = tenancy.sync_team(db, getattr(request.app.state, "directory", None), o)
    me = request.state.member_id
    members, invites = services.list_team(db, org)
    return {
        "linked": bool(o.voicent_tenant_id), "in_sync": in_sync, "can_manage": request.state.role == "admin" and not o.voicent_tenant_id,
        "me": me, "members": [_member_out(r, me) for r in members],
        "invites": [{"id": i.id, "email": i.email, "role": i.role, "invited_by": i.invited_by, "created_at": i.created_at} for i in invites],
    }


class InviteIn(BaseModel):
    email: str = Field(max_length=200)
    role: str = "member"


@router.post("/team/invites", status_code=201)
def create_invite(body: InviteIn, request: Request, db: Session = Db, org: str = AdminOrg):
    """For an org with no Voicent tenant. They join when they sign in with this address."""
    from ..auth import current_actor

    i = services.invite(db, org, body.email, body.role, current_actor(request).label)
    return {"id": i.id, "email": i.email, "role": i.role}


@router.delete("/team/invites/{invite_id}", status_code=204)
def delete_invite(invite_id: str, db: Session = Db, org: str = AdminOrg):
    services.cancel_invite(db, org, invite_id)


class MemberPatch(BaseModel):
    role: str


@router.patch("/team/members/{member_id}")
def patch_member(member_id: str, body: MemberPatch, request: Request, db: Session = Db, org: str = AdminOrg):
    return _member_out(services.change_member(db, org, member_id, role=body.role), request.state.member_id)


@router.delete("/team/members/{member_id}", status_code=204)
def delete_member(member_id: str, db: Session = Db, org: str = AdminOrg):
    services.change_member(db, org, member_id, remove=True)


class MeIn(BaseModel):
    notify_email: bool | None = None
    name: str | None = Field(default=None, max_length=200)


@router.put("/team/me")
def put_me(body: MeIn, request: Request, db: Session = Db, org: str = SelfOrg):
    row = services.update_me(db, org, request.state.member_id, notify_email=body.notify_email, name=body.name)
    return _member_out(row, request.state.member_id)


# ---------------------------------------------------------------- notifications

@router.get("/notifications")
def get_notifications(request: Request, unread_only: bool = False, db: Session = Db, org: str = SelfOrg):
    rows, unread = notifications.for_member(db, org, request.state.member_id, unread_only)
    return {"unread": unread, "items": [
        {"id": n.id, "kind": n.kind, "text": n.text, "onboarding_id": n.onboarding_id, "step_key": n.step_key, "read": n.read_at is not None,
         "created_at": n.created_at} for n in rows]}


class ReadIn(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=200)  # leave out to mark all as read


@router.post("/notifications/read")
def read_notifications(body: ReadIn, request: Request, db: Session = Db, org: str = SelfOrg):
    return {"marked": notifications.mark_read(db, org, request.state.member_id, body.ids, request.app.state.clock())}


# ---------------------------------------------------------------- assigning

class AssignIn(BaseModel):
    member_id: str | None = None


@router.put("/onboardings/{onboarding_id}/owner")
def set_owner(onboarding_id: str, body: AssignIn, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    from ..schemas import onboarding_detail

    ob = services.set_onboarding_owner(db, org, onboarding_id, body.member_id, request.state.member_id)
    notifications.kick(request, background)
    return onboarding_detail(ob)


@router.put("/onboardings/{onboarding_id}/steps/{key}/team-assignee")
def set_step_assignee(onboarding_id: str, key: str, body: AssignIn, request: Request, background: BackgroundTasks, db: Session = Db, org: str = Org):
    from ..schemas import step_out

    step = services.set_step_team_assignee(db, org, onboarding_id, key, body.member_id, request.state.member_id)
    notifications.kick(request, background)
    return step_out(services.get_onboarding(db, org, onboarding_id), step)
