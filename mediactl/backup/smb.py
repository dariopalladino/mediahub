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

SMB backup target using smbprotocol.

This is a deliberate, scoped exception to the read-only SMB posture described
in 001_REQUIREMENTS.md's Non-Goals: the backup module is the only part of
mediactl permitted to write to a remote SMB share, and only to the
user-configured backup destination — never to the scan source. See
.spec/15_requirements/001_REQUIREMENTS.md and .spec/30_delivery/PROMOTION_LOG.md.
"""
from __future__ import annotations

from pathlib import Path

import structlog

from mediactl.backup.base import BaseBackupTarget
from mediactl.scanner.smb import parse_smb_uri

log = structlog.get_logger()


class SMBBackupTarget(BaseBackupTarget):
    """Writes backup files to a remote SMB share."""

    def __init__(self, destination: str, username: str = "", password: str = "") -> None:
        try:
            import smbclient  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "smbprotocol not installed. Run: uv add smbprotocol"
            ) from exc

        self._smbclient = smbclient
        self.host, self.share, subpath = parse_smb_uri(destination)
        self.root = f"\\\\{self.host}\\{self.share}" + subpath.replace("/", "\\")
        self.username = username
        self.password = password
        self._connected = False

    def _connect(self) -> None:
        if self._connected:
            return
        try:
            self._smbclient.register_session(
                self.host,
                username=self.username or None,
                password=self.password or None,
            )
        except Exception as exc:
            log.error("backup.smb.connect_failed", host=self.host, error=str(exc))
            raise
        self._connected = True

    def write(self, rel_path: str, local_source: Path) -> None:
        self._connect()
        dest_unc = self.root.rstrip("\\") + "\\" + rel_path.replace("/", "\\")
        parent_unc = dest_unc.rsplit("\\", 1)[0]
        self._smbclient.makedirs(parent_unc, exist_ok=True)

        with local_source.open("rb") as src, self._smbclient.open_file(dest_unc, mode="wb") as dst:
            while chunk := src.read(65536):
                dst.write(chunk)

    def describe(self) -> str:
        return f"smb://{self.host}/{self.share}"
