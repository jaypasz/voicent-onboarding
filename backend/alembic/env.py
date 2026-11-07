from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registers the tables on Base.metadata)
from app.db import Base, make_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata
URL = os.environ.get("DATABASE_URL", "sqlite:///./onboarding.db")


def run_migrations_offline() -> None:
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True, render_as_batch=URL.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(URL)
    sqlite = URL.startswith("sqlite")
    with engine.connect() as conn:
        if sqlite:
            # SQLite alters a table by rebuilding it. With foreign keys enforced, dropping the old table would cascade-delete
            # every child row (an onboarding's steps, a client's contacts). Switch enforcement off for the migration, as
            # Alembic's batch-mode guide advises. It can't be changed inside a transaction, so this comes first.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()  # end the transaction that call started, so the migration gets (and commits) its own
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=sqlite)
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
