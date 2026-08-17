from __future__ import annotations

import struct
import zlib

import pytest

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunk(ctype: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def build_png(*, text: dict[str, str] | None = None, c2pa: bool = False) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")  # one red pixel scanline
    out = [PNG_SIGNATURE, png_chunk(b"IHDR", ihdr)]
    for key, value in (text or {}).items():
        out.append(png_chunk(b"tEXt", key.encode() + b"\x00" + value.encode()))
    if c2pa:
        out.append(png_chunk(b"caBX", b"\x00\x00\x00\x18jumb" + b"\x00" * 16))
    out.append(png_chunk(b"IDAT", idat))
    out.append(png_chunk(b"IEND", b""))
    return b"".join(out)


def build_jpeg(*, xmp: bool = False, jumbf: bool = False) -> bytes:
    out = [b"\xff\xd8"]

    def segment(marker: int, payload: bytes) -> bytes:
        return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload

    out.append(segment(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00"))
    if xmp:
        out.append(segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>"))
    if jumbf:
        out.append(segment(0xEB, b"\x00\x00\x00\x18jumb" + b"\x00" * 16))
    out.append(b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00")
    out.append(b"\xff\xd9")
    return b"".join(out)


@pytest.fixture
def clean_text() -> str:
    return "# Title\n\nA plain paragraph of text.\n\n- one\n- two\n"


@pytest.fixture
def dirty_text() -> str:
    """Text carrying every invisible-character class this tool reports."""
    return (
        "\ufeff# Title\r\n"
        "\r\n"
        "A plain\u200b paragraph\u00a0of text.\u200e\n"
        "Trailing spaces here.   \n"
        "\n\n\n\n"
        "Hidden payload:\U000e0048\U000e0049\n"
    )
