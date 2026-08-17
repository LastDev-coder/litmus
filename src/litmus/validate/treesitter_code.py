"""Language-agnostic structural code validation via tree-sitter.

Extends the Python-only AST proof (``validate/code.py``) to JavaScript,
TypeScript, Java, Kotlin and Swift without needing each language's compiler.
It is optional: installing the ``code`` extra enables it; without it the
loader returns ``None`` and the caller degrades to refuse-unless-forced.

**The proof.** We parse both versions and compare their *significant token
streams*: every leaf token, in order, with its source text, **excluding
comments**. Whitespace is not a token in tree-sitter, so reformatting leaves
the stream unchanged. A comment edit is excluded, so it is safe. A change to a
string literal or identifier changes that leaf's text, so it is caught. This is
the same guarantee ``ast.dump`` gives for Python, generalized.

A parse that yields any ERROR node is treated as "does not parse", so syntax
the transform broke is rejected rather than silently compared.
"""

from __future__ import annotations

from typing import Any

from ..model import Check, ValidationReport

# Our language name -> tree-sitter-language-pack name. Identity today, but kept
# explicit so a divergence (e.g. "c#" vs "c_sharp") has one place to live.
_LANG_MAP = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "java": "java",
    "kotlin": "kotlin",
    "swift": "swift",
}


def treesitter_available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
    except ImportError:
        return False
    return True


def _load_parser(language: str | None) -> Any | None:
    ts_name = _LANG_MAP.get(language or "")
    if ts_name is None:
        return None
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    try:
        return get_parser(ts_name)
    except Exception:  # noqa: BLE001 - a missing/broken grammar is "unavailable", not a crash
        return None


def _significant_tokens(root: Any) -> list[tuple[str, bytes]]:
    """Leaf tokens in document order, with text, excluding comments."""
    tokens: list[tuple[str, bytes]] = []
    stack: list[Any] = [root]
    while stack:
        node = stack.pop()
        if "comment" in node.type:
            continue
        if node.child_count == 0:
            tokens.append((node.type, node.text or b""))
        else:
            stack.extend(reversed(node.children))
    return tokens


def validate_code_treesitter(
    before: str, after: str, language: str | None
) -> ValidationReport | None:
    """Return a report, or ``None`` if tree-sitter cannot handle this language."""
    parser = _load_parser(language)
    if parser is None:
        return None

    before_tree = parser.parse(before.encode("utf-8"))
    after_tree = parser.parse(after.encode("utf-8"))
    before_ok = not before_tree.root_node.has_error
    after_ok = not after_tree.root_node.has_error

    checks = [
        Check(
            name="code_parses_after",
            passed=after_ok,
            detail="Output parses cleanly (no tree-sitter ERROR nodes)."
            if after_ok
            else "Output contains parse errors; the transform broke the syntax.",
        )
    ]

    preserved: bool | None
    if not after_ok:
        preserved = None
        detail = "Cannot compare structure because the output does not parse."
    elif not before_ok:
        preserved = None
        detail = "Original does not parse cleanly; structural equivalence is unprovable."
    else:
        preserved = _significant_tokens(before_tree.root_node) == _significant_tokens(
            after_tree.root_node
        )
        detail = (
            "Significant token streams are identical (comments and whitespace aside): "
            "the transform provably preserved the program."
            if preserved
            else "Significant token streams differ: the transform changed a string, "
            "identifier or other token, not just whitespace or comments."
        )
    checks.append(
        Check(
            name="code_semantics_preserved",
            passed=preserved,
            detail=detail,
            measurements={
                "language": language or "unknown",
                "method": "tree-sitter significant-token equality",
            },
        )
    )
    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True, all_passed=all(decided) if decided else None, checks=checks
    )
