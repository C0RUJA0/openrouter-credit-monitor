"""Engine and session management for SQLite."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _ensure_sqlite_dir(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    db_path = url.database
    if not db_path or db_path == ":memory:":
        return
    directory = os.path.dirname(db_path)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)


def init_engine(database_url: str) -> Engine:
    global _engine, _SessionLocal
    _ensure_sqlite_dir(database_url)
    connect_args = {}
    if make_url(database_url).get_backend_name() == "sqlite":
        connect_args = {"check_same_thread": False}
    _engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
    )
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Engine not initialized. Call init_engine() first.")
    return _engine


def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Session factory not initialized. Call init_engine() first.")
    return _SessionLocal()


def reset_engine() -> None:
    """Testing helper."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
