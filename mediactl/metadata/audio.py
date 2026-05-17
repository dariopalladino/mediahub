"""Audio metadata extractor using mutagen."""
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
