"""Database session factory and FastAPI dependency."""
from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL not set in environment")
        _engine = create_engine(url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    return _engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, always closes on exit."""
    _get_engine()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
