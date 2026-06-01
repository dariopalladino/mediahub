# Contributing to MediaHub CLI

Thank you for your interest in contributing to MediaHub CLI. This guide is the fast path for getting a fresh checkout running locally, validating changes, and opening a pull request without having to piece together setup notes from multiple files.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Layout](#project-layout)
- [Making Changes](#making-changes)
- [Submitting Changes](#submitting-changes)
- [Project Conventions](#project-conventions)

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

- Read the [README](README.md) for product context.
- Check [open issues](https://github.com/dariopalladino/mediahub/issues) and discussions before starting work.
- For security issues, follow [SECURITY.md](SECURITY.md) and do not file public issues.

## Development Setup

Read the [README](README.md) for installation instructions.
Use the Makefile to install, test and run.


## Project Layout

```text
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

## Making Changes

1. Start from `main` and create a focused branch.
2. Keep the diff small and scoped to the issue you are solving.
3. Run the smallest relevant checks locally before pushing.
4. Update docs with code whenever behavior, commands, or contributor workflow changes.


## Submitting Changes

1. Push your branch to your fork.
2. Open a pull request against `dariopalladino/mediahub:main`.
3. Explain the scope of your changes and what new components were added.
4. Link the issue using a closing keyword such as `Closes #1441`.
5. Call out any blocked validation commands with the exact command and error.


## Project Conventions

- Follow the contracts to implement new scanners or metadata plugins 
- Always use Makefile
- Keep `pyproject.toml` or `uv.lock` up-to-date.
- Always keep README up-to-date.

Thank you for contributing to MediaHub CLI.