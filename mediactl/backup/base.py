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

Abstract backup target — write side of the backup module.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseBackupTarget(ABC):
    """Abstract destination for backup writes.

    A target only needs to copy a local source file to a relative path
    under the destination root, creating parent directories as needed.
    Change detection lives in engine.py, not in the target.
    """

    @abstractmethod
    def write(self, rel_path: str, local_source: Path) -> None:
        """Copy local_source to rel_path under the destination root.

        Args:
            rel_path: POSIX-style path relative to the destination root.
            local_source: Absolute local path to read file content from.
        """

    def describe(self) -> str:
        """Human-readable destination identifier for logging/console output."""
        return self.__class__.__name__
