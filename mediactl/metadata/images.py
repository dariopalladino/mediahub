"""Image metadata extractor using Pillow and EXIF data."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from mediactl.metadata.base import MetadataPlugin

log = structlog.get_logger()

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "tiff", "bmp", "gif"}


class ImageMetadataPlugin(MetadataPlugin):
    """Extract image dimensions, EXIF, GPS, camera model, timestamps."""

    def supports(self, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in IMAGE_EXTS

    def process(self, file_path: Path) -> dict[str, Any]:
        result: dict[str, Any] = {}
        try:
            from PIL import Image
            from PIL.ExifTags import GPSTAGS, TAGS

            with Image.open(file_path) as img:
                result["width"] = img.width
                result["height"] = img.height
                result["format"] = img.format
                result["mode"] = img.mode

                exif_data = img._getexif()  # type: ignore[attr-defined]
                if exif_data:
                    exif = {TAGS.get(k, k): v for k, v in exif_data.items()}

                    result["camera_make"] = str(exif.get("Make", ""))
                    result["camera_model"] = str(exif.get("Model", ""))
                    result["datetime_original"] = str(exif.get("DateTimeOriginal", ""))
                    result["datetime_digitized"] = str(exif.get("DateTimeDigitized", ""))
                    result["exposure_time"] = str(exif.get("ExposureTime", ""))
                    result["f_number"] = str(exif.get("FNumber", ""))
                    result["iso"] = str(exif.get("ISOSpeedRatings", ""))
                    result["focal_length"] = str(exif.get("FocalLength", ""))

                    # GPS extraction
                    gps_info = exif.get("GPSInfo")
                    if gps_info and isinstance(gps_info, dict):
                        gps = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
                        result["gps"] = _decode_gps(gps)

        except ImportError:
            result["error"] = "Pillow not installed"
        except Exception as exc:
            log.warning("metadata.image.error", path=str(file_path), error=str(exc))
            result["error"] = str(exc)

        return result


def _decode_gps(gps: dict) -> dict[str, float]:
    """Decode GPS EXIF data to decimal degrees."""
    out: dict[str, float] = {}
    try:
        lat = gps.get("GPSLatitude")
        lat_ref = gps.get("GPSLatitudeRef", "N")
        lon = gps.get("GPSLongitude")
        lon_ref = gps.get("GPSLongitudeRef", "E")

        if lat and lon:
            out["latitude"] = _dms_to_dd(lat, lat_ref)
            out["longitude"] = _dms_to_dd(lon, lon_ref)
    except Exception:
        pass
    return out


def _dms_to_dd(dms: tuple, ref: str) -> float:
    """Convert degrees/minutes/seconds to decimal degrees."""
    d, m, s = (float(x.numerator) / float(x.denominator) if hasattr(x, "numerator") else float(x) for x in dms)
    dd = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        dd = -dd
    return round(dd, 7)
