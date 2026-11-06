from __future__ import annotations

import datetime as dt

from .base import StepType


class BookCall(StepType):
    type = "book_call"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["url"],
        "properties": {
            "url": {"type": "string", "pattern": r"^https://\S+$", "maxLength": 500},
            "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 240},
            "instructions": {"type": "string", "maxLength": 1000},
        },
    }

    def validate_response(self, config, data):
        if not isinstance(data, dict) or set(data) - {"booked", "when"} or not isinstance(data.get("booked"), bool):
            return {}, ['Send {"booked": true or false, "when": optional date and time}.']
        out = {"booked": data["booked"]}
        when = data.get("when")
        if when is not None:
            try:
                dt.datetime.fromisoformat(str(when))
            except ValueError:
                return {}, ["when must be a date and time like 2026-11-20T14:00."]
            out["when"] = str(when)
        return out, []

    def resulting_status(self, config, cleaned):
        return "done" if cleaned["booked"] else "in_progress"
