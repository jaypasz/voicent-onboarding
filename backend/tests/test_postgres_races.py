"""Races that only a real database shows: two requests at once, each in its own transaction. SQLite runs one writer at a time,
so these run only against Postgres (TEST_POSTGRES_URL), as the CI postgres job does."""
import os
import threading
import time

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import models as m, services
from app.db import make_engine
from app.errors import Conflict
from tests.test_migrations import cfg

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="set TEST_POSTGRES_URL to run against a real Postgres")

DOC = {"name": "Workspace", "slug": "workspace", "layout": "checklist", "on_complete": "provision_voicent_workspace",
       "steps": [{"key": "build", "type": "internal_task", "title": "Build the agent", "config": {"checklist": ["Create it"]}}]}


@pytest.fixture()
def sm(monkeypatch):
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(cfg(), "base")
    command.upgrade(cfg(), "head")
    engine = make_engine(url)
    try:
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        command.downgrade(cfg(), "base")


def in_background(fn):
    """Run fn in its own thread (so its own connection and transaction). Returns a join() that gives its result or raises."""
    out: dict = {}

    def run():
        try:
            out["value"] = fn()
        except Exception as e:  # handed back to the test
            out["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()

    def join():
        t.join(10)
        assert not t.is_alive(), "the background request never finished"
        if "error" in out:
            raise out["error"]
        return out.get("value")
    return join


def test_two_admins_removing_each_other_at_once_leave_one_admin(sm):
    with sm() as db:
        org = m.Org(name="Bakery", slug="bakery")
        db.add(org)
        db.flush()
        a = m.OrgMember(org_id=org.id, auth_user_id="u-a", email="a@bakery.test", role="admin", source="local")
        b = m.OrgMember(org_id=org.id, auth_user_id="u-b", email="b@bakery.test", role="admin", source="local")
        db.add_all([a, b])
        db.commit()
        org_id, a_id, b_id = org.id, a.id, b.id

    first = sm()
    services.change_member(first, org_id, a_id, remove=True)  # not committed yet

    def second():
        with sm() as db:
            services.change_member(db, org_id, b_id, role="member")
            db.commit()
    join = in_background(second)
    time.sleep(0.5)  # the second request is now waiting for the first, or (without the lock) already done
    first.commit()
    first.close()
    with pytest.raises(Conflict):
        join()
    with sm() as db:
        assert db.scalars(select(m.OrgMember.id).where(m.OrgMember.org_id == org_id, m.OrgMember.role == "admin")).all() == [b_id]


def _onboarding_one_step_from_done(sm):
    with sm() as db:
        org = m.Org(name="Acme", slug="acme")
        db.add(org)
        db.flush()
        tpl, _, _ = services.save_template(db, org.id, DOC)
        client = services.create_client(db, org.id, name="Acme Plumbing")
        ob = services.create_onboarding(db, org.id, client_id=client.id, template_id=tpl.id)
        services.send_onboarding(db, org.id, ob.id)
        db.commit()
        return org.id, client.id, ob.id


@pytest.mark.parametrize("first_in", ["payment", "last step"])
def test_marking_a_client_paying_while_their_last_step_is_done_still_queues_the_workspace(sm, first_in):
    org_id, client_id, ob_id = _onboarding_one_step_from_done(sm)

    def pay(db):
        services.set_client_paying(db, org_id, client_id, True, services.now())

    def finish(db):
        services.complete_step(db, org_id, ob_id, "build")

    first_fn, second_fn = (pay, finish) if first_in == "payment" else (finish, pay)
    first = sm()
    first_fn(first)  # not committed yet

    def second():
        with sm() as db:
            second_fn(db)
            db.commit()
    join = in_background(second)
    time.sleep(0.5)
    first.commit()
    first.close()
    join()
    with sm() as db:
        ob = db.get(m.Onboarding, ob_id)
        assert ob.status == "completed" and db.get(m.Client, client_id).paying_since is not None
        assert ob.provision_state == "pending" and ob.provision_delivery_id
