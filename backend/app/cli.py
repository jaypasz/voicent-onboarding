"""Command line for setup tasks the web app doesn't do.

  python -m app.cli seed --org-name Voicent --org-slug voicent --admin-user-id <supabase user id> --admin-email jay@example.com
  python -m app.cli presets --org-slug voicent
  python -m app.cli nudge [--dry-run]     # one pass of client reminders (the web service already does this on a timer)
  python -m app.cli sync                  # one pass of the AIOS sync

Needs DATABASE_URL (the same variable the server reads). Safe to run twice.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from . import models as m
from . import services
from .config import Settings
from .db import Base, make_engine


def _session(settings: Settings):
    engine = make_engine(settings.database_url)
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)()


def seed(settings: Settings, org_name: str, org_slug: str, admin_user_id: str = "", admin_email: str = "", out=print) -> str:
    with _session(settings) as db:
        org = services.get_or_create_org(db, org_name, org_slug)
        if admin_user_id:
            services.add_member(db, org.id, admin_user_id, admin_email)
            out(f"Member {admin_email or admin_user_id} can sign in to {org.name}.")
        added = services.install_presets(db, org.id)
        out(f"Org '{org.name}' ({org.slug}) ready. Presets added: {', '.join(added) if added else 'none (already there)'}.")
        db.commit()
        return org.id


def presets(settings: Settings, org_slug: str, out=print) -> list[str]:
    with _session(settings) as db:
        org = db.scalar(select(m.Org).where(m.Org.slug == org_slug))
        if not org:
            raise SystemExit(f"No org with slug '{org_slug}'. Run seed first.")
        added = services.install_presets(db, org.id)
        db.commit()
        out(f"Presets added: {', '.join(added) if added else 'none (already there)'}.")
        return added


def run_nudge(settings: Settings, dry_run: bool, out=print) -> None:
    from .nudges import run_nudges
    from .notify import Notifier

    engine = make_engine(settings.database_url)
    summary = run_nudges(sessionmaker(engine, expire_on_commit=False), settings, Notifier(settings), dry_run=dry_run)
    if not summary.enabled:
        out("Reminders are off: they need APP_URL and either Twilio or Resend settings.")
        return
    out(f"{'Would remind' if dry_run else 'Reminded'}: {summary.sent} contact(s) across {summary.considered} onboarding(s); {summary.failed} failed; {summary.flagged} flagged for attention.")
    for line in summary.details:
        out(f"  {line}")


def run_sync(settings: Settings, out=print) -> None:
    from .aios_sync import sync_dirty

    engine = make_engine(settings.database_url)
    r = sync_dirty(sessionmaker(engine, expire_on_commit=False), settings)
    out("AIOS sync is off: set AIOS_API_URL and AIOS_SERVICE_TOKEN." if not r["enabled"] else f"AIOS sync: {r['synced']} up to date, {r['failed']} failed.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="create the org, link a Supabase user to it and install the preset templates")
    s.add_argument("--org-name", required=True)
    s.add_argument("--org-slug", required=True)
    s.add_argument("--admin-user-id", default="", help="the user's id in Supabase Auth (Authentication > Users)")
    s.add_argument("--admin-email", default="")
    pr = sub.add_parser("presets", help="add any missing preset templates to an org")
    pr.add_argument("--org-slug", required=True)
    nd = sub.add_parser("nudge", help="run one pass of client reminders")
    nd.add_argument("--dry-run", action="store_true", help="say who would be reminded, send nothing")
    sub.add_parser("sync", help="run one pass of the AIOS sync")
    a = p.parse_args(argv)
    settings = Settings.from_env()
    if a.cmd == "nudge":
        run_nudge(settings, a.dry_run)
    elif a.cmd == "sync":
        run_sync(settings)
    elif a.cmd == "seed":
        seed(settings, a.org_name, a.org_slug, a.admin_user_id, a.admin_email)
    else:
        presets(settings, a.org_slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
