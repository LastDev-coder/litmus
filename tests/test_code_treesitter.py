"""Multi-language code validation via the optional tree-sitter `code` extra.

Skipped entirely when the extra is not installed, so the base CI install stays
green. Each language proves the same two behaviours: a whitespace/comment-only
edit is accepted, and a change to a string literal is caught.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from litmus.artifact import load_bytes  # noqa: E402
from litmus.pipeline import TransformOptions, analyze  # noqa: E402
from litmus.validate.code import validate_code  # noqa: E402


def _preserved(before: str, after: str, language: str) -> bool | None:
    report = validate_code(before, after, language)
    return next(c for c in report.checks if c.name == "code_semantics_preserved").passed


# (language, safe-before, safe-after [whitespace only], unsafe-after [string changed])
CASES = [
    ("javascript", 'const s = "a";\n', 'const  s  =  "a";\n', 'const s = "b";\n'),
    ("typescript", 'const s: string = "a";\n', 'const s:string="a";\n', 'const s: string = "z";\n'),
    (
        "java",
        'class A { String s = "a"; }\n',
        'class A{String s="a";}\n',
        'class A { String s = "b"; }\n',
    ),
    ("kotlin", 'val s = "a"\n', 'val   s   =   "a"\n', 'val s = "b"\n'),
    ("swift", 'let s = "a"\n', 'let  s  =  "a"\n', 'let s = "b"\n'),
]


@pytest.mark.parametrize(("language", "before", "safe", "unsafe"), CASES)
def test_whitespace_change_is_proven_safe(
    language: str, before: str, safe: str, unsafe: str
) -> None:
    assert _preserved(before, safe, language) is True


@pytest.mark.parametrize(("language", "before", "safe", "unsafe"), CASES)
def test_string_literal_change_is_caught(
    language: str, before: str, safe: str, unsafe: str
) -> None:
    assert _preserved(before, unsafe, language) is False


def test_comment_edit_is_ignored() -> None:
    assert _preserved("val x = 1 // hello\n", "val x = 1 // goodbye\n", "kotlin") is True


def test_broken_output_is_flagged() -> None:
    report = validate_code("val x = 1\n", "val x = (\n", "kotlin")
    assert next(c for c in report.checks if c.name == "code_parses_after").passed is False


def test_javascript_upgrades_to_proven_with_treesitter() -> None:
    # With the extra installed, JS gets a real equivalence proof, not just
    # node --check syntax validation.
    report = validate_code('const s = "a";\n', 'const  s = "a";\n', "javascript")
    preserved = next(c for c in report.checks if c.name == "code_semantics_preserved")
    assert preserved.passed is True
    assert "tree-sitter" in str(preserved.measurements.get("method", ""))


def test_pipeline_accepts_provably_safe_kotlin_comment_edit() -> None:
    # Zero-width character inside a comment: removing it is provably safe.
    artifact = load_bytes('val s = "x" // no\u200bte\n'.encode(), path=Path("a.kt"))
    report, data = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is True
    assert report.validation.all_passed is True
    assert data.decode("utf-8") == 'val s = "x" // note\n'


def test_pipeline_refuses_kotlin_string_change() -> None:
    # Zero-width inside a Kotlin string literal: removing it changes the value.
    artifact = load_bytes('val s = "a\u200bb"\n'.encode(), path=Path("a.kt"))
    report, data = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is False
    assert data.decode("utf-8") == 'val s = "a\u200bb"\n'
