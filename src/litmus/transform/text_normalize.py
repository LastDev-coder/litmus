"""Deterministic text normalization transforms.

These operations remove or normalize content that carries no visible meaning.
They are the honest core of the transformation engine: each one is small,
inspectable, reversible in intent, and validated afterwards.

What is deliberately absent: any "rewrite this so it reads as human" step. It
would be non-deterministic, unverifiable, and is ruled out by the brief (§8).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from ..inspectors.unicode_scan import (
    BIDI_CONTROLS,
    BOM,
    EXOTIC_SPACES,
    OTHER_INVISIBLE,
    ZERO_WIDTH,
    is_tag_char,
    is_variation_selector,
)
from .base import Transform
from .code_structural import REMOVE_UNUSED_IMPORTS

_ZERO_WIDTH_NO_BOM = frozenset(ZERO_WIDTH) - {BOM}
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_MANY_BLANK_LINES = re.compile(r"\n{4,}")


def _drop(text: str, predicate: Callable[[str], bool]) -> str:
    return "".join(ch for ch in text if not predicate(ch))


def _strip_zero_width(text: str) -> str:
    head, rest = (text[0], text[1:]) if text.startswith(BOM) else ("", text)
    return head + _drop(rest, lambda ch: ch in _ZERO_WIDTH_NO_BOM or ch == BOM)


def _strip_bidi(text: str) -> str:
    return _drop(text, lambda ch: ch in BIDI_CONTROLS)


def _strip_variation_selectors(text: str) -> str:
    return _drop(text, is_variation_selector)


def _strip_tag_characters(text: str) -> str:
    return _drop(text, is_tag_char)


def _strip_other_invisible(text: str) -> str:
    return _drop(text, lambda ch: ch in OTHER_INVISIBLE)


def _strip_control_characters(text: str) -> str:
    return _drop(
        text,
        lambda ch: unicodedata.category(ch) == "Cc" and ch not in "\n\r\t",
    )


def _normalize_spaces(text: str) -> str:
    return "".join(" " if ch in EXOTIC_SPACES else ch for ch in text)


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith(BOM) else text


def _normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_trailing_whitespace(text: str) -> str:
    return _TRAILING_WS.sub("", text)


def _collapse_blank_lines(text: str) -> str:
    return _MANY_BLANK_LINES.sub("\n\n\n", text)


def _ensure_final_newline(text: str) -> str:
    if not text or text.endswith("\n"):
        return text
    return text + "\n"


TRANSFORMS: dict[str, Transform] = {
    t.id: t
    for t in [
        Transform(
            "strip_zero_width",
            "Remove zero-width and word-joiner characters",
            True,
            _strip_zero_width,
        ),
        Transform(
            "strip_tag_characters",
            "Remove deprecated Unicode tag characters (U+E0000-U+E007F)",
            True,
            _strip_tag_characters,
            note="These carry hidden ASCII payloads; inspect before removing.",
        ),
        Transform(
            "strip_bidi_controls",
            "Remove bidirectional formatting controls",
            True,
            _strip_bidi,
            note="Removing these changes display order in genuinely right-to-left text.",
        ),
        Transform(
            "strip_variation_selectors",
            "Remove variation selectors",
            True,
            _strip_variation_selectors,
            note="Can change emoji presentation (text vs emoji style).",
        ),
        Transform(
            "strip_other_invisible",
            "Remove soft hyphens, combining grapheme joiners and blank Braille",
            True,
            _strip_other_invisible,
        ),
        Transform(
            "strip_control_characters",
            "Remove C0/C1 control characters other than tab, CR and LF",
            True,
            _strip_control_characters,
        ),
        Transform(
            "normalize_spaces",
            "Replace non-standard space characters with U+0020",
            True,
            _normalize_spaces,
            note="Changes line-breaking behaviour where NO-BREAK SPACE was intentional.",
        ),
        Transform("strip_bom", "Remove a leading UTF-8 byte order mark", True, _strip_bom),
        Transform(
            "normalize_nfc",
            "Normalize to Unicode NFC",
            True,
            _normalize_nfc,
            note="Canonical-equivalence only; NFKC (which is lossy) is not used.",
        ),
        Transform(
            "normalize_line_endings", "Convert CRLF and CR to LF", True, _normalize_line_endings
        ),
        Transform(
            "strip_trailing_whitespace",
            "Remove trailing spaces and tabs from each line",
            True,
            _strip_trailing_whitespace,
            note="In Markdown, two trailing spaces are a hard line break.",
        ),
        Transform(
            "collapse_blank_lines",
            "Collapse runs of more than two blank lines",
            True,
            _collapse_blank_lines,
        ),
        Transform(
            "ensure_final_newline",
            "Ensure the file ends with a newline",
            True,
            _ensure_final_newline,
        ),
        REMOVE_UNUSED_IMPORTS,
    ]
}

PROFILES: dict[str, list[str]] = {
    # Removes only content that has no visible rendering at all.
    "minimal": [
        "strip_zero_width",
        "strip_tag_characters",
        "strip_bidi_controls",
        "strip_variation_selectors",
        "strip_other_invisible",
        "strip_control_characters",
        "strip_bom",
    ],
    # Adds whitespace and Unicode normalization.
    "standard": [
        "strip_zero_width",
        "strip_tag_characters",
        "strip_bidi_controls",
        "strip_variation_selectors",
        "strip_other_invisible",
        "strip_control_characters",
        "strip_bom",
        "normalize_nfc",
        "normalize_spaces",
        "normalize_line_endings",
        "strip_trailing_whitespace",
        "ensure_final_newline",
    ],
    # Standard plus proof-gated structural code operations (Python only today).
    # On non-code files the structural step is skipped, so this degrades to
    # exactly the standard profile.
    "code": [
        "remove_unused_imports",
        "strip_zero_width",
        "strip_tag_characters",
        "strip_bidi_controls",
        "strip_variation_selectors",
        "strip_other_invisible",
        "strip_control_characters",
        "strip_bom",
        "normalize_nfc",
        "normalize_spaces",
        "normalize_line_endings",
        "strip_trailing_whitespace",
        "ensure_final_newline",
    ],
    # Adds structural tidying that changes the byte layout more visibly.
    "tidy": [
        "strip_zero_width",
        "strip_tag_characters",
        "strip_bidi_controls",
        "strip_variation_selectors",
        "strip_other_invisible",
        "strip_control_characters",
        "strip_bom",
        "normalize_nfc",
        "normalize_spaces",
        "normalize_line_endings",
        "strip_trailing_whitespace",
        "collapse_blank_lines",
        "ensure_final_newline",
    ],
}


def resolve_operations(profile: str | None, operations: list[str] | None) -> list[Transform]:
    """Resolve a profile name or an explicit operation list into transforms.

    Order is the profile's declared order, which is significant: invisible
    characters are removed before whitespace normalization so that a
    zero-width character between two spaces does not survive as a gap.
    """
    if operations:
        unknown = [op for op in operations if op not in TRANSFORMS]
        if unknown:
            raise KeyError(f"unknown operation(s): {', '.join(sorted(unknown))}")
        return [TRANSFORMS[op] for op in operations]
    name = profile or "standard"
    if name not in PROFILES:
        raise KeyError(f"unknown profile '{name}'; choose from {', '.join(sorted(PROFILES))}")
    return [TRANSFORMS[op] for op in PROFILES[name]]
