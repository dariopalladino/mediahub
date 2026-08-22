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

Commands:
    scan        Scan SMB share or local path
    dedupe      Detect duplicate files
    generate-moc Generate Obsidian MOC files
    generate-sidecars Generate Artifact sidecar files for knowledge-graph tools (e.g. Graphify)
    stats       Show index statistics
    find        Search indexed files by keyword
    backup      Incrementally back up a local folder to a local/SMB destination
    build-graph Build/update the graph DB consumed by agentic coding tools
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import structlog
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from mediactl import __version__

app = typer.Typer(
    name="mediahub CLI",
    help="Local-first media indexing and deduplication CLI.",
    no_args_is_help=True,
)

_LICENSE_TEXT = (
    "MediaHub CLI - Copyright (C) 2026  Dario Palladino\n"
    "This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.\n"
    "This is free software, and you are welcome to redistribute it\n"
    "under certain conditions. See LICENSE for details."
)
console = Console()
log = structlog.get_logger()

DEFAULT_CONFIG = Path("config.yaml")


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _load_config_or_exit(config_path: Path):
    from mediactl.config import ConfigError, load_config

    try:
        return load_config(config_path)
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(1)


def _init_db_from_config(cfg) -> None:
    from mediactl.db.session import init_db

    init_db(cfg.db_path)


def _resolve_smb_credentials(
    cli_username: str | None,
    cli_password: str | None,
    cfg,
) -> tuple[str, str]:
    """Resolve SMB credentials from CLI > environment > config."""
    user = cli_username
    if user is None:
        user = os.getenv("MEDIACTL_SMB_USER")
    if not user:
        user = cfg.smb.username

    password = cli_password
    if password is None:
        password = os.getenv("MEDIACTL_SMB_PASS")
    if not password:
        password = cfg.smb.password

    return user or "", password or ""


@app.command()
def scan(
    target: str | None = typer.Argument(None, help="SMB URI (smb://host/share) or local path. Overrides config."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    username: str | None = typer.Option(None, "--username", "-u", help="SMB username"),
    password: str | None = typer.Option(None, "--password", "-p", help="SMB password"),
    resume: bool = typer.Option(False, "--resume", help="Skip files already indexed"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scan without writing to DB"),
    exclude: list[str] | None = typer.Option(None, "--exclude", help="Glob patterns to exclude"),
    workers: int = typer.Option(0, "--workers", "-w", help="Worker threads (0 = use config value)"),
    extract_metadata: bool = typer.Option(True, "--metadata/--no-metadata", help="Extract file metadata"),
    log_level: str = typer.Option("INFO", "--log-level", help="Log level"),
) -> None:
    """Scan a media source (SMB share or local path) and index all files."""
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)

    cfg = _load_config_or_exit(config)
    _init_db_from_config(cfg)

    # Determine scan target
    scan_target = target
    use_smb = False

    if scan_target is None:
        if cfg.use_smb:
            scan_target = f"smb://{cfg.smb.host}/{cfg.smb.share}"
            use_smb = True
        elif cfg.local.path:
            scan_target = cfg.local.path
        else:
            console.print("[red]No scan target. Provide target argument or configure smb/local in config.yaml[/red]")
            raise typer.Exit(1)
    elif scan_target.lower().startswith("smb://"):
        use_smb = True

    effective_workers = workers if workers > 0 else cfg.scanner.workers
    effective_exclude = list(exclude or []) + cfg.scanner.exclude

    console.print(f"[green]Scanning:[/green] {scan_target}")
    console.print(f"  workers={effective_workers}, dry_run={dry_run}, resume={resume}")

    # Build scanner
    from mediactl.scanner.base import BaseScanner

    scanner: BaseScanner
    if use_smb:
        from mediactl.scanner.smb import SMBScanner

        smb_user, smb_pass = _resolve_smb_credentials(username, password, cfg)
        if not smb_user or not smb_pass:
            console.print("[red]SMB credentials are required for SMB scans.[/red]")
            console.print(
                "Provide --username/--password, set MEDIACTL_SMB_USER/MEDIACTL_SMB_PASS, "
                "or configure smb.username/smb.password in config.yaml"
            )
            raise typer.Exit(1)

        scanner = SMBScanner(
            username=smb_user,
            password=smb_pass,
            exclude_patterns=effective_exclude,
            max_depth=cfg.scanner.max_depth,
            workers=effective_workers,
        )
    else:
        from mediactl.scanner.local import LocalScanner

        scanner = LocalScanner(
            exclude_patterns=effective_exclude,
            max_depth=cfg.scanner.max_depth,
            workers=effective_workers,
        )

    # Build metadata extractor registry
    plugins = []
    if extract_metadata:
        from mediactl.metadata.audio import AudioMetadataPlugin
        from mediactl.metadata.documents import DocumentMetadataPlugin
        from mediactl.metadata.images import ImageMetadataPlugin
        from mediactl.metadata.video import VideoMetadataPlugin

        plugins = [
            ImageMetadataPlugin(),
            VideoMetadataPlugin(),
            AudioMetadataPlugin(),
            DocumentMetadataPlugin(),
        ]

    from sqlmodel import select

    from mediactl.db.models import File, Scan
    from mediactl.db.session import get_session

    with get_session() as session:
        # Record scan start
        scan_record = Scan(started_at=_now())
        if not dry_run:
            session.add(scan_record)
            session.commit()
            session.refresh(scan_record)

        files_scanned = 0
        files_updated = 0
        errors = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Scanning...", total=None)

            try:
                for entry in scanner.scan(scan_target):
                    progress.update(task, description=f"Scanning: {entry.filename}")
                    files_scanned += 1

                    try:
                        # Check if already indexed
                        existing = session.exec(
                            select(File).where(File.path == entry.path)
                        ).first()

                        if existing and resume:
                            continue

                        now = _now()

                        if existing:
                            # Update existing record
                            existing.size_bytes = entry.size_bytes
                            existing.modified_at = entry.modified_at
                            existing.last_seen_at = now
                            existing.scan_status = "indexed"
                            db_file = existing
                        else:
                            db_file = File(
                                path=entry.path,
                                smb_uri=entry.smb_uri,
                                filename=entry.filename,
                                extension=entry.extension,
                                size_bytes=entry.size_bytes,
                                created_at=entry.created_at,
                                modified_at=entry.modified_at,
                                first_seen_at=now,
                                last_seen_at=now,
                                indexed_at=now,
                                scan_status="indexed",
                            )

                        # Compute hashes
                        if not dry_run:
                            if entry.is_local:
                                try:
                                    from mediactl.fingerprint import hash_file_full
                                    md5, sha256 = hash_file_full(Path(entry.path))
                                    db_file.md5 = md5
                                    db_file.sha256 = sha256
                                except Exception as exc:
                                    log.warning("scan.hash_error", path=entry.path, error=str(exc))
                            elif entry.smb_uri:
                                try:
                                    import smbclient  # type: ignore[import-untyped]
                                    from mediactl.fingerprint import hash_stream_full
                                    from mediactl.scanner.smb import parse_smb_uri
                                    host, share, subpath = parse_smb_uri(entry.smb_uri)
                                    unc = f"\\\\{host}\\{share}{subpath.replace('/', '\\')}"
                                    with smbclient.open_file(unc, mode="rb") as smb_f:
                                        md5, sha256 = hash_stream_full(smb_f)
                                    db_file.md5 = md5
                                    db_file.sha256 = sha256
                                except Exception as exc:
                                    log.warning("scan.hash_error", path=entry.path, error=str(exc))

                        # Extract metadata (local files only — SMB paths cannot be opened as local)
                        if extract_metadata and plugins and not dry_run and entry.is_local:
                            for plugin in plugins:
                                if plugin.supports(entry.extension):
                                    try:
                                        meta = plugin.process(Path(entry.path))
                                        # Store metadata in appropriate fields
                                        if not db_file.mime_type and meta.get("format"):
                                            db_file.mime_type = meta.get("format", "").lower()
                                    except Exception as exc:
                                        log.warning("scan.metadata_error", path=entry.path, error=str(exc))
                                    break

                        if not dry_run:
                            session.add(db_file)
                            if files_scanned % 500 == 0:
                                session.commit()
                            files_updated += 1

                    except Exception as exc:
                        errors += 1
                        log.error("scan.file_error", path=entry.path, error=str(exc))
            except Exception as exc:
                if use_smb:
                    message = str(exc)
                    if "SMBAuthenticationError" in message or "SpnegoError" in message:
                        console.print("[red]SMB authentication failed.[/red]")
                        console.print(
                            "Verify credentials and SMB auth support on the server. "
                            "If needed, include domain in username (example: DOMAIN\\user)."
                        )
                        raise typer.Exit(1)
                raise

            if not dry_run:
                session.commit()

                if scan_record.id is not None:
                    scan_record.completed_at = _now()
                    scan_record.files_scanned = files_scanned
                    scan_record.files_updated = files_updated
                    scan_record.errors_count = errors
                    session.add(scan_record)
                    session.commit()

    console.print("\n[green]Scan complete.[/green]")
    console.print(f"  Files scanned: {files_scanned}")
    console.print(f"  Files updated: {files_updated}")
    console.print(f"  Errors: {errors}")
    if dry_run:
        console.print("  [yellow](dry-run: no changes written)[/yellow]")


@app.command()
def dedupe(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect duplicates without marking them"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Detect and mark duplicate files by content hash (SHA256)."""
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    _init_db_from_config(cfg)

    from mediactl.db.session import get_session
    from mediactl.dedupe import compute_missing_hashes, run_dedupe

    with get_session() as session:
        console.print("[cyan]Computing missing hashes...[/cyan]")
        hashed = compute_missing_hashes(session, dry_run=dry_run)
        console.print(f"  Hashed: {hashed} files")

        console.print("[cyan]Running duplicate detection...[/cyan]")
        groups = run_dedupe(session, dry_run=dry_run)

    if not groups:
        console.print("[green]No duplicates found.[/green]")
        return

    console.print(f"\n[yellow]Duplicate groups found: {len(groups)}[/yellow]")
    table = Table(title="Duplicate Groups", show_header=True)
    table.add_column("SHA256 (prefix)", style="dim")
    table.add_column("Count", justify="right")

    for sha256, ids in sorted(groups.items(), key=lambda x: -len(x[1]))[:20]:
        table.add_row(sha256[:16] + "...", str(len(ids)))

    console.print(table)
    if dry_run:
        console.print("[yellow](dry-run: no changes written)[/yellow]")


@app.command(name="generate-moc")
def generate_moc(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Override MOC output directory"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Generate Obsidian-compatible MOC markdown files."""
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    _init_db_from_config(cfg)

    out = output_dir or cfg.moc_output_path
    if not out:
        console.print("[red]moc.output_dir not configured.[/red]")
        raise typer.Exit(1)

    from mediactl.db.session import get_session
    from mediactl.moc import generate_mocs

    with get_session() as session:
        count = generate_mocs(session, out, dry_run=dry_run)

    console.print(f"[green]MOC generation complete.[/green] Files written: {count}")
    if dry_run:
        console.print("[yellow](dry-run: no files written)[/yellow]")


@app.command(name="generate-sidecars")
def generate_sidecars_cmd(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Override sidecars output directory"),
    force: bool = typer.Option(
        False, "--force", help="Overwrite sidecars that already exist (default: skip them, since a harness "
        "may have enriched them by hand since they were created)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Generate Artifact-sidecar Markdown files for knowledge-graph tools (e.g. Graphify).

    One sidecar per indexed file, containing only the deterministic facts mediactl
    knows (path, hash, timestamps, MOC membership, duplicate status). Topics,
    entities, and summaries are intentionally left blank for later enrichment.

    Requires sidecars.enabled: true and sidecars.output_dir in config.yaml.
    """
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)

    from mediactl.config import ConfigError

    cfg = _load_config_or_exit(config)
    try:
        cfg.validate_sidecars()
    except ConfigError as exc:
        console.print(f"[red]Sidecars error:[/red] {exc}")
        raise typer.Exit(1)

    _init_db_from_config(cfg)

    out = output_dir or cfg.sidecars_output_path

    from mediactl.db.session import get_session
    from mediactl.sidecars import generate_sidecars

    with get_session() as session:
        result = generate_sidecars(session, out, force=force, dry_run=dry_run)

    console.print("\n[green]Sidecar generation complete.[/green]")
    console.print(f"  Total indexed files: {result.total}")
    console.print(f"  Sidecars created: {result.created}")
    console.print(f"  Skipped (already exist): {result.skipped_existing}")
    if dry_run:
        console.print("  [yellow](dry-run: no files written)[/yellow]")


@app.command()
def stats(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Show index statistics."""
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    _init_db_from_config(cfg)

    from sqlmodel import select

    from mediactl.db.models import File, Scan
    from mediactl.db.session import get_session

    with get_session() as session:
        all_files = session.exec(select(File)).all()
        indexed = [f for f in all_files if f.scan_status == "indexed"]
        dups = [f for f in indexed if f.is_duplicate]
        total_size = sum(f.size_bytes or 0 for f in indexed)
        dup_size = sum(f.size_bytes or 0 for f in dups)

        ext_counts: dict[str, int] = {}
        for f in indexed:
            ext = f.extension or "unknown"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        scans = session.exec(select(Scan).order_by(Scan.started_at.desc()).limit(5)).all()  # type: ignore[attr-defined]

    def _fmt(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n //= 1024
        return f"{n} PB"

    console.print("\n[bold]MediaHub Index Stats[/bold]")
    console.print(f"  Database: {cfg.db_path}")
    console.print(f"  Total files: {len(indexed)}")
    console.print(f"  Total storage: {_fmt(total_size)}")
    console.print(f"  Duplicates: {len(dups)} ({_fmt(dup_size)} recoverable)")
    console.print("\n  [bold]Top extensions:[/bold]")
    for ext, cnt in sorted(ext_counts.items(), key=lambda x: -x[1])[:10]:
        console.print(f"    .{ext}: {cnt}")

    if scans:
        console.print("\n  [bold]Recent scans:[/bold]")
        for s in scans:
            status = "✓" if s.completed_at else "⟳"
            console.print(f"    {status} {s.started_at[:19]} — {s.files_scanned} files, {s.errors_count} errors")


@app.command(name="find")
def find_files(
    query: str = typer.Argument(..., help="Search term"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    limit: int = typer.Option(50, "--limit", "-n"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Search indexed files by filename or path."""
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    _init_db_from_config(cfg)

    from sqlmodel import select

    from mediactl.db.models import File
    from mediactl.db.session import get_session

    with get_session() as session:
        stmt = select(File).where(
            (File.filename.contains(query)) | (File.path.contains(query))  # type: ignore[attr-defined]
        ).limit(limit)
        results = session.exec(stmt).all()

    if not results:
        console.print(f"[yellow]No files found matching:[/yellow] {query!r}")
        return

    console.print(f"\n[green]{len(results)} result(s) for:[/green] {query!r}\n")
    table = Table(show_header=True)
    table.add_column("Filename")
    table.add_column("Ext", width=6)
    table.add_column("Size")
    table.add_column("Dup", width=5)
    table.add_column("Path", overflow="fold")

    def _fmt_size(n: int | None) -> str:
        if n is None:
            return "-"
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f}{unit}"
            n //= 1024
        return f"{n}GB"

    for f in results:
        table.add_row(
            f.filename,
            f.extension or "",
            _fmt_size(f.size_bytes),
            "Y" if f.is_duplicate else "",
            f.path,
        )
    console.print(table)


@app.command()
def backup(
    source: str | None = typer.Argument(None, help="Local path to back up. Overrides config."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    destination: str | None = typer.Option(
        None, "--destination", "-d", help="Local/mounted path or smb://host/share[/path]. Overrides config."
    ),
    username: str | None = typer.Option(None, "--username", "-u", help="SMB destination username"),
    password: str | None = typer.Option(None, "--password", "-p", help="SMB destination password"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be copied without writing"),
    exclude: list[str] | None = typer.Option(None, "--exclude", help="Glob patterns to exclude"),
    log_level: str = typer.Option("INFO", "--log-level", help="Log level"),
) -> None:
    """Incrementally back up a local folder to a local/mounted or SMB destination.

    Only files whose content has changed since the last sync are copied.
    Disabled unless backup.enabled: true is set in config.yaml.
    """
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)

    from mediactl.config import ConfigError

    cfg = _load_config_or_exit(config)
    try:
        cfg.validate_backup()
    except ConfigError as exc:
        console.print(f"[red]Backup error:[/red] {exc}")
        raise typer.Exit(1)

    effective_source = source or cfg.backup.source or cfg.local.path
    effective_destination = destination or cfg.backup.destination
    effective_exclude = list(exclude or []) + cfg.backup.exclude

    console.print(f"[green]Backing up:[/green] {effective_source} -> {effective_destination}")
    console.print(f"  dry_run={dry_run}")

    from mediactl.backup.base import BaseBackupTarget

    target: BaseBackupTarget
    if effective_destination.lower().startswith("smb://"):
        from mediactl.backup.smb import SMBBackupTarget

        smb_user = username or os.getenv("MEDIACTL_SMB_USER") or cfg.backup.username
        smb_pass = password or os.getenv("MEDIACTL_SMB_PASS") or cfg.backup.password
        if not smb_user or not smb_pass:
            console.print("[red]SMB credentials are required for SMB backup destinations.[/red]")
            console.print(
                "Provide --username/--password, set MEDIACTL_SMB_USER/MEDIACTL_SMB_PASS, "
                "or configure backup.username/backup.password in config.yaml"
            )
            raise typer.Exit(1)
        target = SMBBackupTarget(destination=effective_destination, username=smb_user, password=smb_pass)
    else:
        from mediactl.backup.local import LocalBackupTarget

        target = LocalBackupTarget(destination=effective_destination)

    from mediactl.backup.engine import BackupEngine

    try:
        engine = BackupEngine(
            source=effective_source,
            target=target,
            state_file=cfg.backup_state_path,
            exclude_patterns=effective_exclude,
            dry_run=dry_run,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Backing up...", total=None)
        result = engine.run(on_file=lambda rel: progress.update(task, description=f"Backing up: {rel}"))

    console.print("\n[green]Backup complete.[/green]")
    console.print(f"  Files scanned: {result.files_scanned}")
    console.print(f"  Files copied: {result.files_copied}")
    console.print(f"  Files unchanged: {result.files_unchanged}")
    console.print(f"  Errors: {result.errors}")
    if dry_run:
        console.print("  [yellow](dry-run: no files written, no state saved)[/yellow]")


@app.command(name="build-graph")
def build_graph(
    target: str | None = typer.Argument(
        None, help="SMB URI or local path override (--source scan only). Overrides config."
    ),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml"),
    source: str = typer.Option(
        "sqlite",
        "--source",
        "-s",
        help="Graph data source: 'sqlite' (derive from the indexed DB) or 'scan' (walk the root directory fresh).",
    ),
    update: bool = typer.Option(
        False,
        "--update",
        help="Incrementally sync an existing graph DB against the source instead of a full rebuild. "
        "Flags and reports drift (incongruences) found along the way.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Wipe and fully rebuild an existing graph DB (mutually exclusive with --update)."
    ),
    username: str | None = typer.Option(None, "--username", "-u", help="SMB username (--source scan only)"),
    password: str | None = typer.Option(None, "--password", "-p", help="SMB password (--source scan only)"),
    exclude: list[str] | None = typer.Option(
        None, "--exclude", help="Glob patterns to exclude (--source scan only)"
    ),
    workers: int = typer.Option(
        0, "--workers", "-w", help="Worker threads (0 = use config value; --source scan only)"
    ),
    max_depth: int | None = typer.Option(
        None, "--max-depth", help="Max directory recursion depth (default: config value; --source scan only)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect changes without writing to the graph DB"),
    log_level: str = typer.Option("INFO", "--log-level", help="Log level"),
) -> None:
    """Build or update the graph DB that agentic coding tools (Claude Code, Codex, etc.)
    query to answer questions about the media library.

    Two sources: 'sqlite' derives nodes/edges from the already-indexed mediactl DB
    (hashes, tags, duplicate groups included). 'scan' walks the root directory fresh,
    independent of the index DB (structural nodes only).

    Re-run with --update to incrementally sync an existing graph DB instead of a full
    rebuild; drift found between the graph and the source is reported at the end.
    """
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)

    if update and force:
        console.print("[red]--update and --force are mutually exclusive.[/red]")
        raise typer.Exit(1)

    if source not in ("sqlite", "scan"):
        console.print(f"[red]Invalid --source: {source!r}. Must be 'sqlite' or 'scan'.[/red]")
        raise typer.Exit(1)

    cfg = _load_config_or_exit(config)

    from mediactl.graphdb.session import get_graph_session, init_graph_db

    init_graph_db(cfg.graph_db_path)

    from sqlmodel import select

    from mediactl.graphdb.models import GraphNode, GraphRun

    with get_graph_session() as graph_session:
        has_existing = graph_session.exec(select(GraphNode).limit(1)).first() is not None

        if has_existing and not update and not force:
            console.print(
                f"[red]Graph DB already has data at {cfg.graph_db_path}.[/red]\n"
                "Pass --update to incrementally sync it, or --force to wipe and rebuild."
            )
            raise typer.Exit(1)

        console.print(f"[green]Building graph:[/green] source={source}, mode={'update' if update else 'build'}")
        console.print(f"  graph_db={cfg.graph_db_path}, dry_run={dry_run}")

        run_record = GraphRun(started_at=_now(), mode="update" if update else "build", source=source)
        if not dry_run:
            graph_session.add(run_record)
            graph_session.commit()
            graph_session.refresh(run_record)

        from mediactl.graphdb.builder import build_from_scan, build_from_sqlite

        if source == "sqlite":
            if username or password or exclude or workers or max_depth is not None:
                console.print(
                    "  [yellow](--source sqlite doesn't scan — "
                    "--username/--password/--exclude/--workers/--max-depth are ignored)[/yellow]"
                )
            _init_db_from_config(cfg)

            from mediactl.db.session import get_session

            with get_session() as index_session:
                result = build_from_sqlite(index_session, graph_session, update=update)
        else:
            scan_target = target
            use_smb = False
            if scan_target is None:
                if cfg.use_smb:
                    scan_target = f"smb://{cfg.smb.host}/{cfg.smb.share}"
                    use_smb = True
                elif cfg.local.path:
                    scan_target = cfg.local.path
                else:
                    console.print(
                        "[red]No scan target. Provide target argument or configure smb/local in config.yaml[/red]"
                    )
                    raise typer.Exit(1)
            elif scan_target.lower().startswith("smb://"):
                use_smb = True

            effective_workers = workers if workers > 0 else cfg.scanner.workers
            effective_exclude = list(exclude or []) + cfg.scanner.exclude
            effective_max_depth = max_depth if max_depth is not None else cfg.scanner.max_depth

            console.print(f"  target={scan_target}, workers={effective_workers}, max_depth={effective_max_depth}")

            from mediactl.scanner.base import BaseScanner

            scanner: BaseScanner
            if use_smb:
                from mediactl.scanner.smb import SMBScanner

                smb_user, smb_pass = _resolve_smb_credentials(username, password, cfg)
                if not smb_user or not smb_pass:
                    console.print("[red]SMB credentials are required for SMB scans.[/red]")
                    raise typer.Exit(1)
                scanner = SMBScanner(
                    username=smb_user,
                    password=smb_pass,
                    exclude_patterns=effective_exclude,
                    max_depth=effective_max_depth,
                    workers=effective_workers,
                )
            else:
                from mediactl.scanner.local import LocalScanner

                scanner = LocalScanner(
                    exclude_patterns=effective_exclude,
                    max_depth=effective_max_depth,
                    workers=effective_workers,
                )

            result = build_from_scan(scanner, scan_target, graph_session, update=update)

        if dry_run:
            graph_session.rollback()
        else:
            graph_session.commit()

            run_record.completed_at = _now()
            run_record.nodes_created = result.nodes_created
            run_record.nodes_updated = result.nodes_updated
            run_record.nodes_removed = result.nodes_removed
            run_record.edges_created = result.edges_created
            run_record.edges_removed = result.edges_removed
            run_record.incongruences_count = result.incongruences_count
            graph_session.add(run_record)
            graph_session.commit()

    console.print("\n[green]Graph build complete.[/green]")
    console.print(f"  Nodes created: {result.nodes_created}")
    console.print(f"  Nodes updated: {result.nodes_updated}")
    console.print(f"  Nodes removed: {result.nodes_removed}")
    console.print(f"  Edges created: {result.edges_created}")
    console.print(f"  Edges removed: {result.edges_removed}")
    if dry_run:
        console.print("  [yellow](dry-run: no changes written)[/yellow]")

    if update:
        if result.incongruences_count:
            console.print(f"\n[yellow]Incongruences detected: {result.incongruences_count}[/yellow]")
            table = Table(title="Graph/Source Incongruences (sample)", show_header=True)
            table.add_column("Kind", style="dim")
            table.add_column("Type")
            table.add_column("Key", overflow="fold")
            table.add_column("Field")
            table.add_column("Old", overflow="fold")
            table.add_column("New", overflow="fold")

            flagged = [e for e in result.incongruences if e.kind in ("updated", "removed")]
            for entry in flagged[:20]:
                table.add_row(
                    entry.kind, entry.node_type, entry.key,
                    entry.field or "", entry.old_value or "", entry.new_value or "",
                )
            console.print(table)
            if len(flagged) > 20:
                console.print(f"  ... and {len(flagged) - 20} more (see full report)")
        else:
            console.print("\n[green]No incongruences detected — graph matches source.[/green]")

        if not dry_run:
            from mediactl.graphdb.builder import write_incongruence_report

            report_path = write_incongruence_report(result, cfg.graph_db_path)
            console.print(f"  Full report: {report_path}")


@app.command()
def init_db(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Initialize the database schema."""
    from mediactl.logging_setup import setup_logging

    setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    _init_db_from_config(cfg)
    console.print(f"[green]Database initialized at:[/green] {cfg.db_path}")


@app.callback(invoke_without_command=True)
def version_callback(
    version: bool = typer.Option(False, "--version", "-V", is_eager=True),
    license: bool = typer.Option(False, "--license", is_eager=True, help="Show license and exit."),
    ctx: typer.Context = typer.Option(None, hidden=True),  # type: ignore[assignment]
) -> None:
    if version:
        console.print(f"mediactl {__version__}")
        raise typer.Exit()
    if license:
        console.print(_LICENSE_TEXT)
        raise typer.Exit()


def main() -> None:
    """CLI entry point."""
    console.print(_LICENSE_TEXT)
    app()


if __name__ == "__main__":
    main()
