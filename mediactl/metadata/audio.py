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

Audio metadata extractor using mutagen.
Extracts duration, artist, album, title, and other tags.
Handles unsupported formats and missing tags gracefully.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from mediactl.metadata.base import MetadataPlugin

log = structlog.get_logger()

AUDIO_EXTS = {"mp3", "flac", "wav", "aac", "ogg", "m4a", "wma", "opus", "aiff"}


class AudioMetadataPlugin(MetadataPlugin):
    """Extract audio duration, artist, album, title via mutagen."""

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in AUDIO_EXTS

    def process(self, file_path: Path) -> dict[str, Any]:
        result: dict[str, Any] = {}
        try:
            import mutagen  # type: ignore[import-untyped]

            audio = mutagen.File(file_path, easy=True)
            if audio is None:
                result["error"] = "mutagen could not parse file"
                return result

            info = getattr(audio, "info", None)
            if info:
                result["duration_seconds"] = getattr(info, "length", None)
                result["bit_rate"] = getattr(info, "bitrate", None)
                result["sample_rate"] = getattr(info, "sample_rate", None)
                result["channels"] = getattr(info, "channels", None)

            tags = audio.tags
            if tags:
                def _first(key: str) -> str:
                    val = tags.get(key)
                    if val:
                        return str(val[0]) if isinstance(val, list) else str(val)
                    return ""

                result["title"] = _first("title")
                result["artist"] = _first("artist")
                result["album"] = _first("album")
                result["album_artist"] = _first("albumartist")
                result["date"] = _first("date")
                result["track_number"] = _first("tracknumber")
                result["genre"] = _first("genre")

        except ImportError:
            result["error"] = "mutagen not installed"
        except Exception as exc:
            log.warning("metadata.audio.error", path=str(file_path), error=str(exc))
            result["error"] = str(exc)

        return result
