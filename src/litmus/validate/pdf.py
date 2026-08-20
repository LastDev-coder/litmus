"""Validation for PDF metadata blanking.

The transform promises same-length, in-place blanking, which allows a proof
stronger than any structural heuristic: the output must be exactly the same
size, and **every byte outside the metadata spans detected in the original
must be identical**. A PDF whose non-metadata bytes are untouched renders
identically — no cross-reference offset, stream length or content byte moved.
"""

from __future__ import annotations

from ..model import Check, ValidationReport
from ..pdf import PDF_SIGNATURE, metadata_spans


def validate_pdf_strip(before: bytes, after: bytes) -> ValidationReport:
    checks: list[Check] = []

    same_size = len(before) == len(after)
    checks.append(
        Check(
            name="pdf_size_unchanged",
            passed=same_size,
            detail="Output is exactly the same size, so no byte offset moved."
            if same_size
            else "Output size differs; an in-place blanking can never change the size.",
            measurements={"before_bytes": len(before), "after_bytes": len(after)},
        )
    )

    intact = after.startswith(PDF_SIGNATURE) and b"%%EOF" in after
    checks.append(
        Check(
            name="pdf_header_and_eof_intact",
            passed=intact,
            detail="The %PDF header and %%EOF marker are present."
            if intact
            else "The %PDF header or %%EOF marker is missing; the file is corrupted.",
        )
    )

    if not same_size:
        confined: bool | None = None
        detail = "Cannot compare byte regions because the sizes differ."
        measurements: dict[str, object] = {}
    else:
        allowed = metadata_spans(before)
        confined = True
        first_stray = -1
        pos = 0
        for start, end in allowed:
            if before[pos:start] != after[pos:start]:
                confined = False
                first_stray = next(i for i in range(pos, start) if before[i] != after[i])
                break
            pos = end
        if confined and before[pos:] != after[pos:]:
            confined = False
            first_stray = next(i for i in range(pos, len(before)) if before[i] != after[i])
        detail = (
            "Every byte outside the detected metadata regions is identical; the "
            "page content, fonts, images and file structure are untouched."
            if confined
            else f"A byte outside the metadata regions changed (offset {first_stray}); "
            "the strip altered more than metadata."
        )
        measurements = {"metadata_regions": len(allowed)}
    checks.append(
        Check(
            name="pdf_changes_confined_to_metadata",
            passed=confined,
            detail=detail,
            measurements=measurements,
        )
    )

    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True,
        all_passed=all(decided) if decided else None,
        checks=checks,
    )
