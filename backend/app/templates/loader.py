"""Validate, normalise, import and export template documents. Every problem is reported, not just the first."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from ..errors import TemplateInvalid
from ..steps import registry
from ..steps.base import schema_problems

SCHEMA = json.loads((Path(__file__).parent / "schema.json").read_text())
PRESET_DIR = Path(__file__).parent / "presets"
MAX_YAML_BYTES = 200_000


def validate_document(doc) -> list[str]:
    if not isinstance(doc, dict):
        return ["The template must be an object."]
    problems = schema_problems(SCHEMA, doc)
    if problems:
        return problems  # structure first: the checks below assume the shape is right
    section_keys = [s["key"] for s in doc.get("sections", [])]
    problems += [f"sections: '{k}' is used twice." for k in sorted({k for k in section_keys if section_keys.count(k) > 1})]
    seen: set[str] = set()
    for i, step in enumerate(doc["steps"]):
        where = f"steps[{i}] ('{step['key']}')"
        if step["key"] in seen:
            problems.append(f"{where}: the key is used twice.")
        seen.add(step["key"])
        if step.get("section") and step["section"] not in section_keys:
            problems.append(f"{where}.section: '{step['section']}' isn't one of the template's sections.")
        stype = registry.get(step["type"])
        if stype is None:
            known = ", ".join(t.type for t in registry.all_types() if t.implemented)
            problems.append(f"{where}.type: unknown step type '{step['type']}'. Available: {known}.")
            continue
        vis = step.get("visibility")
        if stype.client_visible and vis == "internal":
            problems.append(f"{where}.visibility: only internal_task steps can be internal.")
        if not stype.client_visible and vis == "client":
            problems.append(f"{where}.visibility: internal_task steps are never shown to clients.")
        problems += [f"{where}.config.{p}" if not p.startswith("The ") else f"{where}: {p}" for p in stype.validate_config(step.get("config", {}))]
    return problems


def normalise(doc: dict) -> dict:
    """Fill defaults so every stored document is complete. Call only on a document that validated."""
    out = copy.deepcopy(doc)
    out.setdefault("description", "")
    out.setdefault("sections", [])
    out.setdefault("nudge_after_days", 3)
    out.setdefault("on_complete", "none")
    for step in out["steps"]:
        stype = registry.get(step["type"])
        step.setdefault("description", "")
        step.setdefault("section", "")
        step["visibility"] = "client" if stype.client_visible else "internal"
        step.setdefault("assignee_role", "")
        step.setdefault("due_offset_days", None)
        step.setdefault("config", {})
        step.setdefault("show_if", None)
    return out


def check(doc) -> dict:
    """Validate and normalise, or raise TemplateInvalid listing every problem."""
    problems = validate_document(doc)
    if problems:
        raise TemplateInvalid(problems)
    return normalise(doc)


def parse_yaml(text: str) -> dict:
    if len(text.encode()) > MAX_YAML_BYTES:
        raise TemplateInvalid(["The YAML is too large (limit 200 KB)."])
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        line = f" (line {mark.line + 1})" if mark else ""
        raise TemplateInvalid([f"The YAML couldn't be read{line}: {getattr(e, 'problem', None) or 'syntax error'}."]) from None
    if not isinstance(doc, dict):
        raise TemplateInvalid(["The YAML must describe one template (a mapping at the top level)."])
    return doc


def export_yaml(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)


def load_presets() -> list[dict]:
    """The four shipped templates, validated and normalised. A broken preset fails loudly in the tests."""
    return [check(parse_yaml(p.read_text())) for p in sorted(PRESET_DIR.glob("*.yaml"))]
