from __future__ import annotations

from ..redact import redact
from .base import KEY, StepType


class Connect(StepType):
    """Records that an integration is connected, or that access was delegated. Never holds a token or password."""

    type = "connect"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["provider", "label"],
        "properties": {
            "provider": {"type": "string", "pattern": KEY},
            "label": {"type": "string", "minLength": 1, "maxLength": 200},
            "access_mode": {"enum": ["oauth", "delegated"]},
            "start_url": {"type": "string", "pattern": r"^https://\S+$", "maxLength": 500},
            "instructions": {"type": "string", "maxLength": 2000},
        },
    }

    def validate_response(self, config, data):
        if not isinstance(data, dict) or set(data) - {"status", "account_label"}:
            return {}, ["Connect steps record a status and an account label only; never send tokens or passwords."]
        status, label = data.get("status"), data.get("account_label", "")
        if status not in ("connected", "pending"):
            return {}, ["status must be 'connected' or 'pending'."]
        if not isinstance(label, str) or len(label) > 200:
            return {}, ["account_label must be text up to 200 characters."]
        if status == "connected" and not label.strip():
            return {}, ["Say which account was connected."]
        return {"status": status, "account_label": redact(label.strip())}, []

    def resulting_status(self, config, cleaned):
        return "done" if cleaned["status"] == "connected" else "in_progress"
