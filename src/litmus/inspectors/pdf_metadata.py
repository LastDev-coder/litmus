"""PDF metadata inspection.

Surfaces the identifying values a PDF carries invisibly: the document
information dictionary (author, producer, creation tool, timestamps) and XMP
packets. Everything reported here is ``EMBEDDED_METADATA``: unsigned and
trivially forged or stripped. Standard library only.

Scope is stated honestly: the scan reads uncompressed bytes, so an Info
dictionary hidden inside a compressed object stream is not found, and an
encrypted PDF cannot be inspected at all. Absence of findings is not
evidence of absence.
"""

from __future__ import annotations

from ..artifact import Artifact
from ..model import EvidenceClass, EvidenceLabel, Finding, Severity
from ..pdf import is_encrypted, is_pdf, read_info_fields, read_xmp_summary
from .base import InspectorOutcome

# Fields whose presence is a privacy concern rather than mere housekeeping.
_PERSONAL = {"Author", "Title", "Subject", "Keywords"}


class PdfMetadataInspector:
    name = "pdf_metadata"

    def applies_to(self, artifact: Artifact) -> bool:
        return is_pdf(artifact.data)

    def inspect(self, artifact: Artifact) -> InspectorOutcome:
        data = artifact.data
        if is_encrypted(data):
            return InspectorOutcome.skipped(
                "encrypted PDF: strings are encrypted and cannot be inspected"
            )

        findings: list[Finding] = []
        fields = read_info_fields(data)
        if fields:
            has_personal = any(k in _PERSONAL for k in fields)
            findings.append(
                Finding(
                    detector=self.name,
                    category="pdf_info_dictionary",
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=Severity.WARNING if has_personal else Severity.NOTICE,
                    summary=(
                        f"PDF information dictionary carries {len(fields)} field(s)"
                        + (" including author/title information" if has_personal else "")
                    ),
                    label=EvidenceLabel.CONFIRMED,
                    details=dict(fields),
                    removable_by=["strip_pdf_metadata"],
                )
            )

        xmp = read_xmp_summary(data)
        packets = xmp.get("packets", 0)
        if isinstance(packets, int) and packets > 0:
            tool = xmp.get("creator_tool")
            findings.append(
                Finding(
                    detector=self.name,
                    category="pdf_xmp_metadata",
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=Severity.NOTICE,
                    summary=f"PDF carries {packets} XMP metadata packet(s)"
                    + (f" (creator tool: {tool})" if tool else ""),
                    label=EvidenceLabel.CONFIRMED,
                    details=dict(xmp),
                    removable_by=["strip_pdf_metadata"],
                )
            )

        return InspectorOutcome(findings=findings)
