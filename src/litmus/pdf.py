"""PDF metadata detection and same-length, in-place blanking.

A PDF is byte-offset-critical: its cross-reference table points at absolute
byte positions, so inserting or deleting a single byte can corrupt the file.
Rewriting a PDF safely would need a full parser (object streams, incremental
updates, filters). This module deliberately does something smaller and
provable instead: it **overwrites metadata values in place with same-length
padding**. The file size and every byte outside the identified metadata
regions stay identical, which is exactly what the validator then proves.

Two metadata carriers are handled, both findable without decompression:

* **Document information dictionary** — the object referenced by ``/Info`` in
  a trailer. Values of its identifying keys (Author, Creator, Producer,
  Title, Subject, Keywords, CreationDate, ModDate) are blanked. Keys are only
  ever touched *inside an Info object*; a ``/Title`` in an outline or a
  ``/Creator`` in a page-piece dictionary is never modified.
* **XMP packets** — the XMP specification requires packets to be stored
  uncompressed precisely so that byte scanners can find them. Each packet
  body is replaced with an empty ``x:xmpmeta`` element plus whitespace
  padding of exactly the original length.

What is honestly NOT covered: an Info dictionary stored inside a compressed
object stream cannot be found by this scan (rare in practice — most writers
keep Info uncompressed), and encrypted PDFs are refused outright because
their strings cannot be safely rewritten. Absence of findings is not
evidence of absence.
"""

from __future__ import annotations

import re

PDF_SIGNATURE = b"%PDF-"

#: Identifying keys of the document information dictionary (PDF 32000-1 §14.3.3).
INFO_KEYS = (
    b"Author",
    b"Creator",
    b"Producer",
    b"Title",
    b"Subject",
    b"Keywords",
    b"CreationDate",
    b"ModDate",
)

_INFO_REF = re.compile(rb"/Info\s+(\d+)\s+(\d+)\s+R")
_ENCRYPT_REF = re.compile(rb"/Encrypt\s+\d+\s+\d+\s+R")
_INFO_KEY = re.compile(rb"/(" + rb"|".join(INFO_KEYS) + rb")\s*")
_XPACKET_BEGIN = re.compile(rb"<\?xpacket\s+begin=[^>]{0,200}?\?>")
_XPACKET_END = re.compile(rb"<\?xpacket\s+end\s*=\s*[\"'][wr][\"']\s*\?>")
# The `stream` keyword is always followed by an end-of-line (PDF 32000-1 §7.3.8);
# the negative lookbehind keeps `endstream` from matching.
_STREAM_KW = re.compile(rb"(?<![A-Za-z])stream(?:\r\n|\r|\n)")

#: A minimal, valid, empty XMP payload used when blanking a packet body.
_EMPTY_XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'


def is_pdf(data: bytes) -> bool:
    return data.startswith(PDF_SIGNATURE)


def is_encrypted(data: bytes) -> bool:
    """True when any trailer references an encryption dictionary."""
    return _ENCRYPT_REF.search(data) is not None


def _literal_string_end(data: bytes, start: int) -> int | None:
    """Index just past the ``)`` closing the literal string opened at ``start``.

    Handles backslash escapes and unescaped balanced parentheses, both legal
    inside PDF literal strings.
    """
    depth = 0
    i = start
    while i < len(data):
        b = data[i]
        if b == 0x5C:  # backslash escapes the next byte
            i += 2
            continue
        if b == 0x28:  # (
            depth += 1
        elif b == 0x29:  # )
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _stream_regions(data: bytes) -> list[tuple[int, int]]:
    """Byte spans of the content between each ``stream``/``endstream`` pair.

    Used to reject look-alike PDF syntax planted inside a stream. A stream
    whose (usually compressed) bytes happen to contain these keywords only
    shifts the regions, which can at worst *exclude* a genuine match — the
    failure direction is "metadata not removed", never "content damaged".
    """
    regions: list[tuple[int, int]] = []
    pos = 0
    while True:
        kw = _STREAM_KW.search(data, pos)
        if kw is None:
            return regions
        end = data.find(b"endstream", kw.end())
        if end == -1:
            regions.append((kw.end(), len(data)))
            return regions
        regions.append((kw.end(), end))
        pos = end + len(b"endstream")


def _inside(regions: list[tuple[int, int]], offset: int) -> bool:
    return any(start <= offset < end for start, end in regions)


def _info_object_spans(data: bytes) -> list[tuple[int, int]]:
    """Byte spans of every object referenced as ``/Info`` by any trailer.

    A match found *inside* a stream is discarded: it is content that merely
    looks like an Info object (a genuine Info object is never stream data).
    The body must also start with ``<<``, as a real Info dictionary does.
    """
    streams = _stream_regions(data)
    spans: list[tuple[int, int]] = []
    for ref in _INFO_REF.finditer(data):
        num, gen = ref.group(1), ref.group(2)
        obj_re = re.compile(rb"(?<![0-9])" + num + rb"\s+" + gen + rb"\s+obj\b")
        for om in obj_re.finditer(data):
            if _inside(streams, om.start()):
                continue
            end = data.find(b"endobj", om.end())
            span = (om.end(), end if end != -1 else len(data))
            if data[span[0] : span[1]].lstrip()[:2] == b"<<":
                spans.append(span)
    return spans


def info_value_spans(data: bytes) -> list[tuple[int, int, str]]:
    """(start, end, key) spans of the string *contents* of Info values.

    Spans exclude the string delimiters, so blanking a span keeps the value a
    syntactically valid (whitespace-only) PDF string. Values that are not
    direct strings (e.g. indirect references) are left alone.
    """
    spans: list[tuple[int, int, str]] = []
    for obj_start, obj_end in _info_object_spans(data):
        for m in _INFO_KEY.finditer(data, obj_start, obj_end):
            key = m.group(1).decode("ascii")
            pos = m.end()
            if data[pos : pos + 1] == b"(":
                end = _literal_string_end(data, pos)
                if end is not None and end <= obj_end:
                    spans.append((pos + 1, end - 1, key))
            elif data[pos : pos + 1] == b"<" and data[pos : pos + 2] != b"<<":
                gt = data.find(b">", pos + 1)
                if gt != -1 and gt <= obj_end:
                    spans.append((pos + 1, gt, key))
    return spans


def xmp_packet_spans(data: bytes) -> list[tuple[int, int]]:
    """(start, end) spans of the bytes between each ``<?xpacket`` begin/end pair.

    A genuine packet lives entirely inside one metadata stream, so a candidate
    body containing ``endstream`` or ``endobj`` is a mispairing (e.g. a decoy
    ``<?xpacket begin`` planted in page content pairing with a real packet's
    end marker) and is discarded rather than blanked.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        begin = _XPACKET_BEGIN.search(data, pos)
        if begin is None:
            return spans
        end = _XPACKET_END.search(data, begin.end())
        if end is None:
            return spans
        body = data[begin.end() : end.start()]
        if b"endstream" not in body and b"endobj" not in body:
            spans.append((begin.end(), end.start()))
            pos = end.end()
        else:
            pos = begin.end()


def metadata_spans(data: bytes) -> list[tuple[int, int]]:
    """All byte spans this module may legitimately modify, merged and sorted.

    This single definition is shared by the stripper and the validator, so the
    proof of "changes confined to metadata" uses the same notion of metadata
    as the code that makes the changes.
    """
    raw = [(s, e) for s, e, _ in info_value_spans(data)]
    raw.extend(xmp_packet_spans(data))
    raw.sort()
    merged: list[tuple[int, int]] = []
    for start, end in raw:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def strip_pdf_metadata(data: bytes) -> tuple[bytes, list[str]]:
    """Blank metadata values in place. Returns (new_bytes, removed_descriptions).

    The output has exactly the same length as the input; only bytes inside
    detected metadata spans are replaced. Encrypted PDFs are returned
    unchanged — the caller decides how to report the refusal.
    """
    if is_encrypted(data):
        return data, []
    out = bytearray(data)
    removed: list[str] = []
    for start, end, key in info_value_spans(data):
        if data[start:end].strip():
            out[start:end] = b" " * (end - start)
            removed.append(f"info:{key}")
    for start, end in xmp_packet_spans(data):
        body = data[start:end]
        if body.strip() and body.strip() != _EMPTY_XMP:
            filler = _EMPTY_XMP if len(body) >= len(_EMPTY_XMP) else b""
            out[start:end] = filler + b" " * (end - start - len(filler))
            removed.append("xmp_packet")
    return bytes(out), removed


# --- read-only helpers for inspection ---------------------------------------

_XMP_CREATOR_TOOL = re.compile(
    rb"<xmp:CreatorTool>(.{0,500}?)</xmp:CreatorTool>|xmp:CreatorTool=\"([^\"]{0,500})\""
)


def _unescape_literal(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    escapes = {
        0x6E: b"\n", 0x72: b"\r", 0x74: b"\t", 0x62: b"\b", 0x66: b"\f",
        0x28: b"(", 0x29: b")", 0x5C: b"\\",
    }  # fmt: skip
    while i < len(raw):
        b = raw[i]
        if b == 0x5C and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in escapes:
                out += escapes[nxt]
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:  # octal escape, up to three digits
                j = i + 1
                while j < min(i + 4, len(raw)) and 0x30 <= raw[j] <= 0x37:
                    j += 1
                out.append(int(raw[i + 1 : j], 8) & 0xFF)
                i = j
                continue
            i += 1  # lone backslash: the next byte stands for itself
            continue
        out.append(b)
        i += 1
    return bytes(out)


def _decode_string(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    return raw.decode("latin-1", errors="replace")


def read_info_fields(data: bytes) -> dict[str, str]:
    """Best-effort decoded Info values, for reporting only."""
    fields: dict[str, str] = {}
    for start, end, key in info_value_spans(data):
        raw = data[start:end]
        if not raw.strip():
            continue
        if data[start - 1 : start] == b"<":  # hex string
            digits = bytes(b for b in raw if not chr(b).isspace())
            if len(digits) % 2:
                digits += b"0"
            try:
                raw = bytes.fromhex(digits.decode("ascii"))
            except ValueError:
                continue
        else:
            raw = _unescape_literal(raw)
        fields[key] = _decode_string(raw)
    return fields


def read_xmp_summary(data: bytes) -> dict[str, object]:
    """Packet count and a best-effort creator tool, for reporting only."""
    spans = xmp_packet_spans(data)
    live = [s for s in spans if data[s[0] : s[1]].strip() not in (b"", _EMPTY_XMP)]
    summary: dict[str, object] = {"packets": len(live)}
    for start, end in live:
        m = _XMP_CREATOR_TOOL.search(data, start, end)
        if m:
            raw = m.group(1) or m.group(2) or b""
            summary["creator_tool"] = raw.decode("utf-8", errors="replace")
            break
    return summary
