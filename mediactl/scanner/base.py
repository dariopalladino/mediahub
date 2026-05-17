"""Abstract scanner base class and FileEntry dataclass."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from dataclasses import dataclass


@dataclass
class FileEntry:
    """Discovered file metadata before DB indexing."""

    path: str                    # Canonical path (local or SMB URI)
    filename: str
    extension: str
    size_bytes: int
    modified_at: str | None   # ISO8601 string or None
    created_at: str | None    # ISO8601 string or None
    smb_uri: str | None = None
    is_local: bool = True


class BaseScanner(ABC):
    """Abstract base for file scanners."""

    def __init__(
        self,
        exclude_patterns: list[str] | None = None,
        max_depth: int = -1,
        workers: int = 4,
    ) -> None:
        self.exclude_patterns = exclude_patterns or []
        self.max_depth = max_depth
        self.workers = workers

    @abstractmethod
    def scan(self, root: str) -> Generator[FileEntry, None, None]:
        """Yield FileEntry for each discovered file.

        Args:
            root: Root path or SMB URI to scan.
        """

    def _is_excluded(self, name: str) -> bool:
        """Check if filename matches any exclusion pattern."""
        import fnmatch

        return any(fnmatch.fnmatch(name, pat) for pat in self.exclude_patterns)
