import copy

import pytest

from app.errors import TemplateInvalid
from app.templates import loader


def doc(**over):
    base = {
        "name": "T", "slug": "t", "layout": "checklist",
        "sections": [{"key": "a", "title": "A"}],
        "steps": [{"key": "one", "type": "form", "title": "One", "section": "a",
                   "config": {"fields": [{"key": "name", "label": "Name", "type": "text"}]}}],
    }
    return base | over


def test_the_four_presets_are_valid_and_cover_both_layouts():
    docs = {d["slug"]: d for d in loader.load_presets()}
    assert set(docs) == {"trades", "agency", "msp", "blank"}
    assert docs["trades"]["layout"] == "focus" and docs["msp"]["layout"] == "checklist"
    assert len(docs["msp"]["steps"]) > len(docs["trades"]["steps"])
    for d in docs.values():  # every preset uses only step types that exist
        assert all(s["type"] in {"form", "upload", "connect", "book_call", "approval", "internal_task"} for s in d["steps"])


def test_yaml_round_trips_without_loss():
    for d in loader.load_presets():
        assert loader.check(loader.parse_yaml(loader.export_yaml(d))) == d


def test_every_problem_is_reported_not_just_the_first():
    bad = doc(layout="grid", steps=[
        {"key": "one", "type": "nope", "title": "x"},
        {"key": "one", "type": "form", "title": "dup", "section": "missing", "config": {"fields": []}},
        {"key": "Bad Key", "type": "form", "title": ""},
    ])
    problems = loader.validate_document(bad)
    assert len(problems) >= 3
    bad2 = doc(steps=[
        {"key": "one", "type": "nope", "title": "x"},
        {"key": "one", "type": "form", "title": "dup", "section": "missing", "config": {"fields": [{"key": "a", "label": "A", "type": "select"}]}},
    ])
    text = "\n".join(loader.validate_document(bad2))
    assert "unknown step type 'nope'" in text and "used twice" in text and "isn't one of the template's sections" in text and "needs at least one option" in text


def test_unimplemented_step_types_are_refused_with_a_clear_message():
    d = doc(steps=[{"key": "creds", "type": "credential_share", "title": "Passwords"}])
    assert any("isn't available yet" in p for p in loader.validate_document(d))


def test_svg_and_unknown_upload_types_are_refused():
    d = doc(steps=[{"key": "u", "type": "upload", "title": "U", "config": {"accept": ["png", "svg"]}}])
    assert loader.validate_document(d)


def test_visibility_rules():
    internal_form = doc(steps=[{"key": "x", "type": "form", "title": "X", "visibility": "internal", "config": {"fields": [{"key": "a", "label": "A", "type": "text"}]}}])
    assert any("only internal_task" in p for p in loader.validate_document(internal_form))
    client_task = doc(steps=[{"key": "x", "type": "internal_task", "title": "X", "visibility": "client"}])
    assert any("never shown to clients" in p for p in loader.validate_document(client_task))
    ok = loader.check(doc(steps=[{"key": "x", "type": "internal_task", "title": "X"}]))
    assert ok["steps"][0]["visibility"] == "internal"


def test_unknown_fields_are_refused_so_the_builder_cant_invent_them():
    d = doc()
    d["steps"][0]["colour"] = "red"
    assert loader.validate_document(d)
    assert loader.validate_document({**doc(), "extra": 1})


def test_normalise_fills_defaults_and_does_not_mutate_the_input():
    d = doc()
    before = copy.deepcopy(d)
    out = loader.check(d)
    assert d == before
    s = out["steps"][0]
    assert s["visibility"] == "client" and s["due_offset_days"] is None and s["show_if"] is None
    assert out["nudge_after_days"] == 3 and out["on_complete"] == "none"


def test_bad_yaml_gives_a_plain_message():
    for text in ("a: [", "- just\n- a list", "x" * 300_000):
        with pytest.raises(TemplateInvalid) as e:
            loader.parse_yaml(text)
        assert e.value.problems


def test_yaml_cannot_construct_python_objects():
    with pytest.raises(TemplateInvalid):
        loader.parse_yaml("!!python/object/apply:os.system ['echo hi']")
