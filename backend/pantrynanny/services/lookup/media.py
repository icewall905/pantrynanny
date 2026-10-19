"""Image handling: validate, re-encode to WebP (EXIF stripped) and store under PN_UPLOAD_DIR."""

import asyncio
import io
import os
import re
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ...logging import get_logger
from . import runtime

log = get_logger()

MAX_DIMENSION = 1600
MAX_PIXELS = 40_000_000  # decompression-bomb guard
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO", "HEIF", "HEIC"}
FILE_RE = re.compile(r"^[0-9a-f]{32}\.webp$")
# Only images served by the Open*Facts projects may be fetched by the server.
IMAGE_URL_RE = re.compile(
    r"^https://(images|static)\.open(food|beauty|petfood|products)facts\.(org|net)/", re.I
)

try:  # optional HEIC support
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - optional dependency
    log.debug("pillow_heif_not_installed")

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class InvalidImage(ValueError):
    pass


def reencode_webp(data: bytes) -> bytes:
    """Decode (verifying the bytes really are an image) and re-encode as metadata-free WebP."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise InvalidImage(f"unsupported image format: {fmt}")
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)  # apply orientation, then drop all metadata
            has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
            img = img.convert("RGBA" if has_alpha else "RGB")
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            img.info = {}  # no exif/icc/xmp is carried into the encoded file
            out = io.BytesIO()
            img.save(out, "WEBP", quality=82, method=4, exif=b"", icc_profile=None)
            return out.getvalue()
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvalidImage("not a valid image") from exc


def _write(upload_dir: str, payload: bytes) -> str:
    d = Path(upload_dir)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.webp"
    tmp = d / f".{name}.tmp"
    tmp.write_bytes(payload)
    os.replace(tmp, d / name)
    return name


async def store_image(data: bytes, upload_dir: str | None = None) -> str:
    """Validate + re-encode + store. Returns the generated file name."""
    upload_dir = upload_dir or runtime.get_settings().upload_dir
    payload = await asyncio.to_thread(reencode_webp, data)
    return await asyncio.to_thread(_write, upload_dir, payload)


def delete_image(name: str | None, upload_dir: str | None = None) -> None:
    if not name or not FILE_RE.match(name):
        return
    upload_dir = upload_dir or runtime.get_settings().upload_dir
    try:
        (Path(upload_dir) / name).unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        log.warning("image_delete_failed", file=name)


def resolve_media_path(name: str, upload_dir: str) -> Path | None:
    """Safe lookup of a stored file; only our generated names are ever served."""
    if not FILE_RE.match(name):
        return None
    p = Path(upload_dir) / name
    return p if p.is_file() else None


async def download_image(url: str | None, timeout_s: float = 10.0) -> str | None:
    """Fetch an Open*Facts image (size/content-type limited) and store it. None on any failure."""
    if not url or not IMAGE_URL_RE.match(url):
        return None
    limit = runtime.get_settings().image_download_max_bytes
    try:
        async with runtime.get_client().stream("GET", url, timeout=timeout_s) as resp:
            if resp.status_code != 200:
                return None
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                return None
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                return None
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > limit:
                    return None
        return await store_image(bytes(buf))
    except (httpx.HTTPError, InvalidImage) as exc:
        log.info("image_download_failed", url=url, error=str(exc)[:200])
        return None
