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
"""
"""Tests for CLI helper behavior."""
from __future__ import annotations

from mediactl.cli import _resolve_smb_credentials
from mediactl.config import Config, SMBConfig


def test_resolve_smb_credentials_prefers_cli(monkeypatch) -> None:
    cfg = Config(smb=SMBConfig(username="cfg-user", password="cfg-pass"))
    monkeypatch.setenv("MEDIACTL_SMB_USER", "env-user")
    monkeypatch.setenv("MEDIACTL_SMB_PASS", "env-pass")

    user, password = _resolve_smb_credentials("cli-user", "cli-pass", cfg)

    assert user == "cli-user"
    assert password == "cli-pass"


def test_resolve_smb_credentials_uses_env_before_config(monkeypatch) -> None:
    cfg = Config(smb=SMBConfig(username="cfg-user", password="cfg-pass"))
    monkeypatch.setenv("MEDIACTL_SMB_USER", "env-user")
    monkeypatch.setenv("MEDIACTL_SMB_PASS", "env-pass")

    user, password = _resolve_smb_credentials(None, None, cfg)

    assert user == "env-user"
    assert password == "env-pass"


def test_resolve_smb_credentials_falls_back_to_config(monkeypatch) -> None:
    cfg = Config(smb=SMBConfig(username="cfg-user", password="cfg-pass"))
    monkeypatch.delenv("MEDIACTL_SMB_USER", raising=False)
    monkeypatch.delenv("MEDIACTL_SMB_PASS", raising=False)

    user, password = _resolve_smb_credentials(None, None, cfg)

    assert user == "cfg-user"
    assert password == "cfg-pass"
