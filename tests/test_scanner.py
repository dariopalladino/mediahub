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

Tests for local filesystem scanner."""
from __future__ import annotations

from pathlib import Path

import pytest

from mediactl.scanner.local import LocalScanner


def test_local_scanner_finds_files(sample_files: Path) -> None:
    """Scanner discovers all non-excluded files recursively."""
    scanner = LocalScanner(exclude_patterns=["*.tmp", ".DS_Store"])
    entries = list(scanner.scan(str(sample_files)))

    filenames = {e.filename for e in entries}
    assert "file1.txt" in filenames
    assert "file2.txt" in filenames
    assert "photo.jpg" in filenames
    assert "duplicate.txt" in filenames

    # Excluded files must not appear
    assert ".DS_Store" not in filenames
    assert "temp.tmp" not in filenames


def test_local_scanner_file_entry_fields(sample_files: Path) -> None:
    """FileEntry has expected fields populated."""
    scanner = LocalScanner()
    entries = list(scanner.scan(str(sample_files)))

    txt_entries = [e for e in entries if e.filename == "file1.txt"]
    assert len(txt_entries) == 1
    entry = txt_entries[0]

    assert entry.extension == "txt"
    assert entry.size_bytes > 0
    assert entry.modified_at is not None
    assert entry.is_local is True
    assert entry.smb_uri is None


def test_local_scanner_max_depth(tmp_path: Path) -> None:
    """max_depth=0 scans only root-level files."""
    (tmp_path / "root.txt").write_text("root")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "deep.txt").write_text("deep")

    scanner = LocalScanner(max_depth=0)
    entries = list(scanner.scan(str(tmp_path)))

    filenames = {e.filename for e in entries}
    assert "root.txt" in filenames
    assert "deep.txt" not in filenames


def test_local_scanner_invalid_path() -> None:
    """Scanner raises ValueError for non-existent directory."""
    scanner = LocalScanner()
    with pytest.raises(ValueError, match="Not a directory"):
        list(scanner.scan("/nonexistent/path/that/does/not/exist"))


def test_local_scanner_excludes_symlinks(tmp_path: Path) -> None:
    """Scanner skips symbolic links to avoid infinite loops."""
    (tmp_path / "real.txt").write_text("real")
    try:
        (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
        scanner = LocalScanner()
        entries = list(scanner.scan(str(tmp_path)))
        filenames = {e.filename for e in entries}
        assert "link.txt" not in filenames
        assert "real.txt" in filenames
    except OSError:
        pytest.skip("Symlinks not supported on this system")
