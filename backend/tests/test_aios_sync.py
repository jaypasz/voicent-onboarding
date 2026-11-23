"""The AIOS sync: what it creates, what it never sends, and that a failure can't make duplicates or lose a change."""
import httpx
import pytest
from sqlalchemy import select, update

from app import aios_sync, models as m
from app.aios import AiosClient, AiosError
from tests.helpers4 import AIOS_TOKEN, WHEN_STALE, make_world, token_in


@pytest.fixture()
def w():
    world, client = make_world()
    with client:
        yield world


def sync(w, oid=None, org=None):
    ob = w.get(oid)
    return aios_sync.sync_onboarding(w.sm, w.settings, ob.org_id, oid, w.app.state.aios)


def session_for(w, links, who="Pat Owner"):
    tok = w.api.post("/api/portal/exchange", json={"token": token_in(links[who]["url"])}).json()["session"]
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------- what gets created

def test_a_draft_is_not_synced_and_sending_creates_the_project_and_tasks_by_itself(w):
    _, ob = w.client_with()
    assert sync(w, ob["id"]).state == "skipped" and not w.aios.requests
    w.api.post(f"/api/onboardings/{ob['id']}/send")  # the background task runs after the response
    pid = f"onb-{ob['id']}"
    assert pid in w.aios.projects and w.aios.projects[pid]["name"] == "Onboarding: Acme Plumbing" and w.aios.projects[pid]["status"] == "active"
    assert len(w.aios.tasks) == 4
    by_title = {t["title"]: t for t in w.aios.tasks.values()}
    assert "Waiting on client: Company basics" in by_title and "Waiting on client: Grant IT access" in by_title
    assert "Build the agent" in by_title and not by_title["Build the agent"]["title"].startswith("Waiting")  # Jay's own task
    build = by_title["Build the agent"]
    assert "Create it" in build["notes"] and "Test it" in build["notes"]
    assert all(t["project_id"] == pid and t["track"] == "other" for t in w.aios.tasks.values())
    assert all(t["link"] == f"https://onboard.test/onboardings/{ob['id']}#step-{k}" for t, k in zip(sorted(w.aios.tasks.values(), key=lambda t: t["id"]), ("basics", "it_access", "approve", "build")))
    assert by_title["Waiting on client: Company basics"]["date"] and by_title["Waiting on client: Company basics"]["notes"].endswith("For: Pat Owner")
    st = w.api.get(f"/api/onboardings/{ob['id']}/sync").json()
    assert st["state"] == "synced" and st["project_id"] == pid


def test_syncing_again_changes_nothing(w):
    _, oid, _ = w.live()
    w.aios.requests.clear()
    r = sync(w, oid)
    assert r.ok and r.changes == 0 and not w.aios.calls("POST", r".*") and not w.aios.calls("PATCH", r".*")
    assert len(w.aios.tasks) == 4 and len(w.aios.projects) == 1


def test_the_requests_carry_the_token_as_a_header_and_never_in_a_body_or_url(w):
    _, oid, _ = w.live()
    assert AIOS_TOKEN not in w.aios.sent_text


def test_step_changes_flow_through_and_waiting_on_client_goes_away_when_done(w):
    _, oid, _ = w.live()
    tid = lambda k: w.get(oid).steps[[s.key for s in w.get(oid).steps].index(k)].aios_task_id  # noqa: E731
    w.api.put(f"/api/onboardings/{oid}/steps/approve", json={"data": {"decision": "changes_requested", "comment": "Warmer"}})
    assert w.aios.tasks[tid("approve")]["status"] == "doing"
    w.api.post(f"/api/onboardings/{oid}/steps/basics/complete")
    t = w.aios.tasks[tid("basics")]
    assert t["status"] == "done" and t["title"] == "Company basics"  # no longer "Waiting on client"
    w.api.post(f"/api/onboardings/{oid}/steps/it_access/skip")
    t = w.aios.tasks[tid("it_access")]
    assert t["status"] == "done" and "Skipped." in t["notes"]
    w.api.post(f"/api/onboardings/{oid}/steps/basics/reopen")
    assert w.aios.tasks[tid("basics")]["status"] == "todo" and w.aios.tasks[tid("basics")]["title"].startswith("Waiting on client")


def test_the_project_follows_the_onboarding_status(w):
    _, oid, _ = w.live()
    pid = f"onb-{oid}"
    w.api.post(f"/api/onboardings/{oid}/pause")
    assert w.aios.projects[pid]["status"] == "paused"
    w.api.post(f"/api/onboardings/{oid}/resume")
    assert w.aios.projects[pid]["status"] == "active"
    for key in ("basics", "it_access", "approve", "build"):
        w.api.post(f"/api/onboardings/{oid}/steps/{key}/complete")
    assert w.aios.projects[pid]["status"] == "done" and all(t["status"] == "done" for t in w.aios.tasks.values())


# ---------------------------------------------------------------- what is said about the client, and what never is

def test_a_client_action_adds_a_one_line_comment_and_never_their_answers(w):
    _, oid, links = w.live()
    h = session_for(w, links)
    w.api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "TOP-SECRET-COMPANY"}}}, headers=h)
    w.api.put("/api/portal/steps/approve", json={"data": {"decision": "changes_requested", "comment": "Please make it warmer"}}, headers=h)
    ids = {s.key: s.aios_task_id for s in w.get(oid).steps}
    assert w.aios.comments[ids["basics"]] == ["Client filled this in."]
    assert w.aios.comments[ids["approve"]] == ['Client asked for changes: "Please make it warmer"']
    assert "TOP-SECRET-COMPANY" not in w.aios.sent_text


def test_comments_are_redacted_and_not_repeated(w):
    _, oid, links = w.live()
    h = session_for(w, links, "Ivy IT")
    fake = "ghp" + "_" + "a" * 36
    w.api.put("/api/portal/steps/it_access", json={"data": {"status": "connected", "account_label": f"acct {fake}"}}, headers=h)
    tid = {s.key: s.aios_task_id for s in w.get(oid).steps}["it_access"]
    assert len(w.aios.comments[tid]) == 1 and fake not in w.aios.comments[tid][0] and "[redacted]" in w.aios.comments[tid][0]
    sync(w, oid)
    sync(w, oid)
    assert len(w.aios.comments[tid]) == 1  # not posted again


def test_something_jay_did_is_not_announced_back_to_jay(w):
    _, oid, _ = w.live()
    w.api.put(f"/api/onboardings/{oid}/steps/build", json={"data": {"note": "built"}})
    assert not w.aios.comments


def test_no_answer_file_or_link_token_ever_leaves(w):
    _, oid, links = w.live()
    h = session_for(w, links)
    w.api.put("/api/portal/steps/basics", json={"data": {"answers": {"name": "ANSWER-NEEDLE"}}}, headers=h)
    w.api.post("/api/portal/steps/approve/comments", json={"body": "COMMENT-NEEDLE"}, headers=h)
    w.api.post(f"/api/onboardings/{oid}/steps/basics/comments", json={"body": "ADMIN-NEEDLE", "client_visible": False})
    blob = w.aios.sent_text
    for needle in ("ANSWER-NEEDLE", "COMMENT-NEEDLE", "ADMIN-NEEDLE", token_in(links["Pat Owner"]["url"]), "pat@acme.test", "555"):
        assert needle not in blob, needle


# ---------------------------------------------------------------- failures

def test_a_failure_part_way_keeps_what_was_done_and_the_retry_creates_no_duplicates(w):
    _, ob = w.client_with()
    calls = {"n": 0}

    def fail_third_task(req, body):
        if req.method == "POST" and req.url.path == "/api/tasks":
            calls["n"] += 1
            if calls["n"] == 3:
                return httpx.Response(500, json={"detail": "internal error SECRET"})

    w.aios.hooks.append(fail_third_task)
    w.api.post(f"/api/onboardings/{ob['id']}/send")
    assert len(w.aios.tasks) == 2  # the first two were made
    steps = w.get(ob["id"]).steps
    assert [bool(s.aios_task_id) for s in steps] == [True, True, False, False]
    st = w.api.get(f"/api/onboardings/{ob['id']}/sync").json()
    assert st["state"] == "failing" and "status 500" in st["log"][0]["detail"] and "SECRET" not in st["log"][0]["detail"]
    w.aios.hooks.clear()
    r = sync(w, ob["id"])
    assert r.ok and len(w.aios.tasks) == 4 and len({t["link"] for t in w.aios.tasks.values()}) == 4  # no duplicates
    assert w.api.get(f"/api/onboardings/{ob['id']}/sync").json()["state"] == "synced"


def test_a_lost_reply_is_recovered_by_link_not_duplicated(w):
    """AIOS made the task but the answer never arrived. The next pass finds it by its link."""
    _, ob = w.client_with()
    state = {"lost": False}

    def lose_one_reply(req, body):
        if req.method == "POST" and req.url.path == "/api/tasks" and not state["lost"]:
            state["lost"] = True
            w.aios._n += 1
            t = {"id": f"t{w.aios._n}", **body}
            w.aios.tasks[t["id"]] = t  # it was created...
            raise httpx.ReadTimeout("reply lost")  # ...but we never heard

    w.aios.hooks.append(lose_one_reply)
    w.api.post(f"/api/onboardings/{ob['id']}/send")
    assert len(w.aios.calls("POST", "/api/tasks")) == 1  # creation is attempted once, never blindly retried
    w.aios.hooks.clear()
    r = sync(w, ob["id"])
    assert r.ok and len(w.aios.tasks) == 4 and len({t["link"] for t in w.aios.tasks.values()}) == 4
    first = w.get(ob["id"]).steps[0]
    assert first.aios_task_id == "t1"  # adopted, not recreated


def test_the_same_failure_is_not_logged_every_pass(w):
    _, ob = w.client_with()
    w.aios.hooks.append(lambda req, body: httpx.Response(502, json={}))
    w.api.post(f"/api/onboardings/{ob['id']}/send")
    for _ in range(3):
        sync(w, ob["id"])
    with w.sm() as db:
        assert db.query(m.SyncLog).filter_by(onboarding_id=ob["id"], status="failed").count() == 1


def test_a_sync_problem_never_reaches_the_person_who_clicked(w):
    _, ob = w.client_with()
    w.aios.hooks.append(lambda req, body: (_ for _ in ()).throw(RuntimeError("something odd")))
    r = w.api.post(f"/api/onboardings/{ob['id']}/send")
    assert r.status_code == 200 and r.json()["status"] == "active"  # the send itself worked
    assert sync(w, ob["id"]).state == "failed"


def test_a_change_that_lands_during_a_sync_is_not_lost(w):
    _, oid, _ = w.live()
    ob0 = w.get(oid)

    def change_midway(req, body):
        if req.method == "PATCH" and not getattr(change_midway, "done", False):
            change_midway.done = True
            with w.sm() as db:  # someone completes a step while the sync is talking to AIOS
                db.execute(update(m.Onboarding).where(m.Onboarding.id == oid).values(sync_version=m.Onboarding.sync_version + 1))
                db.commit()

    w.api.post(f"/api/onboardings/{oid}/steps/basics/complete")
    before = w.get(oid)
    w.aios.hooks.append(change_midway)
    w.api.post(f"/api/onboardings/{oid}/steps/it_access/complete")
    after = w.get(oid)
    assert after.synced_version < after.sync_version  # still dirty: the next pass will pick up the late change
    w.aios.hooks.clear()
    assert sync(w, oid).ok
    final = w.get(oid)
    assert final.synced_version == final.sync_version and before and ob0


# ---------------------------------------------------------------- the client

def make_client(handler, sleeps):
    from app.config import Settings
    from tests.helpers4 import BASE

    return AiosClient(Settings(**BASE), http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)


def test_reads_and_updates_are_retried_with_backoff_but_creating_is_not():
    sleeps, seen = [], []

    def handler(req):
        seen.append((req.method, req.url.path))
        return httpx.Response(503, json={})

    c = make_client(handler, sleeps)
    with pytest.raises(AiosError) as e:
        c.list_tasks("p")
    assert len(seen) == 3 and sleeps == [0.5, 1.5] and e.value.status == 503 and "status 503" in e.value.message
    seen.clear()
    with pytest.raises(AiosError):
        c.patch_task("t1", {"status": "done"})
    assert len(seen) == 3
    seen.clear()
    for call in (lambda: c.create_task({"title": "x"}), lambda: c.add_comment("t1", "x")):
        with pytest.raises(AiosError):
            call()
    assert len(seen) == 2  # one attempt each


def test_a_refusal_is_not_retried_and_a_timeout_is():
    sleeps, seen = [], []

    def refuse(req):
        seen.append(1)
        return httpx.Response(403, json={"detail": "SECRET OTHER SIDE TEXT"})

    with pytest.raises(AiosError) as e:
        make_client(refuse, sleeps).patch_project("p", {})
    assert len(seen) == 1 and not sleeps and e.value.status == 403 and "SECRET" not in e.value.message
    n = {"i": 0}

    def flaky(req):
        n["i"] += 1
        if n["i"] < 3:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json=[])

    assert make_client(flaky, []).list_tasks("p") == [] and n["i"] == 3


def test_an_existing_project_is_fine():
    c = make_client(lambda req: httpx.Response(409, json={}), [])
    assert c.create_project({"id": "onb-x"}) is False


# ---------------------------------------------------------------- the periodic pass and the admin button

def test_the_periodic_pass_picks_up_only_what_changed_and_skips_drafts(w):
    _, oid, _ = w.live()
    _, draft = w.client_with(name="Draft Co")
    w.aios.requests.clear()
    assert aios_sync.sync_dirty(w.sm, w.settings, w.app.state.aios) == {"enabled": True, "synced": 0, "failed": 0}
    with w.sm() as db:  # a change that the background task missed (say the service restarted)
        db.execute(update(m.Onboarding).where(m.Onboarding.id == oid).values(sync_version=m.Onboarding.sync_version + 1))
        db.commit()
    assert aios_sync.sync_dirty(w.sm, w.settings, w.app.state.aios)["synced"] == 1
    assert not any(draft["id"] in str(r) for r in w.aios.requests)


def test_sync_now_reports_how_it_went_and_the_state(w):
    _, oid, _ = w.live()
    r = w.api.post(f"/api/onboardings/{oid}/sync").json()
    assert r["result"]["ok"] and r["state"] == "synced" and r["enabled"] and r["project_id"] == f"onb-{oid}"
    w.aios.hooks.append(lambda req, body: httpx.Response(500, json={}))
    w.api.post(f"/api/onboardings/{oid}/steps/basics/complete")
    r = w.api.post(f"/api/onboardings/{oid}/sync").json()
    assert not r["result"]["ok"] and r["state"] == "failing" and "status 500" in r["result"]["message"]


def test_with_sync_off_nothing_is_called_and_it_says_so():
    world, client = make_world(aios_api_url="", aios_service_token="")
    with client:
        _, oid, _ = world.live()
        assert not world.aios.requests
        r = client.get(f"/api/onboardings/{oid}/sync").json()
        assert r["enabled"] is False and r["state"] == "off"
        assert aios_sync.sync_onboarding(world.sm, world.settings, world.get(oid).org_id, oid).state == "off"
        assert aios_sync.sync_dirty(world.sm, world.settings)["enabled"] is False


def test_another_org_cannot_sync_an_onboarding_it_does_not_own(w):
    _, oid, _ = w.live()
    r = aios_sync.sync_onboarding(w.sm, w.settings, "some-other-org", oid, w.app.state.aios)
    assert not r.ok and r.message == "Onboarding not found."


def test_every_change_bumps_the_version(w):
    _, oid, _ = w.live()
    v = w.get(oid).sync_version
    for call in (lambda: w.api.post(f"/api/onboardings/{oid}/steps/basics/complete"), lambda: w.api.post(f"/api/onboardings/{oid}/pause")):
        call()
        assert w.get(oid).sync_version > v
        v = w.get(oid).sync_version


# ---------------------------------------------------------------- the commit must come before the background task

def test_the_background_sync_sees_the_change_that_triggered_it(tmp_path):
    """On a real database (separate connections, as in production) the sync runs after the response. If the request's
    changes weren't committed by then, it would read a draft and quietly do nothing. The in-memory test database can't
    show this, because all its sessions share one connection."""
    world, client = make_world(database_url=f"sqlite:///{tmp_path / 'real.db'}")
    with client:
        _, ob = world.client_with()
        r = client.post(f"/api/onboardings/{ob['id']}/send")
        assert r.status_code == 200
        assert f"onb-{ob['id']}" in world.aios.projects  # created by the background task, with no explicit sync call
        assert len(world.aios.tasks) == 4
        client.post(f"/api/onboardings/{ob['id']}/steps/basics/complete")
        done = [t for t in world.aios.tasks.values() if t["title"] == "Company basics"][0]
        assert done["status"] == "done"


# ---------------------------------------------------------------- editing after sending

def test_a_renamed_step_updates_its_task_and_a_removed_step_closes_its_task_and_a_new_one_gets_a_task(w):
    _, oid, _ = w.live()
    doc = w.api.get(f"/api/onboardings/{oid}/document").json()
    steps = [dict(s) for s in doc["document"]["steps"]]
    steps = [s for s in steps if s["key"] != "it_access"]  # removed (no answers on it yet)
    for s in steps:
        if s["key"] == "basics":
            s["title"] = "Business details"
    steps.append({"key": "logo", "type": "upload", "title": "Your logo", "config": {"accept": ["png"]}})
    assert w.api.put(f"/api/onboardings/{oid}/document", json={"steps": steps}).status_code == 200
    sync(w, oid)
    titles = sorted(t["title"] for t in w.aios.tasks.values())
    assert "Waiting on client: Business details" in titles and "Waiting on client: Your logo" in titles
    assert not any(t == "Waiting on client: Company basics" for t in titles)
    removed = [t for t in w.aios.tasks.values() if t["title"].startswith("(Removed from the onboarding)")]
    assert len(removed) == 1 and removed[0]["status"] == "done"
    n = len(w.aios.tasks)
    w.aios.requests.clear()
    assert sync(w, oid).changes == 0 and len(w.aios.tasks) == n and not w.aios.calls("PATCH", r".*")  # settled: nothing repeats


# ---------------------------------------------------------------- stages

FORM = {"fields": [{"key": "name", "label": "Name", "type": "text", "required": True}]}
STAGED = {
    "name": "Staged", "slug": "staged", "layout": "checklist",
    "sections": [{"key": "discover", "title": "Discovery"}, {"key": "build", "title": "Build"}, {"key": "launch", "title": "Launch", "signoff": False}],
    "steps": [
        {"key": "about", "type": "form", "title": "About you", "section": "discover", "assignee_role": "owner", "config": FORM},
        {"key": "assets", "type": "form", "title": "Your assets", "section": "build", "assignee_role": "owner", "config": FORM},
        {"key": "setup", "type": "task", "title": "Set up the account", "section": "build", "config": {"audience": "team"}},
        {"key": "golive", "type": "form", "title": "Go-live day", "section": "launch", "assignee_role": "owner", "config": FORM},
    ],
}


def titles(w):
    return {t["link"].rsplit("#", 1)[1]: t for t in w.aios.tasks.values()}


def test_stages_name_each_task_and_each_sign_off_is_its_own_task(w):
    _, oid, _ = w.live(doc=STAGED)
    t = titles(w)
    assert t["step-about"]["title"] == "[Discovery] Waiting on client: About you"
    assert t["step-assets"]["title"] == "[Build] Your assets"  # not open to the client yet, so not waiting on them
    assert "waits for “Discovery” to be signed off" in t["step-assets"]["notes"]
    assert t["step-setup"]["title"] == "[Build] Set up the account" and "Not open" not in t["step-setup"]["notes"]
    assert t["stage-discover"]["title"] == "Sign off: Discovery" and t["stage-discover"]["status"] == "todo"
    assert t["stage-build"]["title"] == "Sign off: Build"
    assert "stage-launch" not in t  # needs no sign-off
    assert all(x["project_id"] == f"onb-{oid}" for x in t.values())
    w.aios.requests.clear()
    assert sync(w, oid).changes == 0 and not w.aios.calls("PATCH", r".*") and not w.aios.calls("POST", r".*")


def test_a_sign_off_closes_its_task_and_opens_the_next_stage_and_withdrawing_reopens_it(w):
    _, oid, _ = w.live(doc=STAGED)
    w.api.post(f"/api/onboardings/{oid}/steps/about/complete")
    assert titles(w)["stage-discover"]["title"] == "Ready to sign off: Discovery"
    assert w.api.post(f"/api/onboardings/{oid}/stages/discover/signoff").status_code == 200
    t = titles(w)
    assert t["stage-discover"]["status"] == "done" and "Signed off by" in t["stage-discover"]["notes"]
    assert t["step-assets"]["title"] == "[Build] Waiting on client: Your assets" and "Not open" not in t["step-assets"]["notes"]
    assert w.api.delete(f"/api/onboardings/{oid}/stages/discover/signoff").status_code == 200
    t = titles(w)
    assert t["stage-discover"]["status"] == "todo" and t["step-assets"]["title"] == "[Build] Your assets"
    assert len(w.aios.tasks) == 6  # nothing was made twice


def test_a_stage_that_no_longer_needs_a_sign_off_closes_its_task(w):
    _, oid, _ = w.live(doc=STAGED)
    doc = w.api.get(f"/api/onboardings/{oid}/document").json()
    sections = [{**s, "signoff": False} if s["key"] == "build" else s for s in doc["document"]["sections"]]
    r = w.api.put(f"/api/onboardings/{oid}/document", json={"sections": sections, "steps": doc["document"]["steps"], "etag": doc["etag"]})
    assert r.status_code == 200, r.text
    sync(w, oid)  # a document edit is picked up by the timer's pass
    t = titles(w)["stage-build"]
    assert t["status"] == "done" and t["title"].startswith("(No longer needs a sign-off)")


def test_a_lost_reply_to_creating_a_sign_off_task_is_found_by_its_link(w):
    _, oid, _ = w.live(doc=STAGED)
    with w.sm() as db:  # as if AIOS never told us: nothing about stage tasks is stored, so the next pass relies on the link
        db.get(m.Onboarding, oid).sync_version += 1
        db.commit()
    sync(w, oid)
    assert sum(1 for t in w.aios.tasks.values() if "#stage-" in t["link"]) == 2


def test_a_new_due_day_reaches_the_task(w):
    _, oid, _ = w.live(doc=STAGED)
    r = w.api.put(f"/api/onboardings/{oid}/steps/assets/schedule", json={"start_on": None, "due_on": "2026-12-09"})
    assert r.status_code == 200, r.text
    t = titles(w)
    assert t["step-assets"]["date"] == "2026-12-09" and t["stage-build"]["date"] == "2026-12-09"
