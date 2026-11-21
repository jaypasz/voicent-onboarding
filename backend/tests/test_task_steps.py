"""The task step: for the client or for the team, ticked item by item, merged with what used to be the separate team to-do list."""
import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from alembic import command

from app import models as m, services
from app.db import make_engine
from tests.helpers4 import DOC, make_world
from tests.test_migrations import cfg

TASKS = [
    {"key": "sign_off", "type": "task", "title": "Send us your price list", "assignee_role": "owner",
     "config": {"audience": "client", "instructions": "Any format.", "checklist": ["Find it", "Send it"]}},
    {"key": "chase", "type": "task", "title": "Chase the price list", "config": {"audience": "team"}},
]
TASK_DOC = DOC | {"slug": "tasks", "steps": TASKS}


@pytest.fixture()
def w():
    world, client = make_world()
    with client:
        yield world


def as_client(w, oid, key, data):
    with w.sm() as db:
        ob = db.get(m.Onboarding, oid)
        step = services.submit_step(db, ob.org_id, oid, key, data, submitted_by="contact:pat", actor_kind="client")
        db.commit()
        return step.status


def test_a_client_ticks_items_and_the_last_tick_finishes_the_task(w):
    _, oid, _ = w.live(doc=TASK_DOC)
    assert as_client(w, oid, "sign_off", {"checked": [0]}) == "in_progress"
    assert as_client(w, oid, "sign_off", {"checked": [0, 1], "note": "Attached to the email"}) == "done"
    assert as_client(w, oid, "sign_off", {"checked": [0]}) == "in_progress"  # un-ticking reopens it


def test_a_client_cannot_answer_a_team_task(w):
    _, oid, _ = w.live(doc=TASK_DOC)
    with pytest.raises(services.Conflict):
        as_client(w, oid, "chase", {"done": True})


def test_the_portal_only_shows_client_tasks(w):
    _, _, links = w.live(doc=TASK_DOC)
    token = links["Pat Owner"]["url"].rsplit("/", 1)[1]
    sess = w.api.post("/api/portal/exchange", json={"token": token}).json()["session"]
    data = w.api.get("/api/portal/onboarding", headers={"Authorization": f"Bearer {sess}"}).json()
    assert [s["key"] for s in data["steps"]] == ["sign_off"]
    assert data["steps"][0]["config"]["checklist"] == ["Find it", "Send it"]


def test_the_tasks_page_lists_team_tasks_from_onboardings_under_way(w):
    _, oid, _ = w.live(doc=TASK_DOC)
    rows = w.api.get("/api/tasks/in-onboardings").json()
    assert [(r["key"], r["onboarding_id"], r["status"]) for r in rows] == [("chase", oid, "pending")]  # the client task isn't ours
    me = w.api.get("/api/team").json()["members"]
    if me:
        w.api.put(f"/api/onboardings/{oid}/steps/chase/follower", json={"member_id": me[0]["id"]})
        assert len(w.api.get(f"/api/tasks/in-onboardings?assignee_id={me[0]['id']}").json()) == 1
    w.api.post(f"/api/onboardings/{oid}/steps/chase/complete")
    assert w.api.get("/api/tasks/in-onboardings?done=false").json() == []
    assert len(w.api.get("/api/tasks/in-onboardings?done=true").json()) == 1


def test_a_drafts_team_tasks_are_not_listed_until_it_is_sent(w):
    _, ob = w.client_with(doc=TASK_DOC)
    assert w.api.get("/api/tasks/in-onboardings").json() == []


def test_who_a_task_is_for_cant_change_once_it_holds_an_answer(w):
    _, oid, _ = w.live(doc=TASK_DOC)
    as_client(w, oid, "sign_off", {"checked": [0]})
    steps = w.api.get(f"/api/onboardings/{oid}/document").json()["document"]["steps"]
    for s in steps:
        if s["key"] == "sign_off":
            s["config"] = {**s["config"], "audience": "team"}
            s.pop("visibility", None)
    r = w.api.put(f"/api/onboardings/{oid}/document", json={"steps": steps})
    assert r.status_code == 409 and any("who it is for" in p for p in r.json()["problems"])


# ---- migration 0010 ---------------------------------------------------------------------------------------------

def _insert(conn, table, **vals):
    """A row with every required column filled in, so a test only has to name what it cares about."""
    row = {}
    for c in table.c:
        if c.name in vals:
            row[c.name] = vals[c.name]
        elif not c.nullable and c.server_default is None:
            t = c.type
            row[c.name] = (str(uuid.uuid4()) if isinstance(t, sa.String) else 0 if isinstance(t, sa.Integer) else False if isinstance(t, sa.Boolean)
                           else {} if isinstance(t, sa.JSON) else dt.datetime.now(dt.timezone.utc) if isinstance(t, sa.DateTime) else "x")
    conn.execute(table.insert().values(**row))


def test_migration_turns_internal_tasks_and_onboarding_todos_into_task_steps(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(cfg(), "0009")
    eng = make_engine(url)
    org, cl, tv, ob, st = (str(uuid.uuid4()) for _ in range(5))
    old = {"name": "n", "slug": "s", "steps": [
        {"key": "build", "type": "internal_task", "title": "Build", "visibility": "internal", "config": {"checklist": ["a"]}},
        {"key": "f", "type": "form", "title": "F", "visibility": "client", "config": {"fields": []}}]}
    meta = sa.MetaData()
    with eng.begin() as conn:
        t = {n: sa.Table(n, meta, autoload_with=conn) for n in ("orgs", "clients", "templates", "template_versions", "onboardings", "steps", "tasks")}
        _insert(conn, t["orgs"], id=org)
        _insert(conn, t["clients"], id=cl, org_id=org)
        _insert(conn, t["templates"], id=(tpl := str(uuid.uuid4())), org_id=org)
        _insert(conn, t["template_versions"], id=tv, org_id=org, template_id=tpl, document=old)
        _insert(conn, t["onboardings"], id=ob, org_id=org, client_id=cl, template_version_id=tv, document=old, status="active")
        _insert(conn, t["steps"], id=st, org_id=org, onboarding_id=ob, key="build", type="internal_task", title="Build", position=0, visibility="internal")
        _insert(conn, t["steps"], org_id=org, onboarding_id=ob, key="f", type="form", title="F", position=1)
        _insert(conn, t["tasks"], org_id=org, client_id=cl, onboarding_id=ob, title="Call Pat", due_on=dt.date(2026, 12, 1))
        _insert(conn, t["tasks"], org_id=org, client_id=cl, onboarding_id=None, title="Standalone")
    command.upgrade(cfg(), "head")
    with eng.connect() as conn:
        steps = {r.key: r for r in conn.execute(sa.text("select key, type, visibility, position, due_at from steps order by position"))}
        docs = [r[0] for r in conn.execute(sa.text("select document from onboardings"))] + [r[0] for r in conn.execute(sa.text("select document from template_versions"))]
        left = [r[0] for r in conn.execute(sa.text("select title from tasks"))]
    assert steps["build"].type == "task"
    todo = next(r for k, r in steps.items() if k not in ("build", "f"))
    assert (todo.type, todo.visibility, todo.position) == ("task", "internal", 2) and todo.due_at.startswith("2026-12-01")
    assert left == ["Standalone"]
    import json
    for d in docs:
        d = d if isinstance(d, dict) else json.loads(d)
        build = next(s for s in d["steps"] if s["key"] == "build")
        assert build["type"] == "task" and build["config"] == {"checklist": ["a"], "audience": "team"}
    with eng.connect() as conn:
        ob_doc = conn.execute(sa.text("select document from onboardings")).scalar()
    ob_doc = ob_doc if isinstance(ob_doc, dict) else json.loads(ob_doc)
    assert [x["title"] for x in ob_doc["steps"]] == ["Build", "F", "Call Pat"]
