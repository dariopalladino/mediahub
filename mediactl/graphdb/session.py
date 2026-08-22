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

Engine, session factory, and schema initialisation for the graph database.

Mirrors mediactl/db/session.py but holds its own engine, since a graph build
from the sqlite source needs the main index DB and the graph DB open at the
same time.

Usage:
    from mediactl.graphdb.session import get_graph_session, init_graph_db

    init_graph_db(graph_db_path)  # call once at startup
    with get_graph_session() as session:
        session.add(...)
        session.commit()
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import structlog
from sqlalchemy import event
from sqlmodel import Session, create_engine

log = structlog.get_logger()

_graph_engine = None


def get_graph_engine():
    """Return current graph engine (must call init_graph_db first)."""
    if _graph_engine is None:
        raise RuntimeError("Graph database not initialised. Call init_graph_db() first.")
    return _graph_engine


def init_graph_db(db_path: Path) -> None:
    """Initialise the graph SQLite engine and create graph tables.

    Safe to call multiple times; schema created only if absent.
    """
    global _graph_engine  # noqa: PLW0603

    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    _graph_engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})

    @event.listens_for(_graph_engine, "connect")
    def _set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # Import models before create_all so the isolated graph_metadata is fully populated.
    from mediactl.graphdb.models import graph_metadata

    graph_metadata.create_all(_graph_engine)
    log.info("graph_database.initialised", path=str(db_path))


@contextmanager
def get_graph_session() -> Generator[Session, None, None]:
    """Context manager yielding a SQLModel Session bound to the graph engine."""
    with Session(get_graph_engine()) as session:
        yield session
