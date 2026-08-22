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

Configuration loading and validation for mediactl.

Loads config.yaml, applies defaults, validates required fields.

Priority: SMB host > local path.
If neither provided: error.
If moc.output_dir missing: error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or missing required fields."""


@dataclass
class SMBConfig:
    host: str = ""
    share: str = ""
    username: str = ""
    password: str = ""


@dataclass
class LocalConfig:
    path: str = ""


@dataclass
class ScannerConfig:
    workers: int = 4
    exclude: list[str] = field(default_factory=lambda: ["*.tmp", ".DS_Store", "Thumbs.db"])
    max_depth: int = -1  # -1 = unlimited


@dataclass
class DatabaseConfig:
    path: str = "./mediahub.db"


@dataclass
class MOCConfig:
    output_dir: str = ""


@dataclass
class GraphConfig:
    path: str = "./mediahub_graph.db"


@dataclass
class BackupConfig:
    """Independent backup module. Disabled unless explicitly enabled."""

    enabled: bool = False
    source: str = ""          # local dir to back up; falls back to local.path if empty
    destination: str = ""     # local/mounted path OR smb://host/share[/path]
    username: str = ""        # SMB destination credentials (ignored for local destinations)
    password: str = ""
    exclude: list[str] = field(default_factory=list)
    state_file: str = "./backup_state.json"


@dataclass
class SidecarsConfig:
    """Artifact-sidecar generation for knowledge-graph tools (e.g. Graphify).

    Independent module; disabled by default, same gating shape as BackupConfig.
    """

    enabled: bool = False
    output_dir: str = ""


@dataclass
class Config:
    smb: SMBConfig = field(default_factory=SMBConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    moc: MOCConfig = field(default_factory=MOCConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    sidecars: SidecarsConfig = field(default_factory=SidecarsConfig)

    @property
    def db_path(self) -> Path:
        return Path(self.database.path)

    @property
    def moc_output_path(self) -> Path:
        return Path(self.moc.output_dir)

    @property
    def graph_db_path(self) -> Path:
        return Path(self.graph.path)

    @property
    def sidecars_output_path(self) -> Path:
        return Path(self.sidecars.output_dir)

    @property
    def use_smb(self) -> bool:
        """SMB takes priority over local path."""
        return bool(self.smb.host)

    @property
    def backup_state_path(self) -> Path:
        return Path(self.backup.state_file)

    def validate(self) -> None:
        """Raise ConfigError if required fields missing."""
        if not self.use_smb and not self.local.path:
            raise ConfigError(
                "Configuration error: either smb.host or local.path must be provided."
            )
        if not self.moc.output_dir:
            raise ConfigError(
                "Configuration error: moc.output_dir is required."
            )

    def validate_backup(self) -> None:
        """Raise ConfigError if the backup module is enabled but misconfigured."""
        if not self.backup.enabled:
            raise ConfigError(
                "Backup module is disabled. Set backup.enabled: true in config.yaml to use it."
            )
        if not self.backup.source and not self.local.path:
            raise ConfigError(
                "Configuration error: backup.source (or local.path) must be provided."
            )
        if not self.backup.destination:
            raise ConfigError(
                "Configuration error: backup.destination is required."
            )

    def validate_sidecars(self) -> None:
        """Raise ConfigError if the sidecars module is enabled but misconfigured."""
        if not self.sidecars.enabled:
            raise ConfigError(
                "Sidecars module is disabled. Set sidecars.enabled: true in config.yaml to use it."
            )
        if not self.sidecars.output_dir:
            raise ConfigError(
                "Configuration error: sidecars.output_dir is required."
            )


def load_config(config_path: Path) -> Config:
    """Load and validate config.yaml from given path.

    Args:
        config_path: Path to config.yaml file.

    Returns:
        Validated Config dataclass.

    Raises:
        ConfigError: If file missing or validation fails.
    """
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open() as f:
        raw = yaml.safe_load(f) or {}

    smb_raw = raw.get("smb", {}) or {}
    local_raw = raw.get("local", {}) or {}
    scanner_raw = raw.get("scanner", {}) or {}
    db_raw = raw.get("database", {}) or {}
    moc_raw = raw.get("moc", {}) or {}
    backup_raw = raw.get("backup", {}) or {}
    graph_raw = raw.get("graph", {}) or {}
    sidecars_raw = raw.get("sidecars", {}) or {}

    cfg = Config(
        smb=SMBConfig(
            host=smb_raw.get("host", ""),
            share=smb_raw.get("share", ""),
            username=smb_raw.get("username", ""),
            password=smb_raw.get("password", ""),
        ),
        local=LocalConfig(path=local_raw.get("path", "")),
        scanner=ScannerConfig(
            workers=scanner_raw.get("workers", 4),
            exclude=scanner_raw.get("exclude", ["*.tmp", ".DS_Store", "Thumbs.db"]),
            max_depth=scanner_raw.get("max_depth", -1),
        ),
        database=DatabaseConfig(path=db_raw.get("path", "./mediahub.db")),
        moc=MOCConfig(output_dir=moc_raw.get("output_dir", "")),
        backup=BackupConfig(
            enabled=backup_raw.get("enabled", False),
            source=backup_raw.get("source", ""),
            destination=backup_raw.get("destination", ""),
            username=backup_raw.get("username", ""),
            password=backup_raw.get("password", ""),
            exclude=backup_raw.get("exclude", []),
            state_file=backup_raw.get("state_file", "./backup_state.json"),
        ),
        graph=GraphConfig(path=graph_raw.get("path", "./mediahub_graph.db")),
        sidecars=SidecarsConfig(
            enabled=sidecars_raw.get("enabled", False),
            output_dir=sidecars_raw.get("output_dir", ""),
        ),
    )

    cfg.validate()
    return cfg
