"""Who someone is in Voicent-App: their tenant, their role there, and whether they are a Voicent superuser.

Read only, from Voicent-App's Supabase project (PostgREST, with its service key), and only these columns:
  users(auth_id, tenant_id, role, is_superuser)          the person, by their Supabase login id
  tenants(id, slug, company_name, account_type, settings) the tenant, and the brand in settings.branding
  users(auth_id, email, role) where tenant_id = …         the tenant's team, so they can be assigned before signing in
Nothing is ever written there. Answers are cached for a few minutes, so a change in Voicent-App (a new role, someone
removed) reaches this app within that time.

Errors are our own wording; nothing Voicent-App or Supabase says is passed on.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

import httpx

from .branding import clean
from .config import Settings

AUTH_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")  # Supabase user ids are UUIDs; anything else is never sent in a filter
# Voicent-App's roles, mapped to ours. Unknown roles get the least access: viewer.
ROLES = {"super_admin": "admin", "admin": "admin", "owner": "admin", "manager": "manager", "member": "member", "viewer": "viewer"}
CACHE_SECONDS = 300


class DirectoryError(Exception):
    """Voicent-App couldn't be asked. The caller falls back to what it already knew."""


@dataclass(frozen=True)
class Tenant:
    id: str
    slug: str
    name: str
    account_type: str  # direct | reseller
    brand: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Person:
    auth_id: str
    tenant: Tenant | None
    role: str  # admin | manager | member | viewer
    is_superuser: bool


@dataclass(frozen=True)
class TeamMember:
    auth_id: str
    email: str
    role: str


MAX_TEAM = 500


def role_of(raw) -> str:
    return ROLES.get(str(raw or "").strip().lower(), "viewer")


class VoicentDirectory:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.base = settings.voicent_supabase_url.rstrip("/") + "/rest/v1"
        key = settings.voicent_supabase_service_key
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
        self.http = client or httpx.Client(timeout=8.0)

    def _get(self, table: str, params: dict) -> list[dict]:
        try:
            r = self.http.get(f"{self.base}/{table}", params=params, headers=self.headers)
        except httpx.HTTPError:
            raise DirectoryError("Voicent-App didn't answer.") from None
        if r.status_code != 200:
            raise DirectoryError(f"Voicent-App refused the lookup (status {r.status_code}).")
        try:
            rows = r.json()
        except ValueError:
            raise DirectoryError("Voicent-App's answer couldn't be read.") from None
        if not isinstance(rows, list):
            raise DirectoryError("Voicent-App's answer couldn't be read.")
        return [x for x in rows if isinstance(x, dict)]

    def person(self, auth_id: str) -> Person | None:
        """None when this login isn't a Voicent-App user."""
        if not AUTH_ID.match(auth_id):
            return None
        users = self._get("users", {"auth_id": f"eq.{auth_id}", "select": "tenant_id,role,is_superuser", "limit": "1"})
        if not users:
            return None
        u = users[0]
        tenant = None
        tid = str(u.get("tenant_id") or "")
        if AUTH_ID.match(tid):
            rows = self._get("tenants", {"id": f"eq.{tid}", "select": "id,slug,company_name,account_type,settings", "limit": "1"})
            if rows:
                t = rows[0]
                settings = t.get("settings") if isinstance(t.get("settings"), dict) else {}
                tenant = Tenant(
                    id=str(t.get("id")), slug=str(t.get("slug") or "")[:80], name=str(t.get("company_name") or t.get("slug") or "Tenant")[:200],
                    account_type="reseller" if t.get("account_type") == "reseller" else "direct", brand=clean(settings.get("branding")),
                )
        return Person(auth_id=auth_id, tenant=tenant, role=role_of(u.get("role")), is_superuser=u.get("is_superuser") is True)

    def team(self, tenant_id: str) -> list[TeamMember]:
        """Everyone in a tenant (at most MAX_TEAM), so they can be assigned before they first sign in."""
        if not AUTH_ID.match(tenant_id):
            return []
        rows = self._get("users", {"tenant_id": f"eq.{tenant_id}", "select": "auth_id,email,role", "limit": str(MAX_TEAM)})
        out = []
        for r in rows:
            aid = str(r.get("auth_id") or "")
            if AUTH_ID.match(aid):
                out.append(TeamMember(aid, str(r.get("email") or "")[:200], role_of(r.get("role"))))
        return out


class CachedDirectory:
    """Remembers answers for CACHE_SECONDS. `lookup` says whether the answer is fresh, so memberships are only re-synced then."""

    def __init__(self, inner, seconds: int = CACHE_SECONDS, clock=time.monotonic):
        self.inner, self.seconds, self.clock = inner, seconds, clock
        self._cache: dict[str, tuple[float, Person | None]] = {}
        self._lock = threading.Lock()

    def lookup(self, auth_id: str) -> tuple[Person | None, bool]:
        now = self.clock()
        with self._lock:
            hit = self._cache.get(auth_id)
            if hit and hit[0] > now:
                return hit[1], False
        person = self.inner.person(auth_id)  # may raise DirectoryError; failures are not cached
        with self._lock:
            self._cache[auth_id] = (now + self.seconds, person)
        return person, True

    def team(self, tenant_id: str) -> tuple[list[TeamMember], bool]:
        """A tenant's people, cached like `lookup`. Says whether the answer is fresh."""
        key, now = f"team:{tenant_id}", self.clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1], False  # type: ignore[return-value]
        people = self.inner.team(tenant_id)
        with self._lock:
            self._cache[key] = (now + self.seconds, people)  # type: ignore[assignment]
        return people, True

    def forget(self, auth_id: str | None = None) -> None:
        with self._lock:
            if auth_id is None:
                self._cache.clear()
            else:
                self._cache.pop(auth_id, None)
