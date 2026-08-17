"""Inspector protocol and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..artifact import Artifact
from ..model import Finding


@dataclass
class InspectorOutcome:
    findings: list[Finding] = field(default_factory=list)
    ran: bool = True
    reason: str | None = None

    @classmethod
    def skipped(cls, reason: str) -> InspectorOutcome:
        return cls(findings=[], ran=False, reason=reason)


@runtime_checkable
class Inspector(Protocol):
    name: str

    def applies_to(self, artifact: Artifact) -> bool: ...

    def inspect(self, artifact: Artifact) -> InspectorOutcome: ...


def line_col(text: str, offset: int) -> tuple[int, int]:
    """1-based line, 1-based column for a character offset."""
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    return line, offset - last_nl
