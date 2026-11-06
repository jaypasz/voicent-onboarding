from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool  # one shared connection, or each request sees an empty database
        engine = create_engine(url, **kwargs)
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    # Supabase's transaction pooler (port 6543) can't keep prepared statements across transactions.
    return create_engine(normalize_url(url), pool_pre_ping=True, connect_args={"prepare_threshold": None})


def normalize_url(url: str) -> str:
    """Supabase hands out postgres:// or postgresql:// URLs. SQLAlchemy needs the driver named (psycopg 3)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url
