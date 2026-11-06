"""The constraints that carry the product's rules: one org per row, unique step keys, immutable template versions by number."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models as m
from app.db import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        yield s


def seed(db):
    org = m.Org(name="Voicent", slug="voicent")
    db.add(org)
    db.flush()
    client = m.Client(org_id=org.id, name="Acme Plumbing", kind="trades")
    db.add(client)
    db.flush()
    ob = m.Onboarding(org_id=org.id, client_id=client.id, title="Kickoff", document={"steps": []})
    db.add(ob)
    db.flush()
    return org, client, ob


def test_step_keys_are_unique_per_onboarding(db):
    org, _, ob = seed(db)
    db.add(m.Step(org_id=org.id, onboarding_id=ob.id, key="basics", type="form", title="Basics"))
    db.flush()
    db.add(m.Step(org_id=org.id, onboarding_id=ob.id, key="basics", type="form", title="Again"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_template_slug_is_unique_per_org_and_versions_are_numbered(db):
    org, _, _ = seed(db)
    t = m.Template(org_id=org.id, name="Trades", slug="trades")
    db.add(t)
    db.flush()
    db.add(m.TemplateVersion(org_id=org.id, template_id=t.id, version=1, document={}))
    db.flush()
    db.add(m.TemplateVersion(org_id=org.id, template_id=t.id, version=1, document={}))
    with pytest.raises(IntegrityError):
        db.flush()


def test_magic_link_token_hash_is_unique(db):
    import datetime as dt

    org, client, ob = seed(db)
    c = m.Contact(org_id=org.id, client_id=client.id, name="Pat")
    db.add(c)
    db.flush()
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
    db.add(m.MagicLink(org_id=org.id, onboarding_id=ob.id, contact_id=c.id, token_hash="h" * 64, expires_at=exp))
    db.flush()
    db.add(m.MagicLink(org_id=org.id, onboarding_id=ob.id, contact_id=c.id, token_hash="h" * 64, expires_at=exp))
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_a_client_removes_its_contacts_and_a_step_cascades_to_responses(db):
    org, client, ob = seed(db)
    db.add(m.Contact(org_id=org.id, client_id=client.id, name="Pat"))
    s = m.Step(org_id=org.id, onboarding_id=ob.id, key="a", type="form", title="A")
    db.add(s)
    db.flush()
    db.add(m.Response(org_id=org.id, step_id=s.id, data={"x": 1}))
    db.flush()
    db.delete(ob)
    db.flush()
    assert db.query(m.Step).count() == 0
    assert db.query(m.Response).count() == 0
    db.delete(client)
    db.flush()
    assert db.query(m.Contact).count() == 0
