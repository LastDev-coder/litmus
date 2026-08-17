"""Provider capability matrix.

Knowledge about what each provider marks, and whether anyone outside the
provider can verify it, is **data with citations**. Updating a claim is a data
edit plus a source URL, not a code change.

Every row carries an ``EvidenceLabel``. A row must never assert
``CONFIRMED`` without an official provider URL in ``source``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from ..model import ArtifactKind, EvidenceClass, EvidenceLabel


class Detectability(StrEnum):
    #: A public, usable detector exists today.
    PUBLIC_DETECTOR = "public_detector"
    #: The signal is structurally readable without a provider service.
    LOCALLY_READABLE = "locally_readable"
    #: The provider states the signal exists but publishes no detector.
    NO_PUBLIC_DETECTOR = "no_public_detector"
    #: A detector is announced but not yet available.
    ANNOUNCED_NOT_AVAILABLE = "announced_not_available"
    #: No evidence either way.
    UNKNOWN = "unknown"


class Capability(BaseModel):
    provider: str
    surface: str
    artifact_kind: ArtifactKind
    evidence_class: EvidenceClass
    signal: str
    marked: bool | None = Field(description="Does the provider mark this? None = unknown.")
    detectability: Detectability
    label: EvidenceLabel
    source: str | None = None
    notes: str = ""


ANTHROPIC_SURFACES = (
    "claude.ai",
    "api",
    "claude_code",
    "claude_cowork",
    "claude_tag",
    "aws_bedrock",
    "google_cloud",
    "microsoft_foundry",
)

_NEWS = "https://www.anthropic.com/news/claude-text-watermark"
_HELP = "https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content"
_OPENAI_PROVENANCE = "https://openai.com/index/advancing-content-provenance/"
_OPENAI_C2PA_HELP = "https://help.openai.com/en/articles/8912793-c2pa-in-chatgpt-images"

CAPABILITIES: list[Capability] = [
    *(
        Capability(
            provider="anthropic",
            surface=surface,
            artifact_kind=ArtifactKind.TEXT,
            evidence_class=EvidenceClass.STATISTICAL_WATERMARK,
            signal="claude_text_watermark",
            marked=True,
            detectability=Detectability.ANNOUNCED_NOT_AVAILABLE,
            label=EvidenceLabel.CONFIRMED,
            source=_HELP,
            notes=(
                "Applies to Claude models launched on or after 2026-08-02, worldwide. "
                "Applied at token-selection time during generation. No public detector "
                "or published algorithm as of 2026-08-16; a detection API is announced "
                "as forthcoming. This tool therefore cannot detect or measure it."
            ),
        )
        for surface in ANTHROPIC_SURFACES
    ),
    Capability(
        provider="anthropic",
        surface="all",
        artifact_kind=ArtifactKind.SOURCE_CODE,
        evidence_class=EvidenceClass.STATISTICAL_WATERMARK,
        signal="claude_text_watermark",
        marked=True,
        detectability=Detectability.ANNOUNCED_NOT_AVAILABLE,
        label=EvidenceLabel.CONFIRMED,
        source=_NEWS,
        notes=(
            "Anthropic states watermarking of code is sparse because code 'has to be "
            "exact', leaving fewer free token choices. No published threshold."
        ),
    ),
    Capability(
        provider="anthropic",
        surface="all",
        artifact_kind=ArtifactKind.BINARY,
        evidence_class=EvidenceClass.SIGNED_PROVENANCE,
        signal="c2pa_content_credential",
        marked=True,
        detectability=Detectability.LOCALLY_READABLE,
        label=EvidenceLabel.CONFIRMED,
        source=_HELP,
        notes=(
            "Attached to generated .svg, .png and .jpg files. Metadata only - nothing "
            "is embedded in the pixels. Contains no identifying user information. "
            "Readable by any C2PA-aware tool."
        ),
    ),
    Capability(
        provider="anthropic",
        surface="api",
        artifact_kind=ArtifactKind.TEXT,
        evidence_class=EvidenceClass.EMBEDDED_METADATA,
        signal="response_headers_or_fields",
        marked=None,
        detectability=Detectability.UNKNOWN,
        label=EvidenceLabel.UNKNOWN,
        source=None,
        notes=(
            "No documentation found describing provenance in HTTP headers, JSON "
            "fields or token metadata. Not probed; undocumented fields are not invented."
        ),
    ),
    Capability(
        provider="openai",
        surface="all",
        artifact_kind=ArtifactKind.TEXT,
        evidence_class=EvidenceClass.STATISTICAL_WATERMARK,
        signal="text_watermark",
        marked=None,
        detectability=Detectability.UNKNOWN,
        label=EvidenceLabel.UNVERIFIED,
        source=None,
        notes=(
            "Press reporting describes a built-but-unshipped prototype. OpenAI does "
            "not document a deployed text watermark; absence of documentation is weak "
            "evidence of absence."
        ),
    ),
    Capability(
        provider="openai",
        surface="all",
        artifact_kind=ArtifactKind.BINARY,
        evidence_class=EvidenceClass.SIGNED_PROVENANCE,
        signal="c2pa_content_credential",
        marked=True,
        detectability=Detectability.LOCALLY_READABLE,
        label=EvidenceLabel.CONFIRMED,
        source=_OPENAI_C2PA_HELP,
        notes="C2PA Content Credentials on DALL-E 3 and Sora output.",
    ),
    Capability(
        provider="openai",
        surface="all",
        artifact_kind=ArtifactKind.BINARY,
        evidence_class=EvidenceClass.STATISTICAL_WATERMARK,
        signal="synthid_image_watermark",
        marked=True,
        detectability=Detectability.NO_PUBLIC_DETECTOR,
        label=EvidenceLabel.CONFIRMED,
        source=_OPENAI_PROVENANCE,
        notes=(
            "Durable SynthID image watermarking added via partnership with Google. "
            "OpenAI operates a verification tool; no unrestricted third-party detector."
        ),
    ),
    Capability(
        provider="openai",
        surface="codex",
        artifact_kind=ArtifactKind.SOURCE_CODE,
        evidence_class=EvidenceClass.STATISTICAL_WATERMARK,
        signal="code_watermark",
        marked=None,
        detectability=Detectability.UNKNOWN,
        label=EvidenceLabel.UNKNOWN,
        source=None,
        notes="No evidence found either way.",
    ),
    Capability(
        provider="generic",
        surface="all",
        artifact_kind=ArtifactKind.TEXT,
        evidence_class=EvidenceClass.EMBEDDED_METADATA,
        signal="invisible_unicode",
        marked=None,
        detectability=Detectability.LOCALLY_READABLE,
        label=EvidenceLabel.CONFIRMED,
        source=None,
        notes=(
            "Invisible-character anomalies are detectable locally but are NOT a "
            "provider watermark and do not imply AI generation."
        ),
    ),
]


def capabilities(
    provider: str | None = None, artifact_kind: ArtifactKind | None = None
) -> list[Capability]:
    rows = CAPABILITIES
    if provider:
        rows = [r for r in rows if r.provider == provider.lower()]
    if artifact_kind:
        rows = [r for r in rows if r.artifact_kind is artifact_kind]
    return rows


def providers() -> list[str]:
    return sorted({row.provider for row in CAPABILITIES})


def undetectable_signals(artifact_kind: ArtifactKind) -> list[Capability]:
    """Signals that may be present for this artifact kind but cannot be checked.

    These become the ``unknown_signals`` list in the report, which is how the
    system stays honest about the difference between "not found" and
    "not checkable".
    """
    blocked = {
        Detectability.NO_PUBLIC_DETECTOR,
        Detectability.ANNOUNCED_NOT_AVAILABLE,
        Detectability.UNKNOWN,
    }
    seen: set[tuple[str, str]] = set()
    rows: list[Capability] = []
    for row in CAPABILITIES:
        if row.artifact_kind is not artifact_kind or row.detectability not in blocked:
            continue
        key = (row.provider, row.signal)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows
