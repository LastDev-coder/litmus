"""Embedded file-metadata inspection, standard library only.

Parsers are intentionally defensive: a malformed container yields a finding
that says the container is malformed, never an exception and never a silent
empty result (brief §19).

Everything reported here is ``EMBEDDED_METADATA``: unsigned, trivially forged,
and trivially stripped. Signed provenance is handled in ``c2pa.py``.
"""

from __future__ import annotations

import struct

from ..artifact import Artifact
from ..model import EvidenceClass, EvidenceLabel, Finding, Severity
from .base import InspectorOutcome

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"
MAX_VALUE_CHARS = 200

# PNG chunk types that carry metadata rather than image data.
PNG_METADATA_CHUNKS = {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME", b"iCCP"}

JPEG_APP_NAMES = {
    0xE0: "APP0 (JFIF)",
    0xE1: "APP1 (Exif/XMP)",
    0xE2: "APP2 (ICC/FlashPix)",
    0xEB: "APP11 (JUMBF)",
    0xED: "APP13 (Photoshop IRB/IPTC)",
    0xEE: "APP14 (Adobe)",
    0xFE: "COM (comment)",
}


def _clean(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")[:MAX_VALUE_CHARS]


def iter_png_chunks(data: bytes) -> list[tuple[str, bytes]]:
    """Yield (chunk_type, chunk_data). Stops cleanly on truncation."""
    chunks: list[tuple[str, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if length > len(data) or end > len(data):
            break
        chunks.append((ctype.decode("ascii", errors="replace"), data[start:end]))
        if ctype == b"IEND":
            break
        offset = end + 4  # skip CRC
    return chunks


def iter_jpeg_segments(data: bytes) -> list[tuple[int, bytes]]:
    """Yield (marker_byte, payload) for JPEG APPn/COM segments before the scan."""
    segments: list[tuple[int, bytes]] = []
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            break
        marker = data[offset + 1]
        if marker == 0xDA:  # start of scan: metadata region is over
            break
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
        if length < 2:
            break
        start = offset + 4
        end = offset + 2 + length
        if end > len(data):
            break
        segments.append((marker, data[start:end]))
        offset = end
    return segments


class FileMetadataInspector:
    name = "file_metadata"

    def applies_to(self, artifact: Artifact) -> bool:
        data = artifact.data
        if data.startswith(PNG_SIGNATURE) or data.startswith(JPEG_SIGNATURE):
            return True
        return artifact.ref.media_type == "image/svg+xml"

    def inspect(self, artifact: Artifact) -> InspectorOutcome:
        data = artifact.data
        if data.startswith(PNG_SIGNATURE):
            return InspectorOutcome(findings=self._png(data))
        if data.startswith(JPEG_SIGNATURE):
            return InspectorOutcome(findings=self._jpeg(data))
        if artifact.text is not None:
            return InspectorOutcome(findings=self._svg(artifact.text))
        return InspectorOutcome.skipped("unsupported container for metadata inspection")

    def _finding(self, category: str, summary: str, details: dict[str, object]) -> Finding:
        return Finding(
            detector=self.name,
            category=category,
            evidence_class=EvidenceClass.EMBEDDED_METADATA,
            severity=Severity.INFO,
            summary=summary,
            label=EvidenceLabel.CONFIRMED,
            details=details,
            removable_by=[],  # binary rewriting is out of scope for this milestone
        )

    def _png(self, data: bytes) -> list[Finding]:
        chunks = iter_png_chunks(data)
        if not chunks:
            return [
                self._finding(
                    "malformed_container",
                    "PNG signature present but no readable chunks",
                    {"container": "png"},
                )
            ]
        findings: list[Finding] = []
        entries: dict[str, str] = {}
        present: list[str] = []
        for ctype, payload in chunks:
            if ctype.encode("ascii", "replace") not in PNG_METADATA_CHUNKS:
                continue
            present.append(ctype)
            if ctype == "tEXt" and b"\x00" in payload:
                key, _, value = payload.partition(b"\x00")
                entries[_clean(key)] = _clean(value)
            elif ctype == "iTXt" and b"\x00" in payload:
                key, _, rest = payload.partition(b"\x00")
                # compression flag, method, language tag, translated key, text
                parts = rest.split(b"\x00")
                entries[_clean(key)] = _clean(parts[-1]) if parts else ""
            elif ctype == "zTXt":
                key, _, _ = payload.partition(b"\x00")
                entries[_clean(key)] = "<compressed>"
        if present:
            findings.append(
                self._finding(
                    "png_metadata",
                    f"PNG carries {len(present)} metadata chunk(s)",
                    {"container": "png", "chunks": sorted(set(present)), "entries": entries},
                )
            )
        return findings

    def _jpeg(self, data: bytes) -> list[Finding]:
        segments = iter_jpeg_segments(data)
        if not segments:
            return []
        found: dict[str, int] = {}
        for marker, payload in segments:
            name = JPEG_APP_NAMES.get(marker, f"APP{marker - 0xE0}" if marker >= 0xE0 else "other")
            if payload.startswith(b"http://ns.adobe.com/xap/1.0/"):
                name = "APP1 (XMP)"
            elif payload.startswith(b"Exif\x00\x00"):
                name = "APP1 (Exif)"
            found[name] = found.get(name, 0) + 1
        return [
            self._finding(
                "jpeg_metadata",
                f"JPEG carries {sum(found.values())} metadata segment(s)",
                {"container": "jpeg", "segments": found},
            )
        ]

    def _svg(self, text: str) -> list[Finding]:
        markers = {
            "metadata_element": "<metadata" in text,
            "xmp": "x:xmpmeta" in text or "adobe:ns:meta" in text,
            "dublin_core": "dc:" in text or "purl.org/dc/" in text,
            "rdf": "rdf:RDF" in text,
        }
        present = [k for k, v in markers.items() if v]
        if not present:
            return []
        return [
            self._finding(
                "svg_metadata",
                f"SVG carries metadata blocks: {', '.join(present)}",
                {"container": "svg", "blocks": present},
            )
        ]
