"""The admin API end to end: templates, clients, onboardings, steps, and the walls between orgs."""
import jwt
import pytest
from fastapi.testclient import TestClient

from app import models as m
from app import services
from app.config import Settings
from app.main import create_app
from tests.conftest import JWT_SECRET, SERVICE_TOKEN


def bearer(user_id: str, email: str = "") -> dict:
    t = jwt.encode({"sub": user_id, "aud": "authenticated", "exp": 4102444800, "email": email or f"{user_id}@x.test"}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def app_two_orgs():
    """Real auth, two orgs, one admin each."""
    app = create_app(Settings(database_url="sqlite://", supabase_jwt_secret=JWT_SECRET, service_tokens=[SERVICE_TOKEN]))
    with app.state.sessionmaker() as db:
        a, b = services.get_or_create_org(db, "A", "a"), services.get_or_create_org(db, "B", "b")
        services.add_member(db, a.id, "user-a")
        services.add_member(db, b.id, "user-b")
        db.commit()
        ids = (a.id, b.id)
    with TestClient(app) as c:
        c.org_ids = ids
        yield c


DOC = {
    "name": "Mini", "slug": "mini", "layout": "checklist",
    "steps": [
        {"key": "basics", "type": "form", "title": "Basics", "assignee_role": "owner", "due_offset_days": 2,
         "config": {"fields": [{"key": "name", "label": "Name", "type": "text", "required": True}]}},
        {"key": "approve", "type": "approval", "title": "Approve", "config": {"deliverable": {"kind": "text", "text": "Hello"}}},
        {"key": "build", "type": "internal_task", "title": "Build it"},
    ],
}


def setup_client(c, h):
    t = c.post("/api/templates", json=DOC, headers=h).json()
    cl = c.post("/api/clients", json={"name": "Acme Plumbing", "kind": "trades"}, headers=h).json()
    c.post(f"/api/clients/{cl['id']}/contacts", json={"name": "Pat", "role": "Owner"}, headers=h)
    return t, cl


def test_full_flow_create_send_answer_complete(client):
    h = {}
    t, cl = setup_client(client, h)
    r = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=h)
    assert r.status_code == 201
    ob = r.json()
    assert ob["status"] == "draft" and ob["title"] == "Mini: Acme Plumbing" and ob["progress"] == {"done": 0, "total": 3}
    assert [s["key"] for s in ob["steps"]] == ["basics", "approve", "build"]
    assert ob["steps"][0]["assignee_contact_id"] and ob["steps"][1]["assignee_contact_id"] is None  # matched by role (case-insensitive)
    assert all(s["due_at"] is None for s in ob["steps"])  # due dates start at send, not at creation

    sent = client.post(f"/api/onboardings/{ob['id']}/send", headers=h).json()
    assert sent["status"] == "active" and sent["started_at"]
    assert sent["steps"][0]["due_at"] and sent["steps"][1]["due_at"] is None
    assert client.post(f"/api/onboardings/{ob['id']}/send", headers=h).status_code == 409

    r = client.put(f"/api/onboardings/{ob['id']}/steps/basics", json={"data": {"answers": {}}}, headers=h)
    assert r.status_code == 422 and any("Name: this is required" in p for p in r.json()["problems"])

    s = client.put(f"/api/onboardings/{ob['id']}/steps/basics", json={"data": {"answers": {"name": "Acme"}}}, headers=h).json()
    assert s["status"] == "done" and s["response"]["revision"] == 1 and s["response"]["submitted_by"].startswith("admin:")

    s = client.put(f"/api/onboardings/{ob['id']}/steps/approve", json={"data": {"decision": "changes_requested", "comment": "Warmer"}}, headers=h).json()
    assert s["status"] == "in_progress"
    s = client.put(f"/api/onboardings/{ob['id']}/steps/approve", json={"data": {"decision": "approved"}}, headers=h).json()
    assert s["status"] == "done" and s["revisions"] == 2 and s["response"]["revision"] == 2

    mid = client.get(f"/api/onboardings/{ob['id']}", headers=h).json()
    assert mid["status"] == "active" and mid["progress"] == {"done": 2, "total": 3}

    s = client.post(f"/api/onboardings/{ob['id']}/steps/build/complete", headers=h).json()
    assert s["status"] == "done"
    end = client.get(f"/api/onboardings/{ob['id']}", headers=h).json()
    assert end["status"] == "completed" and end["completed_at"]

    assert client.post(f"/api/onboardings/{ob['id']}/steps/basics/reopen", headers=h).json()["status"] == "in_progress"
    assert client.get(f"/api/onboardings/{ob['id']}", headers=h).json()["status"] == "active"  # reopening a step reopens the onboarding


def test_editing_a_template_never_changes_a_live_onboarding(client):
    t, cl = setup_client(client, {})
    ob = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}).json()
    edited = {**DOC, "steps": DOC["steps"][:1]}
    saved = client.post("/api/templates", json=edited).json()
    assert saved["new_version"] is True and saved["current_version"] == 2 and saved["versions"] == [1, 2]
    again = client.get(f"/api/onboardings/{ob['id']}").json()
    assert len(again["steps"]) == 3  # still the snapshot
    newer = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}).json()
    assert len(newer["steps"]) == 1
    old = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"], "version": 1}).json()
    assert len(old["steps"]) == 3


def test_saving_an_unchanged_template_adds_no_version(client):
    first = client.post("/api/templates", json=DOC).json()
    second = client.post("/api/templates", json=DOC).json()
    assert first["id"] == second["id"] and second["new_version"] is False and second["versions"] == [1]


def test_template_import_export_and_dry_run(client):
    from app.templates import loader

    text = loader.export_yaml(loader.load_presets()[0])
    dry = client.post("/api/templates/import", json={"yaml": text, "dry_run": True}).json()
    assert dry["ok"] is True and client.get("/api/templates").json() == []  # nothing saved
    saved = client.post("/api/templates/import", json={"yaml": text}).json()
    exported = client.get(f"/api/templates/{saved['id']}/export")
    assert exported.status_code == 200 and "slug:" in exported.text
    bad = client.post("/api/templates/import", json={"yaml": "name: x\nlayout: nope\nsteps: []", "dry_run": True}).json()
    assert bad["ok"] is False and len(bad["problems"]) >= 2
    r = client.post("/api/templates/import", json={"yaml": "a: ["})
    assert r.status_code == 422 and r.json()["problems"]
    v = client.post("/api/templates/validate", json={"name": "x"}).json()
    assert v["ok"] is False and v["problems"]


def test_step_types_endpoint_lists_all_nine_with_availability(client):
    types = {t["type"]: t for t in client.get("/api/templates/step-types").json()}
    assert len(types) == 9 and types["form"]["implemented"] and not types["credential_share"]["implemented"]


def test_install_presets_is_idempotent_and_leaves_edits_alone(client):
    assert sorted(client.post("/api/templates/install-presets").json()["added"]) == ["agency", "blank", "msp", "trades"]
    assert client.post("/api/templates/install-presets").json()["added"] == []
    assert len(client.get("/api/templates").json()) == 4


def test_pause_resume_archive(client):
    t, cl = setup_client(client, {})
    ob = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}).json()
    assert client.post(f"/api/onboardings/{ob['id']}/pause").status_code == 409  # a draft can't be paused
    client.post(f"/api/onboardings/{ob['id']}/send")
    assert client.post(f"/api/onboardings/{ob['id']}/pause").json()["status"] == "paused"
    assert client.post(f"/api/onboardings/{ob['id']}/resume").json()["status"] == "active"
    assert client.post(f"/api/onboardings/{ob['id']}/archive").json()["status"] == "archived"
    assert client.put(f"/api/onboardings/{ob['id']}/steps/basics", json={"data": {"answers": {"name": "x"}}}).status_code == 409


def test_comments_are_redacted_and_internal_flag_is_kept(client):
    t, cl = setup_client(client, {})
    ob = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}).json()
    fake = "ghp" + "_" + "a" * 36
    c = client.post(f"/api/onboardings/{ob['id']}/steps/basics/comments", json={"body": f"token {fake}", "client_visible": False}).json()
    assert fake not in c["body"] and c["client_visible"] is False
    assert client.post(f"/api/onboardings/{ob['id']}/steps/basics/comments", json={"body": "  "}).status_code == 422


def test_sms_consent_needs_a_source(client):
    cl = client.post("/api/clients", json={"name": "C"}).json()
    r = client.post(f"/api/clients/{cl['id']}/contacts", json={"name": "P", "phone": "+15551234567", "sms_consent": True})
    assert r.status_code == 422
    ok = client.post(f"/api/clients/{cl['id']}/contacts", json={"name": "P", "sms_consent": True, "sms_consent_source": "Signed form 2026-11-01"})
    assert ok.status_code == 201 and ok.json()["sms_consent"] is True


def test_unknown_ids_are_404_and_bad_input_is_422(client):
    assert client.get("/api/onboardings/nope").status_code == 404
    assert client.get("/api/clients/nope").status_code == 404
    assert client.post("/api/onboardings", json={"client_id": "x", "template_id": "y"}).status_code == 404
    assert client.post("/api/clients", json={"name": ""}).status_code == 422
    assert client.post("/api/clients", json={"name": "ok", "kind": "weird"}).status_code == 422


# ------------------------------------------------------------------ the walls between orgs

def test_one_org_cannot_see_or_touch_anothers_data(app_two_orgs):
    c, a, b = app_two_orgs, bearer("user-a"), bearer("user-b")
    t, cl = setup_client(c, a)
    ob = c.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=a).json()
    c.post(f"/api/onboardings/{ob['id']}/send", headers=a)

    assert c.get("/api/clients", headers=b).json() == []
    assert c.get("/api/templates", headers=b).json() == []
    assert c.get("/api/onboardings", headers=b).json() == []
    for method, url, body in [
        ("get", f"/api/clients/{cl['id']}", None),
        ("patch", f"/api/clients/{cl['id']}", {"name": "hijack"}),
        ("post", f"/api/clients/{cl['id']}/contacts", {"name": "x"}),
        ("get", f"/api/templates/{t['id']}", None),
        ("get", f"/api/templates/{t['id']}/export", None),
        ("post", f"/api/templates/{t['id']}/archive", None),
        ("get", f"/api/onboardings/{ob['id']}", None),
        ("post", f"/api/onboardings/{ob['id']}/pause", None),
        ("put", f"/api/onboardings/{ob['id']}/steps/basics", {"data": {"answers": {"name": "x"}}}),
        ("post", f"/api/onboardings/{ob['id']}/steps/basics/complete", None),
        ("post", f"/api/onboardings/{ob['id']}/steps/basics/comments", {"body": "hi"}),
    ]:
        r = getattr(c, method)(url, headers=b, **({"json": body} if body else {}))
        assert r.status_code == 404, (method, url, r.status_code)
    # B can't build an onboarding from A's client or template either
    cl_b = c.post("/api/clients", json={"name": "B client"}, headers=b).json()
    assert c.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=b).status_code == 404
    t_b = c.post("/api/templates", json={**DOC, "slug": "bs"}, headers=b).json()
    assert c.post("/api/onboardings", json={"client_id": cl_b["id"], "template_id": t["id"]}, headers=b).status_code == 404
    assert c.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t_b["id"]}, headers=b).status_code == 404
    # A's data is intact, and the same slug can exist in both orgs
    assert c.get(f"/api/clients/{cl['id']}", headers=a).json()["name"] == "Acme Plumbing"
    assert c.post("/api/templates", json=DOC, headers=b).status_code == 201


def test_a_user_with_no_membership_is_refused(app_two_orgs):
    assert app_two_orgs.get("/api/clients", headers=bearer("stranger")).status_code == 403


def test_service_token_needs_an_org_when_there_are_several(app_two_orgs):
    c, svc = app_two_orgs, {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    assert c.get("/api/clients", headers=svc).status_code == 400
    assert c.get("/api/clients", headers=svc | {"X-Org-Id": c.org_ids[0]}).status_code == 200
    assert c.get("/api/clients", headers=svc | {"X-Org-Id": "nope"}).status_code == 404


def test_admin_routes_need_login(app_two_orgs):
    for url in ("/api/clients", "/api/templates", "/api/templates/step-types", "/api/onboardings"):
        assert app_two_orgs.get(url).status_code == 401, url


def test_internal_steps_are_visible_to_admins_with_their_visibility_flag(client):
    t, cl = setup_client(client, {})
    ob = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}).json()
    build = next(s for s in ob["steps"] if s["key"] == "build")
    assert build["visibility"] == "internal"
