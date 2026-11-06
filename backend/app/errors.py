"""Expected failures. Routers turn these into plain HTTP answers; anything else is a bug and shows only a generic error."""
from __future__ import annotations


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.problems = problems or []


class NotFound(ServiceError):
    status_code = 404


class Forbidden(ServiceError):
    status_code = 403


class Conflict(ServiceError):
    status_code = 409


class Invalid(ServiceError):
    status_code = 422


class TemplateInvalid(Invalid):
    """A template document that failed validation. `problems` lists every one, not just the first."""

    def __init__(self, problems: list[str]):
        super().__init__("The template has problems.", problems)
