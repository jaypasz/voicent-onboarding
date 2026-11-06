import pytest

from app.steps import registry


def t(name):
    return registry.get(name)


FORM = {"fields": [
    {"key": "name", "label": "Name", "type": "text", "required": True},
    {"key": "phone", "label": "Phone", "type": "phone"},
    {"key": "email", "label": "Email", "type": "email"},
    {"key": "site", "label": "Site", "type": "url"},
    {"key": "start", "label": "Start", "type": "date"},
    {"key": "size", "label": "Size", "type": "select", "options": ["small", "large"]},
    {"key": "tools", "label": "Tools", "type": "multiselect", "options": ["a", "b", "c"]},
    {"key": "agree", "label": "Agree", "type": "checkbox", "required": True},
]}


def test_form_accepts_a_good_answer_and_drops_empty_optionals():
    good = {"answers": {"name": " Acme ", "phone": "+1 (555) 123-4567", "email": "a@b.co", "site": "https://acme.test",
                        "start": "2026-12-01", "size": "small", "tools": ["a", "c"], "agree": True, "email2": None} | {}}
    good["answers"].pop("email2")
    cleaned, problems = t("form").validate_response(FORM, good)
    assert problems == [] and cleaned["answers"]["name"] == "Acme" and cleaned["answers"]["tools"] == ["a", "c"]


def test_form_reports_every_problem_by_label():
    bad = {"answers": {"phone": "abc", "email": "nope", "site": "javascript:alert(1)", "start": "12/01/2026", "size": "huge",
                       "tools": ["a", "a"], "agree": "yes", "bogus": 1}}
    _, problems = t("form").validate_response(FORM, bad)
    text = "\n".join(problems)
    for needle in ("Name: this is required", "Phone:", "Email:", "Site:", "Start:", "Size:", "Tools:", "Agree:", "'bogus' isn't a question"):
        assert needle in text, needle


def test_form_redacts_secrets_in_free_text():
    fake = "ghp" + "_" + "a" * 36
    cleaned, problems = t("form").validate_response(FORM, {"answers": {"name": f"key {fake}", "agree": True}})
    assert problems == [] and fake not in cleaned["answers"]["name"] and "[redacted]" in cleaned["answers"]["name"]


def test_form_config_rules():
    f = t("form")
    assert f.validate_config({"fields": [{"key": "a", "label": "A", "type": "select"}]})
    assert f.validate_config({"fields": [{"key": "a", "label": "A", "type": "text", "options": ["x"]}]})
    assert f.validate_config({"fields": [{"key": "a", "label": "A", "type": "text"}, {"key": "a", "label": "B", "type": "text"}]})
    assert f.validate_config({"fields": []})
    assert not f.validate_config({"fields": [{"key": "a", "label": "A", "type": "text"}]})


def test_upload_counts_and_shape():
    u, cfg = t("upload"), {"accept": ["png"], "min_files": 1, "max_files": 2}
    assert u.validate_response(cfg, {"file_ids": []})[1]
    assert u.validate_response(cfg, {"file_ids": ["a", "b", "c"]})[1]
    assert u.validate_response(cfg, {"file_ids": ["a", "a"]})[1]
    assert u.validate_response(cfg, {"file_ids": ["a"], "extra": 1})[1]
    assert u.validate_response(cfg, {"file_ids": ["a", "b"]}) == ({"file_ids": ["a", "b"]}, [])
    assert u.validate_response({"accept": ["png"], "min_files": 0}, {"file_ids": []})[1] == []
    assert u.validate_config({"accept": ["png"], "min_files": 3, "max_files": 2})


def test_connect_never_accepts_tokens_or_passwords():
    c = t("connect")
    for bad in ({"status": "connected", "account_label": "x", "access_token": "abc"}, {"status": "connected", "password": "p"}):
        _, problems = c.validate_response({}, bad)
        assert problems and "never send tokens or passwords" in problems[0]
    assert c.validate_response({}, {"status": "connected", "account_label": ""})[1]
    cleaned, _ = c.validate_response({}, {"status": "connected", "account_label": "Acme Google Business"})
    assert c.resulting_status({}, cleaned) == "done"
    cleaned, _ = c.validate_response({}, {"status": "pending"})
    assert c.resulting_status({}, cleaned) == "in_progress"


def test_book_call():
    b = t("book_call")
    assert b.validate_response({}, {"booked": "yes"})[1]
    assert b.validate_response({}, {"booked": True, "when": "not a date"})[1]
    cleaned, problems = b.validate_response({}, {"booked": True, "when": "2026-11-20T14:00"})
    assert problems == [] and b.resulting_status({}, cleaned) == "done"
    assert b.resulting_status({}, {"booked": False}) == "in_progress"
    assert b.validate_config({"url": "http://insecure.test"})


def test_approval_changes_requested_needs_a_comment_and_reopens():
    a, cfg = t("approval"), {"deliverable": {"kind": "text", "text": "Hi"}}
    assert a.validate_response(cfg, {"decision": "changes_requested"})[1]
    assert a.validate_response(cfg, {"decision": "maybe"})[1]
    cleaned, _ = a.validate_response(cfg, {"decision": "changes_requested", "comment": "Warmer please"})
    assert a.resulting_status(cfg, cleaned) == "in_progress"
    cleaned, _ = a.validate_response(cfg, {"decision": "approved"})
    assert a.resulting_status(cfg, cleaned) == "done"


def test_approval_config_needs_the_matching_field():
    a = t("approval")
    assert a.validate_config({"deliverable": {"kind": "link"}})
    assert a.validate_config({"deliverable": {"kind": "text", "text": "x", "url": "https://x.test"}})
    assert not a.validate_config({"deliverable": {"kind": "link", "url": "https://x.test"}})


def test_internal_task_is_not_client_visible():
    i = t("internal_task")
    assert i.client_visible is False and t("form").client_visible is True
    assert i.validate_response({}, {"note": "done"}) == ({"note": "done"}, [])
    assert i.validate_response({}, {"other": 1})[1]


def test_unimplemented_types_are_known_but_unusable():
    for name in ("credential_share", "info_video", "payment_link"):
        s = t(name)
        assert s is not None and s.implemented is False
        assert s.validate_config({}) and s.validate_response({}, {})[1]


def test_the_registry_lists_six_working_types():
    assert {s.type for s in registry.all_types() if s.implemented} == {"form", "upload", "connect", "book_call", "approval", "internal_task"}
    assert registry.get("nope") is None
