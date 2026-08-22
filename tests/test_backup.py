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

Tests for the backup module (engine + local target + state)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from mediactl.backup.engine import BackupEngine
from mediactl.backup.local import LocalBackupTarget
from mediactl.backup.state import load_state, save_state


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    (source / "docs" / "a.txt").write_text("hello")
    (source / "b.txt").write_text("world")
    (source / ".DS_Store").write_text("ignored")
    (source / "temp.tmp").write_text("ignored too")
    return source


def test_backup_copies_new_files(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    dest = tmp_path / "dest"
    state_file = tmp_path / "state.json"

    target = LocalBackupTarget(destination=str(dest))
    engine = BackupEngine(
        source=str(source),
        target=target,
        state_file=state_file,
        exclude_patterns=["*.tmp", ".DS_Store"],
    )
    result = engine.run()

    assert result.files_scanned == 2
    assert result.files_copied == 2
    assert result.files_unchanged == 0
    assert (dest / "docs" / "a.txt").read_text() == "hello"
    assert (dest / "b.txt").read_text() == "world"
    assert not (dest / "temp.tmp").exists()
    assert not (dest / ".DS_Store").exists()


def test_backup_skips_unchanged_files_on_rerun(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    dest = tmp_path / "dest"
    state_file = tmp_path / "state.json"

    target = LocalBackupTarget(destination=str(dest))
    engine = BackupEngine(
        source=str(source), target=target, state_file=state_file, exclude_patterns=["*.tmp", ".DS_Store"]
    )
    engine.run()

    # Rerun without touching source: nothing should be re-copied.
    result = engine.run()
    assert result.files_copied == 0
    assert result.files_unchanged == 2


def test_backup_recopies_changed_content(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    dest = tmp_path / "dest"
    state_file = tmp_path / "state.json"

    target = LocalBackupTarget(destination=str(dest))
    engine = BackupEngine(
        source=str(source), target=target, state_file=state_file, exclude_patterns=["*.tmp", ".DS_Store"]
    )
    engine.run()

    time.sleep(0.01)
    (source / "b.txt").write_text("changed content")

    result = engine.run()
    assert result.files_copied == 1
    assert result.files_unchanged == 1
    assert (dest / "b.txt").read_text() == "changed content"


def test_backup_dry_run_does_not_write(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    dest = tmp_path / "dest"
    state_file = tmp_path / "state.json"

    target = LocalBackupTarget(destination=str(dest))
    engine = BackupEngine(
        source=str(source),
        target=target,
        state_file=state_file,
        exclude_patterns=["*.tmp", ".DS_Store"],
        dry_run=True,
    )
    result = engine.run()

    assert result.files_copied == 2
    assert not dest.exists()
    assert not state_file.exists()


def test_backup_invalid_source_raises(tmp_path: Path) -> None:
    target = LocalBackupTarget(destination=str(tmp_path / "dest"))
    with pytest.raises(ValueError, match="Not a directory"):
        BackupEngine(
            source=str(tmp_path / "nonexistent"),
            target=target,
            state_file=tmp_path / "state.json",
        )


def test_state_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    save_state(state_file, {"a.txt": {"size": 5, "mtime": 123.0, "sha256": "abc"}})
    loaded = load_state(state_file)
    assert loaded == {"a.txt": {"size": 5, "mtime": 123.0, "sha256": "abc"}}


def test_state_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_state(tmp_path / "missing.json") == {}
