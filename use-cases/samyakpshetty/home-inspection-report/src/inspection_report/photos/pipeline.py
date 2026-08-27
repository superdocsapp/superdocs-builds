"""Taking a photograph from an inspector's phone into a report.

Five things happen to every photo, in this order, and the order matters:

1. **The cap is enforced where it can be.** This module sees bytes that are already in
   memory, so its own check is the last line rather than the first: the API refuses an
   oversized body with a 413 before reading it, and reads what is left in bounded chunks. A
   cap enforced only here would not be a cap — it would decide which error you get after
   paying the whole cost, which is exactly what this used to do.
2. **The image is decoded to prove it is an image.** The filename extension is a claim made
   by whoever uploaded the file, and this endpoint accepts uploads.
3. **EXIF is stripped.** This is the step that is specific to this domain and easy to miss:
   a phone photograph of a house carries the house's GPS coordinates. An inspection report
   is handed to buyers, agents and lenders, so shipping the client's home address inside
   the image metadata would be a real disclosure, silently.
4. **The content is hashed.** The sha256 of the cleaned bytes *is* the photo's identity, so
   the same photograph uploaded twice — a re-run, a retry, a crash halfway through — costs
   one upload, ever.
5. **The image is downscaled and a thumbnail derived.** A phone shoots far more pixels
   than a printed report or a browser card can use, and storing the original is a cost with
   no reader. HEIC — the iPhone default — is decoded and kept as JPEG, so the format is an
   input detail the rest of the build never sees.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from inspection_report.logging import get_logger

_log = get_logger("inspection_report.photos")

# HEIC has been the iPhone camera default since iOS 11, so the device this product is
# actually used on produces a format Pillow cannot read unaided. Registering the opener is
# the difference between "works with the photographs an inspector takes" and "works with the
# photographs an inspector remembers to convert". Optional at import: a deployment without
# the wheel keeps every other format rather than failing to start.
try:  # pragma: no cover - exercised by whether the import succeeds
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:
    # Any failure here means "no HEIC support", not a crash.
    HEIF_SUPPORTED = False

# What an upload may arrive as. Raised well above phone-photograph size because the answer
# to a big photograph is to resize it, not to refuse it: a 48-megapixel phone routinely
# produces more than the old 8 MB, and rejecting an inspector's own camera is not a cap, it
# is a defect. The outer wall is the API's request-size middleware.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# What a photograph is stored at. Beyond this the pixels are a cost with no reader: the
# image is printed a few inches wide in a report and drawn at a few hundred pixels in the
# interface. Downscaling here is also what keeps the database a sane size.
STORED_MAX_EDGE = 2048

# What Pillow reports -> what the API accepts. A format outside this map is refused rather
# than guessed at.
_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    # Decoded via pillow-heif and re-encoded to JPEG on the way out, so nothing downstream
    # has to know the format existed.
    "HEIF": "image/heic",
    "HEIC": "image/heic",
}

THUMBNAIL_MAX_EDGE = 480


class PhotoRejected(Exception):
    """The upload was refused. The message names the cause and what to do about it."""


@dataclass(frozen=True)
class CleanedPhoto:
    """A photograph that is safe to store and send."""

    data: bytes
    sha256: str
    content_type: str
    width: int
    height: int
    thumbnail: bytes
    stripped_exif: bool

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def clean(raw: bytes, *, filename: str) -> CleanedPhoto:
    """Validate, strip and fingerprint one uploaded photograph."""
    if not raw:
        raise PhotoRejected(f"{filename} is empty. Re-take or re-select the photograph.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PhotoRejected(
            f"{filename} is {len(raw) // 1024} KB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1024} KB. Reduce the camera resolution or crop the image."
        )

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()  # structural check; consumes the file object
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            fmt = (image.format or "").upper()
            content_type = _FORMAT_TO_MIME.get(fmt)
            if content_type is None:
                raise PhotoRejected(
                    f"{filename} decoded as {fmt or 'an unknown format'}. Accepted formats "
                    f"are {', '.join(sorted(_FORMAT_TO_MIME))}."
                )
            had_exif = bool(getattr(image, "_getexif", lambda: None)()) or "exif" in image.info
            cleaned, width, height = _strip_metadata(image, fmt)
            thumb = _thumbnail(image, fmt)
            # What we stored, not what arrived: a HEIC is a JPEG by the time it is kept.
            if fmt in ("HEIF", "HEIC"):
                content_type = "image/jpeg"
    except PhotoRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        # Deliberately does not echo the exception: a decoder message can carry file
        # content, and the cause the user can act on is simply that it is not an image.
        raise PhotoRejected(
            f"{filename} could not be read as an image. If it came from a scanner or a "
            f"messaging app, export it as PNG or JPEG and try again."
        ) from exc

    digest = hashlib.sha256(cleaned).hexdigest()
    _log.info(
        "photo_cleaned",
        extra={
            "sha256": digest[:12],
            "content_type": content_type,
            "bytes": len(cleaned),
            "stripped_exif": had_exif,
        },
    )
    return CleanedPhoto(
        data=cleaned,
        sha256=digest,
        content_type=content_type,
        width=width,
        height=height,
        thumbnail=thumb,
        stripped_exif=had_exif,
    )


def _strip_metadata(image: Image.Image, fmt: str) -> tuple[bytes, int, int]:
    """Re-encode through a bare canvas so no metadata survives.

    Copying pixel data into a fresh image is the reliable way to drop EXIF, ICC profiles and
    XMP together: Pillow's ``save`` will otherwise carry ``info`` through for several
    formats, and a per-key deletion list goes stale the moment a phone vendor invents a new
    one.
    """
    working = image.convert("RGBA") if fmt in ("PNG", "GIF", "WEBP") else image.convert("RGB")
    # Downscale before the copy, so a 48-megapixel original costs one resize and is stored
    # at a size someone will actually look at.
    if max(working.size) > STORED_MAX_EDGE:
        working.thumbnail((STORED_MAX_EDGE, STORED_MAX_EDGE), Image.Resampling.LANCZOS)
    bare = Image.new(working.mode, working.size)
    bare.paste(working)  # pixels only; `info` is not carried across a paste

    buf = io.BytesIO()
    if fmt in ("PNG", "GIF", "WEBP"):
        bare.save(buf, format="PNG", optimize=True)
    else:
        # JPEG and HEIC alike. A HEIC leaves here as a JPEG, which is what makes the format
        # an input detail rather than something the rest of the build carries.
        bare.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), working.width, working.height


def _thumbnail(image: Image.Image, fmt: str) -> bytes:
    thumb = image.convert("RGB")
    thumb.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=80, optimize=True)
    return buf.getvalue()


def thumbnail_mime() -> str:
    return "image/jpeg"
