"""Content-based file fingerprinting.

Strategy (per spec):
1. Group files by size (fast pre-filter)
2. Partial hash first 4 MB (MD5)
3. Full SHA256 only when partial hash matches

Streaming hashing — never loads full file into memory.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import IO

PARTIAL_HASH_BYTES = 4 * 1024 * 1024  # 4 MB
CHUNK_SIZE = 65536  # 64 KB read chunks


def _hash_stream(stream: IO[bytes], algo: str, max_bytes: int = -1) -> str:
    """Hash a readable binary stream.

    Args:
        stream: Open binary stream (file or SMB stream).
        algo: Hash algorithm name ('md5' or 'sha256').
        max_bytes: Maximum bytes to read. -1 = read all.

    Returns:
        Hex digest string.
    """
    h = hashlib.new(algo)
    read = 0
    while True:
        if max_bytes >= 0:
            remaining = max_bytes - read
            if remaining <= 0:
                break
            chunk_size = min(CHUNK_SIZE, remaining)
        else:
            chunk_size = CHUNK_SIZE

        chunk = stream.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
        read += len(chunk)
    return h.hexdigest()


def hash_file_partial(path: Path) -> str:
    """Compute MD5 of first 4 MB of file.

    Args:
        path: Local file path.

    Returns:
        MD5 hex digest of first 4 MB.
    """
    with path.open("rb") as f:
        return _hash_stream(f, "md5", max_bytes=PARTIAL_HASH_BYTES)


def hash_file_full(path: Path) -> tuple[str, str]:
    """Compute both MD5 and SHA256 of entire file.

    Args:
        path: Local file path.

    Returns:
        Tuple of (md5_hex, sha256_hex).
    """
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def hash_stream_full(stream: IO[bytes]) -> tuple[str, str]:
    """Compute MD5 + SHA256 from a binary stream (e.g. SMB).

    Args:
        stream: Open binary stream.

    Returns:
        Tuple of (md5_hex, sha256_hex).
    """
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    while chunk := stream.read(CHUNK_SIZE):
        md5.update(chunk)
        sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()
