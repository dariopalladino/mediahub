"""
    Local-first media indexing and deduplication CLI.
    Copyright (C) 2026  Dario Palladino

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
"""Database engine, session factory, and schema initialisation.

Usage:
    from mediactl.db.session import get_session, init_db

    init_db(db_path)  # call once at startup
    with get_session() as session:
        session.add(...)
        session.commit()
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import structlog
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

log = structlog.get_logger()

_engine = None


def get_engine():
    """Return current engine (must call init_db first)."""
    if _engine is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _engine


def init_db(db_path: Path) -> None:
    """Initialise SQLite engine and create all tables.

    Safe to call multiple times; schema created only if absent.
    """
    global _engine  # noqa: PLW0603

    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    _engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})

    # Enable WAL mode for concurrent read performance
    @event.listens_for(_engine, "connect")
    def _set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # Import models before create_all so SQLModel metadata is fully populated.
    # Without this, table creation can miss models that have not been imported yet.
    from mediactl.db import models  # noqa: F401

    SQLModel.metadata.create_all(_engine)
    log.info("database.initialised", path=str(db_path))


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager yielding a SQLModel Session."""
    with Session(get_engine()) as session:
        yield session
