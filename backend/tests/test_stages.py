"""Stages: sections our team signs off before the next opens to the client, and a schedule (start and due day) per step."""
import datetime as dt

from app import models as m
from app import nudges, services
from tests.test_portal import admin, api, app, seed_org, session  # noqa: F401  (api and app are fixtures)

FORM = {"fields": [{"key": "name", "label": "Name", "type": "text", "required": True}]}
DOC = {
    "name": "Staged", "slug": "staged", "layout": "checklist",
    "sections": [
        {"key": "discover", "title": "Discovery"},
        {"key": "build", "title": "Build"},
        {"key": "notes", "title": "Notes", "signoff": False},
        {"key": "launch", "title": "Launch"},
        {"key": "ours", "title": "Our prep"},
    ],
    "steps": [
        {"key": "about", "type": "form", "title": "About you", "section": "discover", "config": FORM},
        {"key": "goals", "type": "form", "title": "Your goals", "section": "discover", "config": FORM},
        {"key": "assets", "type": "form", "title": "Assets", "section": "build", "config": FORM},
        {"key": "extra", "type": "form", "title": "Anything else", "section": "notes", "config": FORM},
        {"key": "golive", "type": "form", "title": "Go-live day", "section": "launch", "config": FORM},
        {"key": "loose", "type": "form", "title": "Not in a stage", "config": FORM},
        {"key": "prep", "type": "task", "title": "Prep the account", "section": "ours", "config": {"audience": "team"}},
    ],
}
ANSWER = {"data": {"answers": {"name": "x"}}}


def live(api, h, tz="America/New_York"):
    t = api.post("/api/templates", json=DOC, headers=h).json()
    cl = api.post("/api/clients", json={"name": "Acme", "timezone": tz}, headers=h).json()
    api.post(f"/api/clients/{cl['id']}/contacts", json={"name": "Pat", "email": "pat@example.com"}, headers=h)
    ob = api.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=h).json()
    sent = api.post(f"/api/onboardings/{ob['id']}/send", headers=h).json()
    return ob["id"], sent["links"][0]["url"].rsplit("/", 1)[1]


def stage(detail, key):
    return next(s for s in detail["stages"] if s["key"] == key)


def done(api, h, oid, *keys):
    for k in keys:
        assert api.post(f"/api/onboardings/{oid}/steps/{k}/complete", headers=h).status_code == 200


def test_a_later_stage_is_locked_for_the_client_until_the_one_before_is_signed_off(api, app):
    h = admin()
    seed_org(app)
    oid, token = live(api, h)
    s = session(api, token)
    view = api.get("/api/portal/onboarding", headers=s).json()
    by_key = {x["key"]: x for x in view["steps"]}
    assert by_key["about"]["can_write"] and not by_key["about"]["locked"]
    assert by_key["assets"]["locked"] and not by_key["assets"]["can_write"]
    assert by_key["loose"]["can_write"]  # a step outside any stage is never held back
    assert [(x["key"], x["state"]) for x in view["stages"]] == [("discover", "open"), ("build", "locked"), ("notes", "locked"), ("launch", "locked")]
    assert "ours" not in str(view)  # a stage holding only internal steps isn't shown
    assert api.put("/api/portal/steps/assets", json=ANSWER, headers=s).status_code == 409

    assert api.put("/api/portal/steps/about", json=ANSWER, headers=s).status_code == 200
    assert api.put("/api/portal/steps/goals", json=ANSWER, headers=s).status_code == 200
    view = api.get("/api/portal/onboarding", headers=s).json()
    assert view["stages"][0]["state"] == "waiting"  # their part is finished; it waits on us
    assert stage(api.get(f"/api/onboardings/{oid}", headers=h).json(), "discover")["state"] == "ready"

    r = api.post(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h)
    assert r.status_code == 200
    d = stage(r.json(), "discover")
    assert d["state"] == "signed_off" and d["signed_at"] and d["signed_by"]
    assert api.put("/api/portal/steps/assets", json=ANSWER, headers=s).status_code == 200


def test_signing_off_needs_every_step_finished_and_the_stages_before_signed(api, app):
    h = admin()
    seed_org(app)
    oid, _ = live(api, h)
    r = api.post(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h)
    assert r.status_code == 409 and any("About you" in p for p in r.json()["problems"])
    done(api, h, oid, "assets")  # our team may work ahead in a locked stage
    assert api.post(f"/api/onboardings/{oid}/stages/build/signoff", headers=h).status_code == 409  # discovery comes first
    assert api.post(f"/api/onboardings/{oid}/stages/notes/signoff", headers=h).status_code == 409  # doesn't need one
    assert api.post(f"/api/onboardings/{oid}/stages/nope/signoff", headers=h).status_code == 404
    done(api, h, oid, "about", "goals")
    assert api.post(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h).status_code == 200
    assert api.post(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h).status_code == 409  # already


def test_a_stage_without_sign_off_does_not_hold_back_the_next(api, app):
    h = admin()
    seed_org(app)
    oid, _ = live(api, h)
    done(api, h, oid, "about", "goals")
    api.post(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h)
    d = api.get(f"/api/onboardings/{oid}", headers=h).json()
    assert [stage(d, k)["state"] for k in ("build", "notes", "launch")] == ["open", "locked", "locked"]  # build still needs its own
    done(api, h, oid, "assets")
    api.post(f"/api/onboardings/{oid}/stages/build/signoff", headers=h)
    d = api.get(f"/api/onboardings/{oid}", headers=h).json()
    assert [stage(d, k)["state"] for k in ("notes", "launch")] == ["open", "open"]  # notes doesn't hold launch back
    done(api, h, oid, "extra")
    assert stage(api.get(f"/api/onboardings/{oid}", headers=h).json(), "notes")["state"] == "done"


def test_it_finishes_only_when_every_stage_is_signed_off_and_withdrawing_locks_again(api, app):
    h = admin()
    seed_org(app)
    oid, token = live(api, h)
    done(api, h, oid, "about", "goals", "assets", "extra", "golive", "loose", "prep")
    for k in ("discover", "build", "launch"):
        assert api.get(f"/api/onboardings/{oid}", headers=h).json()["status"] == "active"
        assert api.post(f"/api/onboardings/{oid}/stages/{k}/signoff", headers=h).status_code == 200, k
    assert api.post(f"/api/onboardings/{oid}/stages/ours/signoff", headers=h).json()["status"] == "completed"
    assert api.delete(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h).status_code == 409  # finished: reopen a step first

    api.post(f"/api/onboardings/{oid}/steps/golive/reopen", headers=h)
    r = api.delete(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h)
    assert r.status_code == 200 and stage(r.json(), "build")["state"] == "locked"
    s = session(api, token)
    assert api.put("/api/portal/steps/golive", json=ANSWER, headers=s).status_code == 409


def test_only_an_admin_or_a_manager_signs_off(api, app):
    h = admin()
    org_id = seed_org(app)
    oid, _ = live(api, h)
    done(api, h, oid, "about", "goals")
    with app.state.sessionmaker() as db:
        db.query(m.OrgMember).filter_by(org_id=org_id).update({"role": "member"})
        db.commit()
    assert api.post(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h).status_code == 403
    with app.state.sessionmaker() as db:
        db.query(m.OrgMember).filter_by(org_id=org_id).update({"role": "manager", "name": "Morgan"})
        db.commit()
    r = api.post(f"/api/onboardings/{oid}/stages/discover/signoff", headers=h)
    assert r.status_code == 200 and stage(r.json(), "discover")["signed_by"] == "Morgan"


def test_the_owner_is_asked_to_sign_off_a_finished_stage_once(api, app):
    h = admin()
    org_id = seed_org(app)
    oid, _ = live(api, h)
    done(api, h, oid, "about", "goals")
    api.post(f"/api/onboardings/{oid}/steps/goals/reopen", headers=h)
    done(api, h, oid, "goals")
    with app.state.sessionmaker() as db:
        rows = db.query(m.Notification).filter_by(org_id=org_id, kind="stage_ready").all()
    assert len(rows) == 1 and "Discovery" in rows[0].text and rows[0].step_key == "discover"


def test_reminders_leave_out_steps_in_a_locked_stage(api, app):
    h = admin()
    seed_org(app)
    oid, _ = live(api, h)
    with app.state.sessionmaker() as db:
        ob = db.get(m.Onboarding, oid)
        contact = db.query(m.Contact).one()
        assert [s.key for s in nudges.open_steps(ob, contact, contact)] == ["about", "goals", "loose"]


def test_a_step_gets_a_start_and_due_day_on_a_draft_and_sending_keeps_them(api, app):
    h = admin()
    seed_org(app)
    t = api.post("/api/templates", json=DOC | {"slug": "staged-2", "name": "Staged 2"}, headers=h).json()
    cl = api.post("/api/clients", json={"name": "Acme", "timezone": "America/Los_Angeles"}, headers=h).json()
    api.post(f"/api/clients/{cl['id']}/contacts", json={"name": "Pat", "email": "pat@example.com"}, headers=h)
    oid = api.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=h).json()["id"]

    r = api.put(f"/api/onboardings/{oid}/steps/about/schedule", json={"start_on": "2026-12-01", "due_on": "2026-12-03"}, headers=h)
    assert r.status_code == 200
    assert r.json()["start_on"] == "2026-12-01" and r.json()["due_on"] == "2026-12-03"
    due_at = dt.datetime.fromisoformat(r.json()["due_at"].replace("Z", "+00:00"))
    assert due_at.astimezone(dt.timezone.utc).date() == dt.date(2026, 12, 4)  # the end of the 3rd in Los Angeles is the 4th in UTC

    bad = api.put(f"/api/onboardings/{oid}/steps/goals/schedule", json={"start_on": "2026-12-05", "due_on": "2026-12-01"}, headers=h)
    assert bad.status_code == 422 and bad.json()["problems"]

    api.post(f"/api/onboardings/{oid}/send", headers=h)
    d = api.get(f"/api/onboardings/{oid}", headers=h).json()
    about = next(s for s in d["steps"] if s["key"] == "about")
    assert about["due_on"] == "2026-12-03" and about["start_on"] == "2026-12-01"
    assert stage(d, "discover")["start_on"] == "2026-12-01" and stage(d, "discover")["due_on"] == "2026-12-03"

    cleared = api.put(f"/api/onboardings/{oid}/steps/about/schedule", json={}, headers=h).json()
    assert cleared["due_on"] is None and cleared["start_on"] is None


def test_admin_steps_come_in_stage_order(api, app):
    h = admin()
    seed_org(app)
    shuffled = DOC | {"slug": "staged-3", "name": "Staged 3", "steps": [DOC["steps"][2], DOC["steps"][5], DOC["steps"][0], *DOC["steps"][1:2], *DOC["steps"][3:5], DOC["steps"][6]]}
    t = api.post("/api/templates", json=shuffled, headers=h).json()
    cl = api.post("/api/clients", json={"name": "Acme"}, headers=h).json()
    ob = api.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=h).json()
    keys = [s["key"] for s in api.get(f"/api/onboardings/{ob['id']}", headers=h).json()["steps"]]
    assert keys == ["about", "goals", "assets", "extra", "golive", "prep", "loose"]


def test_end_of_day_is_the_clients_own():
    assert services.end_of_day(dt.date(2026, 6, 1), "Europe/London") == dt.datetime(2026, 6, 1, 22, 59, tzinfo=dt.timezone.utc)
    assert services.end_of_day(dt.date(2026, 6, 1), "Not/AZone") == dt.datetime(2026, 6, 1, 23, 59, tzinfo=dt.timezone.utc)
