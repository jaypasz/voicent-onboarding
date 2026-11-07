"""A small client for the AIOS app's REST API (projects and tasks). The service token travels as a header only. Errors
carry our own wording plus a status code, never the other side's text. Timeouts, 429 and 5xx are retried with a short
backoff, but only for calls that are safe to repeat. Creating a task and adding a comment are attempted once: if the reply
is lost the thing may already exist, and repeating the call would make a duplicate. (The sync finds a task again by its link
on the next pass.) Any other refusal is not retried, because asking again would get the same answer."""
from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Settings

RETRY_DELAYS = (0.5, 1.5)


class AiosError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


class AiosClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None, sleep=time.sleep):
        self.base = settings.aios_api_url.rstrip("/")
        self.token = settings.aios_service_token
        self.http = http or httpx.Client(timeout=10.0)
        self.sleep = sleep

    def _call(self, method: str, path: str, what: str, json: Any = None, params: dict | None = None, allow: tuple[int, ...] = (), retry: bool = True) -> httpx.Response:
        last_status = 0
        tries = len(RETRY_DELAYS) + 1 if retry else 1
        for attempt in range(tries):
            try:
                r = self.http.request(method, f"{self.base}/api{path}", json=json, params=params, headers={"Authorization": f"Bearer {self.token}"})
            except httpx.HTTPError:
                last_status = 0
            else:
                if r.status_code < 300 or r.status_code in allow:
                    return r
                last_status = r.status_code
                if r.status_code != 429 and r.status_code < 500:
                    raise AiosError(f"AIOS refused it ({what}, status {r.status_code}).", r.status_code)
            if attempt < tries - 1:
                self.sleep(RETRY_DELAYS[attempt])
        raise AiosError(f"AIOS didn't answer ({what}{', status ' + str(last_status) if last_status else ''}).", last_status)

    def create_project(self, body: dict) -> bool:
        """True if it was created, False if a project with that id was already there (which is fine)."""
        return self._call("POST", "/projects", "create project", json=body, allow=(409,)).status_code != 409

    def patch_project(self, project_id: str, body: dict) -> None:
        self._call("PATCH", f"/projects/{project_id}", "update project", json=body)

    def list_tasks(self, project_id: str) -> list[dict]:
        return self._call("GET", "/tasks", "list tasks", params={"project": project_id, "limit": 1000}).json()

    def create_task(self, body: dict) -> dict:
        return self._call("POST", "/tasks", "create task", json=body, retry=False).json()

    def patch_task(self, task_id: str, body: dict) -> None:
        self._call("PATCH", f"/tasks/{task_id}", "update task", json=body)

    def add_comment(self, task_id: str, text: str) -> None:
        self._call("POST", f"/tasks/{task_id}/comments", "add comment", json={"body": text}, retry=False)
