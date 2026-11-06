from __future__ import annotations

from ..redact import redact
from .base import StepType


class Approval(StepType):
    type = "approval"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["deliverable"],
        "properties": {
            "prompt": {"type": "string", "maxLength": 1000},
            "deliverable": {
                "type": "object", "additionalProperties": False, "required": ["kind"],
                "properties": {
                    "kind": {"enum": ["text", "link", "file"]},
                    "text": {"type": "string", "minLength": 1, "maxLength": 5000},
                    "url": {"type": "string", "pattern": r"^https://\S+$", "maxLength": 500},
                    "file_name": {"type": "string", "minLength": 1, "maxLength": 300},
                },
            },
        },
    }
    NEEDS = {"text": "text", "link": "url", "file": "file_name"}

    def extra_config_checks(self, config):
        d = config["deliverable"]
        need = self.NEEDS[d["kind"]]
        out = [f"deliverable.{need}: a '{d['kind']}' deliverable needs {need}."] if need not in d else []
        out += [f"deliverable.{k}: not used by a '{d['kind']}' deliverable." for k in ("text", "url", "file_name") if k in d and k != need]
        return out

    def validate_response(self, config, data):
        if not isinstance(data, dict) or set(data) - {"decision", "comment"} or data.get("decision") not in ("approved", "changes_requested"):
            return {}, ["decision must be 'approved' or 'changes_requested'."]
        comment = data.get("comment", "")
        if not isinstance(comment, str) or len(comment) > 2000:
            return {}, ["comment must be text up to 2000 characters."]
        if data["decision"] == "changes_requested" and not comment.strip():
            return {}, ["Say what should change."]
        return {"decision": data["decision"], "comment": redact(comment.strip())}, []

    def resulting_status(self, config, cleaned):
        # Changes requested reopens the step: it waits on Jay to revise, not on the client.
        return "done" if cleaned["decision"] == "approved" else "in_progress"
