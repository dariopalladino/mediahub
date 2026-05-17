"""Local filesystem scanner using os.scandir for performance."""
from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import structlog

from mediactl.scanner.base import BaseScanner, FileEntry

log = structlog.get_logger()


def _ts(epoch: float) -> str:
    """Convert epoch float to ISO8601 UTC string."""
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


class LocalScanner(BaseScanner):
    """Recursively scan a local filesystem directory."""

    def scan(self, root: str) -> Generator[FileEntry, None, None]:
        """Yield FileEntry for each file under root.

        Args:
            root: Absolute or relative directory path.
        """
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ValueError(f"Not a directory: {root_path}")

        log.info("scanner.local.start", root=str(root_path))
        yield from self._walk(root_path, depth=0)

    def _walk(self, directory: Path, depth: int) -> Generator[FileEntry, None, None]:
        if self.max_depth >= 0 and depth > self.max_depth:
            return

        try:
            entries = list(os.scandir(directory))
        except PermissionError:
            log.warning("scanner.local.permission_denied", path=str(directory))
            return
        except OSError as exc:
            log.error("scanner.local.error", path=str(directory), error=str(exc))
            return

        for entry in entries:
            if self._is_excluded(entry.name):
                continue

            if entry.is_symlink():
                continue  # skip symlinks to avoid loops

            if entry.is_file(follow_symlinks=False):
                try:
                    stat = entry.stat()
                    yield FileEntry(
                        path=entry.path,
                        filename=entry.name,
                        extension=Path(entry.name).suffix.lstrip(".").lower(),
                        size_bytes=stat.st_size,
                        modified_at=_ts(stat.st_mtime),
                        created_at=_ts(stat.st_ctime),
                        smb_uri=None,
                        is_local=True,
                    )
                except OSError as exc:
                    log.error("scanner.local.stat_error", path=entry.path, error=str(exc))

            elif entry.is_dir(follow_symlinks=False):
                yield from self._walk(Path(entry.path), depth + 1)
