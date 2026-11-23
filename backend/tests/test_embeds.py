"""Links and embeds from other tools: what each address is, that only addresses built here are framed, and where they go."""
import pytest

from app import embeds
from app.templates import loader
from tests.helpers4 import make_world, token_in

LOOM = "https://www.loom.com/share/0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize("url,provider,embed", [
    (LOOM, "loom", "https://www.loom.com/embed/0123456789abcdef0123456789abcdef"),
    ("https://loom.com/embed/0123456789abcdef0123456789abcdef", "loom", "https://www.loom.com/embed/0123456789abcdef0123456789abcdef"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "youtube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "youtube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://www.youtube.com/@somechannel", "youtube", None),
    ("https://vimeo.com/123456789", "vimeo", "https://player.vimeo.com/video/123456789"),
    ("https://vimeo.com/123456789/abcdef1234", "vimeo", "https://player.vimeo.com/video/123456789?h=abcdef1234"),
    ("https://www.figma.com/design/AbCdEfGhIjKl/My-file?node-id=1-2&t=x", "figma",
     "https://www.figma.com/embed?embed_host=share&url=https%3A%2F%2Fwww.figma.com%2Fdesign%2FAbCdEfGhIjKl%3Fnode-id%3D1-2"),
    ("https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit?usp=sharing", "google_doc", "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/preview"),
    ("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/edit#gid=0", "google_sheet", "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/preview"),
    ("https://docs.google.com/presentation/d/1AbCdEfGhIjKlMnOp/edit", "google_slides", "https://docs.google.com/presentation/d/1AbCdEfGhIjKlMnOp/preview"),
    ("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing", "google_drive", "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/preview"),
    ("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp", "google_drive", "https://drive.google.com/embeddedfolderview?id=1AbCdEfGhIjKlMnOp#list"),
    ("https://www.notion.so/acme/Kickoff-0123456789abcdef", "notion", None),
    ("https://acme.notion.site/Kickoff-0123456789abcdef", "notion", None),
    ("https://example.com/brief.pdf", "link", None),
])
def test_each_provider_is_recognised_and_its_embed_is_built_from_the_ids(url, provider, embed):
    d = embeds.describe(url)
    assert d["provider"] == provider and d["embed_url"] == embed and d["href"] == url
    if embed:
        assert embed.split("/")[2] in embeds.EMBED_HOSTS


@pytest.mark.parametrize("url", [
    "http://www.loom.com/share/0123456789abcdef0123456789abcdef", "javascript:alert(1)", "https://user:pw@www.loom.com/share/x",
    "https://www.loom.com:8443/share/0123456789abcdef0123456789abcdef", "https://ex ample.com", "", None, "https://" + "a" * 600,
])
def test_anything_but_plain_https_is_refused(url):
    assert embeds.describe(url) is None


@pytest.mark.parametrize("url", [
    "https://www.loom.com.evil.test/share/0123456789abcdef0123456789abcdef", "https://evil-loom.com/share/0123456789abcdef0123456789abcdef",
    "https://www.loom.com/share/../../evil", "https://drive.google.com/file/d/x\"onload=1/view", "https://docs.google.com/forms/d/e/1AbCdEfGhIjKlMnOp/viewform",
])
def test_a_lookalike_or_odd_address_is_only_ever_a_link(url):
    d = embeds.describe(url)
    assert d is not None and d["embed_url"] is None


def _doc(**step):
    return {"name": "T", "slug": "t", "layout": "checklist", "steps": [{"key": "s", "type": "form", "title": "S", "config": {"fields": [
        {"key": "a", "label": "A", "type": "text"}]}, **step}]}


def test_a_template_checks_its_resources_and_fills_an_empty_list():
    assert loader.validate_document(_doc(resources=[{"label": "Walkthrough", "url": LOOM}])) == []
    assert loader.check(_doc())["steps"][0]["resources"] == []
    problems = loader.validate_document(_doc(resources=[{"url": "https://u:p@example.com/x"}]))
    assert problems == ["steps[0] ('s').resources[0].url: use a plain https address (no user name, password or port)."]
    assert loader.validate_document(_doc(resources=[{"url": "http://example.com"}]))
    assert loader.validate_document(_doc(resources=[{"url": "https://example.com"}] * 11))


def test_a_watch_or_read_step_needs_an_https_address():
    ok = {"name": "T", "slug": "t", "layout": "focus", "steps": [{"key": "v", "type": "info_video", "title": "Watch this", "config": {"url": LOOM}}]}
    assert loader.validate_document(ok) == []
    ok["steps"][0]["config"] = {"url": "http://x.test"}
    assert loader.validate_document(ok)
    ok["steps"][0]["config"] = {}
    assert loader.validate_document(ok)


# ---------------------------------------------------------------- end to end

DOC = {
    "name": "Media", "slug": "media", "layout": "checklist",
    "steps": [
        {"key": "intro", "type": "info_video", "title": "Watch the welcome", "assignee_role": "owner", "config": {"url": LOOM, "instructions": "Two minutes."}},
        {"key": "brand", "type": "form", "title": "Your brand", "assignee_role": "owner",
         "config": {"fields": [{"key": "name", "label": "Name", "type": "text"}]},
         "resources": [{"label": "Brand guide", "url": "https://www.figma.com/design/AbCdEfGhIjKl/Guide"}, {"url": "https://acme.notion.site/Brief-1"}]},
        {"key": "prep", "type": "task", "title": "Our prep", "config": {"audience": "team"},
         "resources": [{"label": "Internal runbook", "url": "https://www.notion.so/voicent/SECRET-RUNBOOK-1"}]},
    ],
}


@pytest.fixture()
def w():
    world, client = make_world()
    with client:
        yield world


def test_the_client_sees_the_media_and_resources_and_never_an_internal_steps_links(w):
    _, oid, links = w.live(doc=DOC)
    tok = w.api.post("/api/portal/exchange", json={"token": token_in(links["Pat Owner"]["url"])}).json()["session"]
    h = {"Authorization": f"Bearer {tok}"}
    view = w.api.get("/api/portal/onboarding", headers=h)
    assert view.status_code == 200
    steps = {s["key"]: s for s in view.json()["steps"]}
    assert steps["intro"]["media"]["embed_url"] == "https://www.loom.com/embed/0123456789abcdef0123456789abcdef"
    assert [r["label"] for r in steps["brand"]["resources"]] == ["Brand guide", "Notion page"]  # no label: what it is
    assert steps["brand"]["resources"][0]["embed_url"].startswith("https://www.figma.com/embed?")
    assert steps["brand"]["resources"][1]["embed_url"] is None
    assert "SECRET-RUNBOOK" not in view.text
    # watching it finishes the step
    assert w.api.put("/api/portal/steps/intro", json={"data": {"seen": False}}, headers=h).status_code == 422
    r = w.api.put("/api/portal/steps/intro", json={"data": {"seen": True}}, headers=h)
    assert r.status_code == 200, r.text
    assert next(s for s in w.get(oid).steps if s.key == "intro").status == "done"
    # the admin sees everything, and nothing about the links goes to AIOS
    detail = {s["key"]: s for s in w.api.get(f"/api/onboardings/{oid}").json()["steps"]}
    assert detail["prep"]["resources"][0]["provider"] == "notion" and detail["intro"]["media"]["provider"] == "loom"
    assert "loom.com" not in w.aios.sent_text and "figma.com" not in w.aios.sent_text and "SECRET-RUNBOOK" not in w.aios.sent_text


def test_adding_a_resource_after_sending_is_news_for_the_client_but_old_documents_keep_their_fingerprint():
    from app import changes
    before = {"steps": [{"key": "a", "type": "form", "title": "A", "config": {}, "visibility": "client"}]}
    after_normalise = {"steps": [{**before["steps"][0], "resources": []}]}
    assert changes.snapshot(before) == changes.snapshot(after_normalise)
    added = {"steps": [{**before["steps"][0], "resources": [{"url": LOOM}]}]}
    assert changes.snapshot(added) != changes.snapshot(before)
