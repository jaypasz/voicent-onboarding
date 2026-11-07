"""The background jobs: they run, a failure in one doesn't stop the other, and the thread starts and stops with the app."""
import threading
import time

from fastapi.testclient import TestClient

from app import jobs, nudges
from app.config import Settings
from app.main import create_app
from tests.helpers4 import BASE, NOON_ET, WHEN_STALE, make_world


def test_one_pass_runs_reminders_and_the_aios_sync():
    w, client = make_world()
    with client:
        _, oid, _ = w.live()
        w.aios.requests.clear()
        with w.sm() as db:  # a change AIOS hasn't heard about
            from app import models as m
            db.get(m.Onboarding, oid).sync_version += 1
            db.commit()
        out = jobs.run_once(w.sm, w.settings, w.notifier, w.app.state.aios, now=NOON_ET)
        assert out["aios"]["synced"] == 1
        assert out["reminders"]["enabled"] is True and out["reminders"]["considered"] == 1  # stale since WHEN_STALE, so it is reminded
        assert w.notifier.sms or w.notifier.emails


def test_a_failure_in_one_job_does_not_stop_the_other(monkeypatch):
    w, client = make_world()
    with client:
        _, oid, _ = w.live()
        with w.sm() as db:
            from app import models as m
            db.get(m.Onboarding, oid).sync_version += 1
            db.commit()
        monkeypatch.setattr(nudges, "run_nudges", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        out = jobs.run_once(w.sm, w.settings, w.notifier, w.app.state.aios)
        assert out["reminders"] == {"error": True} and out["aios"]["synced"] == 1


def test_with_nothing_configured_a_pass_does_nothing_and_says_so():
    w, client = make_world(twilio_account_sid="", twilio_auth_token="", twilio_from_number="", resend_api_key="", resend_from="", aios_api_url="", aios_service_token="")
    with client:
        out = jobs.run_once(w.sm, w.settings, w.notifier)
        assert out["reminders"]["enabled"] is False and out["aios"]["enabled"] is False


def test_the_scheduler_runs_the_jobs_and_stops_when_asked(monkeypatch):
    w, client = make_world()
    ran = threading.Event()
    monkeypatch.setattr(jobs, "run_once", lambda *a, **k: ran.set())
    s = jobs.Scheduler(w.sm, w.settings, first_delay_seconds=0.05)
    s.start()
    assert ran.wait(2.0)
    s.stop()
    s._thread.join(2.0)
    assert not s._thread.is_alive()


def test_the_jobs_thread_is_only_started_when_asked_and_stops_with_the_app(monkeypatch):
    monkeypatch.setattr(jobs, "run_once", lambda *a, **k: None)

    def names():
        return [t.name for t in threading.enumerate()]

    off = create_app(Settings(**{**BASE, "jobs_enabled": False}))
    with TestClient(off):
        assert "onboarding-jobs" not in names()
    on = create_app(Settings(**{**BASE, "jobs_enabled": True}))
    with TestClient(on):
        assert "onboarding-jobs" in names()
    for _ in range(40):  # the thread is told to stop when the app shuts down
        if "onboarding-jobs" not in names():
            break
        time.sleep(0.05)
    assert "onboarding-jobs" not in names()


def test_jobs_are_off_by_default_in_code_and_on_by_default_from_the_environment(monkeypatch):
    assert Settings().jobs_enabled is False  # tests and scripts never start a thread by accident
    monkeypatch.delenv("JOBS_ENABLED", raising=False)
    assert Settings.from_env().jobs_enabled is True
    monkeypatch.setenv("JOBS_ENABLED", "0")
    assert Settings.from_env().jobs_enabled is False


def test_the_cli_nudge_and_sync_commands_report_in_plain_words():
    from app import cli

    w, client = make_world()
    out: list[str] = []
    with client:
        w.live()
    # The CLI builds its own session factory from DATABASE_URL, so check the wording against an unconfigured instance.
    cli.run_nudge(Settings(database_url="sqlite://", auth_disabled=True, app_env="local"), dry_run=True, out=out.append)
    cli.run_sync(Settings(database_url="sqlite://", auth_disabled=True, app_env="local"), out=out.append)
    assert "Reminders are off" in out[0] and "APP_URL" in out[0]
    assert "AIOS sync is off" in out[1] and "AIOS_API_URL" in out[1]


def test_settings_for_the_new_features_are_checked():
    import pytest

    for bad in ({"nudge_max": 0}, {"jobs_interval_minutes": 0}, {"nudge_retry_hours": 0}, {"nudge_quiet_start": 24}, {"nudge_quiet_end": -1}):
        with pytest.raises(RuntimeError):
            Settings(**{**BASE, **bad}).validate()
    s = Settings(**{**BASE, "default_timezone": "Mars/Base", "app_url": ""})
    warnings = " ".join(s.optional_warnings())
    assert "APP_URL" in warnings and "DEFAULT_TIMEZONE" in warnings  # warnings only: a bad optional setting never stops the app
    assert s.reminders_enabled is False
    create_app(s)
