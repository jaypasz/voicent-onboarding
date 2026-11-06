"""Command line for setup tasks the web app doesn't do.

  python -m app.cli seed --org-name Voicent --org-slug voicent --admin-user-id <supabase user id> --admin-email jay@example.com
  python -m app.cli presets --org-slug voicent

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
    a = p.parse_args(argv)
    settings = Settings.from_env()
    if a.cmd == "seed":
        seed(settings, a.org_name, a.org_slug, a.admin_user_id, a.admin_email)
    else:
        presets(settings, a.org_slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
