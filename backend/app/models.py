"""The data model. Every table carries org_id so going from one operator to several is configuration, not a migration.

IDs are UUID strings (portable between SQLite in tests and Postgres in production). JSON columns hold
the template document, its per-onboarding snapshot and step responses.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Stamped:
    """id, org_id and timestamps shared by every table except orgs."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


def org_fk() -> Mapped[str]:
    return mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)


class Org(Stamped, Base):
    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    # Tenancy follows Voicent-App: one org per Voicent tenant, which is either a direct customer or a reseller (white-label
    # agency) whose clients are onboarded here under the reseller's own brand. Orgs made by `seed` have no tenant.
    voicent_tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    account_type: Mapped[str] = mapped_column(String(20), default="direct", server_default="direct")  # direct | reseller
    # Logo and colours, copied from the Voicent tenant (it stays the one place a reseller sets them). Set here only for an
    # org with no tenant. {logo_url, primary_color, accent_color}, each checked by branding.clean().
    brand: Mapped[dict] = mapped_column(JSON, default=dict)
    # What Voicent-App doesn't have, set here: the name clients see, and the senders used to reach them.
    brand_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    email_from_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    reply_to_email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    sms_from: Mapped[str] = mapped_column(String(20), default="", server_default="")  # a Twilio number on our account, E.164


class OrgMember(Stamped, Base):
    """Maps a Supabase user to an org. The backend resolves every admin request through this."""

    __tablename__ = "org_members"
    __table_args__ = (UniqueConstraint("org_id", "auth_user_id"),)

    org_id: Mapped[str] = org_fk()
    auth_user_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="admin")  # admin | manager | member | viewer, as in Voicent-App
    # "local": made by seed or by hand, kept until removed. "voicent": copied from Voicent-App, and removed when Voicent-App
    # says the person no longer belongs to that tenant.
    source: Mapped[str] = mapped_column(String(20), default="local", server_default="local")
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # Their own choice: also email them the notifications they get in the app (assignments, a client finishing a step...).
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())


class OrgInvite(Stamped, Base):
    """Someone asked to join an org that has no Voicent tenant (a linked org's people come from Voicent-App). Accepted when a
    person signs in with that email address; until then nothing is granted."""

    __tablename__ = "org_invites"
    __table_args__ = (UniqueConstraint("org_id", "email"),)

    org_id: Mapped[str] = org_fk()
    email: Mapped[str] = mapped_column(String(200))  # stored lower-case
    role: Mapped[str] = mapped_column(String(20), default="member")
    invited_by: Mapped[str] = mapped_column(String(200), default="")
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Client(Stamped, Base):
    __tablename__ = "clients"

    org_id: Mapped[str] = org_fk()
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="other")  # trades | agency | msp | other
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | archived
    notes: Mapped[str] = mapped_column(Text, default="")
    # Reminders respect the client's local time (an IANA name such as America/New_York).
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York", server_default="America/New_York")
    # Set when Jay marks the client as paying. A Voicent workspace is only ever asked for once a client pays: a prospect who
    # finishes onboarding but never pays stays a lead, and leads are kept out of Voicent-App.
    paying_since: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    onboardings: Mapped[list["Onboarding"]] = relationship(back_populates="client")


class Contact(Stamped, Base):
    __tablename__ = "contacts"

    org_id: Mapped[str] = org_fk()
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(40), default="")  # owner | it | billing | ...
    # SMS nudges go only to contacts with recorded consent.
    sms_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_consent_source: Mapped[str] = mapped_column(String(200), default="")
    sms_consent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[Client] = relationship(back_populates="contacts")


class Template(Stamped, Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("org_id", "slug"),)

    org_id: Mapped[str] = org_fk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    versions: Mapped[list["TemplateVersion"]] = relationship(back_populates="template", cascade="all, delete-orphan")


class TemplateVersion(Stamped, Base):
    """One saved version of a template document. Never edited: a change is a new row."""

    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version"),)

    org_id: Mapped[str] = org_fk()
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(200), default="")

    template: Mapped[Template] = relationship(back_populates="versions")


class Onboarding(Stamped, Base):
    """An instance of a template for one client. It keeps its own snapshot, so editing the template later changes nothing here."""

    __tablename__ = "onboardings"
    __table_args__ = (Index("ix_onboardings_org_status_activity", "org_id", "status", "last_activity_at"),)

    org_id: Mapped[str] = org_fk()
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    template_version_id: Mapped[str | None] = mapped_column(ForeignKey("template_versions.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    layout: Mapped[str] = mapped_column(String(20), default="checklist")  # focus | checklist
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active | paused | completed | archived
    document: Mapped[dict] = mapped_column(JSON)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    nudges_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    aios_project_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    aios_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # the project status last sent to AIOS
    # Why Jay should look at this one: nudges_exhausted (the client went quiet after every reminder) or unreachable.
    attention: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # sync_version goes up on every change AIOS should hear about; synced_version is what the last sync covered.
    # A change is never lost, even if it lands while a sync is running: the two just differ until the next pass.
    sync_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    synced_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Asking Voicent-App for a workspace when a template with on_complete: provision_voicent_workspace is finished (provision.py).
    # provision_state: None (nothing asked for yet) | pending | delivered | failed. Retries reuse provision_delivery_id.
    provision_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provision_delivery_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provision_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    provision_next_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provision_error: Mapped[str] = mapped_column(String(300), default="", server_default="")  # our own wording, never the receiver's
    provisioned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voicent_workspace_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The team member who looks after this onboarding: told when it finishes or the client goes quiet.
    owner_member_id: Mapped[str | None] = mapped_column(ForeignKey("org_members.id", ondelete="SET NULL"), nullable=True, index=True)

    client: Mapped[Client] = relationship(back_populates="onboardings")
    steps: Mapped[list["Step"]] = relationship(back_populates="onboarding", cascade="all, delete-orphan", order_by="Step.position")


class Step(Stamped, Base):
    __tablename__ = "steps"
    __table_args__ = (
        UniqueConstraint("onboarding_id", "key"),
        Index("ix_steps_onboarding_position", "onboarding_id", "position"),
    )

    org_id: Mapped[str] = org_fk()
    onboarding_id: Mapped[str] = mapped_column(ForeignKey("onboardings.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    section: Mapped[str] = mapped_column(String(80), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    visibility: Mapped[str] = mapped_column(String(20), default="client")  # client | internal
    assignee_contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    # Who on our side follows this step up (the contact above is who answers it on the client's side). Never shown to clients.
    team_assignee_id: Mapped[str | None] = mapped_column(ForeignKey("org_members.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | in_progress | done | skipped
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aios_task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    aios_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # the task status last sent to AIOS
    aios_comment_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # last response revision noted in AIOS

    onboarding: Mapped[Onboarding] = relationship(back_populates="steps")
    responses: Mapped[list["Response"]] = relationship(back_populates="step", cascade="all, delete-orphan", order_by="Response.revision")
    files: Mapped[list["File"]] = relationship(back_populates="step", cascade="all, delete-orphan")
    comments: Mapped[list["StepComment"]] = relationship(back_populates="step", cascade="all, delete-orphan", order_by="StepComment.created_at")


class Response(Stamped, Base):
    """A submitted answer. Resubmitting adds a revision; earlier ones stay as history."""

    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("step_id", "revision"),)

    org_id: Mapped[str] = org_fk()
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    submitted_by: Mapped[str] = mapped_column(String(200), default="")  # "contact:<id>" or "admin:<email>"
    submitted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    step: Mapped[Step] = relationship(back_populates="responses")


class File(Stamped, Base):
    __tablename__ = "files"

    org_id: Mapped[str] = org_fk()
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(300))
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(100), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")

    step: Mapped[Step] = relationship(back_populates="files")


class StepComment(Stamped, Base):
    """One thread per step. Admin comments can be hidden from the client."""

    __tablename__ = "step_comments"

    org_id: Mapped[str] = org_fk()
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"), index=True)
    author_kind: Mapped[str] = mapped_column(String(10))  # client | admin
    author_label: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    client_visible: Mapped[bool] = mapped_column(Boolean, default=True)

    step: Mapped[Step] = relationship(back_populates="comments")


class MagicLink(Stamped, Base):
    """A client's way in. Only the hash of the token is stored; the raw token exists once, when it is issued."""

    __tablename__ = "magic_links"

    org_id: Mapped[str] = org_fk()
    onboarding_id: Mapped[str] = mapped_column(ForeignKey("onboardings.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Nudge(Stamped, Base):
    """One attempt to remind one contact on one channel. (onboarding, contact, channel, round) is unique, so two
    overlapping runs can't send the same reminder twice: the second insert fails and that contact is skipped."""

    __tablename__ = "nudges"
    __table_args__ = (UniqueConstraint("onboarding_id", "contact_id", "channel", "round", name="uq_nudges_attempt"),)

    org_id: Mapped[str] = org_fk()
    onboarding_id: Mapped[str] = mapped_column(ForeignKey("onboardings.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(10))  # sms | email
    template: Mapped[str] = mapped_column(String(40), default="stalled")  # stalled (automatic) | manual
    round: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | sent | failed
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(String(300), default="")  # our own wording plus a status code, never provider text


class SyncLog(Stamped, Base):
    """Every attempt to sync to AIOS or to provision a workspace, so a failure is visible on the onboarding."""

    __tablename__ = "sync_log"

    org_id: Mapped[str] = org_fk()
    onboarding_id: Mapped[str] = mapped_column(ForeignKey("onboardings.id", ondelete="CASCADE"), index=True)
    target: Mapped[str] = mapped_column(String(20))  # aios | voicent
    action: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # ok | failed
    detail: Mapped[str] = mapped_column(String(300), default="")


class Notification(Stamped, Base):
    """Something a team member should know about. Shown in the app; also emailed when they want that. The text is our own
    wording (who did what, where); it never carries what a client typed."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_member_read", "member_id", "read_at"),)

    org_id: Mapped[str] = org_fk()
    member_id: Mapped[str] = mapped_column(ForeignKey("org_members.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # assigned_onboarding | assigned_step | step_done | completed | quiet
    onboarding_id: Mapped[str | None] = mapped_column(ForeignKey("onboardings.id", ondelete="CASCADE"), nullable=True, index=True)
    step_key: Mapped[str] = mapped_column(String(80), default="")
    text: Mapped[str] = mapped_column(String(300))
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # none (not wanted) | pending | sending (claimed by one sender) | sent | failed
    email_state: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
