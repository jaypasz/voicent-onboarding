from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlparse

from ..redact import redact
from .base import KEY, StepType

FIELD_TYPES = ("text", "textarea", "select", "multiselect", "phone", "email", "url", "date", "checkbox")
PHONE = re.compile(r"^\+?[0-9 ()\-.]{7,20}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LEN = {"text": 500, "textarea": 5000, "email": 200, "url": 500}


def _empty(v) -> bool:
    return v is None or v == "" or v == []


class Form(StepType):
    type = "form"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["fields"],
        "properties": {
            "intro": {"type": "string", "maxLength": 2000},
            "fields": {
                "type": "array", "minItems": 1, "maxItems": 40,
                "items": {
                    "type": "object", "additionalProperties": False, "required": ["key", "label", "type"],
                    "properties": {
                        "key": {"type": "string", "pattern": KEY},
                        "label": {"type": "string", "minLength": 1, "maxLength": 200},
                        "type": {"enum": list(FIELD_TYPES)},
                        "required": {"type": "boolean"},
                        "help": {"type": "string", "maxLength": 500},
                        "options": {"type": "array", "minItems": 1, "maxItems": 50, "items": {"type": "string", "minLength": 1, "maxLength": 100}},
                    },
                },
            },
        },
    }

    def extra_config_checks(self, config):
        out, seen = [], set()
        for i, f in enumerate(config["fields"]):
            where = f"fields[{i}]"
            if f["key"] in seen:
                out.append(f"{where}.key: '{f['key']}' is used twice.")
            seen.add(f["key"])
            has_options = f["type"] in ("select", "multiselect")
            if has_options and not f.get("options"):
                out.append(f"{where}.options: a {f['type']} field needs at least one option.")
            if not has_options and "options" in f:
                out.append(f"{where}.options: only select and multiselect fields take options.")
        return out

    def validate_response(self, config, data):
        if not isinstance(data, dict) or set(data) - {"answers"} or not isinstance(data.get("answers"), dict):
            return {}, ['Send {"answers": {...}}.']
        answers, fields, problems, clean = data["answers"], {f["key"]: f for f in config["fields"]}, [], {}
        for k in answers:
            if k not in fields:
                problems.append(f"'{k}' isn't a question on this form.")
        for key, f in fields.items():
            label, v = f["label"], answers.get(key)
            if f["type"] == "checkbox":
                if v is not None and not isinstance(v, bool):
                    problems.append(f"{label}: must be true or false.")
                elif f.get("required") and v is not True:
                    problems.append(f"{label}: this needs to be ticked.")
                elif v is not None:
                    clean[key] = v
                continue
            if _empty(v):
                if f.get("required"):
                    problems.append(f"{label}: this is required.")
                continue
            value, err = self._clean(f, v)
            if err:
                problems.append(f"{label}: {err}")
            else:
                clean[key] = value
        return ({"answers": clean} if not problems else {}), problems

    @staticmethod
    def _clean(f, v):
        t = f["type"]
        if t == "multiselect":
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                return None, "pick from the list."
            if len(set(v)) != len(v) or any(x not in f["options"] for x in v):
                return None, "pick only from the listed options."
            return v, None
        if not isinstance(v, str):
            return None, "must be text."
        v = v.strip()
        if len(v) > MAX_LEN.get(t, 100):
            return None, f"too long (max {MAX_LEN.get(t, 100)} characters)."
        if t in ("text", "textarea"):
            return redact(v), None
        if t == "select":
            return (v, None) if v in f["options"] else (None, "pick one of the listed options.")
        if t == "phone":
            return (v, None) if PHONE.match(v) else (None, "doesn't look like a phone number.")
        if t == "email":
            return (v, None) if EMAIL.match(v) else (None, "doesn't look like an email address.")
        if t == "url":
            u = urlparse(v)
            return (v, None) if u.scheme in ("http", "https") and u.netloc else (None, "must be a web address starting with http:// or https://.")
        if t == "date":
            try:
                dt.date.fromisoformat(v)
            except ValueError:
                return None, "use the format YYYY-MM-DD."
            return v, None
        return None, "unsupported field type."
