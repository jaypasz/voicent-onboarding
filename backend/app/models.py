"""The data model. Every table carries org_id so going from one operator to several is configuration, not a migration.

IDs are UUID strings (portable between SQLite in tests and Postgres in production). JSON columns hold
the template document, its per-onboarding snapshot and step responses.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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


class OrgMember(Stamped, Base):
    """Maps a Supabase user to an org. The backend resolves every admin request through this."""

    __tablename__ = "org_members"
    __table_args__ = (UniqueConstraint("org_id", "auth_user_id"),)

    org_id: Mapped[str] = org_fk()
    auth_user_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="admin")


class Client(Stamped, Base):
    __tablename__ = "clients"

    org_id: Mapped[str] = org_fk()
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="other")  # trades | agency | msp | other
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | archived
    notes: Mapped[str] = mapped_column(Text, default="")
    # Reminders respect the client's local time (an IANA name such as America/New_York).
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York", server_default="America/New_York")

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
