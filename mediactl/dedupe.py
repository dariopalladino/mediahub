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

Duplicate detection and canonical file selection.

Algorithm (per spec):
1. Group files by size (fast pre-filter — size 0 files excluded)
2. Within same-size group: compute partial MD5 (first 4 MB)
3. Within same partial-MD5 group: compute full SHA256
4. Files with identical SHA256 are duplicates

Canonical selection rules (per spec):
1. Oldest creation date
2. Shortest path depth
3. Largest metadata completeness (proxy: non-null field count)
4. Deterministic tie-breaker: lexicographic path sort
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import structlog
from sqlmodel import Session, select

from mediactl.db.models import File
from mediactl.fingerprint import hash_file_full

log = structlog.get_logger()


def run_dedupe(session: Session, dry_run: bool = False) -> dict[str, list[int]]:
    """Run full duplicate detection pipeline.

    Groups files by SHA256 and marks duplicates in DB.
    Returns dict of sha256 -> [file_id, ...] for groups with >1 file.

    Args:
        session: Active DB session.
        dry_run: If True, detect only — do not write to DB.

    Returns:
        Dict mapping sha256 -> list of file IDs (all files in duplicate group).
    """
    log.info("dedupe.start", dry_run=dry_run)

    # Group indexed files by sha256
    stmt = select(File).where(File.sha256 != None, File.scan_status == "indexed")  # noqa: E711
    files = session.exec(stmt).all()

    sha_groups: dict[str, list[File]] = defaultdict(list)
    for f in files:
        if f.sha256:
            sha_groups[f.sha256].append(f)

    duplicate_groups: dict[str, list[int]] = {}
    updated = 0

    for sha256, group in sha_groups.items():
        if len(group) <= 1:
            continue

        canonical = _select_canonical(group)
        duplicate_groups[sha256] = [f.id for f in group if f.id is not None]

        if not dry_run:
            for f in group:
                if f.id == canonical.id:
                    f.is_duplicate = 0
                    f.canonical_file_id = None
                else:
                    f.is_duplicate = 1
                    f.canonical_file_id = canonical.id
                session.add(f)
                updated += 1

    if not dry_run:
        session.commit()
        log.info("dedupe.complete", groups=len(duplicate_groups), records_updated=updated)
    else:
        log.info("dedupe.dry_run_complete", groups=len(duplicate_groups))

    return duplicate_groups


def _select_canonical(group: list[File]) -> File:
    """Select canonical file from duplicate group.

    Rules (per spec):
    1. Oldest creation date (earliest created_at)
    2. Shortest path depth
    3. Highest non-null field count (proxy for metadata completeness)
    4. Lexicographic path sort (deterministic tie-breaker)
    """

    def sort_key(f: File):
        # created_at: None sorts last (treat as far future)
        ts = f.created_at or "9999-12-31"
        depth = len(Path(f.path).parts) if f.path else 999
        # metadata completeness: count non-null optional fields
        completeness = -sum(1 for v in [f.md5, f.sha256, f.mime_type, f.modified_at, f.created_at] if v is not None)
        return (ts, depth, completeness, f.path or "")

    return min(group, key=sort_key)


def compute_missing_hashes(session: Session, dry_run: bool = False) -> int:
    """Compute MD5/SHA256 for all indexed files missing hashes.

    Only processes local files (SMB files need streaming hash — handled in scanner).
    Returns count of files hashed.
    """
    stmt = select(File).where(
        File.sha256 == None,  # noqa: E711
        File.smb_uri == None,  # noqa: E711
        File.scan_status == "indexed",
    )
    files = session.exec(stmt).all()
    count = 0

    for f in files:
        path = Path(f.path)
        if not path.is_file():
            continue
        try:
            md5, sha256 = hash_file_full(path)
            if not dry_run:
                f.md5 = md5
                f.sha256 = sha256
                session.add(f)
            count += 1
        except Exception as exc:
            log.error("dedupe.hash_error", path=f.path, error=str(exc))

    if not dry_run and count:
        session.commit()

    log.info("dedupe.hashes_computed", count=count, dry_run=dry_run)
    return count
