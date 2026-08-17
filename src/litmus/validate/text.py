"""Local, deterministic validation of a text transformation.

Every check here runs offline with no model and no randomness, so a validation
result is reproducible from the artifact pair alone.

Naming is deliberate: the similarity metric is called **lexical** similarity,
not semantic similarity, because ``difflib`` measures token overlap and nothing
about meaning. True semantic similarity is reported as an explicitly
unperformed check rather than approximated by a proxy and mislabelled.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from ..model import Check, ValidationReport

DEFAULT_MIN_LEXICAL_SIMILARITY = 0.98

_WORD = re.compile(r"\S+")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)
_MD_FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
_MD_LIST = re.compile(r"^\s*([-*+]|\d+\.)\s", re.MULTILINE)


def _visible_skeleton(text: str) -> str:
    """Text reduced to its visible content: no format/control chars, whitespace collapsed.

    Two texts with the same skeleton render the same words in the same order.
    """
    kept = [
        ch
        for ch in unicodedata.normalize("NFC", text)
        if unicodedata.category(ch) not in {"Cf", "Cc"} or ch in "\n\t"
    ]
    return " ".join("".join(kept).split())


def _words(text: str) -> list[str]:
    return _WORD.findall(_visible_skeleton(text))


def _line_structure_view(text: str) -> str:
    """Line structure with format/control characters removed.

    Markdown structure must be counted on this view rather than on the raw
    text. Otherwise an invisible character sitting in front of a ``#`` hides
    the heading from the "before" count, and removing that character - which
    repairs the document - is misreported as a structural change.
    """
    kept = [ch for ch in text if unicodedata.category(ch) not in {"Cf", "Cc"} or ch in "\n\t"]
    return "".join(kept).replace("\r\n", "\n").replace("\r", "\n")


def validate_text(
    before: str,
    after: str,
    *,
    min_lexical_similarity: float = DEFAULT_MIN_LEXICAL_SIMILARITY,
) -> ValidationReport:
    checks: list[Check] = []

    skeleton_before = _visible_skeleton(before)
    skeleton_after = _visible_skeleton(after)
    checks.append(
        Check(
            name="visible_content_preserved",
            passed=skeleton_before == skeleton_after,
            detail=(
                "Visible content is byte-identical after removing format/control "
                "characters and collapsing whitespace."
                if skeleton_before == skeleton_after
                else "Visible content changed."
            ),
            measurements={
                "skeleton_chars_before": len(skeleton_before),
                "skeleton_chars_after": len(skeleton_after),
            },
        )
    )

    words_before, words_after = _words(before), _words(after)
    added = sorted(set(words_after) - set(words_before))
    removed = sorted(set(words_before) - set(words_after))
    checks.append(
        Check(
            name="no_unintended_additions",
            passed=not added,
            detail="No word appears in the output that was absent from the input."
            if not added
            else f"{len(added)} word form(s) introduced.",
            measurements={"added_examples": added[:10], "removed_examples": removed[:10]},
        )
    )

    ratio = difflib.SequenceMatcher(a=words_before, b=words_after, autojunk=False).ratio()
    checks.append(
        Check(
            name="lexical_similarity",
            passed=ratio >= min_lexical_similarity,
            detail=(
                f"Word-sequence similarity {ratio:.4f} "
                f"(threshold {min_lexical_similarity:.2f}). "
                "This measures token overlap, not meaning."
            ),
            measurements={
                "ratio": round(ratio, 6),
                "words_before": len(words_before),
                "words_after": len(words_after),
            },
        )
    )

    struct_before, struct_after = _line_structure_view(before), _line_structure_view(after)
    structure = {
        "headings": (
            len(_MD_HEADING.findall(struct_before)),
            len(_MD_HEADING.findall(struct_after)),
        ),
        "code_fences": (
            len(_MD_FENCE.findall(struct_before)),
            len(_MD_FENCE.findall(struct_after)),
        ),
        "list_items": (len(_MD_LIST.findall(struct_before)), len(_MD_LIST.findall(struct_after))),
    }
    structure_ok = all(b == a for b, a in structure.values())
    checks.append(
        Check(
            name="structure_preserved",
            passed=structure_ok,
            detail="Markdown heading, code-fence and list-item counts are unchanged."
            if structure_ok
            else "Markdown structure counts changed.",
            measurements={k: {"before": b, "after": a} for k, (b, a) in structure.items()},
        )
    )

    checks.append(
        Check(
            name="semantic_similarity",
            passed=None,
            detail=(
                "Not measured. A genuine semantic-similarity score needs an embedding "
                "model, which the default profile excludes to keep validation local, "
                "deterministic and offline. Lexical similarity is reported instead and "
                "is not a substitute."
            ),
        )
    )

    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True,
        all_passed=all(decided) if decided else None,
        checks=checks,
    )
