"""The step builder's backend: a customised copy per client at creation, editing a draft's steps, and the limits on both."""
from tests.test_api import DOC, app_two_orgs, bearer, setup_client  # noqa: F401  (app_two_orgs is a fixture)

UPLOAD = {"key": "logo", "type": "upload", "title": "Your logo", "config": {"accept": ["png", "pdf"]}}


def create(c, t, cl, **extra):
    return c.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]} | extra)


def test_a_client_can_get_a_customised_copy_and_the_template_is_untouched(client):
    t, cl = setup_client(client, {})
    steps = [DOC["steps"][1], UPLOAD, DOC["steps"][0]]  # reordered, one removed, one added
    r = create(client, t, cl, steps=steps, sections=[{"key": "brand", "title": "Brand"}])
    assert r.status_code == 201
    ob = r.json()
    assert [s["key"] for s in ob["steps"]] == ["approve", "logo", "basics"]
    doc = client.get(f"/api/onboardings/{ob['id']}/document").json()
    assert doc["editable"] is True and doc["locked"] == []
    assert doc["document"]["sections"] == [{"key": "brand", "title": "Brand"}]
    assert doc["document"]["slug"] == "mini" and doc["document"]["steps"][1]["visibility"] == "client"  # normalised like a template
    assert len(client.get(f"/api/templates/{t['id']}").json()["document"]["steps"]) == 3
    plain = create(client, t, cl).json()
    assert [s["key"] for s in plain["steps"]] == ["basics", "approve", "build"]


def test_a_bad_customisation_lists_every_problem_and_creates_nothing(client):
    t, cl = setup_client(client, {})
    r = create(client, t, cl, steps=[{"key": "x", "type": "upload", "title": "X", "config": {}}, {"key": "x", "type": "nope", "title": "Y"}])
    assert r.status_code == 422
    problems = r.json()["problems"]
    assert any("accept" in p for p in problems) and any("used twice" in p for p in problems) and any("unknown step type" in p for p in problems)
    assert client.get("/api/onboardings").json() == []


def test_a_draft_can_have_steps_added_removed_reordered_and_edited(client):
    t, cl = setup_client(client, {})
    ob = create(client, t, cl).json()
    doc = client.get(f"/api/onboardings/{ob['id']}/document").json()["document"]
    steps = [{**doc["steps"][2], "title": "Build the workspace"}, UPLOAD, doc["steps"][0]]
    r = client.put(f"/api/onboardings/{ob['id']}/document", json={"sections": [], "steps": steps})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [(s["key"], s["position"]) for s in out["steps"]] == [("build", 0), ("logo", 1), ("basics", 2)]
    assert out["steps"][0]["title"] == "Build the workspace" and out["steps"][0]["visibility"] == "internal"
    assert out["steps"][1]["config"] == {"accept": ["png", "pdf"]}
    again = client.get(f"/api/onboardings/{ob['id']}").json()
    assert [s["key"] for s in again["steps"]] == ["build", "logo", "basics"]
    # due dates come from the edited copy when it is sent
    sent = client.post(f"/api/onboardings/{ob['id']}/send").json()
    assert next(s for s in sent["steps"] if s["key"] == "basics")["due_at"] is not None
    assert next(s for s in sent["steps"] if s["key"] == "logo")["due_at"] is None


def test_steps_with_answers_keep_their_place_and_type(client):
    t, cl = setup_client(client, {})
    ob = create(client, t, cl).json()
    assert client.put(f"/api/onboardings/{ob['id']}/steps/basics", json={"data": {"answers": {"name": "Pat"}}}).status_code == 200
    doc = client.get(f"/api/onboardings/{ob['id']}/document").json()
    assert doc["locked"] == ["basics"]
    steps = doc["document"]["steps"]
    removed = client.put(f"/api/onboardings/{ob['id']}/document", json={"steps": steps[1:]})
    assert removed.status_code == 409 and "can't be removed" in removed.json()["problems"][0]
    retyped = [{**steps[0], "type": "upload", "config": {"accept": ["pdf"]}}] + steps[1:]
    r = client.put(f"/api/onboardings/{ob['id']}/document", json={"steps": retyped})
    assert r.status_code == 409 and "type can't change" in r.json()["problems"][0]
    renamed = [{**steps[0], "title": "About you"}] + steps[1:]
    ok = client.put(f"/api/onboardings/{ob['id']}/document", json={"steps": renamed}).json()
    basics = next(s for s in ok["steps"] if s["key"] == "basics")
    assert basics["title"] == "About you" and basics["response"]["data"] == {"answers": {"name": "Pat"}}


def test_only_a_draft_can_be_edited(client):
    t, cl = setup_client(client, {})
    ob = create(client, t, cl).json()
    client.post(f"/api/onboardings/{ob['id']}/send")
    doc = client.get(f"/api/onboardings/{ob['id']}/document").json()
    assert doc["editable"] is False
    r = client.put(f"/api/onboardings/{ob['id']}/document", json={"steps": doc["document"]["steps"][:1]})
    assert r.status_code == 409 and "draft" in r.json()["detail"]
    assert len(client.get(f"/api/onboardings/{ob['id']}").json()["steps"]) == 3


def test_the_name_slug_and_on_complete_are_not_customised(client):
    t, cl = setup_client(client, {})
    ob = create(client, t, cl).json()
    doc = client.get(f"/api/onboardings/{ob['id']}/document").json()["document"]
    client.put(f"/api/onboardings/{ob['id']}/document", json={"steps": doc["steps"], "name": "Other", "on_complete": "provision_voicent_workspace"})
    after = client.get(f"/api/onboardings/{ob['id']}/document").json()["document"]
    assert after["name"] == "Mini" and after["on_complete"] == "none"


def test_another_org_cannot_read_or_edit_the_document(app_two_orgs):
    c, a, b = app_two_orgs, bearer("user-a"), bearer("user-b")
    t, cl = setup_client(c, a)
    ob = c.post("/api/onboardings", json={"client_id": cl["id"], "template_id": t["id"]}, headers=a).json()
    assert c.get(f"/api/onboardings/{ob['id']}/document", headers=b).status_code == 404
    assert c.put(f"/api/onboardings/{ob['id']}/document", json={"steps": [UPLOAD]}, headers=b).status_code == 404
    assert len(c.get(f"/api/onboardings/{ob['id']}", headers=a).json()["steps"]) == 3


def test_a_new_required_question_reopens_a_draft_step_that_was_already_answered(client):
    """Otherwise the step stays done, the client is never asked the new question, and the onboarding can finish without it."""
    t, cl = setup_client(client, {})
    ob = create(client, t, cl).json()
    assert client.put(f"/api/onboardings/{ob['id']}/steps/basics", json={"data": {"answers": {"name": "Pat"}}}).status_code == 200
    steps = client.get(f"/api/onboardings/{ob['id']}/document").json()["document"]["steps"]
    basics = steps[0]
    renamed = [{**basics, "title": "About you"}] + steps[1:]  # an edit that leaves the answer valid keeps it done
    out = client.put(f"/api/onboardings/{ob['id']}/document", json={"steps": renamed}).json()
    assert next(s for s in out["steps"] if s["key"] == "basics")["status"] == "done"
    fields = basics["config"]["fields"] + [{"key": "phone", "label": "Phone", "type": "text", "required": True}]
    more = [{**basics, "config": {**basics["config"], "fields": fields}}] + steps[1:]
    out = client.put(f"/api/onboardings/{ob['id']}/document", json={"steps": more}).json()
    step = next(s for s in out["steps"] if s["key"] == "basics")
    assert step["status"] == "in_progress" and step["response"]["data"] == {"answers": {"name": "Pat"}}
