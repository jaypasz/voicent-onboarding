from __future__ import annotations

from ..redact import redact
from .base import StepType


class InternalTask(StepType):
    """Jay's own side of the checklist. Never shown to a client."""

    type = "internal_task"
    client_visible = False
    config_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "notes": {"type": "string", "maxLength": 5000},
            "checklist": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 300}},
        },
    }

    def validate_response(self, config, data):
        if not isinstance(data, dict) or set(data) - {"note"} or not isinstance(data.get("note", ""), str) or len(data.get("note", "")) > 2000:
            return {}, ['Send {"note": optional text up to 2000 characters}.']
        return {"note": redact(data.get("note", "").strip())}, []
