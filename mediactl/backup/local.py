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

Local/mounted filesystem backup target (external drives, NAS mounts, etc.).
"""
from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from mediactl.backup.base import BaseBackupTarget


class LocalBackupTarget(BaseBackupTarget):
    """Writes backup files under a local/mounted destination root."""

    def __init__(self, destination: str) -> None:
        self.root = Path(destination).expanduser()

    def write(self, rel_path: str, local_source: Path) -> None:
        dest_path = self.root / PurePosixPath(rel_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_source, dest_path)

    def describe(self) -> str:
        return str(self.root)
