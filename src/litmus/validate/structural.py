"""Proof for structural code transforms.

Token/AST equality cannot gate a transform whose purpose is to change the
tree, so each structural operation gets its own validator. The proof is
computed from the before/after pair alone — it does not trust the transform's
account of what it did.

For Python import removal the obligations are:

1. the output parses;
2. the top-level AST delta is *exactly* the removal of whole
   ``import``/``from-import`` statements: every surviving statement is
   structurally identical and in order, and nothing was added. A change
   nested anywhere else would alter its enclosing top-level statement's
   ``ast.dump`` and fail this check;
3. every removed statement is neither a ``__future__`` import nor a star
   import, and every name it bound is unreferenced in the original — where
   "referenced" includes identifiers inside string literals (``__all__``,
   quoted annotations, dynamic lookups).
"""

from __future__ import annotations

import ast

from ..model import Check, ValidationReport
from ..transform.code_structural import import_bindings, referenced_names


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def validate_python_import_removal(before: str, after: str) -> ValidationReport:
    checks: list[Check] = []

    after_tree = _parse(after)
    checks.append(
        Check(
            name="structural_output_parses",
            passed=after_tree is not None,
            detail="Output parses as valid Python."
            if after_tree is not None
            else "Output does not parse as Python.",
        )
    )
    before_tree = _parse(before)

    removed: list[ast.Import | ast.ImportFrom] = []
    delta_ok: bool | None
    if after_tree is None or before_tree is None:
        delta_ok = None
        delta_detail = "Cannot compare structure: the {} does not parse.".format(
            "output" if after_tree is None else "original"
        )
    else:
        after_dumps = [ast.dump(s, include_attributes=False) for s in after_tree.body]
        i = 0
        problem: str | None = None
        for stmt in before_tree.body:
            if i < len(after_dumps) and ast.dump(stmt, include_attributes=False) == after_dumps[i]:
                i += 1
            elif isinstance(stmt, ast.Import | ast.ImportFrom):
                removed.append(stmt)
            else:
                problem = f"a non-import statement changed or disappeared (line {stmt.lineno})"
                break
        if problem is None and i != len(after_dumps):
            problem = "the output contains statements that are not in the original"
        delta_ok = problem is None
        delta_detail = (
            f"The only top-level difference is the removal of {len(removed)} whole "
            "import statement(s); every other statement is structurally identical."
            if delta_ok
            else f"The delta is not import removal only: {problem}."
        )
    checks.append(
        Check(
            name="structural_delta_is_import_removal_only",
            passed=delta_ok,
            detail=delta_detail,
            measurements={"removed_statements": len(removed)},
        )
    )

    removed_bindings: list[str] = []
    unreferenced: bool | None
    if delta_ok is not True or before_tree is None:
        unreferenced = None
        unref_detail = "Not evaluated: the delta was not proven to be import removal only."
    else:
        referenced = referenced_names(before_tree)
        problems: list[str] = []
        for stmt in removed:
            if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
                problems.append(
                    f"line {stmt.lineno}: __future__ imports change compilation "
                    "and are never removable"
                )
                continue
            bindings = import_bindings(stmt)
            if bindings is None:
                problems.append(f"line {stmt.lineno}: star-import bindings are unknowable")
                continue
            removed_bindings.extend(bindings)
            problems.extend(
                f"'{name}' (line {stmt.lineno}) is referenced elsewhere in the file"
                for name in bindings
                if name in referenced
            )
        unreferenced = not problems
        unref_detail = (
            f"All {len(removed_bindings)} removed binding(s) are unreferenced anywhere "
            "in the original, including inside string literals."
            if unreferenced
            else "; ".join(problems)
        )
    checks.append(
        Check(
            name="removed_imports_unreferenced",
            passed=unreferenced,
            detail=unref_detail,
            measurements={
                "removed_bindings": sorted(removed_bindings),
                "method": "top-level AST delta + identifier/string reference scan",
            },
        )
    )

    decided = [c.passed for c in checks if c.passed is not None]
    return ValidationReport(
        performed=True, all_passed=all(decided) if decided else None, checks=checks
    )
