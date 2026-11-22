"""The rules. Routers call these; nothing else writes to the database.

Every function takes org_id and filters by it. A row from another org is a NotFound, never a leak.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import models as m
from . import branding, changes, notifications, provision, stages
from .errors import Conflict, Invalid, NotFound
from .redact import redact
from .steps import registry
from .steps.upload import ALLOWED_UPLOADS, SNIFF_BYTES, content_matches
from .storage import extension, stored_content_type
from .templates import loader

ONBOARDING_STATUSES = ("draft", "active", "paused", "completed", "archived")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------- orgs

def get_or_create_org(db: Session, name: str, slug: str) -> m.Org:
    org = db.scalar(select(m.Org).where(m.Org.slug == slug))
    if org:
        return org
    org = m.Org(name=name, slug=slug)
    db.add(org)
    db.flush()
    return org


def add_member(db: Session, org_id: str, auth_user_id: str, email: str = "") -> m.OrgMember:
    row = db.scalar(select(m.OrgMember).where(m.OrgMember.org_id == org_id, m.OrgMember.auth_user_id == auth_user_id))
    if row:
        return row
    row = m.OrgMember(org_id=org_id, auth_user_id=auth_user_id, email=email)
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------- the org's own settings

ORG_FIELDS = ("brand_name", "email_from_name", "reply_to_email", "sms_from")


def get_org(db: Session, org_id: str) -> m.Org:
    org = db.get(m.Org, org_id)
    if not org:
        raise NotFound("Organization not found.")
    return org


def update_org_settings(db: Session, org_id: str, fields: dict) -> m.Org:
    """The name clients see and the senders that reach them. Logo and colours only for an org with no Voicent tenant: for
    the others Voicent-App is where they are set, and they are copied from there."""
    org = get_org(db, org_id)
    if "brand" in fields and org.voicent_tenant_id:
        raise Conflict("This organization's logo and colours come from Voicent-App. Change them there.")
    fields = {k: (v.strip() if isinstance(v, str) else v) for k, v in fields.items()}
    problems = branding.settings_problems(fields)
    if problems:
        raise Invalid("Some settings need fixing.", problems)
    for k in ORG_FIELDS:
        if k in fields and fields[k] is not None:
            setattr(org, k, redact(fields[k]) if k in ("brand_name", "email_from_name") else fields[k])
    if "brand" in fields and fields["brand"] is not None:
        org.brand = branding.clean(fields["brand"])
    db.flush()
    return org


# ---------------------------------------------------------------- the team

ROLES = ("admin", "manager", "member", "viewer")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _member(db: Session, org_id: str, member_id: str) -> m.OrgMember:
    row = db.scalar(select(m.OrgMember).where(m.OrgMember.id == member_id, m.OrgMember.org_id == org_id))
    if not row:
        raise NotFound("That person isn't on this team.")
    return row


def list_team(db: Session, org_id: str) -> tuple[list[m.OrgMember], list[m.OrgInvite]]:
    members = list(db.scalars(select(m.OrgMember).where(m.OrgMember.org_id == org_id).order_by(m.OrgMember.email)))
    invites = list(db.scalars(select(m.OrgInvite).where(m.OrgInvite.org_id == org_id, m.OrgInvite.accepted_at.is_(None)).order_by(m.OrgInvite.created_at)))
    return members, invites


def _not_linked(org: m.Org) -> None:
    if org.voicent_tenant_id:
        raise Conflict("This team comes from Voicent-App. Add people and change their roles there.")


def invite(db: Session, org_id: str, email: str, role: str, by: str) -> m.OrgInvite:
    org = get_org(db, org_id)
    _not_linked(org)
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise Invalid("That isn't an email address.")
    if role not in ROLES:
        raise Invalid(f"Role must be one of {', '.join(ROLES)}.")
    if db.scalar(select(m.OrgMember.id).where(m.OrgMember.org_id == org_id, func.lower(m.OrgMember.email) == email)):
        raise Conflict("That person is already on the team.")
    row = db.scalar(select(m.OrgInvite).where(m.OrgInvite.org_id == org_id, m.OrgInvite.email == email))
    if row is None:
        row = m.OrgInvite(org_id=org_id, email=email)
        db.add(row)
    row.role, row.invited_by, row.accepted_at = role, by[:200], None
    db.flush()
    return row


def cancel_invite(db: Session, org_id: str, invite_id: str) -> None:
    row = db.scalar(select(m.OrgInvite).where(m.OrgInvite.id == invite_id, m.OrgInvite.org_id == org_id))
    if not row:
        raise NotFound("Invite not found.")
    db.delete(row)
    db.flush()


def _admins_left(db: Session, org_id: str, without: str) -> int:
    return len(list(db.scalars(select(m.OrgMember.id).where(m.OrgMember.org_id == org_id, m.OrgMember.role == "admin", m.OrgMember.id != without))))


def change_member(db: Session, org_id: str, member_id: str, *, role: str | None = None, remove: bool = False) -> m.OrgMember | None:
    """Roles of people copied from Voicent-App are set there. The last admin can't be removed or demoted.

    The org row is locked first, so two of these for one org run one after the other: otherwise two admins removing or
    demoting each other at once would each still see the other as an admin, and both would succeed."""
    org = db.scalar(select(m.Org).where(m.Org.id == org_id).with_for_update().execution_options(populate_existing=True))
    if not org:
        raise NotFound("Organization not found.")
    row = _member(db, org_id, member_id)
    if row.source == "voicent" or org.voicent_tenant_id:
        raise Conflict("This person's role comes from Voicent-App. Change it there.")
    if (remove or (role and role != "admin")) and row.role == "admin" and _admins_left(db, org_id, row.id) == 0:
        raise Conflict("The team needs at least one admin.")
    if remove:
        db.delete(row)
        db.flush()
        return None
    if role is not None:
        if role not in ROLES:
            raise Invalid(f"Role must be one of {', '.join(ROLES)}.")
        row.role = role
    db.flush()
    return row


def update_me(db: Session, org_id: str, member_id: str | None, *, notify_email: bool | None = None, name: str | None = None) -> m.OrgMember:
    if not member_id:
        raise Conflict("You aren't on this organization's team, so there is nothing of yours to change here.")
    row = _member(db, org_id, member_id)
    if notify_email is not None:
        row.notify_email = notify_email
    if name is not None:
        row.name = redact(name.strip())[:200]
    db.flush()
    return row


def set_onboarding_owner(db: Session, org_id: str, onboarding_id: str, member_id: str | None, by_member_id: str | None) -> m.Onboarding:
    ob = _onboarding(db, org_id, onboarding_id)
    if member_id is not None:
        _member(db, org_id, member_id)
    if ob.owner_member_id != member_id:
        ob.owner_member_id = member_id
        notifications.onboarding_owner_set(db, ob, by_member_id)
    db.flush()
    return ob


def set_step_team_assignee(db: Session, org_id: str, onboarding_id: str, key: str, member_id: str | None, by_member_id: str | None) -> m.Step:
    ob, step = _step(db, org_id, onboarding_id, key)
    if member_id is not None:
        _member(db, org_id, member_id)
    if step.team_assignee_id != member_id:
        step.team_assignee_id = member_id
        notifications.step_assignee_set(db, ob, step, by_member_id)
    db.flush()
    return step


# ---------------------------------------------------------------- clients and contacts

def _client(db: Session, org_id: str, client_id: str) -> m.Client:
    c = db.scalar(select(m.Client).where(m.Client.id == client_id, m.Client.org_id == org_id))
    if not c:
        raise NotFound("Client not found.")
    return c


def get_client(db: Session, org_id: str, client_id: str) -> m.Client:
    return _client(db, org_id, client_id)


STAGES = ("lead", "onboarding", "won", "lost", "stalled")


def list_clients(db: Session, org_id: str, status: str | None = None, stage: str | None = None) -> list[m.Client]:
    if stage is not None and stage not in STAGES:
        raise Invalid(f"Stage must be one of {', '.join(STAGES)}.")
    q = select(m.Client).where(m.Client.org_id == org_id).options(selectinload(m.Client.onboardings)).order_by(m.Client.name)
    if status:
        q = q.where(m.Client.status == status)
    rows = list(db.scalars(q))
    return [c for c in rows if c.stage == stage] if stage else rows


def set_client_outcome(db: Session, org_id: str, client_id: str, outcome: str | None) -> m.Client:
    """Jay's call that a prospect is lost or stalled, or null to take it back. A paying client can't be marked: they're won."""
    c = _client(db, org_id, client_id)
    if outcome is not None and c.paying_since:
        raise Conflict("This client is paying. Unmark them as paying first.")
    c.outcome = outcome
    db.flush()
    return c


def _task(db: Session, org_id: str, task_id: str) -> m.Task:
    t = db.scalar(select(m.Task).where(m.Task.id == task_id, m.Task.org_id == org_id))
    if not t:
        raise NotFound("Task not found.")
    return t


def list_tasks(db: Session, org_id: str, *, client_id: str | None = None,
               assignee_id: str | None = None, done: bool | None = None) -> list[m.Task]:
    q = select(m.Task).where(m.Task.org_id == org_id)
    if client_id:
        q = q.where(m.Task.client_id == client_id)
    if assignee_id:
        q = q.where(m.Task.assignee_id == assignee_id)
    if done is not None:
        q = q.where(m.Task.done_at.is_not(None) if done else m.Task.done_at.is_(None))
    # Open work first, soonest due first (undated last), then newest.
    return list(db.scalars(q.order_by(m.Task.done_at.is_not(None), m.Task.due_on.is_(None), m.Task.due_on, m.Task.created_at.desc())))


def list_team_steps(db: Session, org_id: str, *, assignee_id: str | None = None, done: bool | None = None) -> list[dict]:
    """The team's own task steps across every onboarding that is under way. They sit in the flow, so the Tasks page reads them from there."""
    q = (select(m.Step, m.Onboarding).join(m.Onboarding, m.Onboarding.id == m.Step.onboarding_id)
         .where(m.Step.org_id == org_id, m.Step.type == "task", m.Step.visibility == "internal", m.Onboarding.status.in_(("active", "paused"))))
    if assignee_id:
        q = q.where(m.Step.team_assignee_id == assignee_id)
    out = []
    for step, ob in db.execute(q):
        finished = step.status in ("done", "skipped")
        if done is not None and finished != done:
            continue
        out.append({"onboarding_id": ob.id, "key": step.key, "title": step.title, "client_id": ob.client_id, "status": step.status,
                    "team_assignee_id": step.team_assignee_id, "due_at": step.due_at})
    far = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    out.sort(key=lambda r: (r["status"] in ("done", "skipped"), (r["due_at"] if r["due_at"] and r["due_at"].tzinfo else (r["due_at"].replace(tzinfo=dt.timezone.utc) if r["due_at"] else far))))
    return out


def create_task(db: Session, org_id: str, *, client_id: str, title: str, assignee_id: str | None = None, due_on: dt.date | None = None) -> m.Task:
    _client(db, org_id, client_id)
    if assignee_id:
        _member(db, org_id, assignee_id)
    t = m.Task(org_id=org_id, client_id=client_id, title=redact(title.strip()), assignee_id=assignee_id, due_on=due_on)
    db.add(t)
    db.flush()
    return t


def update_task(db: Session, org_id: str, task_id: str, fields: dict, at: dt.datetime) -> m.Task:
    """`fields` holds only what was sent, so null clears an assignee or a date while leaving out leaves it alone."""
    t = _task(db, org_id, task_id)
    if "title" in fields and fields["title"] is not None:
        t.title = redact(fields["title"].strip())
    if "assignee_id" in fields:
        if fields["assignee_id"]:
            _member(db, org_id, fields["assignee_id"])
        t.assignee_id = fields["assignee_id"]
    if "due_on" in fields:
        t.due_on = fields["due_on"]
    if fields.get("done") is not None:
        t.done_at = (t.done_at or at) if fields["done"] else None
    db.flush()
    return t


def delete_task(db: Session, org_id: str, task_id: str) -> None:
    db.delete(_task(db, org_id, task_id))
    db.flush()


def create_client(db: Session, org_id: str, *, name: str, kind: str = "other", notes: str = "", timezone: str = "America/New_York") -> m.Client:
    c = m.Client(org_id=org_id, name=redact(name.strip()), kind=kind, notes=redact(notes), timezone=timezone)
    db.add(c)
    db.flush()
    return c


def update_client(db: Session, org_id: str, client_id: str, **fields) -> m.Client:
    c = _client(db, org_id, client_id)
    for k, v in fields.items():
        if v is not None:
            setattr(c, k, redact(v.strip()) if k in ("name", "notes") else v)
    db.flush()
    return c


def set_client_paying(db: Session, org_id: str, client_id: str, paying: bool, at: dt.datetime) -> tuple[m.Client, list[str]]:
    """Mark a client as paying, or not. A Voicent workspace is only asked for once a client pays, so marking one as paying
    queues the request for every finished onboarding of theirs whose template wants a workspace. Unmarking cancels any
    request still waiting; one already accepted by Voicent-App stays. Returns the client and the onboarding ids queued.

    The client row is locked before its onboardings are read, and finishing an onboarding takes the same lock (_after_change),
    so marking a client as paying and their last step can't each miss the other and leave a finished, paying client with no
    request queued."""
    c = db.scalar(select(m.Client).where(m.Client.id == client_id, m.Client.org_id == org_id).with_for_update()
                  .execution_options(populate_existing=True))
    if not c:
        raise NotFound("Client not found.")
    queued = []
    obs = list(db.scalars(select(m.Onboarding).where(m.Onboarding.client_id == c.id, m.Onboarding.org_id == org_id)))
    if paying:
        if c.paying_since is None:
            c.paying_since = at
        db.flush()
        for ob in obs:
            if ob.status == "completed" and provision.queue(ob, at):
                queued.append(ob.id)
    else:
        c.paying_since = None
        for ob in obs:
            if ob.provision_state == "pending":
                ob.provision_state, ob.provision_next_at, ob.provision_error = None, None, ""
    db.flush()
    return c, queued


def add_contact(db: Session, org_id: str, client_id: str, *, name: str, email: str = "", phone: str = "", role: str = "",
                sms_consent: bool = False, sms_consent_source: str = "") -> m.Contact:
    _client(db, org_id, client_id)
    if sms_consent and not sms_consent_source.strip():
        raise Invalid("Say where the SMS consent came from.")
    c = m.Contact(
        org_id=org_id, client_id=client_id, name=name.strip(), email=email.strip(), phone=phone.strip(), role=role.strip().lower(),
        sms_consent=sms_consent, sms_consent_source=sms_consent_source.strip(), sms_consent_at=now() if sms_consent else None,
    )
    db.add(c)
    db.flush()
    return c


def update_contact(db: Session, org_id: str, client_id: str, contact_id: str, **fields) -> m.Contact:
    _client(db, org_id, client_id)
    c = db.scalar(select(m.Contact).where(m.Contact.id == contact_id, m.Contact.client_id == client_id, m.Contact.org_id == org_id))
    if not c:
        raise NotFound("Contact not found.")
    consent = fields.pop("sms_consent", None)
    source = fields.pop("sms_consent_source", None)
    for k, v in fields.items():
        if v is not None:
            setattr(c, k, v.strip().lower() if k == "role" else v.strip())
    if source is not None:
        c.sms_consent_source = source.strip()
    if consent is not None:
        if consent and not c.sms_consent_source:
            raise Invalid("Say where the SMS consent came from.")
        if consent and not c.sms_consent:
            c.sms_consent_at = now()
        c.sms_consent = consent
        if not consent:
            c.sms_consent_at = None
    db.flush()
    return c


# ---------------------------------------------------------------- templates

def _template(db: Session, org_id: str, template_id: str) -> m.Template:
    t = db.scalar(select(m.Template).where(m.Template.id == template_id, m.Template.org_id == org_id))
    if not t:
        raise NotFound("Template not found.")
    return t


def get_template(db: Session, org_id: str, template_id: str) -> m.Template:
    return _template(db, org_id, template_id)


def list_templates(db: Session, org_id: str, include_archived: bool = False) -> list[m.Template]:
    q = select(m.Template).where(m.Template.org_id == org_id).order_by(m.Template.name)
    if not include_archived:
        q = q.where(m.Template.archived.is_(False))
    return list(db.scalars(q))


def template_document(db: Session, org_id: str, template: m.Template, version: int | None = None) -> m.TemplateVersion:
    v = db.scalar(select(m.TemplateVersion).where(
        m.TemplateVersion.template_id == template.id, m.TemplateVersion.org_id == org_id,
        m.TemplateVersion.version == (version or template.current_version)))
    if not v:
        raise NotFound("Template version not found.")
    return v


def save_template(db: Session, org_id: str, document, *, created_by: str = "", create_only: bool = False) -> tuple[m.Template, m.TemplateVersion, bool]:
    """Validate and store a document. A new slug makes a template; an existing slug adds a version, unless nothing changed.
    With create_only (a new template, or "save as template"), an existing slug is refused instead, archived ones included,
    so a template is never changed, or brought back from the archive, by something that promised a new one.

    Returns (template, version, created_new_version). Raises TemplateInvalid listing every problem.
    """
    doc = loader.check(document)
    t = db.scalar(select(m.Template).where(m.Template.org_id == org_id, m.Template.slug == doc["slug"]))
    if t is not None and create_only:
        where = " (it's archived)" if t.archived else ""
        raise Conflict(f"A template called “{t.name}” already uses that name{where}. Choose another name.")
    if t is None:
        t = m.Template(org_id=org_id, name=doc["name"], slug=doc["slug"], current_version=1)
        db.add(t)
        db.flush()
        doc["version"] = 1
        v = m.TemplateVersion(org_id=org_id, template_id=t.id, version=1, document=doc, created_by=created_by)
        db.add(v)
        db.flush()
        return t, v, True
    current = template_document(db, org_id, t)
    if _same_content(current.document, doc):
        return t, current, False
    n = max(v.version for v in t.versions) + 1
    doc["version"] = n
    v = m.TemplateVersion(org_id=org_id, version=n, document=doc, created_by=created_by)
    t.versions.append(v)  # through the relationship, so t.versions is current when the router lists it
    t.current_version, t.name, t.archived = n, doc["name"], False
    db.flush()
    return t, v, True


def _same_content(a: dict, b: dict) -> bool:
    strip = lambda d: {k: v for k, v in d.items() if k != "version"}  # noqa: E731
    return strip(a) == strip(b)


def install_presets(db: Session, org_id: str, created_by: str = "presets") -> list[str]:
    """Add any shipped preset the org doesn't have yet. Existing templates are left alone, even if edited."""
    added = []
    for doc in loader.load_presets():
        if not db.scalar(select(m.Template.id).where(m.Template.org_id == org_id, m.Template.slug == doc["slug"])):
            save_template(db, org_id, doc, created_by=created_by)
            added.append(doc["slug"])
    return added


def archive_template(db: Session, org_id: str, template_id: str, archived: bool = True) -> m.Template:
    t = _template(db, org_id, template_id)
    t.archived = archived
    db.flush()
    return t


# ---------------------------------------------------------------- onboardings

def _onboarding(db: Session, org_id: str, onboarding_id: str) -> m.Onboarding:
    ob = db.scalar(select(m.Onboarding).where(m.Onboarding.id == onboarding_id, m.Onboarding.org_id == org_id))
    if not ob:
        raise NotFound("Onboarding not found.")
    return ob


def get_onboarding(db: Session, org_id: str, onboarding_id: str) -> m.Onboarding:
    return _onboarding(db, org_id, onboarding_id)


def list_onboardings(db: Session, org_id: str, status: str | None = None, client_id: str | None = None, owner_member_id: str | None = None) -> list[m.Onboarding]:
    q = select(m.Onboarding).where(m.Onboarding.org_id == org_id).order_by(m.Onboarding.last_activity_at.desc())
    if status:
        q = q.where(m.Onboarding.status == status)
    if client_id:
        q = q.where(m.Onboarding.client_id == client_id)
    if owner_member_id:
        q = q.where(m.Onboarding.owner_member_id == owner_member_id)
    return list(db.scalars(q))


def _with_steps(doc: dict, sections: list | None, steps: list | None) -> dict:
    """The document with its sections and steps swapped for the ones given, validated like any template.
    Only sections and steps can be customised per client: the name, slug, layout and on_complete stay the template's."""
    if sections is None and steps is None:
        return doc
    return loader.check({**doc, "sections": doc["sections"] if sections is None else sections, "steps": doc["steps"] if steps is None else steps})


def _assignee(contacts: list[m.Contact], role: str) -> str | None:
    c = next((c for c in contacts if role and c.role == role), None)
    return c.id if c else None


def _contacts(db: Session, org_id: str, client_id: str) -> list[m.Contact]:
    return list(db.scalars(select(m.Contact).where(m.Contact.client_id == client_id, m.Contact.org_id == org_id).order_by(m.Contact.created_at)))


def create_onboarding(db: Session, org_id: str, *, client_id: str, template_id: str, title: str = "", version: int | None = None,
                      sections: list | None = None, steps: list | None = None, owner_member_id: str | None = None) -> m.Onboarding:
    """Copy the template version into the onboarding. Editing the template afterwards changes nothing here.
    With sections or steps, this client gets a customised copy; the template itself is not touched."""
    client = _client(db, org_id, client_id)
    t = _template(db, org_id, template_id)
    tv = template_document(db, org_id, t, version)
    doc = _with_steps(copy.deepcopy(tv.document), sections, steps)
    contacts = _contacts(db, org_id, client.id)
    ob = m.Onboarding(
        org_id=org_id, client_id=client.id, template_version_id=tv.id, title=redact(title.strip()) or f"{doc['name']}: {client.name}",
        layout=doc["layout"], status="draft", document=doc, owner_member_id=owner_member_id,  # whoever makes it looks after it
    )
    db.add(ob)
    db.flush()
    for i, s in enumerate(doc["steps"]):
        ob.steps.append(m.Step(
            org_id=org_id, key=s["key"], type=s["type"], title=s["title"], section=s["section"], position=i,
            visibility=s["visibility"], assignee_contact_id=_assignee(contacts, s["assignee_role"]),
        ))
    db.flush()
    return ob


def _has_data(step: m.Step) -> bool:
    return bool(step.responses or step.files or step.comments)


def locked_step_keys(ob: m.Onboarding) -> list[str]:
    """Steps that already hold answers, files or comments: they can be edited but not removed or turned into another type."""
    return [s.key for s in ob.steps if _has_data(s)]


def document_etag(doc: dict) -> str:
    """A fingerprint of an onboarding's steps, so a save made from a stale screen is refused instead of overwriting someone else's edit."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:16]


def update_onboarding_steps(db: Session, org_id: str, onboarding_id: str, *, sections: list, steps: list, etag: str | None = None, notify_client: bool = True) -> m.Onboarding:
    """Replace an onboarding's sections and steps. A draft can change freely; after sending, the same rules hold (a step that
    holds answers, files or comments can be edited but not removed or retyped; skip it instead) and what depends on the steps is
    brought in line: new steps get due dates from the start, the onboarding reopens when it gains an open step or finishes when
    it loses the last one, and the AIOS sync follows. Only an archived onboarding is closed to changes."""
    ob = _onboarding(db, org_id, onboarding_id)
    if ob.status == "archived":
        raise Conflict("This onboarding is archived, so its steps can't change.")
    if etag is not None and etag != document_etag(ob.document):
        raise Conflict("These steps were changed by someone else after you opened them. Reload to see their changes, then make yours again.")
    sent = ob.status != "draft"
    seen_before = changes.snapshot(ob.document)
    doc = _with_steps(ob.document, sections, steps)
    wanted = {d["key"]: d for d in doc["steps"]}
    existing = {s.key: s for s in ob.steps}
    problems = []
    for key, s in existing.items():
        if not _has_data(s):
            continue
        if key not in wanted:
            problems.append(f"'{s.title}' already has answers, files or comments, so it can't be removed." + (" Skip it instead." if sent else ""))
        elif wanted[key]["type"] != s.type:
            problems.append(f"'{s.title}' already has answers, files or comments, so its type can't change.")
        elif wanted[key]["visibility"] != s.visibility:
            problems.append(f"'{s.title}' already has answers, files or comments, so who it is for can't change.")
    if problems:
        raise Conflict("Some steps can't be changed.", problems)
    old_roles = {d["key"]: d.get("assignee_role", "") for d in ob.document["steps"]}
    contacts = _contacts(db, org_id, ob.client_id)
    for key, s in existing.items():
        if key not in wanted:
            ob.steps.remove(s)  # delete-orphan removes the row
    for i, d in enumerate(doc["steps"]):
        s = existing.get(d["key"])
        if s is None:
            s = m.Step(org_id=org_id, key=d["key"], assignee_contact_id=_assignee(contacts, d["assignee_role"]))
            if sent and d.get("due_offset_days") is not None and ob.started_at:
                s.due_at = ob.started_at + dt.timedelta(days=d["due_offset_days"])  # counted from kickoff, as at sending
            ob.steps.append(s)
        elif old_roles.get(d["key"], "") != d["assignee_role"]:
            s.assignee_contact_id = _assignee(contacts, d["assignee_role"])
        s.type, s.title, s.section, s.position, s.visibility = d["type"], d["title"], d["section"], i, d["visibility"]
        _recheck_answer(s, d["config"])
    ob.document = doc  # a new object, so the JSON column is seen as changed
    gone = {sec["key"] for sec in doc["sections"] if not stages.needs_signoff(sec)} | ({x.section_key for x in ob.signoffs} - {sec["key"] for sec in doc["sections"]})
    for row in [x for x in ob.signoffs if x.section_key in gone]:
        ob.signoffs.remove(row)  # a stage that was removed, or no longer needs one, keeps no sign-off to come back with
    ob.sync_version += 1
    db.flush()
    db.expire(ob, ["steps"])  # reload in position order
    if sent:
        _reconcile_status(db, ob)
        if notify_client:
            changes.note_edit(ob, seen_before, now())
    return ob


def _reconcile_status(db: Session, ob: m.Onboarding) -> None:
    """After steps were added or removed: a finished onboarding that gained an open step is active again (a delivery to
    Voicent-App already made stays made; provision.queue never sends twice), and an active one with nothing left to do is finished.
    Editing is not client activity, so the quiet-client timer is left alone."""
    if ob.status == "completed" and (any(s.status not in ("done", "skipped") for s in ob.steps) or not stages.all_signed_off(ob)):
        ob.status, ob.completed_at = "active", None
    else:
        _complete_if_finished(db, ob)
    db.flush()


def _recheck_answer(step: m.Step, config: dict) -> None:
    """A done step whose settings were just edited is checked again against them, using its latest answer: a new required
    question, or a changed one, reopens it, so it isn't skipped as finished. The answers stay as they were."""
    if step.status != "done" or not step.responses:
        return
    stype = registry.get(step.type)
    latest = max(step.responses, key=lambda r: r.revision)
    _, problems = stype.validate_response(config, latest.data)
    if problems or stype.resulting_status(config, latest.data) != "done":
        step.status, step.completed_at = "in_progress", None


def send_onboarding(db: Session, org_id: str, onboarding_id: str) -> m.Onboarding:
    """Start the onboarding. Due dates count from now, because the template's offsets are relative to kickoff, except where
    a date was already picked on the draft."""
    ob = _onboarding(db, org_id, onboarding_id)
    if ob.status != "draft":
        raise Conflict(f"Only a draft can be sent; this one is {ob.status}.")
    start = now()
    offsets = {s["key"]: s["due_offset_days"] for s in ob.document["steps"]}
    for step in ob.steps:
        days = offsets.get(step.key)
        if step.due_at is None and days is not None:  # a date picked on the draft stays; the rest count from now
            step.due_at = start + dt.timedelta(days=days)
    ob.status, ob.started_at, ob.last_activity_at = "active", start, start
    ob.sync_version += 1
    db.flush()
    return ob


def set_onboarding_status(db: Session, org_id: str, onboarding_id: str, status: str) -> m.Onboarding:
    """pause, resume and archive. Completing happens by itself when the last step is done."""
    ob = _onboarding(db, org_id, onboarding_id)
    allowed = {"paused": ("active",), "active": ("paused",), "archived": ("draft", "active", "paused", "completed")}
    if status not in allowed:
        raise Invalid(f"Can't set status to '{status}'.")
    if ob.status not in allowed[status]:
        raise Conflict(f"Can't go from {ob.status} to {status}.")
    ob.status = status
    ob.last_activity_at = now()
    ob.sync_version += 1
    db.flush()
    return ob


def request_provisioning(db: Session, org_id: str, onboarding_id: str, at: dt.datetime) -> m.Onboarding:
    """Jay asks for the Voicent workspace now: the first time after a failure, or again to send updated answers."""
    ob = _onboarding(db, org_id, onboarding_id)
    if not provision.wants_provisioning(ob):
        raise Conflict("This onboarding's template doesn't set up a Voicent workspace.")
    if ob.status != "completed":
        raise Conflict(f"A workspace is requested when the onboarding is finished; this one is {ob.status}.")
    if not (ob.client and ob.client.paying_since):
        raise Conflict(f"Mark {ob.client.name if ob.client else 'the client'} as a paying customer first. A Voicent workspace is only set up for paying customers.")
    provision.request_again(ob, at)
    db.flush()
    return ob


def set_nudges_paused(db: Session, org_id: str, onboarding_id: str, paused: bool) -> m.Onboarding:
    ob = _onboarding(db, org_id, onboarding_id)
    ob.nudges_paused = paused
    db.flush()
    return ob


# ---------------------------------------------------------------- steps

def _step(db: Session, org_id: str, onboarding_id: str, key: str) -> tuple[m.Onboarding, m.Step]:
    ob = _onboarding(db, org_id, onboarding_id)
    step = next((s for s in ob.steps if s.key == key), None)
    if not step:
        raise NotFound("Step not found.")
    return ob, step


def _step_config(ob: m.Onboarding, key: str) -> dict:
    return next(s["config"] for s in ob.document["steps"] if s["key"] == key)


def latest_response(step: m.Step) -> m.Response | None:
    return step.responses[-1] if step.responses else None


def submit_step(db: Session, org_id: str, onboarding_id: str, key: str, data, *, submitted_by: str, actor_kind: str = "admin", storage=None) -> m.Step:
    """Record an answer as a new revision and move the step to whatever the type says it now is."""
    ob, step = _step(db, org_id, onboarding_id, key)
    if actor_kind == "client" and (ob.status != "active" or step.visibility != "client"):
        raise Conflict("This step can't be changed right now.")
    if actor_kind == "client" and step.key in stages.locked_keys(ob):
        raise Conflict("This step opens once the part before it has been signed off.")
    if ob.status in ("completed", "archived"):
        raise Conflict(f"This onboarding is {ob.status}.")
    stype = registry.get(step.type)
    cleaned, problems = stype.validate_response(_step_config(ob, key), data)
    if problems:
        raise Invalid("The answer has problems.", problems)
    if step.type == "upload":
        _check_uploaded_files(step, cleaned, _step_config(ob, key), storage)
    step.responses.append(m.Response(
        org_id=org_id, revision=len(step.responses) + 1, data=cleaned, submitted_by=submitted_by, submitted_at=now()))
    _set_step_status(ob, step, stype.resulting_status(_step_config(ob, key), cleaned))
    if actor_kind == "client":
        ob.attention = None  # they're back, so whatever was worrying us isn't true any more
        notifications.client_answered(db, ob, step, submitted_by)
    _after_change(db, ob)
    return step


def _check_uploaded_files(step: m.Step, cleaned: dict, config: dict, storage) -> None:
    """Every file named in an upload answer must belong to this step and, when storage is on, really be there."""
    owned = {f.id: f for f in step.files}
    if any(i not in owned for i in cleaned.get("file_ids", [])):
        raise Invalid("Some of those files don't belong to this step.")
    if storage is None:
        return
    limit = config.get("max_mb", 10) * 1024 * 1024
    for i in cleaned.get("file_ids", []):
        f = owned[i]
        info = storage.info(f.storage_path)
        if info is None:
            raise Invalid(f"'{f.name}' hasn't finished uploading.")
        info = info if isinstance(info, dict) else {}
        size = info.get("size")
        if size is None and isinstance(info.get("metadata"), dict):
            size = info["metadata"].get("size")
        if isinstance(size, int):
            if size > limit:
                raise Invalid(f"'{f.name}' is larger than {config.get('max_mb', 10)} MB.")
            f.size = size
        _check_file_type(f, config, info, storage)


def _check_file_type(f: m.File, config: dict, info: dict, storage) -> None:
    """The type storage recorded and the file's first bytes must both match what the step allows. The browser sets
    the content type when it uploads, so the type declared when the URL was issued proves nothing on its own."""
    ext = extension(f.name)
    expected = ALLOWED_UPLOADS.get(ext)
    wrong = f"'{f.name}' isn't a {ext or 'supported'} file. Upload it again in the right format."
    if expected is None or ext not in config.get("accept", []) or expected != f.content_type:
        raise Invalid(wrong)
    if stored_content_type(info) != expected:
        raise Invalid(wrong)
    head = storage.head(f.storage_path, SNIFF_BYTES)
    if head is None:
        raise Invalid(f"'{f.name}' hasn't finished uploading.")
    if not content_matches(ext, head):
        raise Invalid(wrong)


def complete_step(db: Session, org_id: str, onboarding_id: str, key: str) -> m.Step:
    """Jay marks a step done without an answer (a call that happened offline, an access granted by email)."""
    ob, step = _step(db, org_id, onboarding_id, key)
    if ob.status in ("completed", "archived"):
        raise Conflict(f"This onboarding is {ob.status}.")
    _set_step_status(ob, step, "done")
    _after_change(db, ob)
    return step


def skip_step(db: Session, org_id: str, onboarding_id: str, key: str) -> m.Step:
    ob, step = _step(db, org_id, onboarding_id, key)
    if ob.status in ("completed", "archived"):
        raise Conflict(f"This onboarding is {ob.status}.")
    _set_step_status(ob, step, "skipped")
    _after_change(db, ob)
    return step


def reopen_step(db: Session, org_id: str, onboarding_id: str, key: str) -> m.Step:
    ob, step = _step(db, org_id, onboarding_id, key)
    if ob.status == "archived":
        raise Conflict("This onboarding is archived.")
    _set_step_status(ob, step, "in_progress" if step.responses else "pending")
    if ob.status == "completed":
        ob.status, ob.completed_at = "active", None
    _after_change(db, ob)
    return step


def _set_step_status(ob: m.Onboarding, step: m.Step, status: str) -> None:
    step.status = status
    step.completed_at = now() if status in ("done", "skipped") else None


def _after_change(db: Session, ob: m.Onboarding) -> None:
    ob.last_activity_at = now()
    ob.sync_version += 1  # AIOS needs to hear about this
    db.flush()
    for st in stages.stages(ob):
        if st.state == "ready":
            notifications.stage_ready(db, ob, st.key, st.title)
    _complete_if_finished(db, ob)
    db.flush()


def _complete_if_finished(db: Session, ob: m.Onboarding) -> None:
    if ob.status == "active" and ob.steps and all(s.status in ("done", "skipped") for s in ob.steps) and stages.all_signed_off(ob):
        ob.status, ob.completed_at = "completed", now()
        if ob.client_id:  # wait for, then re-read, a payment being marked at this moment (see set_client_paying)
            db.scalar(select(m.Client).where(m.Client.id == ob.client_id).with_for_update().execution_options(populate_existing=True))
        provision.queue(ob, ob.completed_at)  # sent after the response by provision.kick, or by the timer
        notifications.onboarding_completed(db, ob)
    db.flush()


# ---------------------------------------------------------------- schedule

def end_of_day(day: dt.date, tz_name: str) -> dt.datetime:
    """The last minute of a calendar day where the client is: a step due on the 3rd isn't overdue until the 3rd is over for them."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # an unknown zone name: fall back to UTC rather than refuse the date
        tz = dt.timezone.utc
    return dt.datetime.combine(day, dt.time(23, 59), tzinfo=tz).astimezone(dt.timezone.utc)


def due_on(step: m.Step, tz_name: str) -> dt.date | None:
    """The calendar day a step is due, where the client is."""
    if step.due_at is None:
        return None
    at = step.due_at if step.due_at.tzinfo else step.due_at.replace(tzinfo=dt.timezone.utc)
    try:
        return at.astimezone(ZoneInfo(tz_name)).date()
    except Exception:
        return at.astimezone(dt.timezone.utc).date()


def set_step_schedule(db: Session, org_id: str, onboarding_id: str, key: str, *, start_on: dt.date | None, due: dt.date | None) -> m.Step:
    """Pick the day work on a step starts and the day it is due. Either may be cleared. Works on a draft too: sending keeps it."""
    ob, step = _step(db, org_id, onboarding_id, key)
    if ob.status == "archived":
        raise Conflict("This onboarding is archived.")
    if start_on and due and start_on > due:
        raise Invalid("The start date is after the due date.", ["Start: pick a day on or before the due date."])
    tz = ob.client.timezone if ob.client else "UTC"
    step.start_on = start_on
    step.due_at = end_of_day(due, tz) if due else None
    ob.sync_version += 1  # the due date goes to AIOS
    db.flush()
    return step


# ---------------------------------------------------------------- stage sign-off

def sign_off_stage(db: Session, org_id: str, onboarding_id: str, key: str, *, member_id: str | None, signed_by: str) -> m.Onboarding:
    """Our team says a stage is finished, which opens the next one to the client. Possible once every step in it is done or
    skipped and the stages before it are signed off. Signing off the last stage finishes the onboarding."""
    ob = _onboarding(db, org_id, onboarding_id)
    if ob.status not in ("active", "paused"):
        raise Conflict("Send this onboarding first." if ob.status == "draft" else f"This onboarding is {ob.status}.")
    st = stages.find(ob, key)
    if st is None:
        raise NotFound("Stage not found.")
    if not st.signoff:
        raise Conflict(f"“{st.title}” doesn't need a sign-off.")
    if st.state == "signed_off":
        raise Conflict(f"“{st.title}” is already signed off.")
    if st.state == "locked":
        raise Conflict(f"Sign off the stages before “{st.title}” first.")
    if st.state == "open":
        left = [s.title for s in st.steps if s.status not in stages.FINISHED]
        raise Conflict(f"Every step in “{st.title}” must be done or skipped before it can be signed off.", [f"Still open: {t}" for t in left])
    ob.signoffs.append(m.StageSignoff(org_id=org_id, section_key=key, member_id=member_id, signed_by=signed_by[:200], signed_at=now()))
    notifications.stage_signed_off(db, ob, st.title, member_id)
    _after_change(db, ob)
    return ob


def withdraw_signoff(db: Session, org_id: str, onboarding_id: str, key: str) -> m.Onboarding:
    """Take a sign-off back: the stages after it lock again for the client (their answers stay). Not once the onboarding is finished."""
    ob = _onboarding(db, org_id, onboarding_id)
    if ob.status in ("completed", "archived"):
        raise Conflict(f"This onboarding is {ob.status}. Reopen a step first to change its stages.")
    row = next((x for x in ob.signoffs if x.section_key == key), None)
    if row is None:
        raise NotFound("That stage isn't signed off.")
    ob.signoffs.remove(row)
    ob.sync_version += 1
    db.flush()
    return ob


def add_comment(db: Session, org_id: str, onboarding_id: str, key: str, *, body: str, author_kind: str, author_label: str, client_visible: bool = True) -> m.StepComment:
    ob, step = _step(db, org_id, onboarding_id, key)
    body = redact(body.strip())
    if not body or len(body) > 2000:
        raise Invalid("A comment needs 1 to 2000 characters.")
    if author_kind == "client" and (step.visibility != "client" or ob.status != "active"):
        raise Conflict("This step can't be commented on right now.")
    c = m.StepComment(org_id=org_id, step_id=step.id, author_kind=author_kind, author_label=author_label,
                      body=body, client_visible=client_visible if author_kind == "admin" else True)
    step.comments.append(c)
    ob.last_activity_at = now()
    db.flush()
    return c
