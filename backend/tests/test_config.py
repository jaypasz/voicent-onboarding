import logging

from app.config import Settings
from app.main import create_app

LOCAL = dict(database_url="sqlite://", auth_disabled=True, app_env="local")


def test_half_set_optional_features_warn_and_never_stop_startup(caplog):
    s = Settings(**LOCAL, twilio_account_sid="AC1", resend_api_key="re_x", aios_api_url="http://insecure", supabase_url="http://x")
    assert len(s.optional_warnings()) >= 4
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        create_app(s)  # must not raise
    assert not s.sms_enabled and not s.email_enabled and not s.aios_sync_enabled and not s.uploads_enabled


def test_fully_set_features_are_enabled_without_warnings():
    s = Settings(
        **LOCAL, twilio_account_sid="AC1", twilio_auth_token="t", twilio_from_number="+15551234567",
        resend_api_key="re_x", resend_from="Voicent <hi@example.com>",
        aios_api_url="https://aios.example.com", aios_service_token="x" * 24,
        supabase_url="https://p.supabase.co", supabase_service_key="k",
    )
    assert s.optional_warnings() == []
    assert s.sms_enabled and s.email_enabled and s.aios_sync_enabled and s.uploads_enabled


def test_vite_supabase_url_is_not_read_as_an_uploads_signal(monkeypatch):
    monkeypatch.setenv("VITE_SUPABASE_URL", "https://p.supabase.co")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert Settings.from_env().supabase_url == ""


def test_service_key_aliases(monkeypatch):
    for n in ("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "abc")
    assert Settings.from_env().supabase_service_key == "abc"
