"""The team: who is on it (from Voicent-App, or invited), who looks after which onboarding and step, and what they are told."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m, notifications, services
from app.config import Settings
from app.main import create_app
from app.voicent_directory import CachedDirectory, DirectoryError, Person, TeamMember
from tests.conftest import JWT_SECRET
from tests.helpers4 import FakeNotifier
from tests.test_api import bearer
from tests.test_tenancy import ACME

TPL = {"name": "Mini", "slug": "mini", "layout": "checklist", "steps": [
    {"key": "basics", "type": "form", "title": "Basics", "config": {"fields": [{"key": "name", "label": "Name", "type": "text"}]}},
    {"key": "build", "type": "internal_task", "title": "Build it"}]}


class Directory:
    def __init__(self):
        self.people: dict[str, Person] = {}
        self.teams: dict[str, list[TeamMember]] = {}
        self.down = False

    def person(self, auth_id):
        if self.down:
            raise DirectoryError("down")
        return self.people.get(auth_id)

    def team(self, tenant_id):
        if self.down:
            raise DirectoryError("down")
        return self.teams.get(tenant_id, [])


@pytest.fixture()
def t():
    s = Settings(database_url="sqlite://", supabase_jwt_secret=JWT_SECRET, app_url="https://onboard.test", resend_api_key="re_x",
                 resend_from="Voicent <hello@voicent.test>")
    app = create_app(s)
    d = Directory()
    app.state.directory = CachedDirectory(d, seconds=0)
    app.state.notifier = FakeNotifier()
    with TestClient(app) as c:
        c.dir, c.sm, c.mail, c.settings = d, app.state.sessionmaker, app.state.notifier, s
        yield c


def local_org(t, *people):
    """An org with no Voicent tenant, and people in it: (auth id, email, role)."""
    with t.sm() as db:
        org = services.get_or_create_org(db, "Bakery Co", "bakery")
        for aid, email, role in people:
            services.add_member(db, org.id, aid, email).role = role
        db.commit()
        return org.id


def member_id(t, auth_id):
    with t.sm() as db:
        return db.scalar(select(m.OrgMember.id).where(m.OrgMember.auth_user_id == auth_id))


def setup_onboarding(t, h):
    tpl = t.post("/api/templates", json=TPL, headers=h).json()
    cl = t.post("/api/clients", json={"name": "Shop"}, headers=h).json()
    t.post(f"/api/clients/{cl['id']}/contacts", json={"name": "Pat Client", "email": "pat@shop.test"}, headers=h)
    return t.post("/api/onboardings", json={"client_id": cl["id"], "template_id": tpl["id"]}, headers=h).json()


def notes(t, auth_id):
    with t.sm() as db:
        mid = db.scalar(select(m.OrgMember.id).where(m.OrgMember.auth_user_id == auth_id))
        return [(n.kind, n.text, n.email_state) for n in db.scalars(select(m.Notification).where(m.Notification.member_id == mid).order_by(m.Notification.created_at))]


# ---------------------------------------------------------------- who is on the team

def test_a_linked_orgs_team_comes_from_voicent_including_people_who_never_signed_in(t):
    t.dir.people["u-ann"] = Person("u-ann", ACME, "admin", False)
    t.dir.teams[ACME.id] = [TeamMember("u-ann", "ann@acme.test", "admin"), TeamMember("u-bo", "bo@acme.test", "member")]
    h = bearer("u-ann", "ann@acme.test")
    team = t.get("/api/team", headers=h).json()
    assert team["linked"] is True and team["can_manage"] is False and team["in_sync"] is True
    assert sorted((p["email"], p["role"], p["source"]) for p in team["members"]) == [("ann@acme.test", "admin", "voicent"), ("bo@acme.test", "member", "voicent")]
    # people come and go in Voicent-App, not here
    assert t.post("/api/team/invites", json={"email": "cy@acme.test"}, headers=h).status_code == 409
    bo = next(p for p in team["members"] if p["email"] == "bo@acme.test")
    assert t.patch(f"/api/team/members/{bo['id']}", json={"role": "admin"}, headers=h).status_code == 409
    t.dir.teams[ACME.id] = [TeamMember("u-ann", "ann@acme.test", "admin")]
    assert [p["email"] for p in t.get("/api/team", headers=h).json()["members"]] == ["ann@acme.test"]
    t.dir.down = True
    t.dir.people["u-ann"] = Person("u-ann", ACME, "admin", False)
    r = t.get("/api/team", headers=h).json()
    assert r["in_sync"] is False and [p["email"] for p in r["members"]] == ["ann@acme.test"]


def test_an_invited_person_joins_with_their_role_when_they_sign_in_with_that_address(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"))
    h = bearer("u-jay", "jay@bakery.test")
    r = t.post("/api/team/invites", json={"email": "Kim@Bakery.test", "role": "manager"}, headers=h)
    assert r.status_code == 201 and r.json()["email"] == "kim@bakery.test"
    assert t.post("/api/team/invites", json={"email": "not-an-email"}, headers=h).status_code == 422
    assert t.post("/api/team/invites", json={"email": "jay@bakery.test"}, headers=h).status_code == 409  # already on the team
    assert t.get("/api/clients", headers=bearer("u-kim", "someone-else@x.test")).status_code == 403  # another address gets nothing
    assert t.get("/api/clients", headers=bearer("u-kim", "kim@bakery.test")).status_code == 200
    team = t.get("/api/team", headers=h).json()
    assert team["invites"] == [] and {(p["email"], p["role"]) for p in team["members"]} == {("jay@bakery.test", "admin"), ("kim@bakery.test", "manager")}


def test_only_admins_manage_the_team_and_the_last_admin_stays(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"), ("u-mo", "mo@bakery.test", "member"))
    assert t.post("/api/team/invites", json={"email": "x@bakery.test"}, headers=bearer("u-mo")).status_code == 403
    jay = member_id(t, "u-jay")
    r = t.patch(f"/api/team/members/{jay}", json={"role": "member"}, headers=bearer("u-jay"))
    assert r.status_code == 409 and "at least one admin" in r.json()["detail"]
    assert t.delete(f"/api/team/members/{jay}", headers=bearer("u-jay")).status_code == 409
    mo = member_id(t, "u-mo")
    assert t.patch(f"/api/team/members/{mo}", json={"role": "viewer"}, headers=bearer("u-jay")).json()["role"] == "viewer"
    assert t.delete(f"/api/team/members/{mo}", headers=bearer("u-jay")).status_code == 204
    assert t.get("/api/clients", headers=bearer("u-mo")).status_code == 403


def test_a_viewer_can_set_their_own_preferences_but_not_assign(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"), ("u-vi", "vi@bakery.test", "viewer"))
    ob = setup_onboarding(t, bearer("u-jay"))
    hv = bearer("u-vi")
    assert t.put("/api/team/me", json={"notify_email": False, "name": "Vi"}, headers=hv).json()["notify_email"] is False
    assert t.post("/api/notifications/read", json={}, headers=hv).status_code == 200
    assert t.put(f"/api/onboardings/{ob['id']}/owner", json={"member_id": member_id(t, "u-vi")}, headers=hv).status_code == 403


# ---------------------------------------------------------------- assigning, and who hears what

def test_the_maker_owns_it_and_a_new_owner_or_step_follower_is_told_but_never_about_their_own_action(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"), ("u-kim", "kim@bakery.test", "member"))
    hj = bearer("u-jay")
    ob = setup_onboarding(t, hj)
    assert ob["owner_member_id"] == member_id(t, "u-jay")
    kim = member_id(t, "u-kim")
    assert t.put(f"/api/onboardings/{ob['id']}/owner", json={"member_id": kim}, headers=hj).json()["owner_member_id"] == kim
    r = t.put(f"/api/onboardings/{ob['id']}/steps/build/team-assignee", json={"member_id": kim}, headers=hj)
    assert r.json()["team_assignee_id"] == kim
    assert [k for k, _, _ in notes(t, "u-kim")] == ["assigned_onboarding", "assigned_step"]
    t.put(f"/api/onboardings/{ob['id']}/owner", json={"member_id": member_id(t, "u-jay")}, headers=hj)
    assert notes(t, "u-jay") == []  # they did it themselves
    assert [o["id"] for o in t.get("/api/onboardings?mine=1", headers=bearer("u-kim")).json()] == []
    assert [o["id"] for o in t.get("/api/onboardings?mine=1", headers=hj).json()] == [ob["id"]]


def test_someone_from_another_org_cant_be_given_anything(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"))
    with t.sm() as db:
        other = services.get_or_create_org(db, "Other", "other")
        stranger = services.add_member(db, other.id, "u-x", "x@other.test").id
        db.commit()
    ob = setup_onboarding(t, bearer("u-jay"))
    assert t.put(f"/api/onboardings/{ob['id']}/owner", json={"member_id": stranger}, headers=bearer("u-jay")).status_code == 404
    assert t.put(f"/api/onboardings/{ob['id']}/steps/basics/team-assignee", json={"member_id": stranger}, headers=bearer("u-jay")).status_code == 404


def test_a_client_answering_tells_the_step_follower_then_the_owner_finishing_tells_the_owner_without_their_words(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"), ("u-kim", "kim@bakery.test", "member"))
    hj = bearer("u-jay")
    ob = setup_onboarding(t, hj)
    t.put(f"/api/onboardings/{ob['id']}/steps/basics/team-assignee", json={"member_id": member_id(t, "u-kim")}, headers=hj)
    sent = t.post(f"/api/onboardings/{ob['id']}/send", headers=hj).json()
    session = t.post("/api/portal/exchange", json={"token": sent["links"][0]["url"].rsplit("/c/", 1)[1]}).json()["session"]
    secret = "my secret recipe is cinnamon"
    r = t.put("/api/portal/steps/basics", json={"data": {"answers": {"name": secret}}}, headers={"Authorization": f"Bearer {session}"})
    assert r.status_code == 200
    kim = notes(t, "u-kim")
    assert kim[-1][0] == "step_done" and kim[-1][1] == "Pat Client answered “Basics” in “Mini: Shop”."
    assert t.post(f"/api/onboardings/{ob['id']}/steps/build/complete", headers=hj).status_code == 200
    assert ("completed", "“Mini: Shop” is finished.", "sent") in notes(t, "u-jay")  # already emailed after the response
    # the emails went out after the responses, and say what happened, never what the client typed
    assert {e["to"] for e in t.mail.emails} == {"kim@bakery.test", "jay@bakery.test"}
    for e in t.mail.emails:
        assert secret not in e["text"] + e["html"] and f"https://onboard.test/onboardings/{ob['id']}" in e["text"]
        assert e["from"] == "Voicent <hello@voicent.test>"  # a direct customer with no brand name set goes out under the configured name
    assert all(state == "sent" for _, _, state in notes(t, "u-kim") if _ == "step_done")


def test_notifications_are_your_own_and_marking_read_only_touches_yours(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"), ("u-kim", "kim@bakery.test", "member"))
    hj = bearer("u-jay")
    ob = setup_onboarding(t, hj)
    t.put(f"/api/onboardings/{ob['id']}/owner", json={"member_id": member_id(t, "u-kim")}, headers=hj)
    mine = t.get("/api/notifications", headers=bearer("u-kim")).json()
    assert mine["unread"] == 1 and mine["items"][0]["text"] == "You now look after “Mini: Shop”."
    assert t.get("/api/notifications", headers=hj).json() == {"unread": 0, "items": []}
    assert t.post("/api/notifications/read", json={"ids": [mine["items"][0]["id"]]}, headers=hj).json()["marked"] == 0
    assert t.post("/api/notifications/read", json={}, headers=bearer("u-kim")).json()["marked"] == 1
    assert t.get("/api/notifications?unread_only=1", headers=bearer("u-kim")).json() == {"unread": 0, "items": []}


# ---------------------------------------------------------------- emailing

def test_emails_go_once_respect_the_persons_choice_and_old_news_is_dropped(t):
    local_org(t, ("u-jay", "jay@bakery.test", "admin"), ("u-kim", "kim@bakery.test", "member"), ("u-lu", "lu@bakery.test", "member"))
    with t.sm() as db:
        org = db.scalar(select(m.Org))
        kim, lu = member_id(t, "u-kim"), member_id(t, "u-lu")
        db.get(m.OrgMember, lu).notify_email = False
        a = notifications.notify(db, org.id, kim, "x", "fresh news")
        notifications.notify(db, org.id, lu, "x", "lu said no to emails")
        old = notifications.notify(db, org.id, kim, "x", "old news")
        old.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
        db.commit()
        aid = a.id
    out = notifications.send_pending(t.sm, t.settings, t.mail)
    again = notifications.send_pending(t.sm, t.settings, t.mail)
    assert out == {"sent": 1, "failed": 0} and again == {"sent": 0, "failed": 0}
    assert [e["subject"] for e in t.mail.emails] == ["fresh news"]
    with t.sm() as db:
        assert db.get(m.Notification, aid).email_state == "sent"
        assert {n.text: n.email_state for n in db.scalars(select(m.Notification))}["old news"] == "none"


def test_with_email_off_nothing_is_sent_and_nothing_breaks(t):
    local_org(t, ("u-kim", "kim@bakery.test", "member"))
    with t.sm() as db:
        notifications.notify(db, db.scalar(select(m.Org.id)), member_id(t, "u-kim"), "x", "news")
        db.commit()
    assert notifications.send_pending(t.sm, Settings(), t.mail) == {"sent": 0, "failed": 0} and t.mail.emails == []
