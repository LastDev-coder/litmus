"""Validation for Office Open XML metadata stripping.

The proof mirrors the image pixel-identity proof: metadata was removed *and the
document content is provably unchanged*. We show it by comparing the
decompressed bytes of every non-metadata archive member before and after. If
any content part differs, the strip touched more than metadata and is rejected.
"""

from __future__ import annotations

from ..model import Check, ValidationReport
from ..office import content_members, is_ooxml


def validate_office_strip(before: bytes, after: bytes) -> ValidationReport:
    checks: list[Check] = []

    parses = is_ooxml(after)
    checks.append(
        Check(
            name="office_parses_after",
            passed=parses,
            detail="Output is still a valid Office Open XML document."
            if parses
            else "Output no longer reads as an Office document; the strip corrupted it.",
        )
    )

    before_members = content_members(before)
    after_members = content_members(after)
    if not parses or before_members is None or after_members is None:
        preserved: bool | None = None
        detail = "Cannot compare content because an archive could not be read."
        measurements: dict[str, object] = {}
    else:
        same_names = set(before_members) == set(after_members)
        same_bytes = same_names and all(
            before_members[name] == after_members[name] for name in before_members
        )
        preserved = same_bytes
        changed = sorted(
            name
            for name in set(before_members) & set(after_members)
            if before_members[name] != after_members[name]
        )
        detail = (
            "Every document part (text, sheets, slides, media) is byte-for-byte "
            "identical; only metadata was removed."
            if preserved
            else "A document part changed; the strip altered more than metadata."
        )
        measurements = {
            "content_parts": len(before_members),
            "changed_parts": changed[:10],
            "added_or_removed_parts": sorted(
                set(before_members).symmetric_difference(after_members)
            )[:10],
        }
    checks.append(
        Check(
            name="document_content_identical",
            passed=preserved,
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
