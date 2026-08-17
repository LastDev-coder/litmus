"""Markers embedded in the visible byte stream but not in the rendered output.

Only structurally unambiguous markers are reported. This inspector deliberately
does **not** do stylometry or "does this read like an LLM" scoring: that is
``HEURISTIC_STYLE`` evidence, it is unreliable per document, and emitting it
would invite exactly the authorship conclusions the brief forbids.
"""

from __future__ import annotations

import re

from ..artifact import Artifact
from ..model import ArtifactKind, EvidenceClass, Finding, Location, Severity
from .base import InspectorOutcome, line_col

MAX_LOCATIONS = 25
MAX_EXCERPT = 160

_HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
_MARKUP_KINDS = {".md", ".html", ".htm", ".xml", ".svg", ".markdown", ".txt"}


class TextMarkerInspector:
    name = "text_markers"

    def applies_to(self, artifact: Artifact) -> bool:
        if not artifact.is_textual:
            return False
        # HTML comments in .ts/.js/.py are not markup comments; skip source
        # code to avoid reporting ordinary code as an embedded marker.
        return artifact.ref.kind is not ArtifactKind.SOURCE_CODE

    def inspect(self, artifact: Artifact) -> InspectorOutcome:
        text = artifact.text
        if text is None:
            return InspectorOutcome.skipped("artifact is not decodable text")

        matches = list(_HTML_COMMENT.finditer(text))
        if not matches:
            return InspectorOutcome(findings=[])

        locations = []
        for match in matches[:MAX_LOCATIONS]:
            line, col = line_col(text, match.start())
            body = " ".join(match.group(1).split())
            locations.append(
                Location(
                    offset=match.start(),
                    line=line,
                    column=col,
                    length=match.end() - match.start(),
                    excerpt=body[:MAX_EXCERPT],
                )
            )

        return InspectorOutcome(
            findings=[
                Finding(
                    detector=self.name,
                    category="markup_comment",
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=Severity.INFO,
                    summary=(
                        f"{len(matches)} HTML/XML comment(s) present "
                        "(not rendered, but present in the source)"
                    ),
                    count=len(matches),
                    locations=locations,
                    # Comments can be load-bearing (licences, directives, build
                    # pragmas). Removing them is not automatically safe.
                    removable_by=[],
                )
            ]
        )
