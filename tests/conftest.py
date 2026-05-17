"""Pytest fixtures for mediactl tests."""
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
