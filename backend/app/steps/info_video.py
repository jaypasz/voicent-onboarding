from __future__ import annotations

from .. import embeds
from .base import StepType


class InfoVideo(StepType):
    """"Watch or read": one video or document from another tool (a Loom, a YouTube video, a Figma file, a Google Doc, a Notion
    page), shown inside the step when the provider allows it and as a link otherwise. The client says they've seen it."""

    type = "info_video"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["url"],
        "properties": {
            "url": {"type": "string", "pattern": r"^https://\S+$", "maxLength": 500},
            "instructions": {"type": "string", "maxLength": 2000},
        },
    }

    def extra_config_checks(self, config):
        return [] if embeds.describe(config["url"]) else ["url: use a plain https address (no user name, password or port)."]

    def validate_response(self, config, data):
        if not isinstance(data, dict) or set(data) != {"seen"} or data["seen"] is not True:
            return {}, ['Send {"seen": true} once it has been watched or read.']
        return {"seen": True}, []
