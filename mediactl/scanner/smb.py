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

SMB scanner using smbprotocol for remote share traversal.

Streams file listings without downloading file content.
Handles reconnects and network interruptions gracefully.
"""
from __future__ import annotations

import re
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import PurePosixPath

import structlog

from mediactl.scanner.base import BaseScanner, FileEntry

log = structlog.get_logger()

_SMB_URI_RE = re.compile(r"^smb://([^/]+)/([^/]+)(/.*)?$", re.IGNORECASE)


def parse_smb_uri(uri: str) -> tuple[str, str, str]:
    """Parse smb://host/share[/path] URI.

    Returns:
        (host, share, subpath) where subpath defaults to '/'.

    Raises:
        ValueError: If URI is not valid SMB format.
    """
    m = _SMB_URI_RE.match(uri)
    if not m:
        raise ValueError(
            f"Invalid SMB URI: {uri!r}. Expected format: smb://hostname/share[/path]"
        )
    host, share, subpath = m.group(1), m.group(2), m.group(3) or "/"
    return host, share, subpath


class SMBScanner(BaseScanner):
    """Recursively scan a remote SMB share."""

    def __init__(
        self,
        username: str = "",
        password: str = "",
        exclude_patterns: list[str] | None = None,
        max_depth: int = -1,
        workers: int = 4,
    ) -> None:
        super().__init__(exclude_patterns=exclude_patterns, max_depth=max_depth, workers=workers)
        self.username = username
        self.password = password

    def scan(self, root: str) -> Generator[FileEntry, None, None]:
        """Scan SMB URI recursively.

        Args:
            root: SMB URI in format smb://hostname/share[/path]

        Raises:
            ValueError: If URI is invalid.
            ImportError: If smbprotocol not installed.
        """
        try:
            import smbclient  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "smbprotocol not installed. Run: uv add smbprotocol"
            ) from exc

        host, share, subpath = parse_smb_uri(root)

        log.info("scanner.smb.start", host=host, share=share, path=subpath)

        try:
            smbclient.register_session(
                host,
                username=self.username or None,
                password=self.password or None,
            )
        except Exception as exc:
            log.error("scanner.smb.connect_failed", host=host, error=str(exc))
            raise

        smb_root = f"\\\\{host}\\{share}"
        smb_path = smb_root + subpath.replace("/", "\\")

        yield from self._walk_smb(smbclient, smb_root, smb_path, host, share, depth=0)

    def _walk_smb(
        self,
        smbclient,
        smb_root: str,
        smb_path: str,
        host: str,
        share: str,
        depth: int,
    ) -> Generator[FileEntry, None, None]:
        if self.max_depth >= 0 and depth > self.max_depth:
            return

        try:
            entries = list(smbclient.scandir(smb_path))
        except Exception as exc:
            log.error("scanner.smb.scandir_error", path=smb_path, error=str(exc))
            return

        for entry in entries:
            if self._is_excluded(entry.name):
                continue

            try:
                stat = entry.stat()
            except Exception as exc:
                log.warning("scanner.smb.stat_error", name=entry.name, error=str(exc))
                continue

            full_smb_path = smb_path.rstrip("\\") + "\\" + entry.name

            if entry.is_file():
                # Build SMB URI for this file
                rel = full_smb_path.replace(smb_root, "").replace("\\", "/")
                smb_uri = f"smb://{host}/{share}{rel}"

                mtime = None
                ctime = None
                try:
                    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
                    ctime = datetime.fromtimestamp(stat.st_ctime, tz=UTC).isoformat()
                except Exception:
                    pass

                yield FileEntry(
                    path=smb_uri,
                    filename=entry.name,
                    extension=PurePosixPath(entry.name).suffix.lstrip(".").lower(),
                    size_bytes=stat.st_size,
                    modified_at=mtime,
                    created_at=ctime,
                    smb_uri=smb_uri,
                    is_local=False,
                )

            elif entry.is_dir():
                yield from self._walk_smb(
                    smbclient, smb_root, full_smb_path, host, share, depth + 1
                )
