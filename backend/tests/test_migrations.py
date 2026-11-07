"""The migrations have to build exactly the schema the models describe, or production drifts from the tests."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db import make_engine, normalize_url

ROOT = Path(__file__).resolve().parents[1]

TABLES = {
    "orgs", "org_members", "clients", "contacts", "templates", "template_versions", "onboardings", "steps",
    "responses", "files", "step_comments", "magic_links", "nudges", "sync_log",
}


def cfg() -> Config:
    c = Config(str(ROOT / "alembic.ini"))
    c.set_main_option("script_location", str(ROOT / "alembic"))
    return c


def test_upgrade_matches_models_and_downgrades_clean(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(cfg(), "head")
    tables = set(inspect(make_engine(url)).get_table_names())
    assert TABLES <= tables
    command.check(cfg())  # raises if the models have changes the migration doesn't cover
    command.downgrade(cfg(), "base")
    assert set(inspect(make_engine(url)).get_table_names()) <= {"alembic_version"}


def test_every_table_is_scoped_by_org():
    from app.db import Base
    from app import models  # noqa: F401

    for name, table in Base.metadata.tables.items():
        if name == "orgs":
            continue
        assert "org_id" in table.c, f"{name} has no org_id"
        assert not table.c.org_id.nullable, f"{name}.org_id must be NOT NULL"


def test_postgres_urls_get_the_psycopg_driver():
    assert normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_url("sqlite:///x.db") == "sqlite:///x.db"
    assert make_engine("postgresql://u:p@localhost:5432/db").dialect.driver == "psycopg"  # driver imports, no connection made


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="set TEST_POSTGRES_URL to run against a real Postgres")
def test_postgres_migration_enables_rls_on_every_table(monkeypatch):
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(cfg(), "base")
    command.upgrade(cfg(), "head")
    try:
        engine = make_engine(url)
        with engine.connect() as conn:
            rows = conn.execute(text("select relname, relrowsecurity from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r'")).all()
        enabled = {name for name, on in rows if on}
        assert TABLES <= enabled
        command.check(cfg())
    finally:
        command.downgrade(cfg(), "base")


def test_upgrading_a_database_that_already_has_data_keeps_it_and_fills_in_the_new_columns(tmp_path, monkeypatch):
    """Your deployed database has rows from before the reminders and AIOS sync. The migration must keep them and give the new
    NOT NULL columns sensible values (every existing sent onboarding then counts as 'not yet synced')."""
    url = f"sqlite:///{tmp_path / 'old.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(cfg(), "0002")
    engine = make_engine(url)
    with engine.begin() as conn:
        t = "2026-11-06 12:00:00"
        conn.execute(text(f"insert into orgs (id, name, slug, created_at, updated_at) values ('o1', 'V', 'v', '{t}', '{t}')"))
        conn.execute(text(f"insert into clients (id, org_id, name, kind, status, notes, created_at, updated_at) values ('c1', 'o1', 'Acme', 'trades', 'active', '', '{t}', '{t}')"))
        conn.execute(text(
            f"insert into onboardings (id, org_id, client_id, title, layout, status, document, last_activity_at, nudges_paused, created_at, updated_at) "
            f"values ('ob1', 'o1', 'c1', 'Kickoff', 'focus', 'active', '{{}}', '{t}', 0, '{t}', '{t}')"))
        conn.execute(text(
            f"insert into steps (id, org_id, onboarding_id, key, type, title, section, position, visibility, status, created_at, updated_at) "
            f"values ('s1', 'o1', 'ob1', 'basics', 'form', 'Basics', '', 0, 'client', 'pending', '{t}', '{t}')"))
    command.upgrade(cfg(), "head")
    with engine.connect() as conn:
        client = conn.execute(text("select timezone from clients where id = 'c1'")).one()
        ob = conn.execute(text("select sync_version, synced_version, attention, aios_status, aios_project_id from onboardings where id = 'ob1'")).one()
        step = conn.execute(text("select aios_status, aios_comment_revision from steps where id = 's1'")).one()
    assert client.timezone == "America/New_York"
    assert (ob.sync_version, ob.synced_version) == (1, 0)  # dirty, so the next pass syncs it
    assert ob.attention is None and ob.aios_status is None and ob.aios_project_id is None
    assert step.aios_status is None and step.aios_comment_revision == 0
    command.downgrade(cfg(), "0002")  # and it can be undone
    command.upgrade(cfg(), "head")
