# MediaHub CLI (mediactl)

CLI to build your Media Server database, find any file with semantic searches, generate deduplication reports and Map of Contents (MOC) stored as Obsidian Vault compatible [[wikilinks]]

## What it does

- Recursively scans SMB network shares or local directories
- Indexes all files into a local SQLite database
- Detects duplicate files by content hash (SHA256) — independent of filename
- Extracts metadata: EXIF (images), ffprobe (video), mutagen (audio), PyMuPDF/python-docx (documents)
- Generates Obsidian-compatible Maps of Content (MOCs)
- Builds a SQLite property graph and Artifact-sidecar Markdown files for agentic
  coding/knowledge-graph tools to query
- Fully incremental — skips unchanged files on rescan
- Read-only by default — no file is ever modified or deleted

## Requirements

- Python 3.12+
- macOS or Linux
- `uv` (installed automatically — see Setup)
- `ffprobe` (optional, for video metadata): `brew install ffmpeg`

## Setup

```bash
# From project root
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

cd app/
uv sync
```

After sync, the `mediactl` CLI is available at `app/.venv/bin/mediactl`.

To use globally:

```bash
uv tool install --editable app/
```

## Configuration

Copy `app/config.yaml.example` to `app/config.yaml` and edit:

```yaml
smb:
  host: media-server     # set to scan SMB share; leave empty for local
  share: archive

local:
  path: /home/user/Documents  # used when smb.host is empty

scanner:
  workers: 8
  exclude:
    - "*.tmp"
    - ".DS_Store"

database:
  path: ./mediahub.db

moc:
  output_dir: ./vault    # required
```

**Priority rule**: `smb.host` takes priority over `local.path`.
`moc.output_dir` is required — error if missing.

**Secrets**: never put SMB passwords in config.yaml committed to version control. Use `--password` CLI flag or a local-only config.yaml (it is in `.gitignore`).

## Usage

### Scan

```bash
# Scan from config
mediactl scan

# Scan specific SMB share (overrides config)
mediactl scan smb://media-server/archive --username user --password pass

# Scan local path (dry run)
mediactl scan /Volumes/Media --dry-run

# Resume interrupted scan
mediactl scan --resume

# Exclude patterns, limit workers
mediactl scan --exclude "*.tmp" --exclude ".Spotlight*" --workers 4
```

### Detect Duplicates

```bash
mediactl dedupe

# Preview without writing
mediactl dedupe --dry-run
```

### Generate Obsidian MOCs

```bash
mediactl generate-moc

# Custom output dir
mediactl generate-moc --output-dir /path/to/vault

# Preview
mediactl generate-moc --dry-run
```

### Generate knowledge-graph sidecars

Emits one Artifact-sidecar Markdown file per indexed file (YAML frontmatter +
short body), matching the format a downstream graph compiler (e.g. Graphify)
expects as input. Only deterministic facts mediactl actually knows are filled in
— path, hash, timestamps, MOC membership, duplicate status — never topics,
entities, or summaries, since mediactl has no content-understanding pipeline.
`status: inventoried` / `needs_enrichment: true` mark that clearly for whatever
processes the sidecar next.

Disabled by default. Requires `sidecars.enabled: true` and `sidecars.output_dir`
in config.yaml.

**Create-only by default**: once a sidecar exists, later runs skip it rather than
overwrite it, since an agentic harness may have since enriched it by hand (added
topics, a summary, curated relationships). Use `--force` to intentionally
regenerate from scratch.

```bash
mediactl generate-sidecars

# Overwrite existing sidecars (destroys any manual enrichment — use deliberately)
mediactl generate-sidecars --force

# Preview
mediactl generate-sidecars --dry-run
```

### Statistics

```bash
mediactl stats
```

### Search

```bash
mediactl find "invoice"
mediactl find "vacation" --limit 20
```

### Build the graph DB (for agentic tools)

Builds/updates a SQLite property graph (`graph.path` in config, default
`./mediahub_graph.db`) of files, directories, tags, media types, and duplicate
groups — meant to be queried by agentic coding harnesses (Claude Code, Codex,
GitHub Copilot, etc.) to answer questions about the media library.

```bash
# Full build from the already-indexed mediactl DB (hashes/tags/dup groups included)
mediactl build-graph

# Full build by walking the root directory fresh, independent of the index DB
mediactl build-graph --source scan

# Incrementally sync an existing graph DB against its source; drift found
# between the graph and the source ("incongruences") is flagged and written
# to graph_reports/graph_<source>_update_<timestamp>.json next to the graph DB
mediactl build-graph --update
mediactl build-graph --source scan --update

# Wipe and fully rebuild an existing graph DB
mediactl build-graph --force

# Scanner-style options apply to --source scan
mediactl build-graph --source scan --workers 4 --exclude "*.tmp" --max-depth 3

# Preview without writing
mediactl build-graph --update --dry-run
```

## Development

```bash
cd app/

# Install deps
make install

# Run tests
make test

# Lint
make lint

# Type check
make typecheck

# Coverage
make test-cov
```

## Architecture

```
app/
├── mediactl/
│   ├── cli.py              # Typer CLI entry point
│   ├── config.py           # config.yaml loading + validation
│   ├── logging_setup.py    # structlog + Rich
│   ├── fingerprint.py      # Streaming MD5/SHA256 hashing
│   ├── dedupe.py           # Duplicate detection + canonical selection
│   ├── moc.py              # Obsidian MOC generator
│   ├── sidecars.py         # Artifact-sidecar generator (Graphify/knowledge-graph input)
│   ├── db/
│   │   ├── models.py       # SQLModel table definitions
│   │   └── session.py      # SQLite engine + session factory
│   ├── graphdb/
│   │   ├── models.py       # GraphNode/GraphEdge/GraphRun (isolated SQLModel metadata)
│   │   ├── session.py      # Graph SQLite engine + session factory
│   │   └── builder.py      # Build/update from sqlite or scan + incongruence reporting
│   ├── scanner/
│   │   ├── base.py         # Abstract BaseScanner
│   │   ├── local.py        # Local filesystem scanner
│   │   └── smb.py          # SMB scanner (smbprotocol)
│   └── metadata/
│       ├── base.py         # MetadataPlugin ABC (plugin interface)
│       ├── images.py       # Pillow + EXIF
│       ├── video.py        # ffprobe
│       ├── audio.py        # mutagen
│       └── documents.py    # PyMuPDF + python-docx
└── tests/
    ├── test_scanner.py
    ├── test_fingerprint.py
    ├── test_dedupe.py
    ├── test_moc.py
    ├── test_graphdb.py
    └── test_sidecars.py
```

## Database

SQLite at `./mediahub.db` (configurable). Schema: `files`, `scans`, `tags`, `file_tags`.

The SQLite index is the source of truth. Markdown MOCs are generated artifacts.

A separate SQLite graph DB (`./mediahub_graph.db`, configurable via `graph.path`)
mirrors the index as a property graph — `graph_nodes` (file/directory/tag/media_type/
duplicate_group) and `graph_edges` (CONTAINS/HAS_TAG/HAS_TYPE/DUPLICATE_OF/MEMBER_OF)
— for agentic coding tools to query directly. See `mediactl build-graph`.

## Plugin Architecture

Future AI enrichment plugins (OCR, Whisper, CLIP, LLM tagging) implement:

```python
from mediactl.metadata.base import MetadataPlugin

class MyPlugin(MetadataPlugin):
    def supports(self, file_type: str) -> bool: ...
    def process(self, file_path: Path) -> dict[str, Any]: ...
```

## Tech Stack

| Purpose | Library |
|---|---|
| CLI | Typer |
| ORM | SQLModel |
| SMB | smbprotocol |
| Hashing | hashlib (stdlib) |
| Images | Pillow |
| PDFs | PyMuPDF |
| Video | ffprobe (subprocess) |
| Audio | mutagen |
| Logging | structlog + Rich |
| Packaging | uv |
| Linting | Ruff |
| Types | Mypy |
| Tests | Pytest |
