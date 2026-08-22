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

Local JSON sync-state persistence for the backup module.

State is a flat mapping of POSIX-relative source path -> last-synced
{size, mtime, sha256}. It is always stored locally (never on the backup
destination) so the module works identically against local and SMB targets.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class SyncEntry(TypedDict):
    size: int
    mtime: float
    sha256: str


def load_state(state_file: Path) -> dict[str, SyncEntry]:
    """Load prior sync state. Returns empty dict if missing or unreadable."""
    if not state_file.exists():
        return {}
    try:
        with state_file.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state_file: Path, state: dict[str, SyncEntry]) -> None:
    """Atomically persist sync state (write to temp file, then rename)."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = state_file.with_suffix(state_file.suffix + ".tmp")
    with tmp_file.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp_file.replace(state_file)
