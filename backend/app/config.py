from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


# The same secret goes by several names: Supabase's own dashboard and most templates say SERVICE_ROLE.
SERVICE_KEY_NAMES = ("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY")


_PROCESS_KEY = ""


def valid_timezone(name: str) -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(name)
        return bool(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def _make_process_key(value: str) -> str:
    global _PROCESS_KEY
    _PROCESS_KEY = value
    return value


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
    # Magic links and the short-lived portal session they are exchanged for.
    link_ttl_days: int = 30
    session_ttl_minutes: int = 30
    # Signs portal session tokens. Unset: derived from SUPABASE_JWT_SECRET if there is one, else random per process
    # (clients then reopen their link after a restart).
    portal_signing_key: str = ""
    # Portal rate limits, per minute. Exchange is limited per client address and across everyone; writes per link.
    rate_exchange_per_ip: int = 20
    rate_exchange_global: int = 300
    rate_writes_per_link: int = 60
    # Nudges. SMS through Twilio, email through Resend. Either can be left unset.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    resend_api_key: str = ""
    resend_from: str = ""
    # One-way sync into the AIOS app (projects and tasks).
    aios_api_url: str = ""
    aios_service_token: str = ""
    # Background jobs (reminders and AIOS sync) run inside the web process every few minutes. Off unless from_env turns
    # them on, so tests and scripts never start a thread by accident. Run one instance of the service.
    jobs_enabled: bool = False
    jobs_interval_minutes: int = 15
    # Reminders: at most nudge_max automatic rounds, never texting between quiet_start and quiet_end (the client's local hours),
    # and retry a failed send no sooner than retry_hours.
    nudge_max: int = 3
    nudge_quiet_start: int = 21
    nudge_quiet_end: int = 8
    nudge_retry_hours: int = 6
    default_timezone: str = "America/New_York"
    brand_name: str = "Voicent"

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
        if not self.portal_signing_key and not self.supabase_jwt_secret:
            out.append("Client sessions: set PORTAL_SIGNING_KEY so portal sessions survive a restart. Using a random key for now.")
        if self.portal_signing_key and len(self.portal_signing_key) < 24:
            out.append("Client sessions: PORTAL_SIGNING_KEY is shorter than 24 characters. Using a random key until it is longer.")
        if (self.sms_enabled or self.email_enabled) and not self.app_url:
            out.append("Reminders: set APP_URL (the public address of this service) so reminders can carry a link. Reminders are off until then.")
        if not valid_timezone(self.default_timezone):
            out.append(f"DEFAULT_TIMEZONE '{self.default_timezone}' isn't a time zone name. Using America/New_York.")
        if self.aios_api_url and not self.aios_api_url.startswith("https://"):
            out.append("AIOS sync: AIOS_API_URL must be an https:// URL. Sync is off until it is.")
        return out

    def portal_key(self) -> str:
        """The key that signs portal session tokens. Never the same value as the Supabase JWT secret."""
        import hashlib
        import secrets

        if len(self.portal_signing_key) >= 24:
            return self.portal_signing_key
        if self.supabase_jwt_secret:
            return hashlib.sha256(("portal-session|" + self.supabase_jwt_secret).encode()).hexdigest()
        return _PROCESS_KEY or _make_process_key(secrets.token_hex(32))

    @property
    def reminders_enabled(self) -> bool:
        """Reminders need a way to send and an address to put in the message."""
        return (self.sms_enabled or self.email_enabled) and self.app_url.startswith(("https://", "http://"))

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
            session_ttl_minutes=int(e("SESSION_TTL_MINUTES", "30")),
            portal_signing_key=e("PORTAL_SIGNING_KEY", "").strip(),
            rate_exchange_per_ip=int(e("RATE_EXCHANGE_PER_IP", "20")),
            rate_exchange_global=int(e("RATE_EXCHANGE_GLOBAL", "300")),
            rate_writes_per_link=int(e("RATE_WRITES_PER_LINK", "60")),
            twilio_account_sid=e("TWILIO_ACCOUNT_SID", "").strip(),
            twilio_auth_token=e("TWILIO_AUTH_TOKEN", "").strip(),
            twilio_from_number=e("TWILIO_FROM_NUMBER", "").strip(),
            resend_api_key=e("RESEND_API_KEY", "").strip(),
            resend_from=e("RESEND_FROM", "").strip(),
            aios_api_url=e("AIOS_API_URL", "").rstrip("/"),
            aios_service_token=e("AIOS_SERVICE_TOKEN", "").strip(),
            jobs_enabled=e("JOBS_ENABLED", "1") != "0",
            jobs_interval_minutes=int(e("JOBS_INTERVAL_MINUTES", "15")),
            nudge_max=int(e("NUDGE_MAX", "3")),
            nudge_quiet_start=int(e("NUDGE_QUIET_START", "21")),
            nudge_quiet_end=int(e("NUDGE_QUIET_END", "8")),
            nudge_retry_hours=int(e("NUDGE_RETRY_HOURS", "6")),
            default_timezone=e("DEFAULT_TIMEZONE", "America/New_York").strip(),
            brand_name=e("BRAND_NAME", "Voicent").strip() or "Voicent",
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
        if self.jobs_interval_minutes < 1 or self.nudge_max < 1 or self.nudge_retry_hours < 1:
            raise RuntimeError("JOBS_INTERVAL_MINUTES, NUDGE_MAX and NUDGE_RETRY_HOURS must be at least 1.")
        if not (0 <= self.nudge_quiet_start <= 23 and 0 <= self.nudge_quiet_end <= 23):
            raise RuntimeError("NUDGE_QUIET_START and NUDGE_QUIET_END must be hours from 0 to 23.")
        if self.session_ttl_minutes < 1:
            raise RuntimeError("SESSION_TTL_MINUTES must be at least 1.")
        if min(self.rate_exchange_per_ip, self.rate_exchange_global, self.rate_writes_per_link) < 1:
            raise RuntimeError("Rate limits must be at least 1 per minute.")
