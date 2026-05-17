"""Video metadata extractor using ffprobe (subprocess)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import structlog

from mediactl.metadata.base import MetadataPlugin

log = structlog.get_logger()

VIDEO_EXTS = {"mp4", "mkv", "mov", "avi", "wmv", "flv", "webm", "m4v", "ts", "m2ts"}


class VideoMetadataPlugin(MetadataPlugin):
    """Extract video codec, duration, resolution via ffprobe."""

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in VIDEO_EXTS

    def process(self, file_path: Path) -> dict[str, Any]:
        result: dict[str, Any] = {}

        if not shutil.which("ffprobe"):
            result["error"] = "ffprobe not found in PATH"
            return result

        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                str(file_path),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0:
                result["error"] = proc.stderr.strip()
                return result

            data = json.loads(proc.stdout)
            fmt = data.get("format", {})
            result["duration_seconds"] = float(fmt.get("duration", 0))
            result["size_bytes"] = int(fmt.get("size", 0))
            result["bit_rate"] = int(fmt.get("bit_rate", 0))
            result["format_name"] = fmt.get("format_name", "")

            for stream in data.get("streams", []):
                codec_type = stream.get("codec_type", "")
                if codec_type == "video":
                    result["video_codec"] = stream.get("codec_name", "")
                    result["width"] = stream.get("width", 0)
                    result["height"] = stream.get("height", 0)
                    result["frame_rate"] = stream.get("r_frame_rate", "")
                elif codec_type == "audio":
                    result["audio_codec"] = stream.get("codec_name", "")
                    result["audio_channels"] = stream.get("channels", 0)
                    result["audio_sample_rate"] = stream.get("sample_rate", "")

        except subprocess.TimeoutExpired:
            result["error"] = "ffprobe timeout"
        except json.JSONDecodeError as exc:
            result["error"] = f"ffprobe JSON parse error: {exc}"
        except Exception as exc:
            log.warning("metadata.video.error", path=str(file_path), error=str(exc))
            result["error"] = str(exc)

        return result
