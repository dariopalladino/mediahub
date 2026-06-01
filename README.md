# MediaHub — mediactl

Local-first media indexing, deduplication, and Obsidian MOC generation CLI.

## What it does

- Recursively scans SMB network shares or local directories
- Indexes all files into a local SQLite database
- Detects duplicate files by content hash (SHA256) — independent of filename
- Extracts metadata: EXIF (images), ffprobe (video), mutagen (audio), PyMuPDF/python-docx (documents)
- Generates Obsidian-compatible Maps of Content (MOCs)
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

### Statistics

```bash
mediactl stats
```

### Search

```bash
mediactl find "invoice"
mediactl find "vacation" --limit 20
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
│   ├── db/
│   │   ├── models.py       # SQLModel table definitions
│   │   └── session.py      # SQLite engine + session factory
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
    └── test_moc.py
```

## Database

SQLite at `./mediahub.db` (configurable). Schema: `files`, `scans`, `tags`, `file_tags`.

The SQLite index is the source of truth. Markdown MOCs are generated artifacts.

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
