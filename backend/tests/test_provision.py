"""The Voicent-App provisioning hook: when it fires, what it sends and never sends, the signature, retries, and that a
delivery can't go out twice or get lost. A fake Voicent-App sits behind httpx.MockTransport, so the real sender runs."""
import datetime as dt
import json

import httpx
import pytest
from sqlalchemy import select

from app import jobs, models as m, provision
from app.config import Settings
from tests.helpers4 import BASE, DOC, make_world, token_in

URL = "https://voicent-app.test/api/provisioning/onboarding"
SECRET = "s" * 40
PROV_DOC = {**DOC, "name": "Mini with workspace", "slug": "mini-ws", "on_complete": "provision_voicent_workspace"}


class FakeVoicent:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.replies: list = []  # queued: an int status, an httpx.Response, or an exception to raise
        self.during = None  # called while a request is being handled (to start a second delivery mid-send)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.during:
            self.during()
        r = self.replies.pop(0) if self.replies else 200
        if isinstance(r, Exception):
            raise r
        if isinstance(r, httpx.Response):
            return r
        return httpx.Response(r, json={"workspace_id": "ws_123", "status": "created"} if r < 300 else {"detail": "internal detail from the far side"})

    def sender(self, settings) -> provision.Sender:
        return provision.Sender(settings, http=httpx.Client(transport=httpx.MockTransport(self.handler)))

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture()
def w():
    world, client = make_world(voicent_provision_url=URL, voicent_provision_secret=SECRET)
    world.voicent = FakeVoicent()
    world.app.state.provisioner = world.voicent.sender(world.settings)
    with client:
        yield world


def finish(w, oid, last=True):
    """Answer every step as Jay. With last=False the final step is left open."""
    api = w.api
    assert api.put(f"/api/onboardings/{oid}/steps/it_access", json={"data": {"status": "connected", "account_label": "Cloudflare (acme)"}}).status_code == 200
    assert api.put(f"/api/onboardings/{oid}/steps/approve", json={"data": {"decision": "changes_requested", "comment": "Make it warmer please"}}).status_code == 200
    assert api.put(f"/api/onboardings/{oid}/steps/approve", json={"data": {"decision": "approved"}}).status_code == 200
    api.post(f"/api/onboardings/{oid}/steps/approve/comments", json={"body": "A private note about the client", "client_visible": False})
    assert api.post(f"/api/onboardings/{oid}/steps/build/complete").status_code == 200
    if last:
        r = api.put(f"/api/onboardings/{oid}/steps/basics", json={"data": {"answers": {"name": "Acme sk-live-abcdefghijklmnop1234"}}})
        assert r.status_code == 200


def live(w, doc=PROV_DOC, paying=True):
    """A sent onboarding. Its client is a paying customer unless paying=False: a workspace is only asked for once they pay."""
    cl, oid, links = w.live(doc=doc)
    if paying:
        assert w.api.post(f"/api/clients/{cl['id']}/paying", json={"paying": True}).status_code == 200
    w.client_id = cl["id"]
    return oid, links


def state(w, oid) -> m.Onboarding:
    return w.get(oid)


# ---------------------------------------------------------------- settings

def test_off_unless_an_https_url_and_a_long_secret_are_both_set_and_half_set_only_warns():
    assert not Settings().provisioning_enabled
    assert Settings(voicent_provision_url=URL, voicent_provision_secret=SECRET).provisioning_enabled
    for bad in (dict(voicent_provision_url=URL), dict(voicent_provision_secret=SECRET),
                dict(voicent_provision_url="http://voicent-app.test/x", voicent_provision_secret=SECRET),
                dict(voicent_provision_url=URL, voicent_provision_secret="short")):
        s = Settings(**{**BASE, **bad})
        assert not s.provisioning_enabled
        assert any(x.startswith("Voicent provisioning:") for x in s.optional_warnings())
        s.validate()  # never fatal


def test_turned_off_nothing_is_sent_and_the_page_says_so():
    world, client = make_world()
    with client:
        cl, oid, _ = world.live(doc=PROV_DOC)
        client.post(f"/api/clients/{cl['id']}/paying", json={"paying": True})
        finish(world, oid)
        ob = world.get(oid)
        assert ob.status == "completed" and ob.provision_state == "pending"  # it waits, so turning it on later still sends it
        st = client.get(f"/api/onboardings/{oid}/provision").json()
        assert st["state"] == "off" and st["enabled"] is False
        r = client.post(f"/api/onboardings/{oid}/provision").json()
        assert r["result"]["state"] == "off"
        assert client.get("/api/features").json()["provisioning"] is False


# ---------------------------------------------------------------- when it fires

def test_a_template_that_doesnt_ask_for_it_never_sends(w):
    oid, _ = live(w, DOC)
    finish(w, oid)
    assert state(w, oid).status == "completed" and state(w, oid).provision_state is None
    assert not w.voicent.requests
    assert w.api.get(f"/api/onboardings/{oid}/provision").json()["state"] == "not_wanted"
    assert w.api.post(f"/api/onboardings/{oid}/provision").status_code == 409


def test_nothing_goes_until_the_last_step_is_done_then_exactly_one_signed_delivery(w):
    oid, _ = live(w)
    finish(w, oid, last=False)
    assert not w.voicent.requests and state(w, oid).provision_state is None
    assert w.api.get(f"/api/onboardings/{oid}/provision").json()["state"] == "waiting"
    assert w.api.post(f"/api/onboardings/{oid}/provision").status_code == 409  # not finished yet

    w.api.put(f"/api/onboardings/{oid}/steps/basics", json={"data": {"answers": {"name": "Acme"}}})
    assert len(w.voicent.requests) == 1
    req = w.voicent.requests[0]
    assert req.method == "POST" and str(req.url) == URL
    h = req.headers
    assert h["x-voicent-event"] == "workspace.requested" and h["content-type"] == "application/json"
    assert provision.verify(SECRET, h["x-voicent-signature"], h["x-voicent-timestamp"], req.content)
    body = json.loads(req.content)
    assert h["x-voicent-delivery"] == body["delivery_id"] == state(w, oid).provision_delivery_id

    ob = state(w, oid)
    assert ob.provision_state == "delivered" and ob.voicent_workspace_id == "ws_123" and ob.provision_attempts == 1
    st = w.api.get(f"/api/onboardings/{oid}/provision").json()
    assert st["state"] == "delivered" and st["workspace_id"] == "ws_123" and st["log"][0]["status"] == "ok"
    assert w.api.get("/api/onboardings").json()[0]["provision_state"] == "delivered"

    # the timer finds nothing more to do, and finishing again after a reopen doesn't send twice
    assert provision.deliver_due(w.sm, w.settings, w.app.state.provisioner)["delivered"] == 0
    w.api.post(f"/api/onboardings/{oid}/steps/build/reopen")
    w.api.post(f"/api/onboardings/{oid}/steps/build/complete")
    assert state(w, oid).status == "completed" and len(w.voicent.requests) == 1


def test_the_client_finishing_it_in_the_portal_sends_it_too(w):
    oid, links = live(w)
    finish(w, oid, last=False)
    tok = w.api.post("/api/portal/exchange", json={"token": token_in(links["Pat Owner"]["url"])}).json()["session"]
    r = w.api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "Acme"}}}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert len(w.voicent.requests) == 1 and state(w, oid).provision_state == "delivered"


# ---------------------------------------------------------------- what goes out

def test_the_payload_carries_the_tenant_client_contacts_and_answers_but_no_connected_accounts(w):
    oid, _ = live(w)
    finish(w, oid)
    p = w.voicent.bodies()[0]
    assert p["event"] == "workspace.requested" and p["schema_version"] == 2 and p["source"] == "voicent-onboarding"
    with w.sm() as db:
        org = db.get(m.Org, w.get(oid).org_id)
        assert p["org"] == {"id": org.id, "slug": org.slug, "name": org.name}
    assert p["tenant"] == {"voicent_tenant_id": None, "account_type": "direct"}  # an org made by seed has no Voicent tenant
    assert p["client"]["paying_since"].endswith("Z")
    assert p["client"]["name"] == "Acme Plumbing" and p["client"]["timezone"] == "America/New_York"
    assert p["onboarding"]["id"] == oid and p["onboarding"]["template"] == {"slug": "mini-ws", "version": 1, "name": "Mini with workspace"}
    assert p["onboarding"]["url"] == f"https://onboard.test/onboardings/{oid}" and p["onboarding"]["completed_at"].endswith("Z")
    people = {c["name"]: c for c in p["contacts"]}
    assert people["Pat Owner"]["email"] == "pat@acme.test" and people["Pat Owner"]["sms_consent"] is True and people["Pat Owner"]["role"] == "owner"
    assert people["Ivy IT"]["phone"] is None and people["Ivy IT"]["sms_consent"] is False
    assert p["answers"] == {"basics": {"name": {"label": "Name", "type": "text", "value": "Acme [redacted]"}}}
    assert "integrations" not in p and p["files"] == []  # only text answers and files go to Voicent-App


def test_the_payload_never_carries_internal_steps_comments_approval_notes_files_tokens_or_the_secret(w):
    oid, links = live(w)
    finish(w, oid)
    req = w.voicent.requests[0]
    raw = req.content.decode()
    for never in ("build", "Build the agent", "Create it", "Make it warmer", "A private note", "approve", "sk-live-abcdefghijklmnop1234", SECRET,
                  "it_access", "Cloudflare"):
        assert never not in raw, never
    for link in links.values():
        assert token_in(link["url"]) not in raw
    assert SECRET not in json.dumps(dict(req.headers))


def test_the_payload_preview_is_what_would_be_sent(w):
    oid, _ = live(w)
    finish(w, oid, last=False)
    p = w.api.get(f"/api/onboardings/{oid}/provision/payload").json()
    assert p["delivery_id"] == "preview" and p["answers"] == {} and p["files"] == [] and "integrations" not in p


# ---------------------------------------------------------------- the signature

def test_the_signature_rejects_a_changed_body_a_wrong_secret_and_an_old_timestamp():
    body, now = b'{"a":1}', dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc)
    ts = str(int(now.timestamp()))
    sig = provision.sign(SECRET, int(ts), body)
    assert sig.startswith("v1=") and provision.verify(SECRET, sig, ts, body, now=now)
    assert not provision.verify(SECRET, sig, ts, b'{"a":2}', now=now)
    assert not provision.verify("x" * 40, sig, ts, body, now=now)
    assert not provision.verify(SECRET, sig, ts, body, now=now + dt.timedelta(minutes=6))
    assert not provision.verify(SECRET, sig, "not a number", body, now=now)
    assert not provision.verify(SECRET, "", ts, body, now=now)


# ---------------------------------------------------------------- failures and retries

def test_an_outage_is_retried_by_the_timer_with_the_same_delivery_id(w):
    oid, _ = live(w)
    w.voicent.replies = [503, httpx.ConnectError("down")]
    finish(w, oid)
    ob = state(w, oid)
    first_id = ob.provision_delivery_id
    assert ob.provision_state == "pending" and ob.provision_attempts == 1 and "status 503" in ob.provision_error
    assert "internal detail" not in ob.provision_error  # never the other side's words
    when = provision._aware(ob.provision_next_at)
    assert w.api.get(f"/api/onboardings/{oid}/provision").json()["state"] == "pending"

    # not due yet: the timer leaves it alone
    assert provision.deliver_due(w.sm, w.settings, w.app.state.provisioner, now=when - dt.timedelta(seconds=1))["delivered"] == 0
    assert len(w.voicent.requests) == 1
    # due: a connection error is retried again later
    out = jobs.run_once(w.sm, w.settings, w.notifier, w.app.state.aios, now=when, provisioner=w.app.state.provisioner)
    assert out["provisioning"] == {"enabled": True, "delivered": 0, "failed": 1}
    ob = state(w, oid)
    assert ob.provision_attempts == 2 and provision._aware(ob.provision_next_at) == when + provision.RETRY_AFTER[1]
    assert "didn't answer." in ob.provision_error
    # and then it goes through
    out = provision.deliver_due(w.sm, w.settings, w.app.state.provisioner, now=when + provision.RETRY_AFTER[1])
    assert out["delivered"] == 1
    assert {r.headers["x-voicent-delivery"] for r in w.voicent.requests} == {first_id}
    assert state(w, oid).provision_state == "delivered"


def test_it_gives_up_after_the_last_try_and_jay_can_send_it_again(w):
    oid, _ = live(w)
    w.voicent.replies = [500] * provision.MAX_ATTEMPTS
    finish(w, oid)
    for _ in range(provision.MAX_ATTEMPTS - 1):
        provision.deliver(w.sm, w.settings, w.get(oid).org_id, oid, w.app.state.provisioner, now=provision._aware(state(w, oid).provision_next_at))
    ob = state(w, oid)
    assert ob.provision_state == "failed" and ob.provision_attempts == provision.MAX_ATTEMPTS and "Gave up after 6 tries" in ob.provision_error
    assert w.api.get("/api/onboardings").json()[0]["provision_state"] == "failed"
    old = ob.provision_delivery_id
    r = w.api.post(f"/api/onboardings/{oid}/provision").json()
    assert r["result"]["state"] == "delivered" and r["state"] == "delivered" and r["workspace_id"] == "ws_123"
    assert w.voicent.requests[-1].headers["x-voicent-delivery"] != old  # a new delivery, so the receiver doesn't drop it


def test_a_refusal_is_not_retried_by_itself(w):
    oid, _ = live(w)
    w.voicent.replies = [422]
    finish(w, oid)
    ob = state(w, oid)
    assert ob.provision_state == "failed" and "refused it (status 422)" in ob.provision_error and ob.provision_next_at is None
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)
    assert provision.deliver_due(w.sm, w.settings, w.app.state.provisioner, now=later)["delivered"] == 0
    assert len(w.voicent.requests) == 1
    st = w.api.get(f"/api/onboardings/{oid}/provision").json()
    assert st["state"] == "failed" and st["log"][0]["status"] == "failed"


def test_two_runs_at_once_send_it_only_once(w):
    oid, _ = live(w)
    org_id = None
    seen = []

    def second_run():
        if not seen:  # while the first request is in flight, the timer fires too
            seen.append(provision.deliver(w.sm, w.settings, org_id, oid, w.app.state.provisioner))

    finish(w, oid, last=False)
    org_id = w.get(oid).org_id
    w.voicent.during = second_run
    w.api.put(f"/api/onboardings/{oid}/steps/basics", json={"data": {"answers": {"name": "Acme"}}})
    assert seen and seen[0].state == "skipped"
    assert len(w.voicent.requests) == 1 and state(w, oid).provision_state == "delivered"


def test_a_crash_mid_send_is_retried_after_the_lease(w):
    oid, _ = live(w)
    w.voicent.replies = [RuntimeError("process died")]  # not an httpx error: stands in for anything unexpected
    finish(w, oid)
    ob = state(w, oid)
    assert ob.provision_state == "pending" and ob.provision_attempts == 1
    lease_end = provision._aware(ob.provision_next_at)
    assert provision.deliver_due(w.sm, w.settings, w.app.state.provisioner, now=lease_end - dt.timedelta(seconds=1))["delivered"] == 0
    assert provision.deliver_due(w.sm, w.settings, w.app.state.provisioner, now=lease_end)["delivered"] == 1


def test_an_unsafe_workspace_id_in_the_reply_is_ignored(w):
    oid, _ = live(w)
    w.voicent.replies = [httpx.Response(201, json={"workspace_id": "<script>alert(1)</script>"})]
    finish(w, oid)
    ob = state(w, oid)
    assert ob.provision_state == "delivered" and ob.voicent_workspace_id is None


def test_another_orgs_onboarding_is_not_found(w):
    oid, _ = live(w)
    with w.sm() as db:
        other = m.Org(name="Other", slug="other")
        db.add(other)
        db.flush()
        db.get(m.Onboarding, oid).org_id = other.id
        db.commit()
    for method, path in (("GET", "/provision"), ("GET", "/provision/payload"), ("POST", "/provision")):
        assert w.api.request(method, f"/api/onboardings/{oid}{path}").status_code == 404
    assert provision.deliver(w.sm, w.settings, "not-the-org", oid, w.app.state.provisioner, manual=True).state == "skipped"
    with w.sm() as db:
        assert db.scalars(select(m.SyncLog).where(m.SyncLog.target == "voicent")).first() is None


def test_the_signature_is_hmac_sha256_over_timestamp_dot_body_as_the_contract_says():
    """Pinned independently of provision.sign, so the receiver's copy of the contract can't drift from what is sent."""
    import hashlib
    import hmac

    body = b'{"event":"onboarding.completed"}'
    expected = hmac.new(SECRET.encode(), b"1763553600." + body, hashlib.sha256).hexdigest()
    assert provision.sign(SECRET, 1763553600, body) == f"v1={expected}"


def test_text_is_redacted_again_on_the_way_out(w):
    """An answer stored before a redaction pattern existed still never leaves in the clear."""
    oid, _ = live(w)
    finish(w, oid, last=False)
    with w.sm() as db:
        step = db.scalar(select(m.Step).where(m.Step.onboarding_id == oid, m.Step.key == "basics"))
        step.responses.append(m.Response(org_id=step.org_id, revision=1, data={"answers": {"name": "key ghp_" + "a" * 36}}, submitted_by="contact:x"))
        db.commit()
    p = w.api.get(f"/api/onboardings/{oid}/provision/payload").json()
    assert p["answers"]["basics"]["name"]["value"] == "key [redacted]"


# ---------------------------------------------------------------- only for a paying client

def test_a_client_who_finishes_but_hasnt_paid_is_not_sent_until_marked_paying(w):
    oid, _ = live(w, paying=False)
    finish(w, oid)
    assert state(w, oid).status == "completed" and state(w, oid).provision_state is None and not w.voicent.requests
    st = w.api.get(f"/api/onboardings/{oid}/provision").json()
    assert st["state"] == "unpaid" and st["paying"] is False and st["client_id"] == w.client_id
    r = w.api.post(f"/api/onboardings/{oid}/provision")
    assert r.status_code == 409 and "paying customer" in r.json()["detail"]
    assert provision.deliver_due(w.sm, w.settings, w.app.state.provisioner)["delivered"] == 0

    out = w.api.post(f"/api/clients/{w.client_id}/paying", json={"paying": True}).json()
    assert out["paying_since"] is not None
    assert len(w.voicent.requests) == 1 and state(w, oid).provision_state == "delivered"
    # marking them paying again changes nothing and sends nothing more
    w.api.post(f"/api/clients/{w.client_id}/paying", json={"paying": True})
    assert len(w.voicent.requests) == 1


def test_unmarking_paying_cancels_a_request_still_waiting_but_not_one_already_accepted(w):
    oid, _ = live(w)
    w.voicent.replies = [503]
    finish(w, oid)
    assert state(w, oid).provision_state == "pending"
    w.api.post(f"/api/clients/{w.client_id}/paying", json={"paying": False})
    assert state(w, oid).provision_state is None
    assert w.api.get(f"/api/onboardings/{oid}/provision").json()["state"] == "unpaid"
    assert provision.deliver_due(w.sm, w.settings, w.app.state.provisioner, now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2))["delivered"] == 0

    w.api.post(f"/api/clients/{w.client_id}/paying", json={"paying": True})
    assert state(w, oid).provision_state == "delivered"
    w.api.post(f"/api/clients/{w.client_id}/paying", json={"paying": False})
    assert state(w, oid).provision_state == "delivered" and state(w, oid).voicent_workspace_id == "ws_123"


def test_another_org_cannot_mark_a_client_paying(w):
    from app import services
    from app.errors import NotFound

    _, oid, _ = w.live(doc=PROV_DOC)
    with w.sm() as db:
        other = m.Org(name="Other", slug="other")
        db.add(other)
        db.flush()
        cid = db.get(m.Onboarding, oid).client_id
        with pytest.raises(NotFound):
            services.set_client_paying(db, other.id, cid, True, dt.datetime.now(dt.timezone.utc))
        assert db.get(m.Client, cid).paying_since is None


# ---------------------------------------------------------------- files, as short-lived links

UPLOAD_DOC = {**PROV_DOC, "slug": "mini-ws-files", "steps": PROV_DOC["steps"] + [
    {"key": "logo", "type": "upload", "title": "Your logo", "config": {"accept": ["png", "pdf"]}}]}


class FakeStorage:
    def __init__(self, fail=False):
        self.fail, self.signed = fail, []

    def info(self, path):
        return {"size": 2048}

    def signed_download(self, path, ttl=600):
        from app.storage import StorageError
        if self.fail:
            raise StorageError("no")
        self.signed.append((path, ttl))
        return f"https://store.test/sign/{path}?ttl={ttl}"


def add_file(w, oid, key, name):
    with w.sm() as db:
        step = next(s for s in db.get(m.Onboarding, oid).steps if s.key == key)
        f = m.File(org_id=step.org_id, step_id=step.id, storage_path=f"{step.org_id}/{oid}/{step.id}/{name}", name=name, size=2048, content_type="image/png")
        db.add(f)
        db.commit()
        return f.id


def test_the_files_the_client_uploaded_go_as_links_that_expire(w):
    w.app.state.storage = FakeStorage()
    oid, _ = live(w, UPLOAD_DOC)
    old = add_file(w, oid, "logo", "draft.png")
    keep = add_file(w, oid, "logo", "logo.png")
    assert w.api.put(f"/api/onboardings/{oid}/steps/logo", json={"data": {"file_ids": [old]}}).status_code == 200
    assert w.api.put(f"/api/onboardings/{oid}/steps/logo", json={"data": {"file_ids": [keep]}}).status_code == 200
    finish(w, oid)
    p = w.voicent.bodies()[0]
    assert p["files"] == [{
        "step_key": "logo", "step_title": "Your logo", "id": keep, "name": "logo.png", "content_type": "image/png", "size": 2048,
        "url": f"https://store.test/sign/{w.get(oid).org_id}/{oid}/{next(s.id for s in w.get(oid).steps if s.key == 'logo')}/logo.png?ttl=3600",
        "url_expires_at": p["files"][0]["url_expires_at"],
    }]  # only the file in the accepted answer, not an earlier attempt
    assert p["files"][0]["url_expires_at"].endswith("Z")
    # the preview never hands out a working link
    preview = w.api.get(f"/api/onboardings/{oid}/provision/payload").json()
    assert preview["files"][0]["url"] is None and len(w.app.state.storage.signed) == 1


def test_if_file_links_cant_be_made_the_request_waits_and_is_tried_again(w):
    w.app.state.storage = FakeStorage(fail=True)
    oid, _ = live(w, UPLOAD_DOC)
    fid = add_file(w, oid, "logo", "logo.png")
    w.app.state.storage.fail = False
    w.api.put(f"/api/onboardings/{oid}/steps/logo", json={"data": {"file_ids": [fid]}})
    w.app.state.storage.fail = True
    finish(w, oid)
    ob = state(w, oid)
    assert not w.voicent.requests and ob.provision_state == "pending" and "file links" in ob.provision_error
    w.app.state.storage.fail = False
    r = provision.deliver(w.sm, w.settings, ob.org_id, oid, w.app.state.provisioner, manual=True, storage=w.app.state.storage)
    assert r.state == "delivered" and w.voicent.bodies()[0]["files"][0]["url"].startswith("https://store.test/")


def test_send_it_now_waits_for_a_send_already_in_flight_rather_than_sending_alongside_it(w):
    oid, _ = live(w)
    org_id = None
    seen = []

    def jay_clicks_send_now():
        if not seen:  # while the first request is in flight, Jay asks for it now (which also resets the retry time)
            with w.sm() as db:
                provision.request_again(db.get(m.Onboarding, oid), dt.datetime.now(dt.timezone.utc))
                db.commit()
            seen.append(provision.deliver(w.sm, w.settings, org_id, oid, w.app.state.provisioner, manual=True))

    finish(w, oid, last=False)
    org_id = w.get(oid).org_id
    w.voicent.during = jay_clicks_send_now
    w.api.put(f"/api/onboardings/{oid}/steps/basics", json={"data": {"answers": {"name": "Acme"}}})
    assert seen and seen[0].state == "skipped" and "right now" in seen[0].message
    ob = state(w, oid)
    assert len(w.voicent.requests) == 1 and ob.provision_state == "delivered" and ob.provision_lease_until is None


def test_send_it_now_still_skips_the_wait_for_a_retry(w):
    oid, _ = live(w)
    w.voicent.replies = [500]
    finish(w, oid)
    ob = state(w, oid)
    assert ob.provision_state == "pending" and ob.provision_lease_until is None  # the failed try reported back
    r = w.api.post(f"/api/onboardings/{oid}/provision").json()
    assert r["result"]["state"] == "delivered" and len(w.voicent.requests) == 2


def test_finishing_again_after_a_delivery_failed_for_good_does_not_start_it_over(w):
    oid, _ = live(w)
    w.voicent.replies = [422]
    finish(w, oid)
    ob = state(w, oid)
    assert ob.provision_state == "failed"
    old = ob.provision_delivery_id
    assert w.api.post(f"/api/onboardings/{oid}/steps/basics/reopen").status_code == 200
    assert w.api.put(f"/api/onboardings/{oid}/steps/basics", json={"data": {"answers": {"name": "Acme"}}}).status_code == 200
    ob = state(w, oid)
    assert w.get(oid).status == "completed"
    assert ob.provision_state == "failed" and ob.provision_delivery_id == old and "refused it (status 422)" in ob.provision_error
    assert len(w.voicent.requests) == 1  # only Jay's "send it again" starts it over
