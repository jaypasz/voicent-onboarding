from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import branding, models as m, services, tenancy
from ..deps import AdminOrg, Auth, Actor, Db, Org, Session

router = APIRouter(tags=["org"])


@router.get("/me")
def me(request: Request, actor: Actor = Auth, db: Session = Db):
    """Who is signed in and which organizations they can work in. Behind auth, so it doubles as the check that login works.
    Works before an organization is chosen, so a Voicent superuser (who may work in any of them) can pick one."""
    who = {"id": actor.id, "label": actor.label, "kind": actor.kind}
    if actor.kind != "user":
        orgs = list(db.scalars(select(m.Org).order_by(m.Org.name))) if actor.kind == "service" else [services.get_or_create_org(db, "Local", "local")]
        return who | {"email": actor.label, "superuser": actor.kind == "local", "orgs": [_org_row(o, "admin") for o in orgs]}
    acc = tenancy.access_for(db, getattr(request.app.state, "directory", None), actor.id, actor.label)
    if acc.superuser:
        orgs = list(db.scalars(select(m.Org).order_by(m.Org.name)))
        rows = [_org_row(o, acc.orgs.get(o.id, "admin")) for o in orgs]
    else:
        orgs = list(db.scalars(select(m.Org).where(m.Org.id.in_(acc.orgs)).order_by(m.Org.name))) if acc.orgs else []
        rows = [_org_row(o, acc.orgs[o.id]) for o in orgs]
    return who | {"email": actor.label, "superuser": acc.superuser, "orgs": rows}


def _org_row(o: m.Org, role: str) -> dict:
    return {"id": o.id, "name": o.name, "account_type": o.account_type, "role": role}


def _settings_out(request: Request, org: m.Org) -> dict:
    s = request.app.state.settings
    return {
        "id": org.id, "name": org.name, "slug": org.slug, "account_type": org.account_type, "linked": bool(org.voicent_tenant_id),
        "role": request.state.role, "brand": branding.public(org, s), "logo_url": branding.clean(org.brand).get("logo_url"),
        "brand_name": org.brand_name, "email_from_name": org.email_from_name, "reply_to_email": org.reply_to_email, "sms_from": org.sms_from,
        "email_from_preview": branding.email_from(org, s) if s.resend_from else None,
    }


@router.get("/org")
def get_org(request: Request, db: Session = Db, org: str = Org):
    return _settings_out(request, services.get_org(db, org))


class BrandIn(BaseModel):
    logo_url: str = Field(default="", max_length=500)
    primary_color: str = Field(default="", max_length=7)
    accent_color: str = Field(default="", max_length=7)


class OrgSettingsIn(BaseModel):
    brand_name: str | None = Field(default=None, max_length=120)
    email_from_name: str | None = Field(default=None, max_length=120)
    reply_to_email: str | None = Field(default=None, max_length=200)
    sms_from: str | None = Field(default=None, max_length=20)
    brand: BrandIn | None = None  # only for an organization with no Voicent tenant


@router.put("/org")
def put_org(body: OrgSettingsIn, request: Request, db: Session = Db, org: str = AdminOrg):
    fields = body.model_dump(exclude_unset=True)
    return _settings_out(request, services.update_org_settings(db, org, fields))
