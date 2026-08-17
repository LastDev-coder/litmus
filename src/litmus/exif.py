"""Minimal EXIF reader for surfacing privacy-relevant fields (feature 2).

Purpose is narrow and honest: pull out the handful of tags people actually care
about when sharing a photo — GPS location, camera make/model, capture date, and
authoring software — so the inspector can name them plainly. It is not a full
EXIF library; unknown tags are ignored. Standard library only; no allocation
beyond the segment; bounded by the segment length.

The JPEG APP1 Exif payload is a TIFF stream: an 8-byte header giving byte order
and the offset of the first Image File Directory (IFD), then IFDs of 12-byte
entries. GPS data lives in a sub-IFD referenced by tag 0x8825.
"""

from __future__ import annotations

import struct

EXIF_PREFIX = b"Exif\x00\x00"

# TIFF field type -> byte size, for the types we read.
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}

# Tags we care about, in the primary IFD.
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_SOFTWARE = 0x0131
_TAG_DATETIME = 0x0132
_TAG_ARTIST = 0x013B
_TAG_GPS_IFD = 0x8825
_TAG_EXIF_IFD = 0x8769
_TAG_DATETIME_ORIG = 0x9003

_PRIMARY_LABELS = {
    _TAG_MAKE: "camera make",
    _TAG_MODEL: "camera model",
    _TAG_SOFTWARE: "software",
    _TAG_DATETIME: "date/time",
    _TAG_ARTIST: "artist",
}

# GPS sub-IFD tags.
_GPS_LAT_REF = 0x0001
_GPS_LAT = 0x0002
_GPS_LON_REF = 0x0003
_GPS_LON = 0x0004


def _read_header(buf: bytes) -> tuple[str, int] | None:
    if len(buf) < 8:
        return None
    if buf[:2] == b"II":
        endian = "<"
    elif buf[:2] == b"MM":
        endian = ">"
    else:
        return None
    (first_ifd,) = struct.unpack(endian + "I", buf[4:8])
    return endian, first_ifd


def _entries(buf: bytes, endian: str, offset: int) -> list[tuple[int, int, int, bytes]]:
    """Return (tag, type, count, value_or_offset_bytes) for one IFD."""
    if offset + 2 > len(buf):
        return []
    (count,) = struct.unpack(endian + "H", buf[offset : offset + 2])
    entries: list[tuple[int, int, int, bytes]] = []
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > len(buf):
            break
        tag, ftype, num = struct.unpack(endian + "HHI", buf[pos : pos + 8])
        entries.append((tag, ftype, num, buf[pos + 8 : pos + 12]))
        pos += 12
    return entries


def _value_bytes(buf: bytes, endian: str, ftype: int, count: int, raw: bytes) -> bytes:
    size = _TYPE_SIZE.get(ftype, 0) * count
    if size == 0:
        return b""
    if size <= 4:
        return raw[:size]
    (off,) = struct.unpack(endian + "I", raw)
    return buf[off : off + size] if off + size <= len(buf) else b""


def _ascii(buf: bytes, endian: str, ftype: int, count: int, raw: bytes) -> str:
    return (
        _value_bytes(buf, endian, ftype, count, raw).split(b"\x00", 1)[0].decode("ascii", "replace")
    )


def _rationals(buf: bytes, endian: str, count: int, raw: bytes) -> list[float]:
    data = _value_bytes(buf, endian, 5, count, raw)
    out: list[float] = []
    for i in range(0, len(data) - 7, 8):
        num, den = struct.unpack(endian + "II", data[i : i + 8])
        out.append(num / den if den else 0.0)
    return out


def _gps_coord(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    deg, minute, sec = values[0], values[1], values[2]
    return deg + minute / 60 + sec / 3600


def parse_exif_from_app1(payload: bytes) -> dict[str, object]:
    """Extract privacy-relevant fields from a JPEG APP1 Exif payload.

    Returns a flat dict (possibly empty). Never raises: a malformed stream
    yields whatever could be read.
    """
    if not payload.startswith(EXIF_PREFIX):
        return {}
    tiff = payload[len(EXIF_PREFIX) :]
    header = _read_header(tiff)
    if header is None:
        return {}
    endian, first = header
    result: dict[str, object] = {}
    gps_offset = 0
    for tag, ftype, count, raw in _entries(tiff, endian, first):
        if tag in _PRIMARY_LABELS and ftype == 2:
            text = _ascii(tiff, endian, ftype, count, raw)
            if text:
                result[_PRIMARY_LABELS[tag]] = text
        elif tag == _TAG_GPS_IFD and ftype == 4:
            (gps_offset,) = struct.unpack(endian + "I", raw)
        elif tag == _TAG_EXIF_IFD and ftype == 4:
            (exif_off,) = struct.unpack(endian + "I", raw)
            for etag, eftype, ecount, eraw in _entries(tiff, endian, exif_off):
                if etag == _TAG_DATETIME_ORIG and eftype == 2:
                    text = _ascii(tiff, endian, eftype, ecount, eraw)
                    if text:
                        result["date/time original"] = text

    if gps_offset:
        lat = lon = None
        lat_ref = lon_ref = ""
        for tag, ftype, count, raw in _entries(tiff, endian, gps_offset):
            if tag == _GPS_LAT and ftype == 5:
                lat = _gps_coord(_rationals(tiff, endian, count, raw))
            elif tag == _GPS_LON and ftype == 5:
                lon = _gps_coord(_rationals(tiff, endian, count, raw))
            elif tag == _GPS_LAT_REF and ftype == 2:
                lat_ref = _ascii(tiff, endian, ftype, count, raw)
            elif tag == _GPS_LON_REF and ftype == 2:
                lon_ref = _ascii(tiff, endian, ftype, count, raw)
        if lat is not None and lon is not None:
            if lat_ref.upper() == "S":
                lat = -lat
            if lon_ref.upper() == "W":
                lon = -lon
            result["gps_latitude"] = round(lat, 6)
            result["gps_longitude"] = round(lon, 6)
    return result
