from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import models as m
from . import embeds, services, stages
from .config import valid_timezone

ClientKind = Literal["trades", "agency", "msp", "other"]


def _tz(v: str | None) -> str | None:
    if v is not None and not valid_timezone(v):
        raise ValueError("That isn't a time zone name. Use one like America/New_York.")
    return v


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: ClientKind = "other"
    notes: str = Field(default="", max_length=5000)
    timezone: str | None = Field(default=None, max_length=64)
    _tz = field_validator("timezone")(_tz)


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: ClientKind | None = None
    status: Literal["active", "archived"] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    timezone: str | None = Field(default=None, max_length=64)
    _tz = field_validator("timezone")(_tz)


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
    timezone: str
    created_at: dt.datetime
    paying_since: dt.datetime | None = None
    outcome: str | None = None
    stage: str
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
    # A customised copy for this client: replaces the template's sections and steps. Leave both out to use the template as is.
    sections: list[Any] | None = Field(default=None, max_length=20)
    steps: list[Any] | None = Field(default=None, max_length=100)


class OnboardingStepsIn(BaseModel):
    sections: list[Any] = Field(default_factory=list, max_length=20)
    steps: list[Any] = Field(max_length=100)
    # What the editor was looking at (from GET /document). If the steps changed since, the save is refused.
    etag: str | None = Field(default=None, max_length=64)
    # After sending, tell the client about the change (one batched message). Off for a typo fix.
    notify_client: bool = True


class ScheduleIn(BaseModel):
    """A step's schedule as calendar days. Both are replaced: leave one out (or null) to clear it."""
    start_on: dt.date | None = None
    due_on: dt.date | None = None


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


def step_out(ob: m.Onboarding, s: m.Step, locked: set[str] | None = None) -> dict:
    """The admin's view of a step: everything, internal steps included."""
    doc = next(d for d in ob.document["steps"] if d["key"] == s.key)
    cfg = doc["config"]
    locked = stages.locked_keys(ob) if locked is None else locked
    tz = ob.client.timezone if ob.client else "UTC"
    last = s.responses[-1] if s.responses else None
    return {
        "id": s.id, "key": s.key, "type": s.type, "title": s.title, "section": s.section, "position": s.position,
        "visibility": s.visibility, "status": s.status, "assignee_contact_id": s.assignee_contact_id, "team_assignee_id": s.team_assignee_id,
        "due_at": s.due_at, "due_on": services.due_on(s, tz), "start_on": s.start_on, "completed_at": s.completed_at, "config": cfg,
        "resources": embeds.resources(doc), "media": embeds.media(doc),
        "locked": s.key in locked,  # the client can't work on it until an earlier stage is signed off
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
        "nudges_paused": ob.nudges_paused, "attention": ob.attention, "provision_state": ob.provision_state,
        "owner_member_id": ob.owner_member_id,
        "progress": {"done": sum(1 for s in live if s.status == "done"), "total": len(live)},
    }


def stage_out(ob: m.Onboarding, st: stages.Stage) -> dict:
    tz = ob.client.timezone if ob.client else "UTC"
    live = [s for s in st.steps if s.status != "skipped"]
    starts = [s.start_on for s in st.steps if s.start_on]
    dues = [d for d in (services.due_on(s, tz) for s in st.steps) if d]
    return {
        "key": st.key, "title": st.title, "signoff": st.signoff, "state": st.state,
        "signed_by": st.signed.signed_by if st.signed else None, "signed_at": st.signed.signed_at if st.signed else None,
        "progress": {"done": sum(1 for s in live if s.status == "done"), "total": len(live)},
        "start_on": min(starts) if starts else None, "due_on": max(dues) if dues else None,
    }


def onboarding_detail(ob: m.Onboarding) -> dict:
    locked = stages.locked_keys(ob)
    return onboarding_summary(ob) | {
        "stages": [stage_out(ob, st) for st in stages.stages(ob)],
        "stage_notice_pending": ob.stage_opened_at is not None,  # the client is about to hear the next stage is open
        "steps": [step_out(ob, s, locked) for s in stages.ordered_steps(ob, list(ob.steps))],
    }


class TaskIn(BaseModel):
    client_id: str
    title: str = Field(min_length=1, max_length=200)
    assignee_id: str | None = None
    due_on: dt.date | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    assignee_id: str | None = None
    due_on: dt.date | None = None
    done: bool | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    client_id: str
    title: str
    assignee_id: str | None
    due_on: dt.date | None
    done_at: dt.datetime | None
    created_at: dt.datetime


class TeamStepTaskOut(BaseModel):
    """A team task that lives in an onboarding's flow, shown on the Tasks page next to the standalone ones."""
    onboarding_id: str
    key: str
    title: str
    client_id: str
    status: str
    team_assignee_id: str | None
    due_at: dt.datetime | None
