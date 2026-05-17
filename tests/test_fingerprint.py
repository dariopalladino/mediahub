"""Tests for content hashing / fingerprinting."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from mediactl.fingerprint import (
    PARTIAL_HASH_BYTES,
    hash_file_full,
    hash_file_partial,
    hash_stream_full,
)


def _write_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_hash_file_full_correctness(tmp_path: Path) -> None:
    """MD5 and SHA256 match expected values for known content."""
    content = b"hello mediactl"
    path = _write_file(tmp_path / "test.bin", content)

    expected_md5 = hashlib.md5(content).hexdigest()
    expected_sha = hashlib.sha256(content).hexdigest()

    md5, sha256 = hash_file_full(path)
    assert md5 == expected_md5
    assert sha256 == expected_sha


def test_hash_file_partial_uses_first_bytes(tmp_path: Path) -> None:
    """Partial hash uses only first PARTIAL_HASH_BYTES bytes."""
    content = b"A" * (PARTIAL_HASH_BYTES + 1000)
    path = _write_file(tmp_path / "large.bin", content)

    partial = hash_file_partial(path)
    expected = hashlib.md5(content[:PARTIAL_HASH_BYTES]).hexdigest()
    assert partial == expected


def test_hash_file_partial_small_file(tmp_path: Path) -> None:
    """Partial hash of file smaller than 4MB equals full file MD5."""
    content = b"small content"
    path = _write_file(tmp_path / "small.bin", content)

    partial = hash_file_partial(path)
    expected = hashlib.md5(content).hexdigest()
    assert partial == expected


def test_hash_stream_full(tmp_path: Path) -> None:
    """Stream hash produces same result as file hash."""
    content = b"streaming test content " * 100
    path = _write_file(tmp_path / "stream.bin", content)

    md5_file, sha_file = hash_file_full(path)

    stream = BytesIO(content)
    md5_stream, sha_stream = hash_stream_full(stream)

    assert md5_file == md5_stream
    assert sha_file == sha_stream


def test_different_content_different_hash(tmp_path: Path) -> None:
    """Different content produces different SHA256."""
    p1 = _write_file(tmp_path / "a.bin", b"content A")
    p2 = _write_file(tmp_path / "b.bin", b"content B")

    _, sha1 = hash_file_full(p1)
    _, sha2 = hash_file_full(p2)
    assert sha1 != sha2


def test_identical_content_same_hash(tmp_path: Path) -> None:
    """Identical content produces same SHA256 regardless of filename."""
    content = b"same content here"
    p1 = _write_file(tmp_path / "original.bin", content)
    p2 = _write_file(tmp_path / "copy.bin", content)

    _, sha1 = hash_file_full(p1)
    _, sha2 = hash_file_full(p2)
    assert sha1 == sha2
