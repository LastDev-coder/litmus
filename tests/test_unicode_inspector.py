from __future__ import annotations

from litmus.artifact import load_bytes
from litmus.inspectors import UnicodeInspector
from litmus.model import EvidenceClass, Severity


def _categories(text: str, name: str = "sample.md") -> dict[str, object]:
    from pathlib import Path

    artifact = load_bytes(text.encode("utf-8"), path=Path(name))
    outcome = UnicodeInspector().inspect(artifact)
    return {f.category: f for f in outcome.findings}


def test_clean_text_has_no_findings(clean_text: str) -> None:
    assert _categories(clean_text) == {}


def test_detects_zero_width(dirty_text: str) -> None:
    found = _categories(dirty_text)
    assert "zero_width" in found
    assert found["zero_width"].severity is Severity.WARNING  # type: ignore[union-attr]
    assert found["zero_width"].evidence_class is EvidenceClass.EMBEDDED_METADATA  # type: ignore[union-attr]


def test_detects_bom_separately_from_zero_width(dirty_text: str) -> None:
    found = _categories(dirty_text)
    assert "byte_order_mark" in found
    # The leading BOM must not also be counted as a hidden zero-width character.
    assert found["zero_width"].count == 1  # type: ignore[union-attr]


def test_decodes_tag_character_payload(dirty_text: str) -> None:
    finding = _categories(dirty_text)["unicode_tag_char"]
    assert finding.details["decoded_ascii_payload"] == "HI"  # type: ignore[union-attr]


def test_detects_exotic_space_bidi_and_line_endings(dirty_text: str) -> None:
    found = _categories(dirty_text)
    assert "exotic_space" in found
    assert "bidi_control" in found
    assert "mixed_line_endings" in found


def test_bidi_is_a_warning_in_source_code() -> None:
    code = _categories('x = "a\u202eb"\n', name="a.py")
    plain = _categories("a\u202eb\n", name="a.md")
    assert code["bidi_control"].severity is Severity.WARNING  # type: ignore[union-attr]
    assert plain["bidi_control"].severity is Severity.NOTICE  # type: ignore[union-attr]


def test_mixed_script_word_detected() -> None:
    # Cyrillic '\u0430' inside an otherwise-Latin word.
    found = _categories("The p\u0430ssword is here\n")
    assert "mixed_script_word" in found


def test_cjk_text_is_not_flagged_as_mixed_script() -> None:
    assert "mixed_script_word" not in _categories("日本語のテキスト\n")


def test_locations_are_reported_with_line_and_column() -> None:
    finding = _categories("ok\nbad\u200bhere\n")["zero_width"]
    location = finding.locations[0]  # type: ignore[union-attr]
    assert location.line == 2
    assert location.column == 4


def test_identifier_plus_cjk_string_on_one_line_is_not_mixed_script() -> None:
    # A whitespace-delimited "word" in code routinely spans an identifier and a
    # string literal; only letter runs are examined, so this must stay clean.
    assert "mixed_script_word" not in _categories('label("日本語")\n', name="a.py")
