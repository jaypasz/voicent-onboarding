"""The background jobs (reminders and AIOS sync) and the thread that runs them.

They run inside the web process because this is one small service. That means: run one instance. If it is ever scaled out,
reminders are still safe (a unique constraint refuses a second send of the same one) and so is the sync (it reconciles), but
the work would be repeated, so move them to a scheduled worker then. `python -m app.cli nudge` and `... sync` run the same
passes by hand or from a cron.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import sessionmaker

from . import aios_sync, nudges
from .aios import AiosClient
from .config import Settings
from .notify import Notifier

log = logging.getLogger("uvicorn.error")


def run_once(sm: sessionmaker, settings: Settings, notifier: Notifier | None = None, aios: AiosClient | None = None, now=None) -> dict:
    """One pass of every job. A failure in one is logged and never stops the others or the loop."""
    out: dict = {}
    try:
        s = nudges.run_nudges(sm, settings, notifier or Notifier(settings), now=now)
        out["reminders"] = {"enabled": s.enabled, "considered": s.considered, "sent": s.sent, "failed": s.failed, "flagged": s.flagged}
    except Exception:  # noqa: BLE001
        log.error("Reminder job failed", exc_info=True)
        out["reminders"] = {"error": True}
    try:
        out["aios"] = aios_sync.sync_dirty(sm, settings, aios)
    except Exception:  # noqa: BLE001
        log.error("AIOS sync job failed", exc_info=True)
        out["aios"] = {"error": True}
    return out


class Scheduler:
    def __init__(self, sm: sessionmaker, settings: Settings, first_delay_seconds: float = 30.0):
        self.sm, self.settings, self.first_delay = sm, settings, first_delay_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="onboarding-jobs", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        delay = self.first_delay
        while not self._stop.wait(delay):
            run_once(self.sm, self.settings)
            delay = self.settings.jobs_interval_minutes * 60
