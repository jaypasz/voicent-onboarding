from __future__ import annotations

from ..redact import redact
from .base import StepType


class Task(StepType):
    """Something to do, by the client or by us. `audience` decides who: a client task is in their portal, a team task never is.
    A checklist is ticked item by item; the task is done when every item is ticked, or when it is marked done."""

    type = "task"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["audience"],
        "properties": {
            "audience": {"enum": ["client", "team"]},
            "instructions": {"type": "string", "maxLength": 5000},
            "checklist": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 300}},
        },
    }

    def visibility_for(self, config: dict) -> str:
        return "client" if (config or {}).get("audience") == "client" else "internal"

    def validate_response(self, config, data):
        if not isinstance(data, dict) or set(data) - {"checked", "done", "note"}:
            return {}, ['Send {"checked": [item numbers], "done": true or false, "note": optional text}.']
        note = data.get("note", "")
        if not isinstance(note, str) or len(note) > 2000:
            return {}, ["note must be text up to 2000 characters."]
        checklist = config.get("checklist") or []
        checked = data.get("checked")
        if checked is not None and (not isinstance(checked, list) or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(checklist) for i in checked)):
            return {}, ["checked must list item numbers from the checklist."]
        done = data.get("done")
        if done is not None and not isinstance(done, bool):
            return {}, ["done must be true or false."]
        ticked = sorted(set(checked or []))
        if done is None:
            # A bare note (the team's "Mark done") finishes it; ticking items finishes it when the last one is ticked.
            done = True if checked is None else bool(checklist) and len(ticked) == len(checklist)
        if done and checklist and config.get("audience") == "client" and len(ticked) != len(checklist):
            return {}, ["Tick every item before marking this done."]
        out: dict = {"done": done, "note": redact(note.strip())}
        if checklist:
            out["checked"] = ticked
        return out, []

    def resulting_status(self, config, cleaned):
        if cleaned.get("done"):
            return "done"
        return "in_progress"
