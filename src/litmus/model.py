"""Typed core models.

The enums here encode the rules from the project brief that must never be
violated by any subsystem:

* ``EvidenceClass`` keeps embedded metadata, signed provenance, statistical
  watermarking and style heuristics permanently distinct (brief §5).
* ``EvidenceLabel`` forces every provider-specific claim to carry its epistemic
  status (brief §20).
* ``Confidence`` has no numeric field, so a confidence value cannot be
  fabricated (brief §16).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

REPORT_SCHEMA_VERSION = "1.0"
TOOL_VERSION = "0.3.0"


class ArtifactKind(StrEnum):
    TEXT = "text"
    SOURCE_CODE = "source_code"
    BINARY = "binary"


class EvidenceClass(StrEnum):
    """What kind of signal a finding is. These are never interchangeable."""

    SIGNED_PROVENANCE = "signed_provenance"
    EMBEDDED_METADATA = "embedded_metadata"
    STATISTICAL_WATERMARK = "statistical_watermark"
    HEURISTIC_STYLE = "heuristic_style"


class EvidenceLabel(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNVERIFIED = "unverified"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    """Deliberately non-numeric."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SIGNAL_PRESENT = "signal_present"
    SIGNAL_ABSENT_IN_SCOPE = "signal_absent_in_scope"
    NOT_DETERMINABLE = "not_determinable"


class Severity(StrEnum):
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"


class Location(BaseModel):
    """Where in the artifact a finding sits. Offsets are 0-based, lines 1-based."""

    offset: int
    line: int | None = None
    column: int | None = None
    length: int = 1
    excerpt: str | None = None


class Finding(BaseModel):
    detector: str
    category: str
    evidence_class: EvidenceClass
    severity: Severity = Severity.INFO
    summary: str
    label: EvidenceLabel = EvidenceLabel.CONFIRMED
    count: int = 1
    locations: list[Location] = Field(default_factory=list)
    details: dict[str, object] = Field(default_factory=dict)
    removable_by: list[str] = Field(
        default_factory=list,
        description="Transform operation ids that would remove this finding, if any.",
    )


class ArtifactRef(BaseModel):
    path: str | None = None
    kind: ArtifactKind
    language: str | None = None
    media_type: str | None = None
    sha256: str
    size_bytes: int
    encoding: str | None = None
    decoded: bool = True


class InspectorStatus(BaseModel):
    """Per-inspector outcome, so a skipped inspector is never a silent gap."""

    name: str
    ran: bool
    reason: str | None = None


class ProvenanceSummary(BaseModel):
    known_signals_detected: list[str] = Field(default_factory=list)
    unknown_signals: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.INSUFFICIENT_EVIDENCE
    notes: list[str] = Field(default_factory=list)


class InspectionReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    inspectors: list[InspectorStatus] = Field(default_factory=list)
    provenance: ProvenanceSummary = Field(default_factory=ProvenanceSummary)


class OperationResult(BaseModel):
    operation: str
    description: str
    semantics_preserving: bool
    applied: bool
    changes: int = 0
    details: dict[str, object] = Field(default_factory=dict)


class TransformationReport(BaseModel):
    performed: bool = False
    accepted: bool = False
    rejected_reason: str | None = None
    operations: list[OperationResult] = Field(default_factory=list)
    output_sha256: str | None = None
    output_size_bytes: int | None = None


class Check(BaseModel):
    """A single validation check.

    ``passed is None`` means the check could not be run; it is reported, never
    silently dropped.
    """

    name: str
    passed: bool | None
    detail: str
    measurements: dict[str, object] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    performed: bool = False
    all_passed: bool | None = None
    checks: list[Check] = Field(default_factory=list)


class Report(BaseModel):
    schema_version: str = REPORT_SCHEMA_VERSION
    tool_version: str = TOOL_VERSION
    artifact: ArtifactRef
    inspection: InspectionReport = Field(default_factory=InspectionReport)
    transformation: TransformationReport = Field(default_factory=TransformationReport)
    validation: ValidationReport = Field(default_factory=ValidationReport)

    @property
    def has_findings(self) -> bool:
        return bool(self.inspection.findings)


class BatchReport(BaseModel):
    schema_version: str = REPORT_SCHEMA_VERSION
    tool_version: str = TOOL_VERSION
    reports: list[Report] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
