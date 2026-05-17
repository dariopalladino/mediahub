"""Tests for Obsidian MOC generator."""
from __future__ import annotations

from pathlib import Path

import pytest

from mediactl.db.models import File
from mediactl.db.session import get_session, init_db
from mediactl.moc import _ext_to_type, generate_mocs


@pytest.fixture
def db_with_files(tmp_path: Path):
    """DB with a sample set of indexed files."""
    db = tmp_path / "moc_test.db"
    init_db(db)

    files = [
        File(
            path="/media/photo1.jpg",
            filename="photo1.jpg",
            extension="jpg",
            size_bytes=1024,
            sha256="aaa",
            first_seen_at="2023-01-15T00:00:00+00:00",
            last_seen_at="2023-01-15T00:00:00+00:00",
            indexed_at="2023-01-15T00:00:00+00:00",
            created_at="2023-01-15T00:00:00+00:00",
            scan_status="indexed",
        ),
        File(
            path="/media/video.mp4",
            filename="video.mp4",
            extension="mp4",
            size_bytes=5000,
            sha256="bbb",
            first_seen_at="2022-06-01T00:00:00+00:00",
            last_seen_at="2022-06-01T00:00:00+00:00",
            indexed_at="2022-06-01T00:00:00+00:00",
            created_at="2022-06-01T00:00:00+00:00",
            scan_status="indexed",
        ),
        File(
            path="/media/dup_photo.jpg",
            filename="dup_photo.jpg",
            extension="jpg",
            size_bytes=1024,
            sha256="aaa",
            is_duplicate=1,
            first_seen_at="2023-02-01T00:00:00+00:00",
            last_seen_at="2023-02-01T00:00:00+00:00",
            indexed_at="2023-02-01T00:00:00+00:00",
            created_at="2023-02-01T00:00:00+00:00",
            scan_status="indexed",
        ),
    ]

    with get_session() as session:
        for f in files:
            session.add(f)
        session.commit()

    return db


def test_generate_mocs_creates_files(db_with_files: Path, tmp_path: Path) -> None:
    """generate_mocs writes MOC files to output directory."""
    vault = tmp_path / "vault"

    with get_session() as session:
        count = generate_mocs(session, vault, dry_run=False)

    assert count > 0
    assert (vault / "MOCs").is_dir()
    assert (vault / "MOCs" / "INDEX.md").exists()
    assert (vault / "MOCs" / "by_type").is_dir()
    assert (vault / "MOCs" / "by_year").is_dir()
    assert (vault / "MOCs" / "duplicates" / "Duplicates.md").exists()


def test_moc_by_type_content(db_with_files: Path, tmp_path: Path) -> None:
    """by_type MOC contains expected wiki-links."""
    vault = tmp_path / "vault2"

    with get_session() as session:
        generate_mocs(session, vault, dry_run=False)

    images_moc = vault / "MOCs" / "by_type" / "Images.md"
    assert images_moc.exists()
    content = images_moc.read_text()
    assert "# Images" in content
    assert "[[photo1.jpg]]" in content


def test_moc_duplicates_content(db_with_files: Path, tmp_path: Path) -> None:
    """Duplicates MOC lists duplicate groups."""
    vault = tmp_path / "vault3"

    with get_session() as session:
        generate_mocs(session, vault, dry_run=False)

    dup_moc = vault / "MOCs" / "duplicates" / "Duplicates.md"
    content = dup_moc.read_text()
    assert "# Duplicates" in content
    assert "dup_photo.jpg" in content


def test_moc_dry_run_no_files(db_with_files: Path, tmp_path: Path) -> None:
    """dry_run=True does not write any files."""
    vault = tmp_path / "vault_dry"

    with get_session() as session:
        generate_mocs(session, vault, dry_run=True)

    # vault dir not created in dry_run
    assert not vault.exists() or not (vault / "MOCs" / "INDEX.md").exists()


def test_ext_to_type_mapping() -> None:
    """Extension-to-type mapping covers expected types."""
    assert _ext_to_type("jpg") == "Images"
    assert _ext_to_type("mp4") == "Videos"
    assert _ext_to_type("mp3") == "Audio"
    assert _ext_to_type("pdf") == "Documents"
    assert _ext_to_type("xyz") == "Other"
