from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .auth import Actor, current_actor


def get_db(request: Request) -> Iterator[Session]:
    """One session per request. Commits when the handler finishes, rolls back if it raises."""
    db: Session = request.app.state.sessionmaker()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


Db = Depends(get_db)
Auth = Depends(current_actor)

__all__ = ["Actor", "Auth", "Db", "Session"]
