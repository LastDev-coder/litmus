"""Validation for source-code transformation.

This is the tool's differentiator. A metadata/whitespace transform on code is
only safe if it did not change program behaviour, and most tools in this space
merely *assert* that. We try to *prove* it, per language, with whatever
toolchain is genuinely available:

* **Python** — parse both versions to an AST and compare ``ast.dump`` with
  attributes excluded. Line/column positions move when whitespace changes but
  the tree does not, so an equal dump is a proof that the program structure is
  identical. If a change lands inside a string literal (e.g. a zero-width
  character that was *inside* a string), the dump differs and we report a
  proven change rather than pretending it was safe. Stdlib only; always runs.
* **JavaScript** — ``node --check`` proves the result still parses. It cannot
  prove structural equivalence, so semantic preservation stays ``unproven``.
* **Everything else** — no toolchain here, so both checks are ``unproven``.

``passed`` semantics: ``True`` proven, ``False`` proven-not, ``None`` could not
be determined. The pipeline decides acceptance from these; it never treats
``None`` as ``True``.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..model import Check, ValidationReport
from .treesitter_code import validate_code_treesitter

_NODE_CHECK_TIMEOUT_S = 10.0


def _python_report(before: str, after: str) -> ValidationReport:
    checks: list[Check] = []
    try:
        after_tree = ast.parse(after)
        parses = True
    except SyntaxError as exc:
        after_tree = None
        parses = False
        parse_detail = f"Output does not parse as Python: {exc}"
    else:
        parse_detail = "Output parses as valid Python."

    checks.append(Check(name="code_parses_after", passed=parses, detail=parse_detail))

    preserved: bool | None
    if not parses or after_tree is None:
        preserved = None
        detail = "Cannot compare structure because the output does not parse."
    else:
        try:
            before_dump = ast.dump(ast.parse(before), include_attributes=False)
            after_dump = ast.dump(after_tree, include_attributes=False)
        except SyntaxError:
            preserved = None
            detail = "Original does not parse as Python; structural equivalence is unprovable."
        else:
            preserved = before_dump == after_dump
            detail = (
                "Abstract syntax trees are identical: the transform provably preserved "
                "program structure."
                if preserved
                else "Abstract syntax trees differ: the transform changed the program "
                "(a change likely landed inside a string or comment-bearing node)."
            )
    checks.append(
        Check(
            name="code_semantics_preserved",
            passed=preserved,
            detail=detail,
            measurements={"language": "python", "method": "ast.dump equality"},
        )
    )
    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True, all_passed=all(decided) if decided else None, checks=checks
    )


def _node_check(after: str, suffix: str) -> bool | None:
    node = shutil.which("node")
    if node is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"check{suffix}"
        target.write_text(after, encoding="utf-8")
        try:
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [node, "--check", str(target)],
                capture_output=True,
                timeout=_NODE_CHECK_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    return result.returncode == 0


def _javascript_report(after: str, suffix: str) -> ValidationReport:
    parses = _node_check(after, suffix)
    checks = [
        Check(
            name="code_parses_after",
            passed=parses,
            detail={
                True: "Output still parses under `node --check`.",
                False: "Output no longer parses under `node --check`.",
                None: "`node` is unavailable; parse validity could not be checked.",
            }[parses],
        ),
        Check(
            name="code_semantics_preserved",
            passed=None,
            detail=(
                "Not proven. `node --check` confirms syntax only; no JavaScript AST "
                "comparison is available, so structural equivalence is unproven."
            ),
            measurements={"language": "javascript", "method": "node --check (syntax only)"},
        ),
    ]
    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True, all_passed=all(decided) if decided else None, checks=checks
    )


def _unsupported_report(language: str | None) -> ValidationReport:
    return ValidationReport(
        performed=True,
        all_passed=None,
        checks=[
            Check(
                name="code_semantics_preserved",
                passed=None,
                detail=(
                    f"No structural validator is available for {language or 'this language'} "
                    "in this environment; semantic preservation is unproven. Review the diff, "
                    "or supply a toolchain (compile/test-based validation is planned)."
                ),
                measurements={"language": language or "unknown", "method": "none"},
            )
        ],
    )


def validate_code(before: str, after: str, language: str | None) -> ValidationReport:
    # Python's stdlib AST is the most precise and needs no optional dependency,
    # so it stays primary. Everything else prefers tree-sitter (the `code`
    # extra) and falls back to a weaker per-language check or a refusal.
    if language == "python":
        return _python_report(before, after)

    treesitter = validate_code_treesitter(before, after, language)
    if treesitter is not None:
        return treesitter

    if language == "javascript":
        # Syntax-only fallback when the `code` extra is not installed.
        return _javascript_report(after, ".js")
    return _unsupported_report(language)
