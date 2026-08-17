"""Shared helpers for Office Open XML documents (DOCX / XLSX / PPTX).

An OOXML file is a ZIP archive of XML parts. Author, company, revision count,
timestamps and custom properties live in the ``docProps/`` parts; the visible
document content lives elsewhere (``word/``, ``xl/``, ``ppt/`` …). That split is
what makes metadata removal *provable*: we touch only ``docProps/`` and can show
every other archive member is byte-for-byte unchanged.

Standard library only (``zipfile`` + ``xml.etree``); deterministic; offline.
"""

from __future__ import annotations

import io
import zipfile

# docProps parts that carry metadata. Order matters only for readability.
CORE_PART = "docProps/core.xml"
APP_PART = "docProps/app.xml"
CUSTOM_PART = "docProps/custom.xml"
METADATA_PARTS = frozenset({CORE_PART, APP_PART, CUSTOM_PART})

# Central-directory members that prove the file is genuinely OOXML.
_CONTENT_TYPES = "[Content_Types].xml"
_OOXML_ROOTS = ("word/", "xl/", "ppt/")

# Human labels for the personal fields we surface, keyed by local XML tag name.
CORE_FIELDS = {
    "creator": "author",
    "lastModifiedBy": "last modified by",
    "title": "title",
    "subject": "subject",
    "keywords": "keywords",
    "description": "description",
    "category": "category",
    "revision": "revision number",
    "created": "created timestamp",
    "modified": "modified timestamp",
    "lastPrinted": "last printed",
    "contentStatus": "content status",
}
APP_FIELDS = {
    "Company": "company",
    "Manager": "manager",
    "Application": "application",
    "AppVersion": "application version",
    "Template": "template",
    "TotalTime": "total edit time",
    "LastModifiedBy": "last modified by",
}


def is_ooxml(data: bytes) -> bool:
    """True when ``data`` is a ZIP that looks like a DOCX/XLSX/PPTX."""
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
    if _CONTENT_TYPES not in names:
        return False
    return any(n.startswith(_OOXML_ROOTS) for n in names)


def ooxml_kind(data: bytes) -> str:
    """Best-effort document type label from the archive layout."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return "ooxml"
    if any(n.startswith("word/") for n in names):
        return "docx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    return "ooxml"


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_properties(data: bytes) -> dict[str, dict[str, str]]:
    """Return non-empty metadata values grouped by part.

    ``{"core": {...}, "app": {...}, "custom": {...}}``. Missing parts and
    malformed XML degrade to empty dicts rather than raising.
    """
    import xml.etree.ElementTree as ET

    result: dict[str, dict[str, str]] = {"core": {}, "app": {}, "custom": {}}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return result

    with zf:
        for part, bucket, allowed in (
            (CORE_PART, "core", CORE_FIELDS),
            (APP_PART, "app", APP_FIELDS),
        ):
            try:
                root = ET.fromstring(zf.read(part))
            except (KeyError, ET.ParseError):
                continue
            for child in root:
                name = _localname(child.tag)
                if name in allowed and child.text and child.text.strip():
                    result[bucket][name] = child.text.strip()
        try:
            custom_root = ET.fromstring(zf.read(CUSTOM_PART))
        except (KeyError, ET.ParseError):
            custom_root = None
        if custom_root is not None:
            for prop in custom_root:
                prop_name = prop.get("name")
                value = "".join(prop.itertext()).strip()
                if prop_name and value:
                    result["custom"][prop_name] = value
    return result


def _clean_fields(xml_bytes: bytes, fields: frozenset[str] | dict[str, str]) -> bytes:
    """Remove every child whose local tag is in ``fields``, preserving the rest."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_bytes)
    for child in list(root):
        if _localname(child.tag) in fields:
            root.remove(child)
    result = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    return result if isinstance(result, bytes) else result.encode("utf-8")


def strip_office_metadata(data: bytes) -> tuple[bytes, list[str]]:
    """Return (new_bytes, removed_parts).

    Rewrites the archive dropping ``docProps/custom.xml`` entirely and clearing
    the metadata fields in ``core.xml`` / ``app.xml``. Every other member is
    copied verbatim (same name, order, compression and timestamp), so the
    document content is provably untouched — see ``validate/office.py``.
    """
    src = zipfile.ZipFile(io.BytesIO(data))
    removed: list[str] = []
    out = io.BytesIO()
    with src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            payload = src.read(info.filename)
            if info.filename == CUSTOM_PART:
                removed.append(CUSTOM_PART)
                continue  # drop the whole custom-properties part
            if info.filename == CORE_PART:
                new = _clean_fields(payload, CORE_FIELDS)
                if new != payload:
                    removed.append(CORE_PART)
                payload = new
            elif info.filename == APP_PART:
                new = _clean_fields(payload, APP_FIELDS)
                if new != payload:
                    removed.append(APP_PART)
                payload = new
            # Preserve the member's own compression and timestamp for stability.
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            new_info.internal_attr = info.internal_attr
            new_info.create_system = info.create_system
            dst.writestr(new_info, payload)
    return out.getvalue(), removed


def content_members(data: bytes) -> dict[str, bytes] | None:
    """Decompressed bytes of every member that is *not* metadata.

    Returns ``None`` if the archive cannot be read. Used by the validator to
    prove the document content is identical before and after stripping. The
    ``[Content_Types].xml`` part still lists custom.xml after removal is
    harmless, but to keep the proof exact it is compared as content too only
    when present in both, so it is excluded here.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return None
    members: dict[str, bytes] = {}
    with zf:
        for name in zf.namelist():
            if name in METADATA_PARTS or name == _CONTENT_TYPES:
                continue
            try:
                members[name] = zf.read(name)
            except (KeyError, OSError):
                return None
    return members
