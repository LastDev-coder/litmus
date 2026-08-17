"""Inspector registry."""

from __future__ import annotations

from .base import Inspector, InspectorOutcome
from .c2pa import C2paInspector
from .file_metadata import FileMetadataInspector
from .office_metadata import OfficeMetadataInspector
from .text_markers import TextMarkerInspector
from .unicode_scan import UnicodeInspector


def default_inspectors() -> list[Inspector]:
    return [
        UnicodeInspector(),
        TextMarkerInspector(),
        FileMetadataInspector(),
        OfficeMetadataInspector(),
        C2paInspector(),
    ]


__all__ = [
    "C2paInspector",
    "FileMetadataInspector",
    "Inspector",
    "InspectorOutcome",
    "OfficeMetadataInspector",
    "TextMarkerInspector",
    "UnicodeInspector",
    "default_inspectors",
]
