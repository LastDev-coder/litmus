"""Office Open XML metadata inspection (DOCX / XLSX / PPTX).

Surfaces the identifying properties these documents carry — author, company,
revision count, timestamps, custom properties — that ride along invisibly when
a file is shared. Everything here is ``EMBEDDED_METADATA``: unsigned and
trivially removable. Standard library only.
"""

from __future__ import annotations

from ..artifact import Artifact
from ..model import EvidenceClass, EvidenceLabel, Finding, Severity
from ..office import is_ooxml, ooxml_kind, read_properties
from .base import InspectorOutcome

# Fields whose presence is a privacy concern rather than mere housekeeping.
_PERSONAL = {"author", "last modified by", "company", "manager"}


class OfficeMetadataInspector:
    name = "office_metadata"

    def applies_to(self, artifact: Artifact) -> bool:
        return is_ooxml(artifact.data)

    def inspect(self, artifact: Artifact) -> InspectorOutcome:
        props = read_properties(artifact.data)
        kind = ooxml_kind(artifact.data)
        entries: dict[str, str] = {}
        for bucket in ("core", "app", "custom"):
            entries.update(props[bucket])
        if not entries:
            return InspectorOutcome(findings=[])

        has_personal = any(k in _PERSONAL for k in entries) or bool(props["custom"])
        finding = Finding(
            detector=self.name,
            category="office_metadata",
            evidence_class=EvidenceClass.EMBEDDED_METADATA,
            severity=Severity.WARNING if has_personal else Severity.NOTICE,
            summary=(
                f"{kind.upper()} document carries {len(entries)} metadata field(s)"
                + (" including author/company information" if has_personal else "")
            ),
            label=EvidenceLabel.CONFIRMED,
            details={
                "container": kind,
                "core": props["core"],
                "app": props["app"],
                "custom": props["custom"],
            },
            removable_by=["strip_office_metadata"],
        )
        return InspectorOutcome(findings=[finding])
