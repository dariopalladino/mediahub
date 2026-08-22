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

Pytest fixtures for mediactl tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test files."""
    return tmp_path


@pytest.fixture
def sample_files(tmp_path: Path) -> Path:
    """Create a tree of sample files for scanner tests."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "images").mkdir()
    (tmp_path / "docs" / "file1.txt").write_text("Hello world")
    (tmp_path / "docs" / "file2.txt").write_text("Duplicate content")
    (tmp_path / "images" / "photo.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    (tmp_path / ".DS_Store").write_text("ignored")
    (tmp_path / "temp.tmp").write_text("ignored too")
    (tmp_path / "docs" / "duplicate.txt").write_text("Duplicate content")  # dup of file2.txt
    return tmp_path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return path for test database."""
    return tmp_path / "test.db"


@pytest.fixture
def initialized_db(db_path: Path):
    """Initialize test database and return path."""
    from mediactl.db.session import init_db
    init_db(db_path)
    return db_path
