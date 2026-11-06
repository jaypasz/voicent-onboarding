from __future__ import annotations

from .base import StepType

# Extension -> content type. SVG is deliberately absent: it can carry script.
ALLOWED_UPLOADS = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
    "pdf": "application/pdf", "mp4": "video/mp4", "mov": "video/quicktime", "csv": "text/csv", "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class Upload(StepType):
    type = "upload"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["accept"],
        "properties": {
            "prompt": {"type": "string", "maxLength": 1000},
            "accept": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": sorted(ALLOWED_UPLOADS)}},
            "max_mb": {"type": "integer", "minimum": 1, "maximum": 100},
            "min_files": {"type": "integer", "minimum": 0, "maximum": 20},
            "max_files": {"type": "integer", "minimum": 1, "maximum": 20},
        },
    }

    def extra_config_checks(self, config):
        if config.get("min_files", 1) > config.get("max_files", 5):
            return ["min_files can't be more than max_files."]
        return []

    def validate_response(self, config, data):
        ids = data.get("file_ids") if isinstance(data, dict) and set(data) == {"file_ids"} else None
        if not isinstance(ids, list) or not all(isinstance(i, str) and 0 < len(i) <= 36 for i in ids) or len(set(ids)) != len(ids):
            return {}, ['Send {"file_ids": [...]} with the ids of the uploaded files.']
        lo, hi = config.get("min_files", 1), config.get("max_files", 5)
        if len(ids) < lo:
            return {}, [f"Add at least {lo} file{'s' if lo != 1 else ''}."]
        if len(ids) > hi:
            return {}, [f"Add at most {hi} file{'s' if hi != 1 else ''}."]
        return {"file_ids": ids}, []
