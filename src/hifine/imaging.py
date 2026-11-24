"""Image decoding and folder navigation shared by the viewer and thumbnailers."""

from __future__ import annotations

import io
import math
import os
import re
import struct
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, ImageCms, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener(depth_images=False, aux_images=False)

SUPPORTED_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".bmp", ".gif", ".webp",
    ".tif", ".tiff", ".ico", ".hif", ".heif", ".heic", ".avif",
})
_FORMATS = ("JPEG", "PNG", "BMP", "GIF", "WEBP", "TIFF", "ICO", "HEIF", "AVIF")
_SRGB = ImageCms.createProfile("sRGB")
_DECODE_ERRORS = (OSError, ValueError, SyntaxError, EOFError, RuntimeError,
                  OverflowError, struct.error, Image.DecompressionBombError)


class ImageLoadError(Exception):
    """An image could not be opened or decoded."""


@dataclass
class LoadedImage:
    image: Image.Image
    metadata: dict[str, str | int]


def _sort_key(path: Path) -> tuple:
    parts = re.split(r"([0-9]+)", path.name.casefold())
    return (tuple(int(part) if index % 2 else part for index, part in enumerate(parts)),
            path.name.casefold(), path.name)


def list_images(directory: str | Path) -> list[Path]:
    """List supported files without opening them, in deterministic natural order."""
    return sorted((item for item in Path(directory).iterdir()
                   if item.suffix.lower() in SUPPORTED_EXTENSIONS and item.is_file()),
                  key=_sort_key)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip(" \t\r\n\0")


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return number if number > 0 and math.isfinite(number) else None


def _photo_metadata(image: Image.Image) -> dict[str, str]:
    try:
        exif = image.getexif()
        tags = dict(exif)
        tags.update(exif.get_ifd(ExifTags.IFD.Exif))
    except (OSError, ValueError, TypeError, struct.error, SyntaxError, OverflowError):
        return {}

    # Some writers put camera fields in IFD0 and others in its Exif sub-IFD.
    fields: dict[str, str] = {}
    T = ExifTags.Base
    for key, tag in (("camera_make", T.Make), ("camera_model", T.Model),
                     ("lens", T.LensModel), ("artist", T.Artist)):
        if value := _text(tags.get(tag)):
            fields[key] = value
    shot = _text(tags.get(T.DateTimeOriginal) or tags.get(T.DateTimeDigitized) or tags.get(T.DateTime))
    if shot:
        fields["taken_at"] = re.sub(r"^(\d{4}):(\d\d):(\d\d)", r"\1-\2-\3", shot)
    if iso := _positive_number(tags.get(T.ISOSpeedRatings)):
        fields["iso"] = f"{iso:g}"
    if aperture := _positive_number(tags.get(T.FNumber)):
        fields["aperture"] = f"f/{aperture:g}"
    if focal := _positive_number(tags.get(T.FocalLength)):
        fields["focal_length"] = f"{focal:g} mm"
    if seconds := _positive_number(tags.get(T.ExposureTime)):
        denominator = round(1 / seconds)
        if seconds < 1 and denominator and math.isclose(seconds, 1 / denominator, rel_tol=0.005):
            fields["exposure"] = f"1/{denominator} s"
        else:
            fields["exposure"] = f"{seconds:g} s"
    return fields


def _display_pixels(image: Image.Image) -> Image.Image:
    """Return detached display pixels, preserving transparency through ICC conversion."""
    mode = "RGBA" if image.has_transparency_data else "RGB"
    profile = image.info.get("icc_profile")
    if image.mode.startswith("I;16"):
        # Pillow's plain conversion from integer grayscale clips values above 255.
        image = image.convert("I").point(lambda value: value / 257).convert("L")
    if profile:
        try:
            color = image if image.mode in {"RGB", "RGBA", "L", "CMYK", "LAB"} else image.convert(mode)
            result = ImageCms.profileToProfile(color, io.BytesIO(profile), _SRGB, outputMode="RGB")
            if mode == "RGBA":
                result.putalpha(image.convert("RGBA").getchannel("A"))
            return result
        except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
            # Broken and mismatched optional profiles should not hide valid pixels.
            pass
    return image.convert(mode)


@contextmanager
def _open_image(path):
    if os.name == "nt":
        from .windows_files import open_image_fd

        source = os.fdopen(open_image_fd(path), "rb")
    else:
        source = nullcontext(path)
    with source as file, Image.open(file, formats=_FORMATS) as image:
        yield image


def load_image(path: str | Path, *, max_pixel_bytes: int | None = None) -> LoadedImage:
    """Decode the primary HEIF image or the first frame of other image formats."""
    path = Path(path)
    try:
        with _open_image(path) as source:
            if max_pixel_bytes is not None:
                channels = 4 if source.has_transparency_data else 3
                if source.width * source.height * channels > max_pixel_bytes:
                    raise ImageLoadError(f"{path.name} 超出图片预读缓存容量。")
            # The HEIF plugin opens the declared primary item, which can follow a preview.
            # Its decoder already applies the container's orientation and clears EXIF orientation.
            image_format = source.format or path.suffix[1:].upper()
            metadata: dict[str, str | int] = {"format": image_format, "color_mode": source.mode}
            metadata.update(_photo_metadata(source))
            if image_format in {"GIF", "WEBP"} and getattr(source, "is_animated", False):
                metadata["animated"] = 1
                orientation = source.getexif().get(ExifTags.Base.Orientation)
                if orientation in range(2, 9):
                    metadata["animation_orientation"] = orientation
            if bit_depth := source.info.get("bit_depth"):
                metadata["bit_depth"] = int(bit_depth)
            ImageOps.exif_transpose(source, in_place=True)
            image = _display_pixels(source)
        metadata.update(width=image.width, height=image.height)
        stat = path.stat()
        metadata["file_size"] = stat.st_size
        metadata["modified"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return LoadedImage(image, metadata)
    except _DECODE_ERRORS as error:
        raise ImageLoadError(f"{path.name}: {error}") from error


def make_thumbnail(path: str | Path, max_size: int) -> Image.Image:
    """Decode an aspect-preserving thumbnail with no upscaling, in RGBA mode."""
    if max_size < 1:
        raise ValueError("max_size must be positive")
    path = Path(path)
    try:
        with _open_image(path) as source:
            # Ask JPEG and HEIF decoders for reduced pixels before loading the full image.
            source.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            ImageOps.exif_transpose(source, in_place=True)
            image = _display_pixels(source)
            return image if image.mode == "RGBA" else image.convert("RGBA")
    except _DECODE_ERRORS as error:
        raise ImageLoadError(f"{path.name}: {error}") from error
