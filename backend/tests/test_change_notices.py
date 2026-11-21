"""Telling the client when their steps change after sending: batched, one message, and only what they can see."""
import datetime as dt

import pytest
from sqlalchemy import select

from app import changes, jobs, models as m
from app.notify import SendResult
from tests.helpers4 import NIGHT_ET, NOON_ET, make_world, token_in

D = dt.timedelta


@pytest.fixture()
def w():
    world, client = make_world()
    with client:
        yield world


def doc_of(w, oid):
    d = w.api.get(f"/api/onboardings/{oid}/document").json()
    return d["document"]["steps"], d["etag"]


def save(w, oid, steps, **kw):
    r = w.api.put(f"/api/onboardings/{oid}/document", json={"steps": steps} | kw)
    assert r.status_code == 200, r.text
    return r.json()


def edited_at(w, oid, when):
    """Say when the latest edit was made, so the quiet period is measured from a known time."""
    with w.sm() as db:
        ob = db.get(m.Onboarding, oid)
        ob.steps_changed_at = when
        db.commit()


def notices(w, now):
    return changes.run_notices(w.sm, w.settings, w.notifier, now=now)


def pending(w, oid):
    return w.get(oid).steps_changed_at is not None


NEW = {"key": "logo", "type": "upload", "title": "Your logo", "assignee_role": "owner", "config": {"accept": ["png"]}}


def sent_text(w):
    return " ".join([b for _, b in w.notifier.sms] + [e["text"] + e["html"] for e in w.notifier.emails])


def test_an_edit_after_sending_tells_each_contact_who_has_something_to_do_once_the_quiet_period_passes(w):
    _, oid, links = w.live()
    steps, _ = doc_of(w, oid)
    body = save(w, oid, steps + [NEW])
    assert body["client_notice_pending"] is True and pending(w, oid)
    edited_at(w, oid, NOON_ET - D(minutes=5))
    r = notices(w, NOON_ET)
    assert r["waiting"] == 1 and r["sent"] == 0 and not w.notifier.sms and not w.notifier.emails  # still within the quiet period
    edited_at(w, oid, NOON_ET - D(minutes=20))
    r = notices(w, NOON_ET)
    assert r["sent"] == 1 and not pending(w, oid)
    text = sent_text(w)
    assert "Your logo" in text and "Build the agent" not in text  # the internal step never appears
    assert w.notifier.sms and w.notifier.sms[0][0] == "+15551234567"  # Pat agreed to texts
    assert [e["to"] for e in w.notifier.emails] == ["ivy@acme.test"]  # Ivy has an email only
    tok = token_in(w.notifier.emails[0]["text"])
    assert w.api.post("/api/portal/exchange", json={"token": tok}).status_code == 200  # a real, working link


def test_several_edits_in_a_row_make_one_message_with_the_net_difference(w):
    _, oid, _ = w.live()
    steps, _ = doc_of(w, oid)
    save(w, oid, steps + [NEW])
    steps2, _ = doc_of(w, oid)
    for s in steps2:
        if s["key"] == "basics":
            s["title"] = "About your business"
    save(w, oid, steps2)
    edited_at(w, oid, NOON_ET - D(minutes=20))
    assert notices(w, NOON_ET)["sent"] == 1
    mail = w.notifier.emails[0]["text"]
    assert "New: “Your logo”" in mail and "Updated: “About your business”" in mail
    assert len(w.notifier.emails) == 1  # one for the batch, not one per edit
    assert notices(w, NOON_ET + D(hours=1))["considered"] == 0  # nothing left


def test_edits_that_cancel_out_send_nothing(w):
    _, oid, _ = w.live()
    steps, _ = doc_of(w, oid)
    save(w, oid, steps + [NEW])
    save(w, oid, steps)  # back to what the client saw
    edited_at(w, oid, NOON_ET - D(minutes=20))
    r = notices(w, NOON_ET)
    assert r["nothing_to_say"] == 1 and not w.notifier.sms and not w.notifier.emails and not pending(w, oid)


def test_a_silent_save_and_an_internal_only_change_tell_nobody(w):
    _, oid, _ = w.live()
    steps, _ = doc_of(w, oid)
    save(w, oid, steps + [NEW], notify_client=False)
    assert not pending(w, oid)
    steps, _ = doc_of(w, oid)
    for s in steps:
        if s["key"] == "build":
            s["title"] = "Build the thing"  # internal
    save(w, oid, steps)
    edited_at(w, oid, NOON_ET - D(minutes=20))
    assert notices(w, NOON_ET)["nothing_to_say"] == 1 and not w.notifier.emails and not w.notifier.sms


def test_at_night_it_waits_and_goes_in_the_morning(w):
    _, oid, _ = w.live()
    steps, _ = doc_of(w, oid)
    save(w, oid, steps + [NEW])
    edited_at(w, oid, NIGHT_ET - D(hours=2))
    assert notices(w, NIGHT_ET)["waiting"] == 1 and pending(w, oid) and not w.notifier.emails and not w.notifier.sms
    assert notices(w, NOON_ET + D(days=1))["sent"] == 1


def test_running_it_twice_sends_once(w):
    _, oid, _ = w.live()
    steps, _ = doc_of(w, oid)
    save(w, oid, steps + [NEW])
    edited_at(w, oid, NOON_ET - D(minutes=20))
    notices(w, NOON_ET)
    n = len(w.notifier.emails) + len(w.notifier.sms)
    notices(w, NOON_ET)
    assert len(w.notifier.emails) + len(w.notifier.sms) == n


def test_a_paused_onboarding_keeps_the_notice_until_it_resumes(w):
    _, oid, _ = w.live()
    steps, _ = doc_of(w, oid)
    save(w, oid, steps + [NEW])
    w.api.post(f"/api/onboardings/{oid}/pause")
    edited_at(w, oid, NOON_ET - D(minutes=20))
    assert notices(w, NOON_ET)["considered"] == 0 and pending(w, oid)
    w.api.post(f"/api/onboardings/{oid}/resume")
    edited_at(w, oid, NOON_ET - D(minutes=20))
    assert notices(w, NOON_ET)["sent"] == 1


def test_a_failed_text_falls_back_to_email_and_a_stop_reply_withdraws_consent(w):
    _, oid, links = w.live()
    w.notifier.sms_results.append(SendResult(False, "That number has opted out.", opted_out=True))
    steps, _ = doc_of(w, oid)
    save(w, oid, steps + [NEW])
    edited_at(w, oid, NOON_ET - D(minutes=20))
    notices(w, NOON_ET)
    assert any(e["to"] == "pat@acme.test" for e in w.notifier.emails)
    with w.sm() as db:
        pat = db.scalar(select(m.Contact).where(m.Contact.name == "Pat Owner"))
        assert pat.sms_consent is False and "STOP" in pat.sms_consent_source
        failed_link = db.scalar(select(m.MagicLink).where(m.MagicLink.contact_id == pat.id, m.MagicLink.revoked_at.is_not(None)))
        assert failed_link is not None  # the link in the text that never arrived is dead


def test_reorder_removal_and_a_changed_form_are_all_described(w):
    _, oid, _ = w.live()
    steps, _ = doc_of(w, oid)
    shuffled = list(reversed([s for s in steps if s["key"] != "it_access"]))
    save(w, oid, shuffled)
    edited_at(w, oid, NOON_ET - D(minutes=20))
    notices(w, NOON_ET)
    mail = " ".join(e["text"] for e in w.notifier.emails) + " ".join(b for _, b in w.notifier.sms)
    assert "No longer needed: “Grant IT access”" in mail and "The order of the steps changed" in mail


def test_the_unit_helpers_describe_differences():
    a = [{"key": "a", "title": "A", "sig": "1"}, {"key": "b", "title": "B", "sig": "2"}]
    assert changes.is_empty(changes.diff(a, a))
    d = changes.diff(a, [{"key": "b", "title": "B", "sig": "2"}, {"key": "a", "title": "A", "sig": "9"}, {"key": "c", "title": "C", "sig": "3"}])
    assert d == {"added": ["C"], "removed": [], "changed": ["A"], "reordered": True}
    many = changes.summary_lines({"added": [str(i) for i in range(8)], "removed": [], "changed": [], "reordered": False})[0]
    assert "and 3 more" in many


def test_the_job_pass_runs_it_and_a_failure_in_it_does_not_stop_the_others(w, monkeypatch):
    out = jobs.run_once(w.sm, w.settings, w.notifier, now=NOON_ET)
    assert out["change_notices"]["considered"] == 0
    monkeypatch.setattr(changes, "run_notices", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = jobs.run_once(w.sm, w.settings, w.notifier, now=NOON_ET)
    assert out["change_notices"] == {"error": True} and "reminders" in out and "provisioning" in out
