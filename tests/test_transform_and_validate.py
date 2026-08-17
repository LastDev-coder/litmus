from __future__ import annotations

from pathlib import Path

import pytest

from litmus.artifact import load_bytes
from litmus.pipeline import TransformOptions, analyze
from litmus.transform import PROFILES, TRANSFORMS, resolve_operations
from litmus.validate import validate_text


def _run(text: str, name: str = "sample.md", **kwargs: object) -> tuple[object, bytes]:
    artifact = load_bytes(text.encode("utf-8"), path=Path(name))
    return analyze(artifact, options=TransformOptions(**kwargs))  # type: ignore[arg-type]


def test_standard_profile_removes_every_invisible_class(dirty_text: str) -> None:
    report, data = _run(dirty_text)
    out = data.decode("utf-8")
    assert report.transformation.accepted is True  # type: ignore[union-attr]
    for ch in ("\ufeff", "\u200b", "\u200e", "\u00a0", "\U000e0048", "\r"):
        assert ch not in out
    assert "Hidden payload:" in out
    assert "A plain paragraph of text." in out


def test_transformation_is_deterministic(dirty_text: str) -> None:
    first = _run(dirty_text)[1]
    second = _run(dirty_text)[1]
    assert first == second


def test_transformation_is_idempotent(dirty_text: str) -> None:
    once = _run(dirty_text)[1]
    twice = _run(once.decode("utf-8"))[1]
    assert once == twice


def test_clean_text_is_unchanged(clean_text: str) -> None:
    report, data = _run(clean_text)
    assert data.decode("utf-8") == clean_text
    assert not [op for op in report.transformation.operations if op.applied]  # type: ignore[union-attr]


def test_minimal_profile_leaves_whitespace_alone() -> None:
    report, data = _run("a\u200bb   \r\n", profile="minimal")
    assert data.decode("utf-8") == "ab   \r\n"


def test_tidy_profile_collapses_blank_line_runs() -> None:
    _, data = _run("a\n\n\n\n\n\nb\n", profile="tidy")
    assert data.decode("utf-8") == "a\n\n\nb\n"


def test_unknown_operation_is_an_error() -> None:
    with pytest.raises(KeyError):
        resolve_operations(None, ["not_a_real_operation"])


def test_unknown_profile_is_an_error() -> None:
    with pytest.raises(KeyError):
        resolve_operations("nope", None)


def test_every_profile_references_real_operations() -> None:
    for ops in PROFILES.values():
        assert all(op in TRANSFORMS for op in ops)


def test_provably_safe_python_change_is_accepted_without_force() -> None:
    # The zero-width character lives inside a comment, so it is absent from the
    # AST. Removing it provably preserves the program: accepted, no --force.
    report, data = _run("x = 1  # note\u200bhere\n", name="a.py")
    assert report.transformation.accepted is True  # type: ignore[union-attr]
    assert data.decode("utf-8") == "x = 1  # notehere\n"
    validation = report.validation  # type: ignore[union-attr]
    assert validation.all_passed is True
    preserved = next(c for c in validation.checks if c.name == "code_semantics_preserved")
    assert preserved.passed is True


def test_python_change_inside_a_string_is_caught_and_refused() -> None:
    # The zero-width character is inside a string literal, so removing it changes
    # the program. The AST comparison catches it and refuses without --force.
    report, data = _run('x = "a\u200bb"\n', name="a.py")
    assert report.transformation.accepted is False  # type: ignore[union-attr]
    assert data.decode("utf-8") == 'x = "a\u200bb"\n'  # original bytes returned
    preserved = next(
        c
        for c in report.validation.checks
        if c.name == "code_semantics_preserved"  # type: ignore[union-attr]
    )
    assert preserved.passed is False


def test_forced_write_of_a_proven_change_records_the_truth() -> None:
    report, data = _run('x = "a\u200bb"\n', name="a.py", force_code=True)
    assert report.transformation.accepted is True  # type: ignore[union-attr]
    assert data.decode("utf-8") == 'x = "ab"\n'
    # Accepted because forced, but validation still reports the change honestly.
    assert report.validation.all_passed is False  # type: ignore[union-attr]


def test_unparseable_source_needs_force_and_stays_unproven() -> None:
    # A zero-width outside any string is a syntax error in Python, so the
    # original does not parse and equivalence is unprovable.
    report, data = _run("x = 1\u200b\n", name="a.py")
    assert report.transformation.accepted is False  # type: ignore[union-attr]
    report2, data2 = _run("x = 1\u200b\n", name="a.py", force_code=True)
    assert report2.transformation.accepted is True  # type: ignore[union-attr]
    assert report2.validation.all_passed is None  # type: ignore[union-attr]


def test_png_metadata_stripped_with_pixel_identity_proof() -> None:
    from conftest import build_png

    original = build_png(text={"Software": "X", "Comment": "hi"}, c2pa=True)
    artifact = load_bytes(original, path=Path("a.png"))
    report, data = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is True
    assert len(data) < len(original)  # metadata was removed
    proof = next(c for c in report.validation.checks if c.name == "pixel_data_identical")
    assert proof.passed is True
    # The stripped output no longer carries the text or C2PA chunks.
    assert b"Software" not in data and b"caBX" not in data


# --- validation ------------------------------------------------------------


def test_validation_accepts_invisible_only_changes() -> None:
    result = validate_text("hello\u200b world", "hello world")
    assert result.all_passed is True
    assert next(c for c in result.checks if c.name == "visible_content_preserved").passed is True


def test_validation_rejects_added_words() -> None:
    result = validate_text("hello world", "hello brave new world")
    assert result.all_passed is False
    assert next(c for c in result.checks if c.name == "no_unintended_additions").passed is False


def test_validation_rejects_structure_changes() -> None:
    result = validate_text("# A\n\ntext\n", "A\n\ntext\n")
    assert next(c for c in result.checks if c.name == "structure_preserved").passed is False


def test_semantic_similarity_is_reported_as_unmeasured() -> None:
    result = validate_text("hello", "hello")
    check = next(c for c in result.checks if c.name == "semantic_similarity")
    assert check.passed is None
    assert "Not measured" in check.detail


def test_failed_validation_returns_the_original_bytes() -> None:
    # A deliberately destructive operation list: dropping bidi controls from
    # text where they carry visible ordering is still visible-preserving, so
    # force a failure through the similarity threshold instead.
    report, data = _run("alpha beta gamma\n", min_lexical_similarity=1.1)
    assert report.transformation.accepted is False  # type: ignore[union-attr]
    assert data.decode("utf-8") == "alpha beta gamma\n"
