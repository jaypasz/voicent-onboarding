"""Fakes and builders for the reminder and AIOS tests. Nothing here touches the network."""
from __future__ import annotations

import datetime as dt
import json
import re

import httpx
from fastapi.testclient import TestClient

from app import models as m
from app.aios import AiosClient
from app.config import Settings
from app.main import create_app
from app.notify import SendResult

AIOS_URL = "https://aios.test"
AIOS_TOKEN = "aios-service-token-0123456789"
BASE = dict(
    database_url="sqlite://", auth_disabled=True, app_env="local", app_url="https://onboard.test",
    twilio_account_sid="AC123", twilio_auth_token="tok", twilio_from_number="+15550001111",
    resend_api_key="re_test", resend_from="Voicent <hi@onboard.test>",
    aios_api_url=AIOS_URL, aios_service_token=AIOS_TOKEN, portal_signing_key="p" * 32,
)
WHEN_STALE = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.timezone.utc)  # the onboarding's last activity in most tests
NOON_ET = dt.datetime(2026, 11, 10, 17, 0, tzinfo=dt.timezone.utc)  # 12:00 in New York
NIGHT_ET = dt.datetime(2026, 11, 10, 8, 0, tzinfo=dt.timezone.utc)  # 03:00 in New York

DOC = {
    "name": "Mini", "slug": "mini", "layout": "checklist", "nudge_after_days": 3,
    "steps": [
        {"key": "basics", "type": "form", "title": "Company basics", "assignee_role": "owner", "due_offset_days": 2,
         "config": {"fields": [{"key": "name", "label": "Name", "type": "text", "required": True}]}},
        {"key": "it_access", "type": "connect", "title": "Grant IT access", "assignee_role": "it", "config": {"provider": "dns", "label": "DNS"}},
        {"key": "approve", "type": "approval", "title": "Approve the greeting", "config": {"deliverable": {"kind": "text", "text": "Hello"}}},
        {"key": "build", "type": "internal_task", "title": "Build the agent", "config": {"checklist": ["Create it", "Test it"]}},
    ],
}


class FakeNotifier:
    """Records what would have been sent. Queue results with `sms_results` / `email_results`; the default is success."""

    def __init__(self):
        self.sms: list[tuple[str, str]] = []
        self.emails: list[dict] = []
        self.sms_results: list[SendResult] = []
        self.email_results: list[SendResult] = []

    def send_sms(self, to, body):
        self.sms.append((to, body))
        return self.sms_results.pop(0) if self.sms_results else SendResult(True)

    def send_email(self, to, subject, text, html):
        self.emails.append({"to": to, "subject": subject, "text": text, "html": html})
        return self.email_results.pop(0) if self.email_results else SendResult(True)


class FakeAios:
    """A tiny in-memory AIOS behind httpx.MockTransport, so the real AiosClient and sync code run end to end."""

    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.comments: dict[str, list[str]] = {}
        self.requests: list[tuple[str, str, object]] = []
        self.sleeps: list[float] = []
        self.hooks: list = []  # each takes (request, body) and returns an httpx.Response, raises, or returns None to carry on
        self._n = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if request.headers.get("authorization") != f"Bearer {AIOS_TOKEN}":
            return httpx.Response(401, json={"detail": "no"})
        for hook in self.hooks:
            r = hook(request, body)
            if r is not None:
                return r
        p, meth = request.url.path, request.method
        if meth == "POST" and p == "/api/projects":
            if body["id"] in self.projects:
                return httpx.Response(409, json={"detail": "exists"})
            self.projects[body["id"]] = dict(body)
            return httpx.Response(201, json=body)
        if meth == "PATCH" and (mt := re.fullmatch(r"/api/projects/([\w-]+)", p)):
            self.projects[mt.group(1)].update(body)
            return httpx.Response(200, json=self.projects[mt.group(1)])
        if meth == "GET" and p == "/api/tasks":
            pid = request.url.params.get("project")
            return httpx.Response(200, json=[t for t in self.tasks.values() if t["project_id"] == pid])
        if meth == "POST" and p == "/api/tasks":
            self._n += 1
            t = {"id": f"t{self._n}", **body}
            self.tasks[t["id"]] = t
            return httpx.Response(201, json=t)
        if meth == "PATCH" and (mt := re.fullmatch(r"/api/tasks/(\w+)", p)):
            self.tasks[mt.group(1)].update(body)
            return httpx.Response(200, json=self.tasks[mt.group(1)])
        if meth == "POST" and (mt := re.fullmatch(r"/api/tasks/(\w+)/comments", p)):
            self.comments.setdefault(mt.group(1), []).append(body["body"])
            return httpx.Response(201, json={"id": 1, "body": body["body"]})
        return httpx.Response(404, json={"detail": "unknown"})

    def client(self, settings: Settings) -> AiosClient:
        return AiosClient(settings, http=httpx.Client(transport=httpx.MockTransport(self.handler)), sleep=self.sleeps.append)

    def calls(self, method: str, path_re: str) -> list:
        return [r for r in self.requests if r[0] == method and re.fullmatch(path_re, r[1])]

    @property
    def sent_text(self) -> str:
        return json.dumps(self.requests)


class World:
    def __init__(self, api: TestClient, app, notifier: FakeNotifier, aios: FakeAios, settings: Settings):
        self.api, self.app, self.notifier, self.aios, self.settings = api, app, notifier, aios, settings
        self.sm = app.state.sessionmaker

    def client_with(self, name="Acme Plumbing", contacts=None, timezone=None, doc=None):
        contacts = contacts if contacts is not None else [
            {"name": "Pat Owner", "role": "owner", "email": "pat@acme.test", "phone": "(555) 123-4567", "sms_consent": True, "sms_consent_source": "signed form"},
            {"name": "Ivy IT", "role": "it", "email": "ivy@acme.test"},
        ]
        body = {"name": name, **({"timezone": timezone} if timezone else {})}
        cl = self.api.post("/api/clients", json=body).json()
        for c in contacts:
            r = self.api.post(f"/api/clients/{cl['id']}/contacts", json=c)
            assert r.status_code == 201, r.text
        tpl = self.api.post("/api/templates", json=doc or DOC).json()
        ob = self.api.post("/api/onboardings", json={"client_id": cl["id"], "template_id": tpl["id"]}).json()
        return cl, ob

    def live(self, **kw):
        """A sent onboarding that has been quiet since WHEN_STALE. Returns (client, onboarding id, links by contact name)."""
        cl, ob = self.client_with(**kw)
        sent = self.api.post(f"/api/onboardings/{ob['id']}/send").json()
        self.set_activity(ob["id"], WHEN_STALE)
        return cl, ob["id"], {l["contact_name"]: l for l in sent["links"]}

    def set_activity(self, onboarding_id, when):
        with self.sm() as db:
            db.get(m.Onboarding, onboarding_id).last_activity_at = when
            db.commit()

    def get(self, onboarding_id) -> m.Onboarding:
        with self.sm() as db:
            ob = db.get(m.Onboarding, onboarding_id)
            list(ob.steps)
            return ob


def make_world(**over) -> tuple[World, TestClient]:
    settings = Settings(**{**BASE, **over})
    app = create_app(settings)
    notifier, aios = FakeNotifier(), FakeAios()
    app.state.notifier = notifier
    if settings.aios_sync_enabled:
        app.state.aios = aios.client(settings)
    c = TestClient(app)
    return World(c, app, notifier, aios, settings), c


def token_in(text: str) -> str:
    return re.search(r"/c/([A-Za-z0-9_-]+)", text).group(1)
