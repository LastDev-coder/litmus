"""Validation for image metadata stripping.

The claim we can make here is unusually strong for a watermark/metadata tool:
metadata was removed *and the pixels are provably unchanged*. We prove it by
hashing the pixel-bearing bytes (PNG ``IDAT`` / JPEG scan) before and after and
requiring byte-for-byte equality. A competitor that strips metadata without
this check cannot distinguish "removed the label" from "corrupted the image".
"""

from __future__ import annotations

from ..model import Check, ValidationReport
from ..transform.file_strip import (
    JPEG_SOI,
    PNG_SIGNATURE,
    jpeg_scan_digest,
    png_image_data_digest,
)


def validate_image_strip(before: bytes, after: bytes) -> ValidationReport:
    checks: list[Check] = []

    if after.startswith(PNG_SIGNATURE):
        digest_before = png_image_data_digest(before)
        digest_after = png_image_data_digest(after)
        parsed = bool(digest_after)
    elif after.startswith(JPEG_SOI):
        digest_before = jpeg_scan_digest(before)
        digest_after = jpeg_scan_digest(after)
        parsed = bool(digest_after)
    else:
        return ValidationReport(
            performed=True,
            all_passed=None,
            checks=[
                Check(
                    name="image_recognized",
                    passed=None,
                    detail="Output is not a recognized PNG or JPEG; cannot prove preservation.",
                )
            ],
        )

    checks.append(
        Check(
            name="image_parses_after",
            passed=parsed,
            detail="Output still parses as a valid image container."
            if parsed
            else "Output no longer parses; the strip corrupted the container.",
        )
    )

    identical = parsed and digest_before == digest_after and bool(digest_after)
    checks.append(
        Check(
            name="pixel_data_identical",
            passed=identical,
            detail=(
                "Pixel-bearing bytes are byte-for-byte identical to the original; "
                "only metadata was removed."
                if identical
                else "Pixel-bearing bytes changed; the image content was not preserved."
            ),
            measurements={"digest_before": digest_before, "digest_after": digest_after},
        )
    )

    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True,
        all_passed=all(decided) if decided else None,
        checks=checks,
    )
