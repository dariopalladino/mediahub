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
"""Tests for database initialization behavior."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from mediactl.db.session import init_db


def test_init_db_creates_scans_table(tmp_path: Path) -> None:
    """init_db creates the scans table required by scan command."""
    db_path = tmp_path / "init.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scans'"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [("scans",)]
