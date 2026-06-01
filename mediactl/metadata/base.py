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

MetadataPlugin ABC — plugin interface for metadata extraction.

Future AI enrichers (OCR, Whisper, CLIP, LLM tagging) implement this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class MetadataPlugin(ABC):
    """Base interface for all metadata extractors and future AI enrichment plugins."""

    @abstractmethod
    def supports(self, file_type: str) -> bool:
        """Return True if this plugin handles the given file extension/mime type.

        Args:
            file_type: Lowercase file extension (e.g. 'jpg', 'mp4') or mime type.
        """

    @abstractmethod
    def process(self, file_path: Path) -> dict[str, Any]:
        """Extract metadata from file.

        Args:
            file_path: Path to the file (local or mounted).

        Returns:
            Dict of extracted metadata. Keys vary by plugin.
            Must not raise on failure — return {'error': str(exc)} instead.
        """
