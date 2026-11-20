"""Which orgs a signed-in person may act for, and with what role. Follows Voicent-App's tenancy.

Voicent-App has tenants (a direct customer, or a reseller: a white-label agency whose clients are its own) and, above them,
platform superusers. Here, each tenant is one org, made the first time one of its people signs in. A person's role comes from
Voicent-App (admin, manager, member, viewer) and is refreshed whenever the directory answer is fresh (every few minutes). If
Voicent-App says they no longer belong to that tenant, the membership copied from it is removed, and their access with it.

Memberships made by `seed` or by hand (source "local") are never touched by this: that is how Jay's own account and orgs
without a tenant keep working, and how the app works with tenancy switched off.

If Voicent-App can't be asked, what was last copied from it is used, and a warning is logged. A person never seen before gets
no access until it can be asked.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import models as m
from .voicent_directory import DirectoryError, Person, Tenant

log = logging.getLogger("uvicorn.error")

RANK = {"viewer": 0, "member": 1, "manager": 2, "admin": 3}


@dataclass
class Access:
    orgs: dict[str, str]  # org id -> role
    superuser: bool = False


def _unique_slug(db: Session, base: str) -> str:
    base = (base or "tenant").lower()[:70] or "tenant"
    slug, n = base, 2
    while db.scalar(select(m.Org.id).where(m.Org.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def ensure_org(db: Session, tenant: Tenant) -> m.Org:
    """The org for a Voicent tenant, made on first sight. Its name, type and brand follow Voicent-App on every fresh answer."""
    org = db.scalar(select(m.Org).where(m.Org.voicent_tenant_id == tenant.id))
    if org is None:
        org = m.Org(name=tenant.name, slug=_unique_slug(db, tenant.slug or tenant.name), voicent_tenant_id=tenant.id)
        db.add(org)
    org.name, org.account_type, org.brand = tenant.name, tenant.account_type, dict(tenant.brand)
    db.flush()
    return org


def sync_person(db: Session, auth_id: str, email: str, person: Person | None) -> None:
    """Make this person's Voicent-sourced memberships match what Voicent-App just said."""
    keep_org = None
    if person and person.tenant:
        org = ensure_org(db, person.tenant)
        keep_org = org.id
        row = db.scalar(select(m.OrgMember).where(m.OrgMember.org_id == org.id, m.OrgMember.auth_user_id == auth_id))
        if row is None:
            db.add(m.OrgMember(org_id=org.id, auth_user_id=auth_id, email=email[:200], role=person.role, source="voicent"))
        elif row.source == "voicent":
            row.role, row.email = person.role, email[:200]
    q = delete(m.OrgMember).where(m.OrgMember.auth_user_id == auth_id, m.OrgMember.source == "voicent")
    if keep_org:
        q = q.where(m.OrgMember.org_id != keep_org)
    db.execute(q)
    db.flush()


def sync_team(db: Session, directory, org: m.Org) -> bool:
    """Bring a linked org's whole team over from Voicent-App, so people can be assigned before they first sign in. Copies
    are added and updated, and removed when Voicent-App no longer lists them. Returns False if Voicent-App couldn't be asked
    (the last copy stays)."""
    if directory is None or not org.voicent_tenant_id:
        return True
    try:
        people, fresh = directory.team(org.voicent_tenant_id)
    except DirectoryError as e:
        log.warning("Voicent tenancy: %s Showing the team as last copied.", e)
        return False
    if not fresh:
        return True
    rows = {r.auth_user_id: r for r in db.scalars(select(m.OrgMember).where(m.OrgMember.org_id == org.id))}
    listed = set()
    for p in people:
        listed.add(p.auth_id)
        row = rows.get(p.auth_id)
        if row is None:
            db.add(m.OrgMember(org_id=org.id, auth_user_id=p.auth_id, email=p.email, role=p.role, source="voicent"))
        elif row.source == "voicent":
            row.role = p.role
            if p.email:
                row.email = p.email
    for aid, row in rows.items():
        if row.source == "voicent" and aid not in listed:
            db.delete(row)
    db.flush()
    return True


def accept_invites(db: Session, auth_id: str, email: str, now) -> None:
    """Someone signed in with an address that was invited: they join those orgs with the role they were invited with.
    Supabase only issues a session for a confirmed address, so the address in the token is theirs."""
    if "@" not in email:
        return
    invites = list(db.scalars(select(m.OrgInvite).where(m.OrgInvite.email == email.strip().lower(), m.OrgInvite.accepted_at.is_(None))))
    for inv in invites:
        exists = db.scalar(select(m.OrgMember.id).where(m.OrgMember.org_id == inv.org_id, m.OrgMember.auth_user_id == auth_id))
        if not exists:
            db.add(m.OrgMember(org_id=inv.org_id, auth_user_id=auth_id, email=email[:200], role=inv.role if inv.role in RANK else "member", source="local"))
        inv.accepted_at = now
    if invites:
        db.flush()


def access_for(db: Session, directory, auth_id: str, email: str) -> Access:
    import datetime as dt

    accept_invites(db, auth_id, email, dt.datetime.now(dt.timezone.utc))
    superuser = False
    if directory is not None:
        try:
            person, fresh = directory.lookup(auth_id)
            if fresh:
                sync_person(db, auth_id, email, person)
            superuser = bool(person and person.is_superuser)
        except DirectoryError as e:
            log.warning("Voicent tenancy: %s Using the memberships last copied from it.", e)
    rows = db.execute(select(m.OrgMember.org_id, m.OrgMember.role).where(m.OrgMember.auth_user_id == auth_id)).all()
    return Access(orgs={org_id: (role if role in RANK else "viewer") for org_id, role in rows}, superuser=superuser)
