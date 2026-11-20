"""Tenancy that follows Voicent-App: who may act for which org with what role, and each org's brand.

Voicent-App's directory is faked twice: as the raw PostgREST answers behind httpx.MockTransport (so the real reader runs),
and as a simple dict of people for the request tests."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import branding, models as m, nudges, services
from app.config import Settings
from app.main import create_app
from app.voicent_directory import CachedDirectory, DirectoryError, Person, Tenant, VoicentDirectory, role_of
from tests.test_api import bearer
from tests.conftest import JWT_SECRET

VURL = "https://voicent.supabase.test"
KEY = "service-role-key-for-voicent"
ACME = Tenant(id="11111111-1111-1111-1111-111111111111", slug="acme-agency", name="Acme Agency", account_type="reseller",
              brand={"logo_url": "https://cdn.acme.test/logo.png", "primary_color": "#aa3300"})
DIRECT = Tenant(id="22222222-2222-2222-2222-222222222222", slug="voicent", name="Voicent", account_type="direct", brand={})


# ---------------------------------------------------------------- reading Voicent-App

def directory_with(handler) -> VoicentDirectory:
    s = Settings(voicent_supabase_url=VURL, voicent_supabase_service_key=KEY)
    return VoicentDirectory(s, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_reader_asks_only_for_the_columns_it_needs_read_only_and_cleans_the_brand():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.path.endswith("/users"):
            return httpx.Response(200, json=[{"tenant_id": ACME.id, "role": "super_admin", "is_superuser": False}])
        return httpx.Response(200, json=[{"id": ACME.id, "slug": "acme-agency", "company_name": "Acme Agency", "account_type": "reseller",
                                          "settings": {"branding": {"logo_url": "javascript:alert(1)", "primary_color": "#AA3300", "accent_color": "red"}}}])

    p = directory_with(handler).person("aaaaaaaa-0000-0000-0000-000000000001")
    assert p == Person(auth_id="aaaaaaaa-0000-0000-0000-000000000001", tenant=Tenant(ACME.id, "acme-agency", "Acme Agency", "reseller", {"primary_color": "#aa3300"}),
                       role="admin", is_superuser=False)
    assert all(r.method == "GET" for r in seen)
    assert seen[0].url.params["select"] == "tenant_id,role,is_superuser" and seen[0].url.params["auth_id"] == "eq.aaaaaaaa-0000-0000-0000-000000000001"
    assert seen[1].url.params["select"] == "id,slug,company_name,account_type,settings"
    assert seen[0].headers["apikey"] == KEY and seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_the_reader_refuses_odd_ids_maps_unknown_roles_to_viewer_and_wraps_failures():
    calls = []
    d = directory_with(lambda r: calls.append(r) or httpx.Response(200, json=[]))
    assert d.person("x,or(1.eq.1)") is None and not calls  # never put into a filter
    assert d.person("aaaaaaaa-0000-0000-0000-000000000001") is None  # not a Voicent-App user
    assert role_of("Owner") == "admin" and role_of("manager") == "manager" and role_of("something-new") == "viewer" and role_of(None) == "viewer"
    for reply in (httpx.Response(500, text="secret internals"), httpx.Response(200, text="not json"), httpx.Response(200, json={"a": 1})):
        with pytest.raises(DirectoryError) as e:
            directory_with(lambda r, reply=reply: reply).person("aaaaaaaa-0000-0000-0000-000000000001")
        assert "secret internals" not in str(e.value)


def test_the_cache_answers_for_a_while_and_never_keeps_a_failure():
    class Inner:
        n, fail = 0, False

        def person(self, auth_id):
            if self.fail:
                raise DirectoryError("down")
            self.n += 1
            return None

    t = [0.0]
    inner = Inner()
    c = CachedDirectory(inner, seconds=300, clock=lambda: t[0])
    assert c.lookup("u") == (None, True) and c.lookup("u") == (None, False) and inner.n == 1
    t[0] = 301
    inner.fail = True
    with pytest.raises(DirectoryError):
        c.lookup("u")
    inner.fail = False
    assert c.lookup("u") == (None, True) and inner.n == 2


# ---------------------------------------------------------------- who may act for which org

class People:
    """Voicent-App's people, as the request tests see them. Edit `people`, then call forget() (or let the cache expire)."""

    def __init__(self):
        self.people: dict[str, Person] = {}
        self.down = False

    def person(self, auth_id):
        if self.down:
            raise DirectoryError("Voicent-App didn't answer.")
        return self.people.get(auth_id)

    def set(self, auth_id, tenant, role="member", superuser=False):
        self.people[auth_id] = Person(auth_id, tenant, role, superuser)


@pytest.fixture()
def t():
    app = create_app(Settings(database_url="sqlite://", supabase_jwt_secret=JWT_SECRET, app_url="https://onboard.test"))
    people = People()
    app.state.directory = CachedDirectory(people, seconds=0)  # always fresh, so each test sees its own edits at once
    with TestClient(app) as c:
        c.people, c.sm = people, app.state.sessionmaker
        yield c


def org_of(t, tenant) -> m.Org:
    with t.sm() as db:
        return db.scalar(select(m.Org).where(m.Org.voicent_tenant_id == tenant.id))


def test_first_sign_in_makes_the_tenants_org_with_its_name_type_and_brand(t):
    t.people.set("u-ann", ACME, "admin")
    r = t.get("/api/org", headers=bearer("u-ann", "ann@acme.test"))
    assert r.status_code == 200
    out = r.json()
    assert out["name"] == "Acme Agency" and out["account_type"] == "reseller" and out["linked"] is True and out["role"] == "admin"
    assert out["brand"] == {"name": "Acme Agency", "logo_url": "https://cdn.acme.test/logo.png", "primary_color": "#aa3300", "accent_color": None}
    with t.sm() as db:
        row = db.scalar(select(m.OrgMember).where(m.OrgMember.auth_user_id == "u-ann"))
        assert row.source == "voicent" and row.role == "admin" and row.email == "ann@acme.test"


def test_roles_follow_voicent_and_removal_takes_access_away(t):
    t.people.set("u-bo", ACME, "member")
    h = bearer("u-bo")
    assert t.post("/api/clients", json={"name": "Shop"}, headers=h).status_code == 201
    t.people.set("u-bo", ACME, "viewer")
    assert t.get("/api/clients", headers=h).status_code == 200
    r = t.post("/api/clients", json={"name": "Shop 2"}, headers=h)
    assert r.status_code == 403 and "look but not change" in r.json()["detail"]
    del t.people.people["u-bo"]
    assert t.get("/api/clients", headers=h).status_code == 403


def test_moving_to_another_tenant_moves_access_and_tenants_never_see_each_other(t):
    t.people.set("u-cy", ACME, "admin")
    t.people.set("u-di", DIRECT, "admin")
    t.post("/api/clients", json={"name": "Acme's client"}, headers=bearer("u-cy"))
    assert [c["name"] for c in t.get("/api/clients", headers=bearer("u-di")).json()] == []
    t.people.set("u-cy", DIRECT, "member")
    assert [c["name"] for c in t.get("/api/clients", headers=bearer("u-cy")).json()] == []
    with t.sm() as db:
        assert db.scalars(select(m.OrgMember.org_id).where(m.OrgMember.auth_user_id == "u-cy")).all() == [org_of(t, DIRECT).id]


def test_only_an_admin_changes_the_brand_and_a_linked_orgs_logo_comes_from_voicent(t):
    t.people.set("u-ed", ACME, "manager")
    t.people.set("u-fa", ACME, "admin")
    assert t.put("/api/org", json={"brand_name": "Acme"}, headers=bearer("u-ed")).status_code == 403
    r = t.put("/api/org", json={"brand_name": "Acme Onboarding", "email_from_name": "Acme Team", "reply_to_email": "help@acme.test", "sms_from": "+15550001111"},
              headers=bearer("u-fa"))
    assert r.status_code == 200 and r.json()["brand"]["name"] == "Acme Onboarding" and r.json()["sms_from"] == "+15550001111"
    r = t.put("/api/org", json={"brand": {"logo_url": "https://x.test/l.png"}}, headers=bearer("u-fa"))
    assert r.status_code == 409 and "Voicent-App" in r.json()["detail"]
    bad = t.put("/api/org", json={"reply_to_email": "nope", "sms_from": "555"}, headers=bearer("u-fa"))
    assert bad.status_code == 422 and len(bad.json()["problems"]) == 2


def test_a_superuser_can_work_in_any_org_and_lists_them_all(t):
    t.people.set("u-cy", ACME, "admin")
    t.get("/api/org", headers=bearer("u-cy"))
    t.people.set("u-root", None, "admin", superuser=True)
    h = bearer("u-root")
    me = t.get("/api/me", headers=h).json()
    assert me["superuser"] is True and [o["name"] for o in me["orgs"]] == ["Acme Agency"]
    assert t.get("/api/clients", headers=h).status_code == 400  # nothing chosen yet
    acme = org_of(t, ACME).id
    assert t.post("/api/clients", json={"name": "Via root"}, headers=h | {"X-Org-Id": acme}).status_code == 201
    assert t.get("/api/clients", headers=h | {"X-Org-Id": "no-such-org"}).status_code == 404


def test_a_non_superuser_cant_pick_someone_elses_org(t):
    t.people.set("u-cy", ACME, "admin")
    t.people.set("u-di", DIRECT, "admin")
    t.get("/api/org", headers=bearer("u-di"))
    acme_clients = t.post("/api/clients", json={"name": "Acme only"}, headers=bearer("u-cy"))
    assert acme_clients.status_code == 201
    r = t.get("/api/clients", headers=bearer("u-di") | {"X-Org-Id": org_of(t, ACME).id})
    assert [c["name"] for c in r.json()] == []  # ignored: they only have their own org


def test_when_voicent_is_down_known_people_keep_working_and_new_ones_wait(t):
    t.people.set("u-gu", ACME, "member")
    assert t.get("/api/clients", headers=bearer("u-gu")).status_code == 200
    t.people.down = True
    assert t.get("/api/clients", headers=bearer("u-gu")).status_code == 200
    t.people.set("u-new", ACME, "admin")
    assert t.get("/api/clients", headers=bearer("u-new")).status_code == 403


def test_memberships_made_by_seed_are_never_touched_by_voicent(t):
    with t.sm() as db:
        org = services.get_or_create_org(db, "Voicent", "voicent")
        services.add_member(db, org.id, "u-jay", "jay@x.test")
        db.commit()
    assert t.get("/api/clients", headers=bearer("u-jay")).status_code == 200  # not a Voicent-App user: seed access stands
    t.people.set("u-jay", ACME, "viewer")
    me = t.get("/api/me", headers=bearer("u-jay")).json()
    assert sorted(o["name"] for o in me["orgs"]) == ["Acme Agency", "Voicent"]


# ---------------------------------------------------------------- what clients see

def test_brand_fields_are_checked_whatever_their_source():
    assert branding.clean({"logo_url": "http://x.test/a.png", "primary_color": "#12345", "accent_color": "#ABCDEF"}) == {"accent_color": "#abcdef"}
    assert branding.clean({"logo_url": 'https://x.test/a.png" onerror="x'}) == {}
    assert branding.clean("not a dict") == {}


def test_a_resellers_clients_never_see_voicent_in_the_portal_or_reminders(t):
    from tests.helpers4 import FakeNotifier

    t.people.set("u-ann", ACME, "admin")
    h = bearer("u-ann")
    t.put("/api/org", json={"email_from_name": "Acme Team", "reply_to_email": "help@acme.test", "sms_from": "+15550001111"}, headers=h)
    tpl = t.post("/api/templates", json={"name": "Mini", "slug": "mini", "layout": "checklist", "steps": [
        {"key": "basics", "type": "form", "title": "Basics", "config": {"fields": [{"key": "name", "label": "Name", "type": "text"}]}}]}, headers=h).json()
    cl = t.post("/api/clients", json={"name": "Bakery"}, headers=h).json()
    t.post(f"/api/clients/{cl['id']}/contacts", json={"name": "Pat", "email": "pat@bakery.test", "phone": "+15557654321", "sms_consent": True,
                                                      "sms_consent_source": "form"}, headers=h)
    ob = t.post("/api/onboardings", json={"client_id": cl["id"], "template_id": tpl["id"]}, headers=h).json()
    sent = t.post(f"/api/onboardings/{ob['id']}/send", headers=h).json()
    raw = sent["links"][0]["url"].rsplit("/c/", 1)[1]
    session = t.post("/api/portal/exchange", json={"token": raw}).json()["session"]
    view = t.get("/api/portal/onboarding", headers={"Authorization": f"Bearer {session}"}).json()
    assert view["brand"] == {"name": "Acme Agency", "logo_url": "https://cdn.acme.test/logo.png", "primary_color": "#aa3300", "accent_color": None}
    assert "Voicent" not in json.dumps(view)

    with t.sm() as db:
        org = db.get(m.Org, org_of(t, ACME).id)
        contact = db.scalar(select(m.Contact).where(m.Contact.client_id == cl["id"]))
        steps = list(db.get(m.Onboarding, ob["id"]).steps)
        msg = nudges.build_message(Settings(resend_from="Voicent <hello@voicent.test>"), contact, steps, "https://onboard.test/c/x",
                                   branding.display_name(org, Settings()))
        assert "Voicent" not in json.dumps(msg) and "Acme Agency" in msg["sms"]
        s = Settings(resend_from="Voicent <hello@voicent.test>", twilio_from_number="+15559990000")
        assert branding.email_from(org, s) == "Acme Team <hello@voicent.test>"  # our verified address, their name
        assert branding.reply_to(org) == "help@acme.test" and branding.sms_from(org, s) == "+15550001111"

    # the admin's client preview is the same view, read-only
    pv = t.get(f"/api/onboardings/{ob['id']}/preview", headers=h).json()
    assert pv["preview"] is True and pv["brand"]["name"] == "Acme Agency" and all(s["can_write"] is False for s in pv["steps"])
    assert [c["name"] for c in pv["contacts"]] == ["Pat"]
    _ = FakeNotifier  # (the end-to-end reminder path is covered in test_nudges; here the pieces it uses)


def test_a_direct_customer_keeps_the_configured_brand_name():
    org = m.Org(name="Voicent", slug="v", account_type="direct", brand={}, brand_name="", email_from_name="", reply_to_email="", sms_from="")
    assert branding.display_name(org, Settings(brand_name="Voicent")) == "Voicent"
    reseller = m.Org(name="Acme Agency", slug="a", account_type="reseller", brand={}, brand_name="", email_from_name="", reply_to_email="", sms_from="")
    assert branding.display_name(reseller, Settings(brand_name="Voicent")) == "Acme Agency"
