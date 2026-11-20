"""The rules. Routers call these; nothing else writes to the database.

Every function takes org_id and filters by it. A row from another org is a NotFound, never a leak.
"""
from __future__ import annotations

import copy
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from . import provision
from .errors import Conflict, Invalid, NotFound
from .redact import redact
from .steps import registry
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


# ---------------------------------------------------------------- clients and contacts

def _client(db: Session, org_id: str, client_id: str) -> m.Client:
    c = db.scalar(select(m.Client).where(m.Client.id == client_id, m.Client.org_id == org_id))
    if not c:
        raise NotFound("Client not found.")
    return c


def get_client(db: Session, org_id: str, client_id: str) -> m.Client:
    return _client(db, org_id, client_id)


def list_clients(db: Session, org_id: str, status: str | None = None) -> list[m.Client]:
    q = select(m.Client).where(m.Client.org_id == org_id).order_by(m.Client.name)
    if status:
        q = q.where(m.Client.status == status)
    return list(db.scalars(q))


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


def save_template(db: Session, org_id: str, document, *, created_by: str = "") -> tuple[m.Template, m.TemplateVersion, bool]:
    """Validate and store a document. A new slug makes a template; an existing slug adds a version, unless nothing changed.

    Returns (template, version, created_new_version). Raises TemplateInvalid listing every problem.
    """
    doc = loader.check(document)
    t = db.scalar(select(m.Template).where(m.Template.org_id == org_id, m.Template.slug == doc["slug"]))
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


def list_onboardings(db: Session, org_id: str, status: str | None = None, client_id: str | None = None) -> list[m.Onboarding]:
    q = select(m.Onboarding).where(m.Onboarding.org_id == org_id).order_by(m.Onboarding.last_activity_at.desc())
    if status:
        q = q.where(m.Onboarding.status == status)
    if client_id:
        q = q.where(m.Onboarding.client_id == client_id)
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
                      sections: list | None = None, steps: list | None = None) -> m.Onboarding:
    """Copy the template version into the onboarding. Editing the template afterwards changes nothing here.
    With sections or steps, this client gets a customised copy; the template itself is not touched."""
    client = _client(db, org_id, client_id)
    t = _template(db, org_id, template_id)
    tv = template_document(db, org_id, t, version)
    doc = _with_steps(copy.deepcopy(tv.document), sections, steps)
    contacts = _contacts(db, org_id, client.id)
    ob = m.Onboarding(
        org_id=org_id, client_id=client.id, template_version_id=tv.id, title=redact(title.strip()) or f"{doc['name']}: {client.name}",
        layout=doc["layout"], status="draft", document=doc,
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


def update_onboarding_steps(db: Session, org_id: str, onboarding_id: str, *, sections: list, steps: list) -> m.Onboarding:
    """Replace a draft onboarding's sections and steps. Only drafts: once the client has a link, the AIOS tasks, the
    completion check and the client's own progress all depend on the steps, so they stay as they were sent."""
    ob = _onboarding(db, org_id, onboarding_id)
    if ob.status != "draft":
        raise Conflict(f"Steps can only be changed while the onboarding is a draft; this one is {ob.status}.")
    doc = _with_steps(ob.document, sections, steps)
    wanted = {d["key"]: d for d in doc["steps"]}
    existing = {s.key: s for s in ob.steps}
    problems = []
    for key, s in existing.items():
        if not _has_data(s):
            continue
        if key not in wanted:
            problems.append(f"'{s.title}' already has answers, files or comments, so it can't be removed.")
        elif wanted[key]["type"] != s.type:
            problems.append(f"'{s.title}' already has answers, files or comments, so its type can't change.")
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
            ob.steps.append(s)
        elif old_roles.get(d["key"], "") != d["assignee_role"]:
            s.assignee_contact_id = _assignee(contacts, d["assignee_role"])
        s.type, s.title, s.section, s.position, s.visibility = d["type"], d["title"], d["section"], i, d["visibility"]
    ob.document = doc  # a new object, so the JSON column is seen as changed
    ob.sync_version += 1
    db.flush()
    db.expire(ob, ["steps"])  # reload in position order
    return ob


def send_onboarding(db: Session, org_id: str, onboarding_id: str) -> m.Onboarding:
    """Start the onboarding. Due dates count from now, because the template's offsets are relative to kickoff."""
    ob = _onboarding(db, org_id, onboarding_id)
    if ob.status != "draft":
        raise Conflict(f"Only a draft can be sent; this one is {ob.status}.")
    start = now()
    offsets = {s["key"]: s["due_offset_days"] for s in ob.document["steps"]}
    for step in ob.steps:
        days = offsets.get(step.key)
        step.due_at = start + dt.timedelta(days=days) if days is not None else None
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
        size = info.get("size") if isinstance(info, dict) else None
        if isinstance(size, int):
            if size > limit:
                raise Invalid(f"'{f.name}' is larger than {config.get('max_mb', 10)} MB.")
            f.size = size


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
    if ob.status == "active" and ob.steps and all(s.status in ("done", "skipped") for s in ob.steps):
        ob.status, ob.completed_at = "completed", now()
        provision.queue(ob, ob.completed_at)  # sent after the response by provision.kick, or by the timer
    db.flush()


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
