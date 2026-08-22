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

Incremental backup engine.

Walks a local source tree, skips excluded files/folders, and copies only
files whose content has changed since the last sync (identity by SHA256,
per 001_REQUIREMENTS.md's content-based identity principle). A quick
size+mtime check avoids re-hashing untouched files on every run; the hash
is still the source of truth whenever size or mtime looks different.

Never deletes or modifies anything at the destination beyond writing new
or changed file content — no mirroring/pruning of removed source files.
"""
from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import structlog

from mediactl.backup.base import BaseBackupTarget
from mediactl.backup.state import SyncEntry, load_state, save_state
from mediactl.fingerprint import hash_file_full

log = structlog.get_logger()


@dataclass
class BackupResult:
    files_scanned: int = 0
    files_copied: int = 0
    files_unchanged: int = 0
    errors: int = 0
    bytes_copied: int = 0


class BackupEngine:
    """Recursively syncs a local source directory to a backup target."""

    def __init__(
        self,
        source: str,
        target: BaseBackupTarget,
        state_file: Path,
        exclude_patterns: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.source = Path(source).expanduser().resolve()
        self.target = target
        self.state_file = state_file
        self.exclude_patterns = exclude_patterns or []
        self.dry_run = dry_run

        if not self.source.is_dir():
            raise ValueError(f"Not a directory: {self.source}")

    def _is_excluded(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, pat) for pat in self.exclude_patterns)

    def _walk(self, directory: Path) -> Generator[Path, None, None]:
        try:
            entries = list(os.scandir(directory))
        except PermissionError:
            log.warning("backup.permission_denied", path=str(directory))
            return
        except OSError as exc:
            log.error("backup.walk_error", path=str(directory), error=str(exc))
            return

        for entry in entries:
            if self._is_excluded(entry.name):
                continue
            if entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                yield Path(entry.path)
            elif entry.is_dir(follow_symlinks=False):
                yield from self._walk(Path(entry.path))

    def run(
        self, on_file: Callable[[str], None] | None = None
    ) -> BackupResult:
        """Sync source -> target, copying only changed files.

        Args:
            on_file: Optional callback invoked with each relative path visited
                (for progress reporting).
        """
        prior_state = load_state(self.state_file)
        new_state: dict[str, SyncEntry] = {}
        result = BackupResult()

        log.info(
            "backup.start", source=str(self.source), target=self.target.describe(), dry_run=self.dry_run
        )

        for abs_path in self._walk(self.source):
            rel_path = PurePosixPath(abs_path.relative_to(self.source).as_posix()).as_posix()
            result.files_scanned += 1
            if on_file:
                on_file(rel_path)

            try:
                stat = abs_path.stat()
                prior = prior_state.get(rel_path)

                needs_copy = True
                sha256 = prior["sha256"] if prior else ""

                if prior and prior["size"] == stat.st_size and prior["mtime"] == stat.st_mtime:
                    # Size + mtime unchanged: trust the cached hash, skip re-reading the file.
                    needs_copy = False
                else:
                    _md5, sha256 = hash_file_full(abs_path)
                    if prior and prior["sha256"] == sha256:
                        # Content unchanged despite a different mtime (e.g. touch/restore).
                        needs_copy = False

                if needs_copy:
                    if not self.dry_run:
                        self.target.write(rel_path, abs_path)
                    result.files_copied += 1
                    result.bytes_copied += stat.st_size
                else:
                    result.files_unchanged += 1

                new_state[rel_path] = SyncEntry(
                    size=stat.st_size, mtime=stat.st_mtime, sha256=sha256
                )
            except OSError as exc:
                result.errors += 1
                log.error("backup.file_error", path=str(abs_path), error=str(exc))

        if not self.dry_run:
            save_state(self.state_file, new_state)

        log.info(
            "backup.complete",
            files_scanned=result.files_scanned,
            files_copied=result.files_copied,
            files_unchanged=result.files_unchanged,
            errors=result.errors,
        )
        return result
