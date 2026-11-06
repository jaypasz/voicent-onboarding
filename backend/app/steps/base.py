"""The contract every step type fulfils. One backend file per type, one renderer per type in the frontend."""
from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

KEY = r"^[a-z][a-z0-9_]{0,63}$"


def schema_problems(schema: dict, instance: Any, prefix: str = "") -> list[str]:
    """Every JSON Schema violation as one readable line each, in a stable order."""
    out = []
    for err in sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: [str(p) for p in e.absolute_path]):
        path = ""
        for p in err.absolute_path:
            path += f"[{p}]" if isinstance(p, int) else f".{p}"
        where = (prefix + path).lstrip(".")
        out.append(f"{where}: {err.message}" if where else err.message)
    return out


class StepType:
    type: str = ""
    implemented: bool = True
    client_visible: bool = True
    config_schema: dict = {"type": "object"}

    # --- template side ---
    def validate_config(self, config: Any) -> list[str]:
        problems = schema_problems(self.config_schema, config)
        return problems or self.extra_config_checks(config)

    def extra_config_checks(self, config: dict) -> list[str]:
        return []

    # --- response side ---
    def validate_response(self, config: dict, data: Any) -> tuple[dict, list[str]]:
        """Returns (cleaned data to store, problems). Free text is redacted here, before it is stored."""
        raise NotImplementedError

    def resulting_status(self, config: dict, cleaned: dict) -> str:
        """The step's status once this response is accepted: done, or in_progress when more is needed."""
        return "done"

    def describe(self) -> dict:
        return {"type": self.type, "implemented": self.implemented, "client_visible": self.client_visible, "config_schema": self.config_schema}
