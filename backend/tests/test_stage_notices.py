"""Telling the client the next stage is open: after a sign-off, once, to whoever has something to do in it."""
import datetime as dt

import pytest

from app import jobs, stage_notices, models as m
from app.notify import SendResult
from tests.helpers4 import NIGHT_ET, NOON_ET, make_world, token_in

D = dt.timedelta
FORM = {"fields": [{"key": "name", "label": "Name", "type": "text", "required": True}]}
DOC = {
    "name": "Staged", "slug": "staged", "layout": "checklist",
    "sections": [{"key": "discover", "title": "Discovery"}, {"key": "build", "title": "Build"}, {"key": "prep", "title": "Our prep"}, {"key": "launch", "title": "Launch"}],
    "steps": [
        {"key": "about", "type": "form", "title": "About you", "section": "discover", "assignee_role": "owner", "config": FORM},
        {"key": "assets", "type": "form", "title": "Your assets", "section": "build", "assignee_role": "owner", "config": FORM},
        {"key": "dns", "type": "connect", "title": "Grant DNS access", "section": "build", "assignee_role": "it", "config": {"provider": "dns", "label": "DNS"}},
        {"key": "secret", "type": "task", "title": "Margin notes", "section": "build", "config": {"audience": "team"}},
        {"key": "setup", "type": "task", "title": "Set up the account", "section": "prep", "config": {"audience": "team"}},
        {"key": "golive", "type": "form", "title": "Go-live day", "section": "launch", "assignee_role": "owner", "config": FORM},
    ],
}


@pytest.fixture()
def w():
    world, client = make_world()
    with client:
        yield world


def live(w):
    _, oid, links = w.live(doc=DOC)
    return oid


def finish_and_sign(w, oid, *steps, stage):
    for k in steps:
        assert w.api.post(f"/api/onboardings/{oid}/steps/{k}/complete").status_code == 200
    r = w.api.post(f"/api/onboardings/{oid}/stages/{stage}/signoff")
    assert r.status_code == 200, r.text


def opened_at(w, oid, when):
    with w.sm() as db:
        db.get(m.Onboarding, oid).stage_opened_at = when
        db.commit()


def run(w, now):
    return stage_notices.run_notices(w.sm, w.settings, w.notifier, now=now)


def sent_text(w):
    return " ".join([b for _, b in w.notifier.sms] + [e["subject"] + e["text"] + e["html"] for e in w.notifier.emails])


def test_a_sign_off_tells_each_contact_with_work_in_the_opened_stage_after_the_quiet_period(w):
    oid = live(w)
    finish_and_sign(w, oid, "about", stage="discover")
    assert w.get(oid).stage_opened_keys == ["build"]
    assert w.api.get(f"/api/onboardings/{oid}").json()["stage_notice_pending"] is True
    opened_at(w, oid, NOON_ET - D(minutes=5))
    assert run(w, NOON_ET)["waiting"] == 1 and not w.notifier.sms and not w.notifier.emails  # an undo still has time
    opened_at(w, oid, NOON_ET - D(minutes=20))
    r = run(w, NOON_ET)
    assert r["sent"] == 1 and w.get(oid).stage_opened_at is None and w.get(oid).stage_opened_keys is None
    sms = dict(w.notifier.sms)
    assert "“Build”" in sms["+15551234567"]  # Pat agreed to texts
    ivy = next(e for e in w.notifier.emails if e["to"] == "ivy@acme.test")
    assert "Grant DNS access" in ivy["text"] and "Your assets" not in ivy["text"]  # only their own steps
    text = sent_text(w)
    assert "Margin notes" not in text and "Our prep" not in text  # never an internal step or a stage with nothing for them
    assert w.api.post("/api/portal/exchange", json={"token": token_in(ivy["text"])}).status_code == 200
    assert run(w, NOON_ET + D(minutes=1))["considered"] == 0  # it goes once


def test_withdrawing_the_sign_off_before_it_goes_sends_nothing(w):
    oid = live(w)
    finish_and_sign(w, oid, "about", stage="discover")
    assert w.api.delete(f"/api/onboardings/{oid}/stages/discover/signoff").status_code == 200
    ob = w.get(oid)
    assert ob.stage_opened_at is None and ob.stage_opened_keys is None
    assert run(w, NOON_ET + D(hours=1))["considered"] == 0 and not w.notifier.emails


def test_a_stage_with_nothing_for_the_client_opens_quietly_and_the_next_one_is_announced(w):
    oid = live(w)
    finish_and_sign(w, oid, "about", stage="discover")
    finish_and_sign(w, oid, "assets", "dns", "secret", stage="build")  # opens "Our prep": team work only
    assert w.get(oid).stage_opened_keys == ["build"]  # nothing new for the client yet (build was already queued)
    finish_and_sign(w, oid, "setup", stage="prep")  # opens Launch
    assert w.get(oid).stage_opened_keys == ["build", "launch"]
    opened_at(w, oid, NOON_ET - D(hours=1))
    assert run(w, NOON_ET)["sent"] == 1
    assert [to for to, _ in w.notifier.sms] == ["+15551234567"] and not w.notifier.emails  # Ivy has nothing in Launch
    text = sent_text(w)
    assert "“Launch”" in text and "Build" not in text  # build has nothing left to do, so it isn't named


def test_never_at_night_where_the_client_is(w):
    oid = live(w)
    finish_and_sign(w, oid, "about", stage="discover")
    opened_at(w, oid, NIGHT_ET - D(hours=1))
    assert run(w, NIGHT_ET)["waiting"] == 1 and not w.notifier.sms and not w.notifier.emails
    assert run(w, NOON_ET)["sent"] == 1


def test_a_paused_onboarding_waits_and_a_failed_send_revokes_its_link(w):
    oid = live(w)
    finish_and_sign(w, oid, "about", stage="discover")
    opened_at(w, oid, NOON_ET - D(hours=1))
    w.api.post(f"/api/onboardings/{oid}/pause")
    assert run(w, NOON_ET)["considered"] == 0
    w.api.post(f"/api/onboardings/{oid}/resume")
    opened_at(w, oid, NOON_ET - D(hours=1))
    w.notifier.sms_results = [SendResult(False, reason="carrier error")]
    w.notifier.email_results = [SendResult(True), SendResult(True)]
    assert run(w, NOON_ET)["sent"] == 1
    with w.sm() as db:
        pat = db.query(m.Contact).filter_by(name="Pat Owner").one()
        failed = [l for l in db.query(m.MagicLink).filter_by(contact_id=pat.id) if l.revoked_at is not None]
    assert len(failed) == 1  # the text's link was revoked; Pat got the email instead
    assert any(e["to"] == "pat@acme.test" for e in w.notifier.emails)


def test_the_timer_runs_it(w):
    oid = live(w)
    finish_and_sign(w, oid, "about", stage="discover")
    opened_at(w, oid, NOON_ET - D(hours=1))
    out = jobs.run_once(w.sm, w.settings, w.notifier, now=NOON_ET)
    assert out["stage_notices"]["sent"] == 1
