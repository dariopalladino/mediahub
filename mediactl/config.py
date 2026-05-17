"""Configuration loading and validation for mediactl.

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
class Config:
    smb: SMBConfig = field(default_factory=SMBConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    moc: MOCConfig = field(default_factory=MOCConfig)

    @property
    def db_path(self) -> Path:
        return Path(self.database.path)

    @property
    def moc_output_path(self) -> Path:
        return Path(self.moc.output_dir)

    @property
    def use_smb(self) -> bool:
        """SMB takes priority over local path."""
        return bool(self.smb.host)

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
    )

    cfg.validate()
    return cfg
