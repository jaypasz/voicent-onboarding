from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


# The same secret goes by several names: Supabase's own dashboard and most templates say SERVICE_ROLE.
SERVICE_KEY_NAMES = ("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY")


@dataclass(frozen=True)
class Settings:
    """Everything the app reads from the environment, in one place."""

    database_url: str = "sqlite:///./onboarding.db"
    # Admin login: Supabase signs user JWTs with an asymmetric key (published at the JWKS URL) or the legacy HS256 secret.
    supabase_jwks_url: str = ""
    supabase_jwt_secret: str = ""
    # Long random tokens for scheduled jobs and tests. Compared in constant time.
    service_tokens: list[str] = field(default_factory=list)
    cors_origins: list[str] = field(default_factory=list)
    # Only honoured when app_env is "local". Anywhere else the app refuses to start.
    auth_disabled: bool = False
    app_env: str = "production"
    static_dir: str = ""  # built frontend to serve at /. Empty in local dev (Vite serves it)
    app_url: str = ""  # public base URL, used to build client links
    # Client file uploads: a private Supabase Storage bucket.
    supabase_url: str = ""
    supabase_service_key: str = ""
    upload_bucket: str = "onboarding-files"
    # Magic links.
    link_ttl_days: int = 30
    # Nudges. SMS through Twilio, email through Resend. Either can be left unset.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    resend_api_key: str = ""
    resend_from: str = ""
    # One-way sync into the AIOS app (projects and tasks).
    aios_api_url: str = ""
    aios_service_token: str = ""

    def optional_warnings(self) -> list[str]:
        """Problems with optional settings. They switch a feature off; they never stop the app starting."""
        out = []
        if bool(self.supabase_url) != bool(self.supabase_service_key):
            out.append("Uploads: set both SUPABASE_URL and SUPABASE_SERVICE_KEY to enable file uploads. Uploads are off until then.")
        if self.supabase_url and not self.supabase_url.startswith("https://"):
            out.append("Uploads: SUPABASE_URL must be an https:// URL. Uploads are off until it is.")
        sms = [self.twilio_account_sid, self.twilio_auth_token, self.twilio_from_number]
        if any(sms) and not all(sms):
            out.append("SMS nudges: set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER together. SMS is off until then.")
        if bool(self.resend_api_key) != bool(self.resend_from):
            out.append("Email nudges: set both RESEND_API_KEY and RESEND_FROM. Email is off until then.")
        if bool(self.aios_api_url) != bool(self.aios_service_token):
            out.append("AIOS sync: set both AIOS_API_URL and AIOS_SERVICE_TOKEN. Sync is off until then.")
        if self.aios_api_url and not self.aios_api_url.startswith("https://"):
            out.append("AIOS sync: AIOS_API_URL must be an https:// URL. Sync is off until it is.")
        return out

    @property
    def uploads_enabled(self) -> bool:
        return bool(self.supabase_url.startswith("https://") and self.supabase_service_key)

    @property
    def sms_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.resend_from)

    @property
    def aios_sync_enabled(self) -> bool:
        return bool(self.aios_api_url.startswith("https://") and self.aios_service_token)

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            database_url=e("DATABASE_URL", "sqlite:///./onboarding.db"),
            supabase_jwks_url=e("SUPABASE_JWKS_URL", ""),
            supabase_jwt_secret=e("SUPABASE_JWT_SECRET", ""),
            service_tokens=_csv(e("SERVICE_TOKENS", "")),
            cors_origins=_csv(e("CORS_ORIGINS", "http://localhost:5173")),
            auth_disabled=e("AUTH_DISABLED", "") == "1",
            app_env=e("APP_ENV", "production"),
            static_dir=e("STATIC_DIR", ""),
            app_url=e("APP_URL", "").rstrip("/"),
            supabase_url=e("SUPABASE_URL", "").rstrip("/"),  # not VITE_SUPABASE_URL: that one is set for login and says nothing about uploads
            supabase_service_key=next((v for n in SERVICE_KEY_NAMES if (v := e(n, "").strip())), ""),
            upload_bucket=e("UPLOAD_BUCKET", "onboarding-files"),
            link_ttl_days=int(e("LINK_TTL_DAYS", "30")),
            twilio_account_sid=e("TWILIO_ACCOUNT_SID", "").strip(),
            twilio_auth_token=e("TWILIO_AUTH_TOKEN", "").strip(),
            twilio_from_number=e("TWILIO_FROM_NUMBER", "").strip(),
            resend_api_key=e("RESEND_API_KEY", "").strip(),
            resend_from=e("RESEND_FROM", "").strip(),
            aios_api_url=e("AIOS_API_URL", "").rstrip("/"),
            aios_service_token=e("AIOS_SERVICE_TOKEN", "").strip(),
        )

    def validate(self) -> None:
        """Only settings the whole app depends on are fatal. Optional features warn instead (see optional_warnings)."""
        if self.auth_disabled and self.app_env != "local":
            raise RuntimeError("AUTH_DISABLED=1 is only allowed when APP_ENV=local.")
        if not self.auth_disabled and not (self.supabase_jwks_url or self.supabase_jwt_secret or self.service_tokens):
            raise RuntimeError(
                "Set SUPABASE_JWKS_URL, SUPABASE_JWT_SECRET or SERVICE_TOKENS, or run with APP_ENV=local AUTH_DISABLED=1."
            )
        if self.supabase_jwks_url and not self.supabase_jwks_url.startswith("https://"):
            raise RuntimeError("SUPABASE_JWKS_URL must be an https:// URL.")
        for t in self.service_tokens:
            if len(t) < 24:
                raise RuntimeError("Each service token must be at least 24 characters.")
        if self.link_ttl_days < 1:
            raise RuntimeError("LINK_TTL_DAYS must be at least 1.")
