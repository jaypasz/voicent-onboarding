"""The client pipeline (stage worked out from what exists, plus a lost/stalled flag) and the team's tasks."""
from tests.test_api import DOC, app_two_orgs, bearer  # noqa: F401 (a fixture)


def mk(c, h=None, name="Acme"):
    t = c.post("/api/templates", json=DOC, headers=h or {}).json() if not hasattr(c, "_t") else c._t
    c._t = t
    cl = c.post("/api/clients", json={"name": name}, headers=h or {}).json()
    return t, cl


def stage(c, cid, h=None):
    return c.get(f"/api/clients/{cid}", headers=h or {}).json()["stage"]


def test_stage_follows_what_exists(client):
    t, cl = mk(client)
    assert cl["stage"] == "lead"
    ob = client.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}).json()
    assert stage(client, cl["id"]) == "lead"  # a draft is still only a lead
    client.post(f"/api/onboardings/{ob['id']}/send")
    assert stage(client, cl["id"]) == "onboarding"
    client.post(f"/api/onboardings/{ob['id']}/pause")
    assert stage(client, cl["id"]) == "onboarding"
    client.post(f"/api/clients/{cl['id']}/paying", json={"paying": True})
    assert stage(client, cl["id"]) == "won"
    client.post(f"/api/clients/{cl['id']}/paying", json={"paying": False})
    assert stage(client, cl["id"]) == "onboarding"


def test_lost_and_stalled_are_a_manual_flag_that_can_be_taken_back(client):
    _, cl = mk(client)
    for flag in ("lost", "stalled"):
        assert client.post(f"/api/clients/{cl['id']}/outcome", json={"outcome": flag}).json()["stage"] == flag
    assert client.post(f"/api/clients/{cl['id']}/outcome", json={"outcome": None}).json()["stage"] == "lead"
    assert client.post(f"/api/clients/{cl['id']}/outcome", json={"outcome": "won"}).status_code == 422


def test_a_paying_client_cannot_be_marked_lost(client):
    _, cl = mk(client)
    client.post(f"/api/clients/{cl['id']}/paying", json={"paying": True})
    r = client.post(f"/api/clients/{cl['id']}/outcome", json={"outcome": "lost"})
    assert r.status_code == 409 and stage(client, cl["id"]) == "won"


def test_the_client_list_filters_by_stage(client):
    _, a = mk(client, name="A")
    _, b = mk(client, name="B")
    client.post(f"/api/clients/{b['id']}/outcome", json={"outcome": "stalled"})
    names = lambda s: [c["name"] for c in client.get(f"/api/clients?stage={s}").json()]  # noqa: E731
    assert names("lead") == ["A"] and names("stalled") == ["B"] and names("won") == []
    assert client.get("/api/clients?stage=nonsense").status_code == 422


def test_tasks_are_created_assigned_dated_finished_and_removed(client):
    t, cl = mk(client)
    me = client.get("/api/team").json()["members"]
    task = client.post("/api/tasks", json={"client_id": cl["id"], "title": " Call Pat ", "due_on": "2026-12-01"})
    assert task.status_code == 201
    tid = task.json()["id"]
    assert task.json()["title"] == "Call Pat" and task.json()["done_at"] is None
    if me:
        r = client.patch(f"/api/tasks/{tid}", json={"assignee_id": me[0]["id"]})
        assert r.json()["assignee_id"] == me[0]["id"]
        assert client.patch(f"/api/tasks/{tid}", json={"assignee_id": None}).json()["assignee_id"] is None
    done = client.patch(f"/api/tasks/{tid}", json={"done": True}).json()
    assert done["done_at"]
    again = client.patch(f"/api/tasks/{tid}", json={"done": True}).json()["done_at"]
    assert again.rstrip("Z") == done["done_at"].rstrip("Z")  # finishing twice keeps the time (SQLite just drops the zone on reload)
    assert client.patch(f"/api/tasks/{tid}", json={"done": False}).json()["done_at"] is None
    assert client.patch(f"/api/tasks/{tid}", json={"due_on": None}).json()["due_on"] is None
    assert [x["id"] for x in client.get(f"/api/tasks?client_id={cl['id']}&done=false").json()] == [tid]
    assert client.get("/api/tasks?done=true").json() == []
    assert client.delete(f"/api/tasks/{tid}").status_code == 204
    assert client.get("/api/tasks").json() == []


def test_open_tasks_come_first_soonest_due_first(client):
    _, cl = mk(client)
    mk_t = lambda title, due=None: client.post("/api/tasks", json={"client_id": cl["id"], "title": title, "due_on": due}).json()["id"]  # noqa: E731
    later, soon, undated, finished = mk_t("later", "2026-12-20"), mk_t("soon", "2026-12-01"), mk_t("undated"), mk_t("finished", "2026-11-01")
    client.patch(f"/api/tasks/{finished}", json={"done": True})
    assert [x["id"] for x in client.get("/api/tasks").json()] == [soon, later, undated, finished]


def test_a_task_must_point_at_this_orgs_client_and_person(app_two_orgs):
    c = app_two_orgs
    ha, hb = bearer("user-a"), bearer("user-b")
    t, a_client = mk(c, ha)
    b_client = c.post("/api/clients", json={"name": "Theirs"}, headers=hb).json()
    b_member = c.get("/api/team", headers=hb).json()["members"][0]["id"]

    assert c.post("/api/tasks", json={"client_id": b_client["id"], "title": "x"}, headers=ha).status_code == 404
    assert c.post("/api/tasks", json={"client_id": a_client["id"], "title": "x", "assignee_id": b_member}, headers=ha).status_code == 404

    mine = c.post("/api/tasks", json={"client_id": a_client["id"], "title": "mine"}, headers=ha).json()["id"]
    assert c.get("/api/tasks", headers=hb).json() == []
    assert c.patch(f"/api/tasks/{mine}", json={"done": True}, headers=hb).status_code == 404
    assert c.delete(f"/api/tasks/{mine}", headers=hb).status_code == 404
    assert c.post(f"/api/clients/{a_client['id']}/outcome", json={"outcome": "lost"}, headers=hb).status_code == 404


def test_deleting_a_client_or_onboarding_does_not_leave_orphan_tasks(client):
    from sqlalchemy import select
    from app import models as m
    _, cl = mk(client)
    client.post("/api/tasks", json={"client_id": cl["id"], "title": "x"})
    with client.app_state.sessionmaker() as db:
        db.delete(db.get(m.Client, cl["id"]))
        db.commit()
        assert db.scalar(select(m.Task.id)) is None


def test_task_text_is_redacted_like_other_free_text(client):
    _, cl = mk(client)
    r = client.post("/api/tasks", json={"client_id": cl["id"], "title": "use key sk_live_abcdefghijklmnopqrstuv"}).json()
    assert "sk_live" not in r["title"]
