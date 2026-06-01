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
"""SQLModel table definitions for mediactl.

Schema per .spec/10_design/DB_SCHEMA_MEDIACTL.md
"""
from __future__ import annotations

from sqlmodel import Field, SQLModel


class File(SQLModel, table=True):
    """Indexed media file record."""

    __tablename__ = "files"

    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(unique=True, index=True, nullable=False)
    smb_uri: str | None = Field(default=None)
    filename: str = Field(nullable=False)
    extension: str | None = Field(default=None, index=True)
    size_bytes: int | None = Field(default=None)
    created_at: str | None = Field(default=None)
    modified_at: str | None = Field(default=None)
    md5: str | None = Field(default=None, index=True)
    sha256: str | None = Field(default=None, index=True)
    mime_type: str | None = Field(default=None, index=True)
    canonical_file_id: int | None = Field(default=None, foreign_key="files.id")
    is_duplicate: int = Field(default=0, index=True)
    first_seen_at: str = Field(nullable=False)
    last_seen_at: str = Field(nullable=False)
    indexed_at: str = Field(nullable=False)
    scan_status: str = Field(default="pending")


class Scan(SQLModel, table=True):
    """Scan run record."""

    __tablename__ = "scans"

    id: int | None = Field(default=None, primary_key=True)
    started_at: str = Field(nullable=False)
    completed_at: str | None = Field(default=None)
    files_scanned: int = Field(default=0)
    files_updated: int = Field(default=0)
    errors_count: int = Field(default=0)


class Tag(SQLModel, table=True):
    """Tag record."""

    __tablename__ = "tags"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, nullable=False)


class FileTag(SQLModel, table=True):
    """File-tag association."""

    __tablename__ = "file_tags"

    file_id: int = Field(foreign_key="files.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True)
