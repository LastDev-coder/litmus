"""Safety invariant: cleaning never rewrites what a reader can see.

This is the property that makes litmus trustworthy and keeps it honest — it
strips *hidden* content, it does not "humanize" or paraphrase. These tests lock
it against future edits: if someone ever adds a transform (or reorders a
profile) that changes a visible word, the build fails here.

The check is done through the real validation gate (``validate_text``), not a
private reimplementation, so it also proves the gate itself still refuses any
visible-content change.
"""

from __future__ import annotations

from pathlib import Path

from litmus.artifact import load_bytes
from litmus.pipeline import TransformOptions, analyze
from litmus.transform import PROFILES, TRANSFORMS
from litmus.validate import validate_text

# Word-rich prose that also carries several invisible-character classes, so the
# strip/normalize transforms genuinely act on it rather than passing it through.
PROSE = (
    "\ufeffThe quick brown fox jumps over the lazy dog.\r\n"
    "Pack my\u00a0box with five dozen\u200b liquor jugs.   \n"
    "\n\n\n\n"
    "Sphinx of black quartz, judge my vow.\U000e0048\U000e0049\n"
)


def _check(before: str, after: str, name: str) -> bool | None:
    for c in validate_text(before, after).checks:
        if c.name == name:
            return c.passed
    raise AssertionError(f"check {name} not present")


def test_every_meaning_preserving_transform_keeps_visible_words() -> None:
    """No transform flagged ``semantics_preserving`` may alter the visible text."""
    preserving = [t for t in TRANSFORMS.values() if t.semantics_preserving]
    assert preserving, "expected at least one meaning-preserving transform"
    for t in preserving:
        after = t.apply(PROSE)
        assert _check(PROSE, after, "visible_content_preserved") is True, (
            f"transform '{t.id}' changed the visible skeleton"
        )
        assert _check(PROSE, after, "no_unintended_additions") is True, (
            f"transform '{t.id}' introduced a word"
        )


def test_every_profile_accepts_and_preserves_prose() -> None:
    """Each profile, run end-to-end, must accept and leave visible words intact."""
    for profile in PROFILES:
        artifact = load_bytes(PROSE.encode("utf-8"), path=Path("note.md"))
        report, output = analyze(artifact, options=TransformOptions(profile=profile))
        assert report.transformation is not None
        assert report.transformation.accepted is True, f"profile '{profile}' was rejected"
        assert _check(PROSE, output.decode("utf-8"), "visible_content_preserved") is True, (
            f"profile '{profile}' changed the visible skeleton"
        )


def test_no_transform_claims_meaning_change() -> None:
    """The only non-preserving transform is the code-structural one, and it is
    gated by a dedicated proof (covered in test_structural_imports). Guard the
    count so a new non-preserving transform can't slip in unnoticed."""
    non_preserving = [t.id for t in TRANSFORMS.values() if not t.semantics_preserving]
    assert non_preserving == ["remove_unused_imports"], (
        f"unexpected non-preserving transform(s): {non_preserving}; "
        "any transform that changes meaning needs its own proof and a review here"
    )
