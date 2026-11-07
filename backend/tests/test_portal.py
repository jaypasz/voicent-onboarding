"""The client's door. The point of these tests is what a client must never get, not just what they can do."""
import datetime as dt
import hashlib

import jwt
import pytest
from fastapi.testclient import TestClient

from app import models as m
from app import services
from app.config import Settings
from app.main import create_app
from tests.conftest import JWT_SECRET, SERVICE_TOKEN

KEY = "portal-signing-key-0123456789-abcdef"
PNG = "image/png"

DOC = {
    "name": "Mini", "slug": "mini", "layout": "checklist",
    "sections": [{"key": "a", "title": "About you"}, {"key": "z", "title": "Our side"}],
    "steps": [
        {"key": "basics", "type": "form", "title": "Basics", "section": "a", "assignee_role": "owner",
         "config": {"fields": [{"key": "name", "label": "Name", "type": "text", "required": True}]}},
        {"key": "it_access", "type": "connect", "title": "IT access", "section": "a", "assignee_role": "it",
         "config": {"provider": "dns", "label": "DNS"}},
        {"key": "logo", "type": "upload", "title": "Logo", "section": "a",
         "config": {"accept": ["png", "pdf"], "max_mb": 1, "min_files": 1, "max_files": 2}},
        {"key": "approve", "type": "approval", "title": "Approve", "section": "a", "config": {"deliverable": {"kind": "text", "text": "Hello"}}},
        {"key": "secret_build", "type": "internal_task", "title": "Internal build notes", "section": "z",
         "config": {"notes": "margin is 40%", "checklist": ["call the supplier"]}},
    ],
}


class FakeStorage:
    """Stands in for Supabase Storage so no network is touched."""

    def __init__(self):
        self.objects: dict[str, int] = {}

    def signed_upload(self, path):
        self.last_path = path
        return {"url": f"https://store.test/upload/{path}", "token": "tok"}

    def info(self, path):
        return {"size": self.objects[path]} if path in self.objects else None

    def signed_download(self, path, ttl=600):
        return f"https://store.test/download/{path}?exp={ttl}"


def make_app(**over):
    settings = Settings(database_url="sqlite://", supabase_jwt_secret=JWT_SECRET, service_tokens=[SERVICE_TOKEN], portal_signing_key=KEY,
                        app_url="https://onboard.test", **over)
    app = create_app(settings)
    app.state.storage = FakeStorage()
    return app


@pytest.fixture()
def app():
    return make_app()


@pytest.fixture()
def api(app):
    with TestClient(app) as c:
        c.app = app
        yield c


def admin(user="user-a"):
    t = jwt.encode({"sub": user, "aud": "authenticated", "exp": 4102444800}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


def seed_org(app, slug="a", user="user-a"):
    with app.state.sessionmaker() as db:
        org = services.get_or_create_org(db, slug, slug)
        services.add_member(db, org.id, user)
        db.commit()
        return org.id


def onboarding(api, h, name="Acme", layout="checklist"):
    doc = {**DOC, "layout": layout, "slug": f"mini-{layout}"}
    t = api.post("/api/templates", json=doc, headers=h).json()
    cl = api.post("/api/clients", json={"name": name}, headers=h).json()
    owner = api.post(f"/api/clients/{cl['id']}/contacts", json={"name": "Pat Owner", "role": "owner"}, headers=h).json()
    it = api.post(f"/api/clients/{cl['id']}/contacts", json={"name": "Ivy IT", "role": "it"}, headers=h).json()
    ob = api.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=h).json()
    return ob, owner, it


def live(api, h, **kw):
    """An active onboarding with a link for each contact. Returns (onboarding, {role: raw token}, contacts)."""
    ob, owner, it = onboarding(api, h, **kw)
    sent = api.post(f"/api/onboardings/{ob['id']}/send", headers=h).json()
    tokens = {l["contact_name"]: l["url"].rsplit("/", 1)[1] for l in sent["links"]}
    return ob, {"owner": tokens["Pat Owner"], "it": tokens["Ivy IT"]}, {"owner": owner, "it": it}


def session(api, token):
    r = api.post("/api/portal/exchange", json={"token": token})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session']}"}


# ---------------------------------------------------------------- links

def test_send_issues_one_link_per_contact_and_stores_only_hashes(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    assert len(set(tokens.values())) == 2
    with app.state.sessionmaker() as db:
        rows = db.query(m.MagicLink).all()
        assert len(rows) == 2
        for raw in tokens.values():
            assert hashlib.sha256(raw.encode()).hexdigest() in {r.token_hash for r in rows}
            assert all(raw not in (r.token_hash + r.id) for r in rows)
    listed = api.get(f"/api/onboardings/{ob['id']}/links", headers=h).json()
    assert len(listed) == 2 and all("url" not in l and "token" not in l for l in listed)  # the raw token can't be shown again
    assert all(l["usable"] for l in listed)


def test_link_urls_use_the_app_url(api, app):
    seed_org(app)
    h = admin()
    ob, tokens, contacts = live(api, h)
    again = api.post(f"/api/onboardings/{ob['id']}/links", json={"contact_id": contacts["owner"]["id"]}, headers=h).json()
    assert again["url"].startswith("https://onboard.test/c/") and len(again["url"].rsplit("/", 1)[1]) >= 40


def test_dead_links_all_answer_the_same(api, app):
    h = admin()
    org = seed_org(app)
    ob, tokens, contacts = live(api, h)
    revoked = api.post(f"/api/onboardings/{ob['id']}/links", json={"contact_id": contacts["owner"]["id"]}, headers=h).json()
    api.post(f"/api/onboardings/{ob['id']}/links/{revoked['id']}/revoke", headers=h)
    expired = api.post(f"/api/onboardings/{ob['id']}/links", json={"contact_id": contacts["owner"]["id"]}, headers=h).json()
    with app.state.sessionmaker() as db:
        db.get(m.MagicLink, expired["id"]).expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        db.commit()
    draft_ob, draft_owner, _ = onboarding(api, h, name="Draft Co")
    draft_link = api.post(f"/api/onboardings/{draft_ob['id']}/links", json={"contact_id": draft_owner["id"]}, headers=h).json()
    bad = [revoked["url"], expired["url"], draft_link["url"], "https://x/c/" + "a" * 43, "short", ""]
    answers = {(r.status_code, r.text) for r in (api.post("/api/portal/exchange", json={"token": u.rsplit("/", 1)[-1]}) for u in bad)}
    assert len(answers) == 1 and answers.pop()[0] == 401
    assert api.post("/api/portal/exchange", json={"token": "a" * 500}).status_code == 422  # oversize input is plain validation; it says nothing about links


def test_archived_onboarding_link_is_dead(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    api.post(f"/api/onboardings/{ob['id']}/archive", headers=h)
    assert api.post("/api/portal/exchange", json={"token": tokens["owner"]}).status_code == 401


def test_revoking_cuts_off_a_live_session_at_once(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    s = session(api, tokens["owner"])
    assert api.get("/api/portal/onboarding", headers=s).status_code == 200
    for l in api.get(f"/api/onboardings/{ob['id']}/links", headers=h).json():
        api.post(f"/api/onboardings/{ob['id']}/links/{l['id']}/revoke", headers=h)
    assert api.get("/api/portal/onboarding", headers=s).status_code == 401


def test_extend_link(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    link = api.get(f"/api/onboardings/{ob['id']}/links", headers=h).json()[0]
    out = api.post(f"/api/onboardings/{ob['id']}/links/{link['id']}/extend", json={"days": 10}, headers=h).json()
    assert out["expires_at"] > link["expires_at"]
    assert api.post(f"/api/onboardings/{ob['id']}/links/{link['id']}/extend", json={"days": 0}, headers=h).status_code == 422
    api.post(f"/api/onboardings/{ob['id']}/links/{link['id']}/revoke", headers=h)
    assert api.post(f"/api/onboardings/{ob['id']}/links/{link['id']}/extend", json={"days": 5}, headers=h).status_code == 409


# ---------------------------------------------------------------- sessions

def test_session_tokens_are_not_interchangeable_with_admin_tokens(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    s = session(api, tokens["owner"])
    assert api.get("/api/clients", headers=s).status_code == 401  # a client session opens nothing on the admin side
    assert api.get("/api/portal/onboarding", headers=h).status_code == 401  # and an admin token isn't a client session
    assert api.get("/api/portal/onboarding", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}).status_code == 401
    assert api.get("/api/portal/onboarding").status_code == 401
    # the raw link token is not a session either
    assert api.get("/api/portal/onboarding", headers={"Authorization": f"Bearer {tokens['owner']}"}).status_code == 401


def test_forged_expired_and_wrong_audience_sessions_are_refused(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    with app.state.sessionmaker() as db:
        link = db.query(m.MagicLink).first()
        lid = link.id
    def mint(key=KEY, aud="portal", exp=4102444800, alg="HS256"):
        return {"Authorization": "Bearer " + jwt.encode({"sub": lid, "aud": aud, "exp": exp}, key, algorithm=alg)}
    assert api.get("/api/portal/onboarding", headers=mint()).status_code == 200  # sanity: this shape works
    assert api.get("/api/portal/onboarding", headers=mint(key="x" * 40)).status_code == 401
    assert api.get("/api/portal/onboarding", headers=mint(aud="authenticated")).status_code == 401
    assert api.get("/api/portal/onboarding", headers=mint(exp=1)).status_code == 401
    assert api.get("/api/portal/onboarding", headers=mint(key=JWT_SECRET)).status_code == 401  # signed with the Supabase secret
    none_token = jwt.encode({"sub": lid, "aud": "portal", "exp": 4102444800}, None, algorithm="none")
    assert api.get("/api/portal/onboarding", headers={"Authorization": f"Bearer {none_token}"}).status_code == 401


def test_refresh_gives_a_new_session_while_the_link_lives(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    s = session(api, tokens["owner"])
    r = api.post("/api/portal/refresh", headers=s)
    assert r.status_code == 200 and r.json()["expires_in"] == 30 * 60
    assert api.get("/api/portal/onboarding", headers={"Authorization": f"Bearer {r.json()['session']}"}).status_code == 200


# ---------------------------------------------------------------- what a client sees

def test_client_never_sees_internal_steps_comments_or_the_template(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    api.post(f"/api/onboardings/{ob['id']}/steps/basics/comments", json={"body": "internal-only note", "client_visible": False}, headers=h)
    api.post(f"/api/onboardings/{ob['id']}/steps/basics/comments", json={"body": "Welcome aboard", "client_visible": True}, headers=h)
    api.put(f"/api/onboardings/{ob['id']}/steps/secret_build", json={"data": {"note": "supplier phone 555"}}, headers=h)
    s = session(api, tokens["owner"])
    r = api.get("/api/portal/onboarding", headers=s)
    body = r.json()
    text = r.text
    assert [st["key"] for st in body["steps"]] == ["basics", "it_access", "logo", "approve"]
    for needle in ("secret_build", "Internal build notes", "margin is 40%", "call the supplier", "supplier phone", "internal-only note", "Our side", '"document"', "visibility"):
        assert needle not in text, needle
    assert body["progress"] == {"done": 0, "total": 4}  # the internal step is not counted either
    assert [c["body"] for c in next(st for st in body["steps"] if st["key"] == "basics")["comments"]] == ["Welcome aboard"]
    assert [sec["key"] for sec in body["sections"]] == ["a"]


def test_client_cannot_touch_an_internal_step_even_by_name(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    s = session(api, tokens["owner"])
    missing = api.put("/api/portal/steps/nope", json={"data": {}}, headers=s)
    internal = api.put("/api/portal/steps/secret_build", json={"data": {"note": "x"}}, headers=s)
    assert internal.status_code == missing.status_code == 404 and internal.json() == missing.json()
    assert api.post("/api/portal/steps/secret_build/comments", json={"body": "hi"}, headers=s).status_code == 404
    assert api.post("/api/portal/steps/secret_build/upload-url", json={"name": "a.png", "size": 5, "content_type": PNG}, headers=s).status_code == 404
    detail = api.get(f"/api/onboardings/{ob['id']}", headers=h).json()
    assert next(st for st in detail["steps"] if st["key"] == "secret_build")["status"] == "pending"


def test_assigned_steps_in_checklist_layout_are_visible_but_not_writable_by_others(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, contacts = live(api, h)
    owner, it = session(api, tokens["owner"]), session(api, tokens["it"])
    view = api.get("/api/portal/onboarding", headers=owner).json()
    by_key = {st["key"]: st for st in view["steps"]}
    assert by_key["it_access"]["can_write"] is False and by_key["it_access"]["assignee"]["name"] == "Ivy IT" and by_key["it_access"]["assignee"]["is_you"] is False
    assert by_key["basics"]["can_write"] is True and by_key["logo"]["can_write"] is True  # unassigned: anyone
    r = api.put("/api/portal/steps/it_access", json={"data": {"status": "connected", "account_label": "x"}}, headers=owner)
    assert r.status_code == 403
    ok = api.put("/api/portal/steps/it_access", json={"data": {"status": "connected", "account_label": "Acme DNS"}}, headers=it)
    assert ok.status_code == 200 and ok.json()["status"] == "done"


def test_focus_layout_hides_other_contacts_steps(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h, layout="focus")
    owner = session(api, tokens["owner"])
    keys = [st["key"] for st in api.get("/api/portal/onboarding", headers=owner).json()["steps"]]
    assert "it_access" not in keys and "basics" in keys
    assert api.put("/api/portal/steps/it_access", json={"data": {"status": "pending"}}, headers=owner).status_code == 404


def test_two_clients_never_see_each_other(api, app):
    h = admin()
    seed_org(app)
    ob1, t1, _ = live(api, h, name="Client One")
    ob2, t2, _ = live(api, h, name="Client Two")
    s1, s2 = session(api, t1["owner"]), session(api, t2["owner"])
    api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "ONE-SECRET-NAME"}}}, headers=s1)
    v2 = api.get("/api/portal/onboarding", headers=s2)
    assert "ONE-SECRET-NAME" not in v2.text and "Client One" not in v2.text and v2.json()["client_name"] == "Client Two"
    assert next(st for st in v2.json()["steps"] if st["key"] == "basics")["response"] is None


def test_a_client_in_another_org_is_walled_off_too(app):
    api = TestClient(app)
    a, b = admin("user-a"), admin("user-b")
    seed_org(app, "a", "user-a")
    seed_org(app, "b", "user-b")
    _, ta, _ = live(api, a, name="Org A Client")
    _, tb, _ = live(api, b, name="Org B Client")
    assert "Org A Client" not in api.get("/api/portal/onboarding", headers=session(api, tb["owner"])).text


# ---------------------------------------------------------------- what a client can do

def test_client_answers_comments_and_the_admin_sees_it(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, contacts = live(api, h)
    s = session(api, tokens["owner"])
    bad = api.put("/api/portal/steps/basics", json={"data": {"answers": {}}}, headers=s)
    assert bad.status_code == 422 and any("Name: this is required" in p for p in bad.json()["problems"])
    good = api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "Acme"}}}, headers=s).json()
    assert good["status"] == "done" and good["response"] == {"answers": {"name": "Acme"}}
    c = api.post("/api/portal/steps/approve/comments", json={"body": "Looks good"}, headers=s)
    assert c.status_code == 201 and c.json()["author_label"] == "Pat Owner"
    detail = api.get(f"/api/onboardings/{ob['id']}", headers=h).json()
    basics = next(st for st in detail["steps"] if st["key"] == "basics")
    assert basics["response"]["submitted_by"] == f"contact:{contacts['owner']['id']}"
    assert next(st for st in detail["steps"] if st["key"] == "approve")["comments"][0]["author_kind"] == "client"
    assert detail["progress"]["done"] == 1


def test_client_secrets_are_redacted_before_storage(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    fake = "ghp" + "_" + "a" * 36
    s = session(api, tokens["owner"])
    api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": f"key {fake}"}}}, headers=s)
    api.post("/api/portal/steps/approve/comments", json={"body": f"token {fake}"}, headers=s)
    with app.state.sessionmaker() as db:
        blob = " ".join(str(r.data) for r in db.query(m.Response)) + " ".join(c.body for c in db.query(m.StepComment))
    assert fake not in blob and "[redacted]" in blob


def test_a_client_cannot_write_to_a_paused_or_completed_onboarding(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    s = session(api, tokens["owner"])
    api.post(f"/api/onboardings/{ob['id']}/pause", headers=h)
    assert api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "x"}}}, headers=s).status_code == 409
    assert api.post("/api/portal/steps/basics/comments", json={"body": "hi"}, headers=s).status_code == 409
    view = api.get("/api/portal/onboarding", headers=s).json()
    assert view["status"] == "paused" and all(st["can_write"] is False for st in view["steps"])  # can still read


def test_client_cannot_change_a_step_by_resubmitting_after_completion_of_the_onboarding(api, app):
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    for key in ("basics", "it_access", "logo", "approve", "secret_build"):
        api.post(f"/api/onboardings/{ob['id']}/steps/{key}/complete", headers=h)
    s = session(api, tokens["owner"])
    assert api.get("/api/portal/onboarding", headers=s).json()["status"] == "completed"
    assert api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "x"}}}, headers=s).status_code == 409


# ---------------------------------------------------------------- uploads

def test_upload_flow_and_checks(api, app):
    h = admin()
    org_id = seed_org(app)
    ob, tokens, _ = live(api, h)
    s = session(api, tokens["owner"])
    store: FakeStorage = app.state.storage
    url = "/api/portal/steps/logo/upload-url"
    assert api.post(url, json={"name": "logo.svg", "size": 10, "content_type": "image/svg+xml"}, headers=s).status_code == 422
    assert api.post(url, json={"name": "logo.exe", "size": 10, "content_type": "application/x-msdownload"}, headers=s).status_code == 422
    assert api.post(url, json={"name": "logo.png", "size": 10, "content_type": "application/pdf"}, headers=s).status_code == 422  # type must match the name
    assert api.post(url, json={"name": "logo.png", "size": 2 * 1024 * 1024, "content_type": PNG}, headers=s).status_code == 422  # over max_mb
    assert api.post("/api/portal/steps/basics/upload-url", json={"name": "a.png", "size": 5, "content_type": PNG}, headers=s).status_code == 422  # not an upload step
    r = api.post(url, json={"name": "../../etc/My Logo?.png", "size": 500, "content_type": PNG}, headers=s)
    assert r.status_code == 200
    out = r.json()
    assert out["upload_url"].startswith("https://store.test/upload/") and ".." not in store.last_path and "?" not in store.last_path
    assert store.last_path.startswith(org_id + "/" + ob["id"] + "/")  # files live under their org and onboarding
    # claiming a file that hasn't finished uploading is refused
    pending = api.put("/api/portal/steps/logo", json={"data": {"file_ids": [out["file_id"]]}}, headers=s)
    assert pending.status_code == 422 and "finished uploading" in pending.text
    store.objects[store.last_path] = 500
    done = api.put("/api/portal/steps/logo", json={"data": {"file_ids": [out["file_id"]]}}, headers=s)
    assert done.status_code == 200 and done.json()["status"] == "done" and done.json()["files"][0]["size"] == 500
    # a file id from another step or onboarding can't be claimed
    assert api.put("/api/portal/steps/logo", json={"data": {"file_ids": ["not-mine"]}}, headers=s).status_code == 422


def test_files_from_another_onboarding_cannot_be_claimed(api, app):
    h = admin()
    seed_org(app)
    _, t1, _ = live(api, h, name="One")
    _, t2, _ = live(api, h, name="Two")
    s1, s2 = session(api, t1["owner"]), session(api, t2["owner"])
    f = api.post("/api/portal/steps/logo/upload-url", json={"name": "a.png", "size": 5, "content_type": PNG}, headers=s1).json()
    app.state.storage.objects[app.state.storage.last_path] = 5
    r = api.put("/api/portal/steps/logo", json={"data": {"file_ids": [f["file_id"]]}}, headers=s2)
    assert r.status_code == 422


def test_uploads_off_says_so(app):
    app.state.storage = None
    api = TestClient(app)
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    r = api.post("/api/portal/steps/logo/upload-url", json={"name": "a.png", "size": 5, "content_type": PNG}, headers=session(api, tokens["owner"]))
    assert r.status_code == 503 and "aren't switched on" in r.json()["detail"]


def test_admin_gets_a_short_lived_download_link_scoped_to_their_org(app):
    api = TestClient(app)
    a, b = admin("user-a"), admin("user-b")
    seed_org(app, "a", "user-a")
    seed_org(app, "b", "user-b")
    ob, tokens, _ = live(api, a)
    s = session(api, tokens["owner"])
    f = api.post("/api/portal/steps/logo/upload-url", json={"name": "logo.png", "size": 5, "content_type": PNG}, headers=s).json()
    url = f"/api/onboardings/{ob['id']}/files/{f['file_id']}/url"
    ok = api.get(url, headers=a)
    assert ok.status_code == 200 and ok.json()["url"].startswith("https://store.test/download/") and ok.json()["name"] == "logo.png"
    assert api.get(url, headers=b).status_code == 404


# ---------------------------------------------------------------- rate limits

def test_exchange_is_limited_per_address_and_globally():
    app = make_app(rate_exchange_per_ip=3, rate_exchange_global=5)
    with TestClient(app) as api:
        codes = [api.post("/api/portal/exchange", json={"token": "a" * 43}).status_code for _ in range(5)]
        assert codes == [401, 401, 401, 429, 429]
        r = api.post("/api/portal/exchange", json={"token": "a" * 43})
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and r.json()["detail"] == "Too many requests. Try again in a minute."


def test_global_exchange_limit_holds_even_if_the_address_changes():
    app = make_app(rate_exchange_per_ip=100, rate_exchange_global=3)
    with TestClient(app) as api:
        codes = [api.post("/api/portal/exchange", json={"token": "a" * 43}, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(5)]
        assert codes.count(429) == 2


def test_writes_are_limited_per_link_not_per_address():
    app = make_app(rate_writes_per_link=2)
    api = TestClient(app)
    h = admin()
    seed_org(app)
    ob, tokens, _ = live(api, h)
    one, other = session(api, tokens["owner"]), session(api, tokens["it"])
    body = {"data": {"answers": {"name": "x"}}}
    codes = [api.put("/api/portal/steps/basics", json=body, headers=one).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    assert api.post("/api/portal/steps/approve/comments", json={"body": "hi"}, headers=other).status_code == 201  # another link is unaffected
    assert api.get("/api/portal/onboarding", headers=one).status_code == 200  # reading isn't limited


def test_rate_limiter_window_and_memory():
    from app.ratelimit import RateLimiter

    t = [0.0]
    lim = RateLimiter(2, 60, clock=lambda: t[0])
    assert lim.allow("k") and lim.allow("k") and not lim.allow("k")
    assert lim.retry_after("k") in range(55, 62)
    t[0] = 61
    assert lim.allow("k")
    for i in range(10_100):
        lim.allow(f"ip{i}")
    t[0] = 200
    lim.allow("trigger")
    assert len(lim._hits) < 10_100
