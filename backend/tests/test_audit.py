"""The audit trail: every change by our team, a client or the system is recorded with who and when, never with what a client
said, and the trail can't be changed."""
import pytest
from sqlalchemy import select

from app import audit, jobs, models as m, services
from tests.helpers4 import NOON_ET, make_world, token_in
from tests.test_api import app_two_orgs, bearer, setup_client  # noqa: F401  (fixture)

SECRET_ANSWER = "TOP-SECRET-ANSWER"
SECRET_COMMENT = "PRIVATE-COMMENT-TEXT"


@pytest.fixture()
def w():
    world, client = make_world()
    with client:
        yield world


def trail(w, oid):
    r = w.api.get(f"/api/onboardings/{oid}/activity")
    assert r.status_code == 200, r.text
    return r.json()


def actions(rows):
    return [r["action"] for r in reversed(rows)]  # oldest first


def portal(w, links, who="Pat Owner"):
    tok = w.api.post("/api/portal/exchange", json={"token": token_in(links[who]["url"])}).json()["session"]
    return {"Authorization": f"Bearer {tok}"}


def test_the_team_s_changes_are_recorded_in_order_with_who_did_them(w):
    _, oid, links = w.live()
    api = w.api
    api.post(f"/api/onboardings/{oid}/steps/basics/complete")
    api.post(f"/api/onboardings/{oid}/steps/it_access/skip")
    api.post(f"/api/onboardings/{oid}/steps/it_access/reopen")
    api.put(f"/api/onboardings/{oid}/steps/approve/schedule", json={"start_on": "2026-12-01", "due_on": "2026-12-05"})
    api.post(f"/api/onboardings/{oid}/steps/approve/comments", json={"body": SECRET_COMMENT, "client_visible": False})
    api.post(f"/api/onboardings/{oid}/pause")
    api.post(f"/api/onboardings/{oid}/resume")
    api.put(f"/api/onboardings/{oid}/nudges", json={"paused": True})
    link = api.get(f"/api/onboardings/{oid}/links").json()[0]
    api.post(f"/api/onboardings/{oid}/links/{link['id']}/extend", json={"days": 7})
    api.post(f"/api/onboardings/{oid}/links/{link['id']}/revoke")
    rows = [r for r in trail(w, oid) if not r["about_client"]]
    assert actions(rows)[:2] == ["onboarding.created", "onboarding.sent"]
    assert actions(rows)[2:] == ["step.completed", "step.skipped", "step.reopened", "step.scheduled", "step.commented", "onboarding.paused",
                                 "onboarding.resumed", "reminders.paused", "link.extended", "link.revoked"]
    assert all(r["actor_kind"] == "team" and r["actor_label"] == "local" for r in rows)
    by = {r["action"]: r for r in rows}
    assert by["step.completed"]["summary"] == "Marked “Company basics” done." and by["step.completed"]["step_key"] == "basics"
    assert by["step.scheduled"]["summary"] == "“Approve the greeting”: starts 2026-12-01, due 2026-12-05 (was none, none)."
    assert by["step.commented"]["summary"] == "Left a note for the team on “Approve the greeting”."
    assert "Pat Owner" in by["link.revoked"]["summary"]
    assert SECRET_COMMENT not in str(rows)


def test_a_client_s_answers_and_comments_are_recorded_by_name_but_never_what_they_said(w):
    _, oid, links = w.live()
    h = portal(w, links)
    w.api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": SECRET_ANSWER}}}, headers=h)
    w.api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": SECRET_ANSWER + "2"}}}, headers=h)
    w.api.put("/api/portal/steps/approve", json={"data": {"decision": "changes_requested", "comment": SECRET_COMMENT}}, headers=h)
    w.api.post("/api/portal/steps/approve/comments", json={"body": SECRET_COMMENT}, headers=h)
    rows = [r for r in trail(w, oid) if r["actor_kind"] == "client"]
    assert [r["summary"] for r in reversed(rows)] == [
        "“Company basics”: filled it in.", "“Company basics”: filled it in (version 2).",
        "“Approve the greeting”: asked for changes.", "Left a comment on “Approve the greeting”.",
    ]
    assert {r["actor_label"] for r in rows} == {"Pat Owner"}
    with w.sm() as db:
        stored = " ".join(f"{e.summary} {e.details}" for e in db.scalars(select(m.AuditEvent)))
    assert SECRET_ANSWER not in stored and SECRET_COMMENT not in stored


def test_editing_the_steps_says_what_changed(w):
    _, oid, _ = w.live()
    doc = w.api.get(f"/api/onboardings/{oid}/document").json()
    steps = [s for s in doc["document"]["steps"] if s["key"] != "it_access"]
    steps[0] = {**steps[0], "title": "Business details"}
    steps.append({"key": "logo", "type": "upload", "title": "Your logo", "config": {"accept": ["png"]}})
    r = w.api.put(f"/api/onboardings/{oid}/document", json={"steps": steps, "notify_client": False})
    assert r.status_code == 200, r.text
    row = next(r for r in trail(w, oid) if r["action"] == "onboarding.steps_edited")
    assert row["summary"] == "Edited the steps: added “Your logo”; removed “Grant IT access”; changed “Business details”. The client wasn't told."


def test_reminders_and_what_the_system_does_are_recorded_as_the_system(w):
    _, oid, _ = w.live()
    jobs.run_once(w.sm, w.settings, w.notifier, now=NOON_ET)
    rows = [r for r in trail(w, oid) if r["action"] == "reminder.sent"]
    assert {r["actor_label"] for r in rows} == {"Reminders"} and {r["actor_kind"] for r in rows} == {"system"}
    assert {r["summary"] for r in rows} == {"Sent automatic reminder 1 to Pat Owner by text.", "Sent automatic reminder 1 to Ivy IT by email."}
    r = w.api.post(f"/api/onboardings/{oid}/nudge")
    assert r.status_code == 200, r.text
    manual = [r for r in trail(w, oid) if r["action"] == "reminder.sent" and r["actor_kind"] == "team"]
    assert manual and manual[0]["summary"].startswith("Sent a reminder to")


def test_finishing_is_recorded_once_by_the_system(w):
    _, oid, _ = w.live()
    for k in ("basics", "it_access", "approve", "build"):
        w.api.post(f"/api/onboardings/{oid}/steps/{k}/complete")
    done = [r for r in trail(w, oid) if r["action"] == "onboarding.completed"]
    assert len(done) == 1 and done[0]["actor_kind"] == "system"


def test_a_change_that_is_refused_leaves_no_entry(w):
    _, oid, _ = w.live()
    before = len(trail(w, oid))
    assert w.api.post(f"/api/onboardings/{oid}/send").status_code == 409
    assert w.api.put(f"/api/onboardings/{oid}/steps/approve/schedule", json={"start_on": "2026-12-09", "due_on": "2026-12-01"}).status_code == 422
    assert len(trail(w, oid)) == before


def test_changes_to_the_client_show_on_its_onboardings(w):
    cl, oid, _ = w.live()
    ivy = next(c for c in w.api.get(f"/api/clients/{cl['id']}").json()["contacts"] if c["name"] == "Ivy IT")
    w.api.patch(f"/api/clients/{cl['id']}/contacts/{ivy['id']}", json={"sms_consent": True, "sms_consent_source": "signed form", "phone": "(555) 765-4321"})
    w.api.post(f"/api/clients/{cl['id']}/paying", json={"paying": True})
    everything = trail(w, oid)
    assert actions(everything)[:4] == ["client.created", "contact.added", "contact.sms_consent_given", "contact.added"]  # before the onboarding existed
    rows = {r["action"]: r for r in reversed(everything)}  # newest of each
    assert rows["contact.sms_consent_given"]["about_client"] is True
    assert rows["contact.sms_consent_given"]["summary"] == "Recorded Ivy IT's consent to texts (source: signed form)."
    assert rows["contact.changed"]["summary"] == "Changed Ivy IT's phone."
    assert rows["client.paying"]["summary"] == "Marked Acme Plumbing as paying."


def test_the_trail_can_t_be_changed_or_deleted(w):
    _, oid, _ = w.live()
    with w.sm() as db:
        row = db.scalars(select(m.AuditEvent).where(m.AuditEvent.onboarding_id == oid)).first()
        row.summary = "rewritten"
        with pytest.raises(RuntimeError):
            db.flush()
        db.rollback()
        db.delete(db.scalars(select(m.AuditEvent).where(m.AuditEvent.onboarding_id == oid)).first())
        with pytest.raises(RuntimeError):
            db.flush()


def test_pages_go_back_in_time(w):
    _, oid, _ = w.live()
    for k in ("basics", "it_access", "approve"):
        w.api.post(f"/api/onboardings/{oid}/steps/{k}/skip")
    first = w.api.get(f"/api/onboardings/{oid}/activity", params={"limit": 2}).json()
    rest = [r for r in w.api.get(f"/api/onboardings/{oid}/activity", params={"before": first[-1]["at"]}).json() if not r["about_client"]]
    assert [r["action"] for r in first] == ["step.skipped", "step.skipped"]
    assert [r["action"] for r in rest][-2:] == ["onboarding.sent", "onboarding.created"] and not {r["id"] for r in rest} & {r["id"] for r in first}


def test_a_named_person_is_recorded_by_name_and_another_org_can_t_read_the_trail(app_two_orgs):  # noqa: F811
    c = app_two_orgs
    ha, hb = bearer("user-a", "morgan@a.test"), bearer("user-b")
    with c.app.state.sessionmaker() as db:
        row = db.scalar(select(m.OrgMember).where(m.OrgMember.auth_user_id == "user-a"))
        row.name = "Morgan"
        db.commit()
    t, cl = setup_client(c, ha)
    ob = c.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=ha).json()
    rows = c.get(f"/api/onboardings/{ob['id']}/activity", headers=ha).json()
    assert rows[0]["actor_label"] == "Morgan" and rows[0]["action"] == "onboarding.created"
    assert c.get(f"/api/onboardings/{ob['id']}/activity", headers=hb).status_code == 404


def test_record_reads_who_is_acting_from_the_session(w):
    with w.sm() as db:
        org = services.get_or_create_org(db, "Local", "local")
        audit.acting(db, audit.Who("team", "m1", "Sam"))
        row = audit.record(db, org.id, "x.y", "Did a thing with a key ghp_" + "a" * 36)
        assert (row.actor_kind, row.actor_label) == ("team", "Sam") and "[redacted]" in row.summary
        row2 = audit.record(db, org.id, "x.z", "System thing", by=audit.system("Reminders"))
        assert (row2.actor_kind, row2.actor_label) == ("system", "Reminders")
        db.rollback()
