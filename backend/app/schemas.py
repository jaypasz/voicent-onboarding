from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import models as m

ClientKind = Literal["trades", "agency", "msp", "other"]


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: ClientKind = "other"
    notes: str = Field(default="", max_length=5000)


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: ClientKind | None = None
    status: Literal["active", "archived"] | None = None
    notes: str | None = Field(default=None, max_length=5000)


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=32)
    role: str = Field(default="", max_length=40)
    sms_consent: bool = False
    sms_consent_source: str = Field(default="", max_length=200)


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    role: str | None = Field(default=None, max_length=40)
    sms_consent: bool | None = None
    sms_consent_source: str | None = Field(default=None, max_length=200)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    client_id: str
    name: str
    email: str
    phone: str
    role: str
    sms_consent: bool
    sms_consent_source: str


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    kind: str
    status: str
    notes: str
    created_at: dt.datetime
    contacts: list[ContactOut] = []


class TemplateYamlIn(BaseModel):
    yaml: str
    dry_run: bool = False


class TemplateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    slug: str
    current_version: int
    archived: bool


class OnboardingIn(BaseModel):
    client_id: str
    template_id: str
    title: str = Field(default="", max_length=200)
    version: int | None = Field(default=None, ge=1)


class StepAnswerIn(BaseModel):
    data: Any


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    client_visible: bool = True


class NudgesIn(BaseModel):
    paused: bool


def template_out(t: m.Template, doc: m.TemplateVersion, versions: list[int] | None = None) -> dict:
    return {
        "id": t.id, "name": t.name, "slug": t.slug, "current_version": t.current_version, "archived": t.archived,
        "document": doc.document, "versions": versions if versions is not None else [t.current_version],
    }


def comment_out(c: m.StepComment) -> dict:
    return {"id": c.id, "author_kind": c.author_kind, "author_label": c.author_label, "body": c.body,
            "client_visible": c.client_visible, "created_at": c.created_at}


def step_out(ob: m.Onboarding, s: m.Step) -> dict:
    """The admin's view of a step: everything, internal steps included."""
    cfg = next(d["config"] for d in ob.document["steps"] if d["key"] == s.key)
    last = s.responses[-1] if s.responses else None
    return {
        "id": s.id, "key": s.key, "type": s.type, "title": s.title, "section": s.section, "position": s.position,
        "visibility": s.visibility, "status": s.status, "assignee_contact_id": s.assignee_contact_id,
        "due_at": s.due_at, "completed_at": s.completed_at, "config": cfg,
        "response": {"revision": last.revision, "data": last.data, "submitted_by": last.submitted_by, "submitted_at": last.submitted_at} if last else None,
        "revisions": len(s.responses),
        "files": [{"id": f.id, "name": f.name, "size": f.size, "content_type": f.content_type} for f in s.files],
        "comments": [comment_out(c) for c in s.comments],
    }


def onboarding_summary(ob: m.Onboarding) -> dict:
    live = [s for s in ob.steps if s.status != "skipped"]
    return {
        "id": ob.id, "client_id": ob.client_id, "title": ob.title, "layout": ob.layout, "status": ob.status,
        "started_at": ob.started_at, "completed_at": ob.completed_at, "last_activity_at": ob.last_activity_at,
        "nudges_paused": ob.nudges_paused,
        "progress": {"done": sum(1 for s in live if s.status == "done"), "total": len(live)},
    }


def onboarding_detail(ob: m.Onboarding) -> dict:
    return onboarding_summary(ob) | {"steps": [step_out(ob, s) for s in ob.steps]}
