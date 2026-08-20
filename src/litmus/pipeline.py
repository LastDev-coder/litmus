"""Orchestration: inspect -> transform -> validate -> report."""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass

from .artifact import Artifact, sha256_hex
from .inspectors import Inspector, default_inspectors
from .model import (
    ArtifactKind,
    Check,
    Confidence,
    EvidenceClass,
    InspectionReport,
    InspectorStatus,
    OperationResult,
    ProvenanceSummary,
    Report,
    TransformationReport,
    ValidationReport,
)
from .office import is_ooxml, ooxml_kind, strip_office_metadata
from .pdf import is_encrypted, is_pdf, metadata_spans, strip_pdf_metadata
from .providers import undetectable_signals
from .transform import STRUCTURAL_CODE_OPS, Transform, resolve_operations
from .transform.file_strip import (
    JPEG_SOI,
    PNG_SIGNATURE,
    strip_jpeg_metadata,
    strip_png_metadata,
    strip_svg_metadata,
)
from .validate import DEFAULT_MIN_LEXICAL_SIMILARITY, validate_text
from .validate.binary import validate_image_strip
from .validate.code import validate_code
from .validate.office import validate_office_strip
from .validate.pdf import validate_pdf_strip
from .validate.structural import validate_python_import_removal

log = logging.getLogger("litmus")

CODE_UNPROVEN_REFUSAL = (
    "Refusing to write transformed source code whose behaviour could not be proven "
    "unchanged. No structural validator was available for this language in this "
    "environment (compile/test-based validation is planned). Re-run with --force to "
    "write it anyway; the report will record that semantic preservation was not proven."
)
CODE_CHANGED_REFUSAL = (
    "Refusing to write transformed source code that provably changed the program "
    "(the abstract syntax tree differs - a change landed inside a string or another "
    "semantic node). Re-run with --force to write it anyway."
)
CODE_BROKEN_REJECTION = (
    "Transformed source code no longer parses; refusing to write broken code. "
    "This is never overridable."
)


@dataclass(frozen=True)
class TransformOptions:
    profile: str | None = None
    operations: list[str] | None = None
    min_lexical_similarity: float = DEFAULT_MIN_LEXICAL_SIMILARITY
    force_code: bool = False


def inspect(artifact: Artifact, inspectors: list[Inspector] | None = None) -> InspectionReport:
    chosen = inspectors if inspectors is not None else default_inspectors()
    report = InspectionReport()

    for inspector in chosen:
        if not inspector.applies_to(artifact):
            report.inspectors.append(
                InspectorStatus(
                    name=inspector.name,
                    ran=False,
                    reason=f"not applicable to a {artifact.ref.kind.value} artifact",
                )
            )
            continue
        try:
            outcome = inspector.inspect(artifact)
        except Exception as exc:  # noqa: BLE001 - one broken inspector must not lose the rest
            log.exception("inspector %s failed", inspector.name)
            report.inspectors.append(
                InspectorStatus(
                    name=inspector.name, ran=False, reason=f"{type(exc).__name__}: {exc}"
                )
            )
            continue
        report.inspectors.append(
            InspectorStatus(name=inspector.name, ran=outcome.ran, reason=outcome.reason)
        )
        report.findings.extend(outcome.findings)

    report.provenance = _summarize(artifact, report)
    return report


def _summarize(artifact: Artifact, report: InspectionReport) -> ProvenanceSummary:
    detected = sorted({f"{f.detector}:{f.category}" for f in report.findings})

    unknown = [
        f"{row.provider}:{row.signal} ({row.detectability.value})"
        for row in undetectable_signals(artifact.ref.kind)
    ]

    signed = [f for f in report.findings if f.evidence_class is EvidenceClass.SIGNED_PROVENANCE]
    verified_provenance = [f for f in signed if f.details.get("verification") == "performed"]
    unverified_provenance = [f for f in signed if f.details.get("verification") != "performed"]

    notes: list[str] = []
    if verified_provenance:
        confidence = Confidence.SIGNAL_PRESENT
        notes.append(
            "A C2PA manifest was found and its signature was verified. This attests to "
            "the signer's claim of involvement; it does not establish authorship."
        )
    elif unverified_provenance:
        confidence = Confidence.INSUFFICIENT_EVIDENCE
        notes.append(
            "A C2PA manifest structure was found but its signature was NOT verified. "
            "Presence alone proves nothing: install the 'c2pa' extra to verify."
        )
    else:
        confidence = Confidence.INSUFFICIENT_EVIDENCE

    if unknown:
        notes.append(
            "One or more provenance signals that may be present cannot be checked by "
            "this tool because no public detector exists. Absence of findings is NOT "
            "evidence of absence, and no finding here speaks to authorship."
        )
    if any(f.evidence_class is EvidenceClass.EMBEDDED_METADATA for f in report.findings):
        notes.append(
            "Embedded-metadata findings (invisible characters, file metadata) are "
            "unsigned and trivially forged or stripped. They are not a provider "
            "watermark and do not indicate AI generation."
        )

    return ProvenanceSummary(
        known_signals_detected=detected,
        unknown_signals=unknown,
        confidence=confidence,
        notes=notes,
    )


def transform(
    artifact: Artifact, options: TransformOptions
) -> tuple[TransformationReport, ValidationReport, bytes]:
    """Route to the right transform and validator. Returns (report, validation, bytes).

    The returned bytes are the **original** bytes unless the transformation was
    accepted, so an unaccepted transformation can never be written by accident.
    """
    media = artifact.ref.media_type
    # PDFs are routed by signature before any text handling: a pure-ASCII PDF
    # decodes as text, and text normalization would corrupt its byte offsets.
    if is_pdf(artifact.data):
        return _transform_pdf(artifact)
    if artifact.ref.kind is ArtifactKind.BINARY:
        if is_ooxml(artifact.data):
            return _transform_office(artifact)
        return _transform_image(artifact)
    if media == "image/svg+xml" and artifact.text is not None:
        return _transform_svg(artifact)
    if artifact.text is None:
        tr = TransformationReport()
        tr.rejected_reason = "artifact is not decodable text and is not a supported image"
        return tr, ValidationReport(), artifact.data
    return _transform_text(artifact, options)


def _finish(
    tr: TransformationReport, vr: ValidationReport, output: bytes, original: bytes
) -> tuple[TransformationReport, ValidationReport, bytes]:
    if not tr.accepted:
        return tr, vr, original
    tr.output_sha256 = sha256_hex(output)
    tr.output_size_bytes = len(output)
    return tr, vr, output


def _transform_image(
    artifact: Artifact,
) -> tuple[TransformationReport, ValidationReport, bytes]:
    tr = TransformationReport()
    data = artifact.data
    if data.startswith(PNG_SIGNATURE):
        new_data, removed, _ = strip_png_metadata(data)
        container = "png"
    elif data.startswith(JPEG_SOI):
        new_data, removed, _ = strip_jpeg_metadata(data)
        container = "jpeg"
    else:
        tr.rejected_reason = (
            "unsupported binary type; only PNG and JPEG metadata stripping is implemented"
        )
        return tr, ValidationReport(), data

    tr.performed = True
    tr.operations.append(
        OperationResult(
            operation="strip_image_metadata",
            description=f"Remove metadata chunks/segments from the {container} container",
            semantics_preserving=True,
            applied=new_data != data,
            changes=len(data) - len(new_data),
            details={"removed": removed, "container": container},
        )
    )
    vr = validate_image_strip(data, new_data)
    tr.accepted = vr.all_passed is True
    if not tr.accepted:
        tr.rejected_reason = "image validation failed: " + "; ".join(
            c.name for c in vr.checks if c.passed is False
        )
    return _finish(tr, vr, new_data, data)


def _transform_office(
    artifact: Artifact,
) -> tuple[TransformationReport, ValidationReport, bytes]:
    tr = TransformationReport()
    data = artifact.data
    new_data, removed = strip_office_metadata(data)
    kind = ooxml_kind(data)
    tr.performed = True
    tr.operations.append(
        OperationResult(
            operation="strip_office_metadata",
            description=f"Remove author/company/custom metadata from the {kind} document",
            semantics_preserving=True,
            applied=new_data != data,
            changes=len(data) - len(new_data),
            details={"removed_parts": removed, "container": kind},
        )
    )
    vr = validate_office_strip(data, new_data)
    tr.accepted = vr.all_passed is True
    if not tr.accepted:
        tr.rejected_reason = "office validation failed: " + "; ".join(
            c.name for c in vr.checks if c.passed is False
        )
    return _finish(tr, vr, new_data, data)


def _transform_pdf(
    artifact: Artifact,
) -> tuple[TransformationReport, ValidationReport, bytes]:
    tr = TransformationReport()
    data = artifact.data
    if is_encrypted(data):
        tr.rejected_reason = (
            "encrypted PDF: its strings cannot be safely rewritten, so nothing was changed"
        )
        return tr, ValidationReport(), data

    new_data, removed = strip_pdf_metadata(data)
    # Only bytes inside metadata spans can differ; counting there keeps this
    # O(metadata) instead of O(file).
    changed_bytes = sum(
        sum(1 for a, b in zip(data[s:e], new_data[s:e], strict=True) if a != b)
        for s, e in metadata_spans(data)
    )
    tr.performed = True
    tr.operations.append(
        OperationResult(
            operation="strip_pdf_metadata",
            description=(
                "Blank the information-dictionary values and XMP packets in place, "
                "preserving every byte offset"
            ),
            semantics_preserving=True,
            applied=new_data != data,
            changes=changed_bytes,
            details={
                "removed": removed,
                "note": (
                    "values are blanked in place rather than deleted, so the file "
                    "size and structure are exactly preserved"
                ),
            },
        )
    )
    vr = validate_pdf_strip(data, new_data)
    tr.accepted = vr.all_passed is True
    if not tr.accepted:
        tr.rejected_reason = "pdf validation failed: " + "; ".join(
            c.name for c in vr.checks if c.passed is False
        )
    return _finish(tr, vr, new_data, data)


def _transform_svg(
    artifact: Artifact,
) -> tuple[TransformationReport, ValidationReport, bytes]:
    tr = TransformationReport()
    assert artifact.text is not None
    before = artifact.text
    after, removed = strip_svg_metadata(before)
    tr.performed = True
    tr.operations.append(
        OperationResult(
            operation="strip_svg_metadata",
            description="Remove <metadata>, XMP and xpacket blocks from SVG",
            semantics_preserving=True,
            applied=after != before,
            changes=len(before) - len(after),
            details={"blocks_removed": removed},
        )
    )
    vr = _validate_svg(before, after)
    tr.accepted = vr.all_passed is True
    if not tr.accepted:
        tr.rejected_reason = "svg validation failed: " + "; ".join(
            c.name for c in vr.checks if c.passed is False
        )
    return _finish(tr, vr, after.encode("utf-8"), artifact.data)


def _validate_svg(before: str, after: str) -> ValidationReport:
    import xml.etree.ElementTree as ET

    checks: list[Check] = []
    try:
        ET.fromstring(after)
        parses = True
        detail = "Output still parses as XML."
    except ET.ParseError as exc:
        parses = False
        detail = f"Output no longer parses as XML: {exc}"
    checks.append(Check(name="svg_parses_after", passed=parses, detail=detail))

    # Drawing element counts must be untouched; only metadata was targeted.
    def draw_count(text: str) -> int:
        return sum(text.count(f"<{tag}") for tag in ("path", "rect", "circle", "g", "polygon"))

    same = draw_count(before) == draw_count(after)
    checks.append(
        Check(
            name="drawing_elements_preserved",
            passed=same,
            detail="Drawing-element counts are unchanged."
            if same
            else "Drawing-element counts changed; the strip removed more than metadata.",
        )
    )
    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True, all_passed=all(decided) if decided else None, checks=checks
    )


def _apply_structural(
    t: Transform, text: str, artifact: Artifact, tr: TransformationReport, checks: list[Check]
) -> str:
    """Apply one structural operation behind its dedicated proof.

    The change is kept only when the proof passes in full; otherwise it is
    discarded and the operation is recorded as not applied. ``--force`` never
    reaches here by design: an unproven structural edit is simply not made.
    """
    details: dict[str, object] = {"note": t.note} if t.note else {}
    applied = False
    result = text
    if artifact.ref.language != "python":
        details["skipped"] = "structural operations are implemented for Python only"
    else:
        candidate = t.apply(text)
        if candidate != text:
            proof = validate_python_import_removal(text, candidate)
            if proof.all_passed is True:
                checks.extend(proof.checks)
                result = candidate
                applied = True
            else:
                details["discarded"] = (
                    "the change could not be proven safe and was not applied "
                    "(not overridable with --force); failing: "
                    + "; ".join(c.name for c in proof.checks if c.passed is not True)
                )
    tr.operations.append(
        OperationResult(
            operation=t.id,
            description=t.description,
            semantics_preserving=t.semantics_preserving,
            applied=applied,
            changes=_change_count(text, result) if applied else 0,
            details=details,
        )
    )
    return result


def _transform_text(
    artifact: Artifact, options: TransformOptions
) -> tuple[TransformationReport, ValidationReport, bytes]:
    tr = TransformationReport()
    assert artifact.text is not None
    transforms: list[Transform] = resolve_operations(options.profile, options.operations)
    structural = [t for t in transforms if t.id in STRUCTURAL_CODE_OPS]
    normalizing = [t for t in transforms if t.id not in STRUCTURAL_CODE_OPS]

    # Structural operations run first, each gated by its own proof. `mid` is
    # the proven-safe structural result; the character-level proofs below then
    # compare against `mid`, not the original, because token/AST equality with
    # the original is impossible once a structural edit has (provenly) landed.
    structural_checks: list[Check] = []
    mid = artifact.text
    for t in structural:
        mid = _apply_structural(t, mid, artifact, tr, structural_checks)

    current = mid
    for t in normalizing:
        result = t.apply(current)
        tr.operations.append(
            OperationResult(
                operation=t.id,
                description=t.description,
                semantics_preserving=t.semantics_preserving,
                applied=result != current,
                changes=0 if result == current else _change_count(current, result),
                details={"note": t.note} if t.note else {},
            )
        )
        current = result

    tr.performed = True
    vr = validate_text(mid, current, min_lexical_similarity=options.min_lexical_similarity)
    is_code = artifact.ref.kind is ArtifactKind.SOURCE_CODE

    if is_code:
        code_vr = validate_code(mid, current, artifact.ref.language)
        # Structural proof leads, then the code verdict, then text checks.
        vr.checks = structural_checks + code_vr.checks + vr.checks
        tr.accepted, tr.rejected_reason, vr.all_passed = _decide_code(
            code_vr, text_ok=vr.all_passed is not False, force=options.force_code
        )
    else:
        vr.checks = structural_checks + vr.checks
        tr.accepted = vr.all_passed is not False
        if not tr.accepted:
            tr.rejected_reason = "validation failed: " + "; ".join(
                c.name for c in vr.checks if c.passed is False
            )

    return _finish(tr, vr, current.encode("utf-8"), artifact.data)


def _check(vr: ValidationReport, name: str) -> bool | None:
    for c in vr.checks:
        if c.name == name:
            return c.passed
    return None


def _decide_code(
    code_vr: ValidationReport, *, text_ok: bool, force: bool
) -> tuple[bool, str | None, bool | None]:
    """Return (accepted, rejected_reason, all_passed) for a code transform.

    Acceptance is driven by whether behaviour was *proven* unchanged, never by
    treating "unproven" as "safe". ``all_passed`` reports validation truth
    independent of ``force``.
    """
    parses = _check(code_vr, "code_parses_after")
    preserved = _check(code_vr, "code_semantics_preserved")

    if parses is False:
        return False, CODE_BROKEN_REJECTION, False
    if preserved is True and text_ok:
        return True, None, True
    if preserved is False:
        return (True, None, False) if force else (False, CODE_CHANGED_REFUSAL, False)
    # preserved is None (unproven), or text validation flagged something.
    if force:
        return True, None, None
    return False, CODE_UNPROVEN_REFUSAL, None


#: Above this size, exact diffing is not worth the quadratic worst case.
_DIFF_LIMIT_CHARS = 200_000


def _change_count(before: str, after: str) -> int:
    """Characters affected by an operation, as a transformation-magnitude measure.

    Falls back to the length delta on very large inputs so that a big file
    cannot make the tool appear to hang.
    """
    if max(len(before), len(after)) > _DIFF_LIMIT_CHARS:
        return abs(len(before) - len(after))
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"
    )


def analyze(
    artifact: Artifact,
    *,
    options: TransformOptions | None = None,
    inspectors: list[Inspector] | None = None,
) -> tuple[Report, bytes]:
    """Full pipeline. Returns the report and the bytes that should be written."""
    inspection = inspect(artifact, inspectors)
    report = Report(artifact=artifact.ref, inspection=inspection)
    output = artifact.data
    if options is not None:
        tr, vr, output = transform(artifact, options)
        report.transformation = tr
        report.validation = vr
    return report, output
