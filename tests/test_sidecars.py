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

Tests for Artifact-sidecar generation."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mediactl.db.models import File
from mediactl.db.session import get_session, init_db
from mediactl.sidecars import _ext_to_type, generate_sidecars


@pytest.fixture
def db_with_files(tmp_path: Path):
    db = tmp_path / "sidecars_test.db"
    init_db(db)

    with get_session() as session:
        canonical = File(
            path="/media/photos/a.jpg", filename="a.jpg", extension="jpg",
            size_bytes=1024, sha256="shared", mime_type="image/jpeg",
            first_seen_at="2023-01-15T00:00:00+00:00", last_seen_at="2023-01-15T00:00:00+00:00",
            indexed_at="2023-01-15T00:00:00+00:00", created_at="2023-01-15T00:00:00+00:00",
            scan_status="indexed",
        )
        session.add(canonical)
        session.commit()
        session.refresh(canonical)

        dup = File(
            path="/media/photos/dup_a.jpg", filename="dup_a.jpg", extension="jpg",
            size_bytes=1024, sha256="shared", is_duplicate=1, canonical_file_id=canonical.id,
            first_seen_at="2023-02-01T00:00:00+00:00", last_seen_at="2023-02-01T00:00:00+00:00",
            indexed_at="2023-02-01T00:00:00+00:00", created_at="2023-02-01T00:00:00+00:00",
            scan_status="indexed",
        )
        session.add(dup)
        session.commit()

    return db


def test_generate_sidecars_creates_files(db_with_files: Path, tmp_path: Path) -> None:
    out = tmp_path / "artifacts"

    with get_session() as session:
        result = generate_sidecars(session, out, dry_run=False)

    assert result.total == 2
    assert result.created == 2
    assert result.skipped_existing == 0
    assert out.is_dir()
    assert (out / "media__photos__a.jpg.md").exists()
    assert (out / "media__photos__dup_a.jpg.md").exists()


def test_sidecar_frontmatter_is_deterministic_only(db_with_files: Path, tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    with get_session() as session:
        generate_sidecars(session, out, dry_run=False)

    content = (out / "media__photos__a.jpg.md").read_text()
    assert content.startswith("---\n")
    frontmatter_raw = content.split("---\n")[1]
    fm = yaml.safe_load(frontmatter_raw)

    assert fm["kg_type"] == "Artifact"
    assert fm["artifact_type"] == "jpg"
    assert fm["title"] == "a"
    assert fm["source_path"] == "/media/photos/a.jpg"
    assert fm["source_hash"] == "sha256:shared"
    assert fm["status"] == "inventoried"
    assert fm["needs_enrichment"] is True
    assert fm["mocs"] == ["[[Images]]", "[[2023]]"]
    # No hallucinated content-understanding fields.
    assert "topics" not in fm
    assert "entities" not in fm
    assert "evidence" not in fm

    assert "## Enrichment Needed" in content


def test_sidecar_duplicate_links_canonical(db_with_files: Path, tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    with get_session() as session:
        generate_sidecars(session, out, dry_run=False)

    content = (out / "media__photos__dup_a.jpg.md").read_text()
    fm = yaml.safe_load(content.split("---\n")[1])
    assert fm["duplicate_of"] == "/media/photos/a.jpg"


def test_generate_sidecars_skips_existing_by_default(db_with_files: Path, tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    with get_session() as session:
        generate_sidecars(session, out, dry_run=False)

    sidecar = out / "media__photos__a.jpg.md"
    # Simulate hand-enrichment by an agentic harness.
    enriched = sidecar.read_text() + "\n## Manual Notes\nEnriched by hand.\n"
    sidecar.write_text(enriched)

    with get_session() as session:
        result = generate_sidecars(session, out, dry_run=False)

    assert result.skipped_existing == 2
    assert result.created == 0
    assert sidecar.read_text() == enriched  # untouched


def test_generate_sidecars_force_overwrites(db_with_files: Path, tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    with get_session() as session:
        generate_sidecars(session, out, dry_run=False)

    sidecar = out / "media__photos__a.jpg.md"
    sidecar.write_text(sidecar.read_text() + "\n## Manual Notes\nEnriched by hand.\n")

    with get_session() as session:
        result = generate_sidecars(session, out, force=True, dry_run=False)

    assert result.created == 2
    assert result.skipped_existing == 0
    assert "Manual Notes" not in sidecar.read_text()


def test_generate_sidecars_dry_run_writes_nothing(db_with_files: Path, tmp_path: Path) -> None:
    out = tmp_path / "artifacts_dry"

    with get_session() as session:
        result = generate_sidecars(session, out, dry_run=True)

    assert result.created == 2
    assert not out.exists()


def test_ext_to_type_reused_from_moc() -> None:
    assert _ext_to_type("jpg") == "Images"
