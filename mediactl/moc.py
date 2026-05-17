"""Obsidian MOC (Map of Content) generator.

Generates markdown files compatible with Obsidian wiki-links.

Output structure (per spec):
    vault/
    ├── MOCs/
    │   ├── by_type/
    │   ├── by_year/
    │   ├── duplicates/
    │   └── tags/
    ├── files/
    ├── reports/
    └── tags/
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlmodel import Session, select

from mediactl.db.models import File

log = structlog.get_logger()


def generate_mocs(session: Session, output_dir: Path, dry_run: bool = False) -> int:
    """Generate all MOC files from DB contents.

    Args:
        session: Active DB session.
        output_dir: Vault root directory.
        dry_run: If True, log what would be written but don't write.

    Returns:
        Count of MOC files written.
    """
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "MOCs").mkdir(exist_ok=True)
        (output_dir / "MOCs" / "by_type").mkdir(exist_ok=True)
        (output_dir / "MOCs" / "by_year").mkdir(exist_ok=True)
        (output_dir / "MOCs" / "duplicates").mkdir(exist_ok=True)
        (output_dir / "MOCs" / "tags").mkdir(exist_ok=True)
        (output_dir / "files").mkdir(exist_ok=True)
        (output_dir / "reports").mkdir(exist_ok=True)

    files = list(session.exec(select(File).where(File.scan_status == "indexed")).all())
    count = 0

    count += _write_moc_by_type(files, output_dir, dry_run)
    count += _write_moc_by_year(files, output_dir, dry_run)
    count += _write_moc_duplicates(session, output_dir, dry_run)
    count += _write_moc_index(files, output_dir, dry_run)
    count += _write_stats_report(session, output_dir, dry_run)

    log.info("moc.complete", files_written=count, dry_run=dry_run)
    return count


def _write_file(path: Path, content: str, dry_run: bool) -> int:
    if dry_run:
        log.debug("moc.dry_run_write", path=str(path))
        return 1
    path.write_text(content, encoding="utf-8")
    return 1


def _ext_to_type(ext: str) -> str:
    """Map extension to human-readable media type."""
    images = {"jpg", "jpeg", "png", "webp", "heic", "heif", "tiff", "gif", "bmp"}
    videos = {"mp4", "mkv", "mov", "avi", "wmv", "flv", "webm", "m4v"}
    audio = {"mp3", "flac", "wav", "aac", "ogg", "m4a", "wma", "opus"}
    docs = {"pdf", "docx", "doc", "txt", "md", "markdown", "rtf", "odt"}
    if ext in images:
        return "Images"
    if ext in videos:
        return "Videos"
    if ext in audio:
        return "Audio"
    if ext in docs:
        return "Documents"
    return "Other"


def _write_moc_by_type(files: list[File], output_dir: Path, dry_run: bool) -> int:
    """Write per-type MOC files."""
    by_type: dict[str, list[File]] = defaultdict(list)
    for f in files:
        media_type = _ext_to_type(f.extension or "")
        by_type[media_type].append(f)

    written = 0
    for media_type, type_files in sorted(by_type.items()):
        lines = [f"# {media_type}", "", f"Total: {len(type_files)} files", ""]
        for f in sorted(type_files, key=lambda x: x.filename):
            dup_marker = " *(duplicate)*" if f.is_duplicate else ""
            lines.append(f"- [[{f.filename}]]{dup_marker}")

        content = "\n".join(lines) + "\n"
        path = output_dir / "MOCs" / "by_type" / f"{media_type}.md"
        written += _write_file(path, content, dry_run)

    return written


def _write_moc_by_year(files: list[File], output_dir: Path, dry_run: bool) -> int:
    """Write per-year MOC files."""
    by_year: dict[str, list[File]] = defaultdict(list)
    for f in files:
        year = "Unknown"
        if f.created_at:
            try:
                year = f.created_at[:4]
            except Exception:
                pass
        elif f.modified_at:
            try:
                year = f.modified_at[:4]
            except Exception:
                pass
        by_year[year].append(f)

    written = 0
    for year, year_files in sorted(by_year.items()):
        lines = [f"# {year}", "", f"Total: {len(year_files)} files", ""]
        for f in sorted(year_files, key=lambda x: x.filename):
            lines.append(f"- [[{f.filename}]]")

        content = "\n".join(lines) + "\n"
        path = output_dir / "MOCs" / "by_year" / f"{year}.md"
        written += _write_file(path, content, dry_run)

    return written


def _write_moc_duplicates(session: Session, output_dir: Path, dry_run: bool) -> int:
    """Write duplicates MOC listing all duplicate groups."""
    dup_files = session.exec(
        select(File).where(File.is_duplicate == 1)
    ).all()

    by_sha: dict[str, list[File]] = defaultdict(list)
    for f in dup_files:
        if f.sha256:
            by_sha[f.sha256].append(f)

    lines = ["# Duplicates", "", f"Duplicate groups: {len(by_sha)}", ""]

    for sha256, group in sorted(by_sha.items()):
        lines.append(f"## Group `{sha256[:12]}...`")
        lines.append("")
        for f in group:
            lines.append(f"- [[{f.filename}]] — `{f.path}`")
        lines.append("")

    if not by_sha:
        lines.append("*No duplicates found.*")

    content = "\n".join(lines) + "\n"
    path = output_dir / "MOCs" / "duplicates" / "Duplicates.md"
    return _write_file(path, content, dry_run)


def _write_moc_index(files: list[File], output_dir: Path, dry_run: bool) -> int:
    """Write main index MOC."""
    total = len(files)
    dups = sum(1 for f in files if f.is_duplicate)
    exts: dict[str, int] = defaultdict(int)
    for f in files:
        exts[f.extension or "unknown"] += 1

    lines = [
        "# MediaHub Index",
        "",
        f"Generated: {datetime.now(tz=UTC).isoformat()}",
        "",
        "## Stats",
        "",
        f"- Total indexed files: {total}",
        f"- Duplicate files: {dups}",
        "",
        "## By Extension",
        "",
    ]
    for ext, cnt in sorted(exts.items(), key=lambda x: -x[1]):
        lines.append(f"- `.{ext}`: {cnt}")

    lines += ["", "## MOC Links", ""]
    lines.append("- [[by_type/Images]]")
    lines.append("- [[by_type/Videos]]")
    lines.append("- [[by_type/Audio]]")
    lines.append("- [[by_type/Documents]]")
    lines.append("- [[by_year/]]")
    lines.append("- [[duplicates/Duplicates]]")

    content = "\n".join(lines) + "\n"
    path = output_dir / "MOCs" / "INDEX.md"
    return _write_file(path, content, dry_run)


def _write_stats_report(session: Session, output_dir: Path, dry_run: bool) -> int:
    """Write stats report to reports/."""
    all_files = session.exec(select(File)).all()
    indexed = [f for f in all_files if f.scan_status == "indexed"]
    dups = [f for f in indexed if f.is_duplicate]
    total_size = sum(f.size_bytes or 0 for f in indexed)
    dup_size = sum(f.size_bytes or 0 for f in dups)

    def _fmt_bytes(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n //= 1024
        return f"{n:.1f} PB"

    lines = [
        "# MediaHub Stats Report",
        "",
        f"Generated: {datetime.now(tz=UTC).isoformat()}",
        "",
        f"- Total files indexed: {len(indexed)}",
        f"- Total storage: {_fmt_bytes(total_size)}",
        f"- Duplicate files: {len(dups)}",
        f"- Space recoverable: {_fmt_bytes(dup_size)}",
        "",
    ]

    content = "\n".join(lines) + "\n"
    path = output_dir / "reports" / "Stats.md"
    return _write_file(path, content, dry_run)
