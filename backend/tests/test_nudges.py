"""Reminders: who gets one, when, how, and what stops them. Times are injected, so nothing here depends on the clock."""
import datetime as dt

import pytest
from sqlalchemy import select

from app import models as m
from app import nudges
from app.notify import SendResult
from tests.helpers4 import NIGHT_ET, NOON_ET, WHEN_STALE, make_world, token_in

token_in = token_in

D = dt.timedelta


@pytest.fixture()
def w():
    world, client = make_world()
    with client:
        yield world


def run(w, now=NOON_ET, **kw):
    return nudges.run_nudges(w.sm, w.settings, w.notifier, now=now, **kw)


def rows(w, oid):
    with w.sm() as db:
        return list(db.scalars(select(m.Nudge).where(m.Nudge.onboarding_id == oid).order_by(m.Nudge.created_at, m.Nudge.channel)))


# ---------------------------------------------------------------- when

def test_nothing_is_sent_before_the_stall_time_and_something_is_after(w):
    _, oid, _ = w.live()
    s = run(w, now=WHEN_STALE + D(days=2, hours=23))
    assert s.considered == 0 and not w.notifier.sms and not w.notifier.emails
    s = run(w, now=WHEN_STALE + D(days=3, hours=1))
    assert s.considered == 1 and s.sent >= 1


def test_the_template_decides_how_long_is_too_long(w):
    from tests.helpers4 import DOC

    _, oid, _ = w.live(doc={**DOC, "slug": "slow", "nudge_after_days": 7})
    assert run(w, now=WHEN_STALE + D(days=6)).considered == 0
    assert run(w, now=WHEN_STALE + D(days=8)).considered == 1


def test_only_active_unpaused_onboardings_with_steps_left_are_reminded(w):
    _, oid, _ = w.live()
    w.api.post(f"/api/onboardings/{oid}/pause")
    w.set_activity(oid, WHEN_STALE)
    assert run(w).considered == 0  # paused
    w.api.post(f"/api/onboardings/{oid}/resume")
    w.set_activity(oid, WHEN_STALE)
    w.api.put(f"/api/onboardings/{oid}/nudges", json={"paused": True})
    assert run(w).considered == 0  # reminders switched off for this one
    w.api.put(f"/api/onboardings/{oid}/nudges", json={"paused": False})
    for key in ("basics", "it_access", "approve"):
        w.api.post(f"/api/onboardings/{oid}/steps/{key}/complete")
    w.set_activity(oid, WHEN_STALE)
    assert run(w).considered == 0  # the client has nothing left (only Jay's own task remains)
    _, draft = w.client_with(name="Draft Co")
    assert run(w).considered == 0  # a draft is never reminded


def test_a_second_pass_straight_after_does_not_send_again(w):
    _, oid, _ = w.live()
    run(w)
    n = len(w.notifier.sms) + len(w.notifier.emails)
    run(w, now=NOON_ET + D(minutes=20))
    run(w, now=NOON_ET + D(days=2))  # still inside the next interval
    assert len(w.notifier.sms) + len(w.notifier.emails) == n


# ---------------------------------------------------------------- who and how

def test_each_contact_gets_one_message_about_their_own_steps(w):
    _, oid, _ = w.live()
    run(w)
    # Pat (owner): consented phone -> a text. Basics (assigned) + approve (unassigned goes to the first contact) = 2 steps.
    assert len(w.notifier.sms) == 1 and not any(e["to"] == "pat@acme.test" for e in w.notifier.emails)
    to, body = w.notifier.sms[0]
    assert to == "+15551234567"
    assert "2 steps left" in body and "Company basics" in body and "Reply STOP to opt out." in body
    # Ivy (IT): no phone -> an email about her one step
    assert [e["to"] for e in w.notifier.emails] == ["ivy@acme.test"]
    assert "1 step left" in w.notifier.emails[0]["subject"] and "Grant IT access" in w.notifier.emails[0]["text"]


def test_a_contact_with_nothing_to_do_is_not_reminded(w):
    _, oid, _ = w.live()
    w.api.post(f"/api/onboardings/{oid}/steps/it_access/complete")
    w.set_activity(oid, WHEN_STALE)
    run(w)
    assert not any(e["to"] == "ivy@acme.test" for e in w.notifier.emails)


def test_no_text_without_recorded_consent_so_it_falls_back_to_email(w):
    contacts = [{"name": "Pat Owner", "role": "owner", "email": "pat@acme.test", "phone": "5551234567"}]
    _, oid, _ = w.live(contacts=contacts)
    run(w)
    assert not w.notifier.sms
    assert [e["to"] for e in w.notifier.emails] == ["pat@acme.test"]


def test_a_contact_with_no_way_to_be_reached_flags_the_onboarding_once(w):
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "phone": "5551234567"}])  # a phone but no consent, no email
    s = run(w)
    assert not w.notifier.sms and not w.notifier.emails and s.flagged == 1
    assert w.get(oid).attention == "unreachable"
    assert run(w, now=NOON_ET + D(days=5)).flagged == 0  # not flagged again
    # adding an email fixes it, and the next reminder clears the flag
    cl = w.api.get("/api/clients").json()[0]
    w.api.patch(f"/api/clients/{cl['id']}/contacts/{cl['contacts'][0]['id']}", json={"email": "pat@acme.test"})
    run(w, now=NOON_ET + D(days=9))
    assert w.get(oid).attention is None and [e["to"] for e in w.notifier.emails] == ["pat@acme.test"]


def test_phone_numbers_are_made_texttable_or_refused(w):
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "email": "p@a.test", "phone": "12-34", "sms_consent": True, "sms_consent_source": "form"}])
    run(w)
    assert not w.notifier.sms and len(w.notifier.emails) == 1  # a number we can't text falls back to email


# ---------------------------------------------------------------- night time

def test_nobody_is_texted_or_emailed_at_night_where_they_are(w):
    _, oid, _ = w.live()
    s = run(w, now=NIGHT_ET)
    assert s.sent == 0 and not w.notifier.sms and not w.notifier.emails
    assert not rows(w, oid)
    assert run(w, now=NOON_ET).sent == 2  # and they are reminded when it's day


def test_quiet_hours_follow_the_clients_own_time_zone(w):
    # 08:00 UTC is 03:00 in New York (night) but 17:00 in Tokyo (day)
    _, oid, _ = w.live(timezone="Asia/Tokyo")
    assert run(w, now=NIGHT_ET).sent == 2
    assert nudges.in_quiet_hours(NIGHT_ET, "America/New_York", 21, 8)
    assert not nudges.in_quiet_hours(NIGHT_ET, "Asia/Tokyo", 21, 8)
    assert not nudges.in_quiet_hours(NOON_ET, "America/New_York", 21, 8)
    assert nudges.in_quiet_hours(NOON_ET.replace(hour=2), "America/New_York", 21, 8)  # 21:00 local: the window wraps midnight


def test_a_manual_reminder_still_never_texts_at_night_but_may_email(w):
    _, oid, _ = w.live()
    with w.sm() as db:
        out = nudges.remind_now(db, w.settings, w.notifier, db.get(m.Onboarding, oid), now=NIGHT_ET)
        db.commit()
    assert not w.notifier.sms
    by = {o.contact: o for o in out}
    assert by["Pat Owner"].status == "sent" and by["Pat Owner"].channel == "email"  # emailed instead of texted
    assert any(e["to"] == "pat@acme.test" for e in w.notifier.emails)


# ---------------------------------------------------------------- the link in the message

def test_every_reminder_carries_a_fresh_working_link_stored_only_as_a_hash(w):
    _, oid, links = w.live()
    old = token_in(links["Pat Owner"]["url"])
    run(w)
    new = token_in(w.notifier.sms[0][1])
    assert new != old and w.api.post("/api/portal/exchange", json={"token": new}).status_code == 200
    assert w.api.post("/api/portal/exchange", json={"token": old}).status_code == 200  # the first link still works too
    with w.sm() as db:
        hashes = {l.token_hash for l in db.scalars(select(m.MagicLink))}
        assert new not in hashes and all(len(h) == 64 for h in hashes)


def test_a_link_for_a_reminder_that_failed_is_revoked(w):
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "email": "p@a.test"}])
    w.notifier.email_results = [SendResult(False, "The email service refused it (status 500).")]
    run(w)
    tok = token_in(w.notifier.emails[0]["text"])
    assert w.api.post("/api/portal/exchange", json={"token": tok}).status_code == 401  # nobody got it, so it is dead


# ---------------------------------------------------------------- failures

def test_a_failed_text_falls_back_to_email_and_both_attempts_are_recorded(w):
    _, oid, _ = w.live()
    w.notifier.sms_results = [SendResult(False, "The text message service refused it (status 500).")]
    run(w)
    r = [(x.channel, x.status) for x in rows(w, oid) if x.channel in ("sms", "email")]
    assert ("sms", "failed") in r and ("email", "sent") in r
    assert any(e["to"] == "pat@acme.test" for e in w.notifier.emails)


def test_a_reply_of_stop_withdraws_consent_and_falls_back(w):
    cl, oid, _ = w.live()
    w.notifier.sms_results = [SendResult(False, "This person has replied STOP, so no more texts.", opted_out=True)]
    run(w)
    pat = w.api.get("/api/clients").json()[0]["contacts"][0]
    assert pat["sms_consent"] is False and "STOP" in pat["sms_consent_source"]
    assert any(e["to"] == "pat@acme.test" for e in w.notifier.emails)
    n_sms = len(w.notifier.sms)
    run(w, now=NOON_ET + D(days=4))
    assert len(w.notifier.sms) == n_sms  # never texted again


def test_a_failed_round_is_retried_later_but_not_every_pass_and_does_not_use_up_a_reminder(w):
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "email": "p@a.test"}])
    fail = SendResult(False, "The email service refused it (status 500).")
    w.notifier.email_results = [fail, fail]
    s = run(w)
    assert s.failed == 1 and len(w.notifier.emails) == 1
    run(w, now=NOON_ET + D(hours=2))  # inside the retry wait
    assert len(w.notifier.emails) == 1
    run(w, now=NOON_ET + D(hours=7))  # after it
    assert len(w.notifier.emails) == 2
    run(w, now=NOON_ET + D(hours=25))  # 13:00 the next day, after the retry wait and not at night
    assert len(w.notifier.emails) == 3 and w.notifier.emails[-1]["to"] == "p@a.test"  # third attempt succeeded
    sent_rounds = {r.round for r in rows(w, oid) if r.status == "sent"}
    assert len(sent_rounds) == 1  # only the success counts toward the cap


def test_two_runs_at_once_cannot_send_the_same_reminder_twice(w):
    """Both runs read "no reminders yet" and pick round 1. Whichever inserts second is refused by the unique constraint."""
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "email": "p@a.test"}])
    with w.sm() as db:
        ob = db.get(m.Onboarding, oid)
        client, contact = db.get(m.Client, ob.client_id), db.scalars(select(m.Contact).where(m.Contact.client_id == ob.client_id)).first()
        steps = nudges.open_steps(ob, contact, contact)
        args = (db, w.settings, w.notifier, ob, client, contact, steps, 1, NOON_ET, False, False, w.settings.app_url)
        first = nudges._nudge_contact(*args)
        second = nudges._nudge_contact(*args)  # the same round, as the other run would have computed
        db.commit()
    assert first.status == "sent" and second.status == "later" and "Another run" in second.reason
    assert len(w.notifier.emails) == 1


# ---------------------------------------------------------------- giving up

def test_after_the_maximum_number_of_reminders_it_stops_and_flags_it_for_jay(w):
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "email": "p@a.test"}])
    t = NOON_ET
    for _ in range(3):
        assert run(w, now=t).sent == 1
        t += D(days=4)
    assert len(w.notifier.emails) == 3
    s = run(w, now=t)
    assert s.sent == 0 and s.flagged == 1 and len(w.notifier.emails) == 3
    assert w.get(oid).attention == "nudges_exhausted"
    assert run(w, now=t + D(days=4)).sent == 0  # and it stays stopped


def test_when_the_client_comes_back_the_flag_clears(w):
    _, oid, links = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "email": "p@a.test"}])
    t = NOON_ET
    for _ in range(4):
        run(w, now=t)
        t += D(days=4)
    assert w.get(oid).attention == "nudges_exhausted"
    sess = w.api.post("/api/portal/exchange", json={"token": token_in(links["Pat Owner"]["url"])}).json()["session"]
    r = w.api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "Acme"}}}, headers={"Authorization": f"Bearer {sess}"})
    assert r.status_code == 200
    assert w.get(oid).attention is None


def test_manual_reminders_do_not_use_up_the_automatic_ones(w):
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "email": "p@a.test"}])
    for i in range(5):
        with w.sm() as db:
            nudges.remind_now(db, w.settings, w.notifier, db.get(m.Onboarding, oid), now=NOON_ET + D(minutes=i))
            db.commit()
    w.set_activity(oid, WHEN_STALE)
    with w.sm() as db:  # push the manual sends far into the past so the stall timer allows an automatic one
        for n in db.scalars(select(m.Nudge)):
            n.sent_at = WHEN_STALE
        db.commit()
    assert run(w).sent == 1


# ---------------------------------------------------------------- dry run and messages

def test_a_dry_run_says_who_would_be_reminded_and_sends_and_records_nothing(w):
    _, oid, links = w.live()
    s = run(w, dry_run=True)
    assert s.sent == 2 and any("would_send" in d for d in s.details)
    assert not w.notifier.sms and not w.notifier.emails and not rows(w, oid)
    with w.sm() as db:
        assert db.query(m.MagicLink).count() == 2  # no new links were made either


def test_messages_escape_what_a_person_or_template_typed(w):
    s = type("S", (), {"title": '<script>alert(1)</script> & "co"'})()
    c = type("C", (), {"name": "<b>Pat</b> Owner"})()
    msg = nudges.build_message(w.settings, c, [s], "https://onboard.test/c/abc")
    assert "<script>" not in msg["html"] and "&lt;script&gt;" in msg["html"] and "&lt;b&gt;Pat&lt;/b&gt;" in msg["html"]
    assert msg["sms"].endswith("Reply STOP to opt out.") and "https://onboard.test/c/abc" in msg["sms"]
    assert len(msg["sms"]) < 320  # a title can't make a text run on


def test_reminders_never_reveal_what_the_client_answered_or_internal_work(w):
    _, oid, links = w.live()
    sess = w.api.post("/api/portal/exchange", json={"token": token_in(links["Pat Owner"]["url"])}).json()["session"]
    w.api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "TOP-SECRET-NAME"}}}, headers={"Authorization": f"Bearer {sess}"})
    w.set_activity(oid, WHEN_STALE)
    run(w)
    blob = " ".join([b for _, b in w.notifier.sms] + [e["text"] + e["html"] + e["subject"] for e in w.notifier.emails])
    assert "TOP-SECRET-NAME" not in blob and "Build the agent" not in blob and "Create it" not in blob


# ---------------------------------------------------------------- the admin API

def test_send_a_reminder_now_reports_what_happened_per_person(w):
    w.app.state.clock = lambda: NOON_ET  # midday in New York, so texting is allowed
    _, oid, _ = w.live()
    r = w.api.post(f"/api/onboardings/{oid}/nudge")
    assert r.status_code == 200
    by = {x["contact"]: x for x in r.json()["results"]}
    assert by["Pat Owner"]["status"] == "sent" and by["Pat Owner"]["channel"] == "sms"
    assert by["Ivy IT"]["channel"] == "email"
    hist = w.api.get(f"/api/onboardings/{oid}/nudges").json()
    assert {h["contact"] for h in hist} == {"Pat Owner", "Ivy IT"} and all(h["kind"] == "manual" and h["status"] == "sent" for h in hist)


def test_a_manual_reminder_needs_an_active_onboarding_and_reminders_switched_on(w):
    _, draft = w.client_with(name="Draft Co")
    assert w.api.post(f"/api/onboardings/{draft['id']}/nudge").status_code == 409
    _, oid, _ = w.live()
    w.api.post(f"/api/onboardings/{oid}/pause")
    assert w.api.post(f"/api/onboardings/{oid}/nudge").status_code == 409
    off, c = make_world(twilio_account_sid="", twilio_auth_token="", twilio_from_number="", resend_api_key="", resend_from="")
    with c:
        _, o2, _ = off.live()
        r = c.post(f"/api/onboardings/{o2}/nudge")
        assert r.status_code == 409 and "aren't switched on" in r.json()["detail"]


def test_nobody_with_steps_left_says_so(w):
    _, oid, _ = w.live()
    for key in ("basics", "it_access", "approve"):
        w.api.post(f"/api/onboardings/{oid}/steps/{key}/complete")
    r = w.api.post(f"/api/onboardings/{oid}/nudge").json()
    assert r["results"] == [] and "no" in r["message"].lower()


def test_another_org_cannot_remind_or_read_the_history(w):
    import jwt
    from fastapi.testclient import TestClient

    from tests.conftest import JWT_SECRET
    from app import services
    from app.config import Settings
    from app.main import create_app
    from tests.helpers4 import BASE

    app = create_app(Settings(**{**BASE, "auth_disabled": False, "app_env": "production", "supabase_jwt_secret": JWT_SECRET}))
    app.state.notifier = w.notifier
    with app.state.sessionmaker() as db:
        a, b = services.get_or_create_org(db, "A", "a"), services.get_or_create_org(db, "B", "b")
        services.add_member(db, a.id, "user-a")
        services.add_member(db, b.id, "user-b")
        db.commit()
    hdr = lambda u: {"Authorization": "Bearer " + jwt.encode({"sub": u, "aud": "authenticated", "exp": 4102444800}, JWT_SECRET, algorithm="HS256")}  # noqa: E731
    with TestClient(app) as c:
        from tests.helpers4 import DOC

        cl = c.post("/api/clients", json={"name": "A client"}, headers=hdr("user-a")).json()
        c.post(f"/api/clients/{cl['id']}/contacts", json={"name": "P", "role": "owner", "email": "p@a.test"}, headers=hdr("user-a"))
        t = c.post("/api/templates", json=DOC, headers=hdr("user-a")).json()
        ob = c.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=hdr("user-a")).json()
        c.post(f"/api/onboardings/{ob['id']}/send", headers=hdr("user-a"))
        assert c.post(f"/api/onboardings/{ob['id']}/nudge", headers=hdr("user-b")).status_code == 404
        assert c.get(f"/api/onboardings/{ob['id']}/nudges", headers=hdr("user-b")).status_code == 404
        assert c.get(f"/api/onboardings/{ob['id']}/sync", headers=hdr("user-b")).status_code == 404
        assert c.post(f"/api/onboardings/{ob['id']}/sync", headers=hdr("user-b")).status_code == 404
        assert not w.notifier.emails


def test_attention_shows_on_the_onboarding_so_the_list_can_flag_it(w):
    _, oid, _ = w.live(contacts=[{"name": "Pat Owner", "role": "owner", "phone": "5551234567"}])
    run(w)
    assert w.api.get(f"/api/onboardings/{oid}").json()["attention"] == "unreachable"
    assert w.api.get("/api/onboardings").json()[0]["attention"] == "unreachable"


def test_features_endpoint_says_which_parts_are_on(w):
    f = w.api.get("/api/features").json()
    assert f["sms"] and f["email"] and f["reminders"] and f["aios_sync"] and not f["uploads"] and not f["jobs"]


# ---------------------------------------------------------------- client time zone

def test_client_time_zone_defaults_validates_and_can_change(w):
    cl = w.api.post("/api/clients", json={"name": "A"}).json()
    assert cl["timezone"] == "America/New_York"
    assert w.api.post("/api/clients", json={"name": "B", "timezone": "Europe/London"}).json()["timezone"] == "Europe/London"
    assert w.api.post("/api/clients", json={"name": "C", "timezone": "Mars/Base"}).status_code == 422
    assert w.api.patch(f"/api/clients/{cl['id']}", json={"timezone": "America/Chicago"}).json()["timezone"] == "America/Chicago"
    assert w.api.patch(f"/api/clients/{cl['id']}", json={"timezone": "nonsense"}).status_code == 422
