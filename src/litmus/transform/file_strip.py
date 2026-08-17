"""Deterministic metadata removal for image containers, standard library only.

This is the capability that turns the tool from *inspect-only* into
*inspect-and-remove* for the formats it already understands, without depending
on ``exiftool`` or ``c2patool``.

The design decision that makes removal safe to claim: **only ancillary metadata
is dropped; the pixel-bearing bytes are copied verbatim.** For PNG that is the
``IDAT`` stream; for JPEG it is everything from the start-of-scan marker to the
end of the file. ``image_data_digest`` hashes exactly those bytes, so a caller
can *prove* the image did not change — see ``validate/binary.py``.

Colour-affecting chunks/segments (ICC profiles, gamma, palette, transparency)
are deliberately kept: dropping them would change how the image renders, which
would violate the quality-preservation contract.
"""

from __future__ import annotations

import hashlib
import re
import struct

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SOI = b"\xff\xd8"

# PNG ancillary chunks that carry metadata rather than image or colour data.
PNG_STRIP_CHUNKS = frozenset({b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME", b"caBX"})

# JPEG APPn/COM markers that carry metadata. APP0 (JFIF) is structural and
# APP2 (ICC) / APP14 (Adobe colour transform) affect rendering, so they stay.
JPEG_STRIP_MARKERS = frozenset({0xE1, 0xED, 0xEB, 0xEF, 0xFE})

_SVG_METADATA = re.compile(r"<metadata\b.*?</metadata\s*>", re.DOTALL | re.IGNORECASE)
_SVG_METADATA_EMPTY = re.compile(r"<metadata\b[^>]*/>", re.IGNORECASE)
_SVG_XMP = re.compile(r"<x:xmpmeta\b.*?</x:xmpmeta\s*>", re.DOTALL | re.IGNORECASE)
_SVG_XPACKET = re.compile(r"<\?xpacket\b.*?\?>", re.DOTALL | re.IGNORECASE)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- PNG --------------------------------------------------------------------


def _iter_png_raw(data: bytes) -> list[tuple[bytes, bytes]]:
    """Yield (chunk_type, full_chunk_bytes) including length prefix and CRC."""
    chunks: list[tuple[bytes, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        end = offset + 12 + length  # length(4)+type(4)+data(length)+crc(4)
        if end > len(data):
            break
        chunks.append((ctype, data[offset:end]))
        offset = end
        if ctype == b"IEND":
            break
    return chunks


def strip_png_metadata(data: bytes) -> tuple[bytes, list[str], str]:
    """Return (new_bytes, removed_chunk_types, image_data_digest)."""
    chunks = _iter_png_raw(data)
    kept: list[bytes] = [PNG_SIGNATURE]
    removed: list[str] = []
    idat = bytearray()
    for ctype, raw in chunks:
        if ctype == b"IDAT":
            idat += raw[8 : len(raw) - 4]  # payload only, excluding length/type/crc
        if ctype in PNG_STRIP_CHUNKS:
            removed.append(ctype.decode("ascii", "replace"))
            continue
        kept.append(raw)
    return b"".join(kept), removed, _sha256(bytes(idat))


def png_image_data_digest(data: bytes) -> str:
    idat = bytearray()
    for ctype, raw in _iter_png_raw(data):
        if ctype == b"IDAT":
            idat += raw[8 : len(raw) - 4]
    return _sha256(bytes(idat))


# --- JPEG -------------------------------------------------------------------


def strip_jpeg_metadata(data: bytes) -> tuple[bytes, list[str], str]:
    """Return (new_bytes, removed_marker_names, scan_data_digest).

    Segments before the start-of-scan are filtered; the scan (pixel data) is
    copied byte-for-byte and hashed for the identity proof.
    """
    out = bytearray(JPEG_SOI)
    removed: list[str] = []
    offset = 2
    n = len(data)
    while offset + 4 <= n:
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        if marker == 0xDA:  # start of scan: copy the remainder verbatim
            scan = data[offset:]
            out += scan
            return bytes(out), removed, _sha256(scan)
        (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
        end = offset + 2 + length
        if length < 2 or end > n:
            break
        if marker in JPEG_STRIP_MARKERS:
            removed.append(f"APP{marker - 0xE0}" if marker >= 0xE0 else "COM")
        else:
            out += data[offset:end]
        offset = end
    # No SOS found (unusual/truncated): return input unchanged, no proof.
    return data, [], ""


def jpeg_scan_digest(data: bytes) -> str:
    offset = 2
    n = len(data)
    while offset + 4 <= n:
        if data[offset] != 0xFF:
            return ""
        marker = data[offset + 1]
        if marker == 0xDA:
            return _sha256(data[offset:])
        (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
        end = offset + 2 + length
        if length < 2 or end > n:
            return ""
        offset = end
    return ""


# --- SVG --------------------------------------------------------------------


def strip_svg_metadata(text: str) -> tuple[str, int]:
    """Remove <metadata>, XMP and xpacket blocks. Return (new_text, removed_count)."""
    removed = 0
    for pattern in (_SVG_METADATA, _SVG_METADATA_EMPTY, _SVG_XMP, _SVG_XPACKET):
        text, count = pattern.subn("", text)
        removed += count
    return text, removed
