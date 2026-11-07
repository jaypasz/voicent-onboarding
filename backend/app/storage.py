"""Client uploads live in a private Supabase Storage bucket. The browser uploads straight to a signed URL, so file
bytes never pass through this service. The service key travels as a header only; error text from Supabase is never
passed on, only our own wording and a status code.

Not verified against a live Supabase project yet: the three REST calls below follow Supabase's documented storage API.
"""
from __future__ import annotations

import posixpath
import re
import uuid
from urllib.parse import quote

import httpx

from .config import Settings
from .errors import ServiceError
from .steps.upload import ALLOWED_UPLOADS


class StorageError(ServiceError):
    status_code = 502


class UploadsOff(ServiceError):
    status_code = 503


def safe_name(name: str) -> str:
    """A filename that can't climb out of its folder or smuggle characters into a path."""
    base = posixpath.basename(name.replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:120].strip(" .")
    return base or "file"


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def storage_path(org_id: str, onboarding_id: str, step_id: str, name: str) -> str:
    return f"{org_id}/{onboarding_id}/{step_id}/{uuid.uuid4().hex}-{safe_name(name)}"


class Storage:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.http = client or httpx.Client(timeout=15.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.s.supabase_service_key}", "apikey": self.s.supabase_service_key}

    def _url(self, *parts: str) -> str:
        return f"{self.s.supabase_url}/storage/v1/" + "/".join(parts)

    def _call(self, method: str, url: str, what: str, **kw) -> httpx.Response:
        try:
            return self.http.request(method, url, headers=self._headers(), **kw)
        except httpx.HTTPError:
            raise StorageError(f"File storage didn't answer ({what}). Try again in a minute.") from None

    def signed_upload(self, path: str) -> dict:
        r = self._call("POST", self._url("object", "upload", "sign", self.s.upload_bucket, quote(path)), "prepare upload")
        if r.status_code >= 300:
            raise StorageError(f"File storage refused the upload (status {r.status_code}).")
        try:
            body = r.json()
            return {"url": self.s.supabase_url + "/storage/v1" + body["url"] if str(body["url"]).startswith("/") else body["url"], "token": body.get("token", "")}
        except (ValueError, KeyError, TypeError):
            raise StorageError("File storage gave an unexpected answer (prepare upload).") from None

    def info(self, path: str) -> dict | None:
        """Metadata for an uploaded object, or None if it isn't there."""
        r = self._call("GET", self._url("object", "info", self.s.upload_bucket, quote(path)), "check upload")
        if r.status_code == 404 or r.status_code == 400:
            return None
        if r.status_code >= 300:
            raise StorageError(f"File storage couldn't check the file (status {r.status_code}).")
        try:
            return r.json()
        except ValueError:
            return {}

    def signed_download(self, path: str, ttl: int = 600) -> str:
        r = self._call("POST", self._url("object", "sign", self.s.upload_bucket, quote(path)), "prepare download", json={"expiresIn": ttl})
        if r.status_code >= 300:
            raise StorageError(f"File storage couldn't prepare the download (status {r.status_code}).")
        try:
            u = r.json()["signedURL"]
        except (ValueError, KeyError, TypeError):
            raise StorageError("File storage gave an unexpected answer (prepare download).") from None
        return self.s.supabase_url + "/storage/v1" + u if u.startswith("/") else u


def check_upload_request(config: dict, name: str, size: int, content_type: str) -> None:
    """Refuse a file the step doesn't allow, before any URL is issued."""
    from .errors import Invalid

    ext = extension(name)
    if ext not in config.get("accept", []):
        allowed = ", ".join(config.get("accept", []))
        raise Invalid(f"That file type isn't allowed here. Allowed: {allowed}.")
    if ALLOWED_UPLOADS.get(ext) != content_type:
        raise Invalid("The file's type doesn't match its name.")
    limit = config.get("max_mb", 10) * 1024 * 1024
    if not 0 < size <= limit:
        raise Invalid(f"Files can be up to {config.get('max_mb', 10)} MB.")
