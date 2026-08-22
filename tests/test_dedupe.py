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

Tests for duplicate detection logic."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import select

from mediactl.db.models import File
from mediactl.db.session import get_session, init_db
from mediactl.dedupe import _select_canonical, run_dedupe


def _make_file(
    path: str,
    sha256: str,
    size: int = 100,
    created_at: str = "2020-01-01T00:00:00+00:00",
) -> File:
    return File(
        path=path,
        filename=Path(path).name,
        extension=Path(path).suffix.lstrip("."),
        size_bytes=size,
        sha256=sha256,
        md5="aabbcc",
        first_seen_at="2020-01-01T00:00:00+00:00",
        last_seen_at="2020-01-01T00:00:00+00:00",
        indexed_at="2020-01-01T00:00:00+00:00",
        created_at=created_at,
        scan_status="indexed",
    )


@pytest.fixture
def db_with_duplicates(tmp_path: Path):
    """DB with 3 files: 2 duplicates + 1 unique."""
    db = tmp_path / "test.db"
    init_db(db)

    sha_dup = "abc" * 21 + "d"  # 64 chars
    sha_unique = "def" * 21 + "g"

    f1 = _make_file("/archive/photo.jpg", sha_dup, created_at="2019-01-01T00:00:00+00:00")
    f2 = _make_file("/backup/photo_copy.jpg", sha_dup, created_at="2021-01-01T00:00:00+00:00")
    f3 = _make_file("/photos/unique.jpg", sha_unique)

    with get_session() as session:
        session.add(f1)
        session.add(f2)
        session.add(f3)
        session.commit()

    return db


def test_run_dedupe_finds_duplicates(db_with_duplicates: Path) -> None:
    """run_dedupe detects the duplicate pair."""
    with get_session() as session:
        groups = run_dedupe(session, dry_run=False)

    assert len(groups) == 1
    assert all(len(ids) == 2 for ids in groups.values())


def test_run_dedupe_marks_is_duplicate(db_with_duplicates: Path) -> None:
    """Duplicate is marked is_duplicate=1, canonical is_duplicate=0."""
    with get_session() as session:
        run_dedupe(session, dry_run=False)
        files = session.exec(select(File)).all()

    by_path = {f.path: f for f in files}

    # Older file = canonical
    canonical = by_path["/archive/photo.jpg"]
    duplicate = by_path["/backup/photo_copy.jpg"]
    unique = by_path["/photos/unique.jpg"]

    assert canonical.is_duplicate == 0
    assert canonical.canonical_file_id is None
    assert duplicate.is_duplicate == 1
    assert duplicate.canonical_file_id == canonical.id
    assert unique.is_duplicate == 0


def test_run_dedupe_dry_run_no_changes(db_with_duplicates: Path) -> None:
    """dry_run=True detects but does not update DB."""
    with get_session() as session:
        groups = run_dedupe(session, dry_run=True)
        files = session.exec(select(File)).all()

    assert len(groups) == 1
    # All files remain un-marked
    for f in files:
        assert f.is_duplicate == 0


def test_select_canonical_prefers_oldest(tmp_path: Path) -> None:
    """_select_canonical picks oldest creation date."""
    old = _make_file("/old/file.jpg", "sha", created_at="2018-01-01T00:00:00+00:00")
    new = _make_file("/new/file.jpg", "sha", created_at="2022-01-01T00:00:00+00:00")
    old.id = 1
    new.id = 2

    result = _select_canonical([old, new])
    assert result is old


def test_select_canonical_prefers_shorter_path(tmp_path: Path) -> None:
    """_select_canonical picks shorter path when dates equal."""
    f1 = _make_file("/a/b/c/d/file.jpg", "sha", created_at="2020-01-01T00:00:00+00:00")
    f2 = _make_file("/a/file.jpg", "sha", created_at="2020-01-01T00:00:00+00:00")
    f1.id = 1
    f2.id = 2

    result = _select_canonical([f1, f2])
    assert result is f2
