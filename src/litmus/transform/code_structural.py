"""Structural code transforms.

Character-level normalizations are gated by token/AST equality, but a
structural transform changes the tree *by design*, so it needs a different
proof. Each structural operation has a dedicated validator
(``validate/structural.py``) and the pipeline discards the change whenever
that proof does not pass — ``--force`` does not override this, because an
unproven structural edit is simply never made.

First operation: removal of provably-unreferenced module-level Python imports.
"Unreferenced" is deliberately conservative: a binding counts as referenced if
its name appears anywhere as an identifier *or inside any string literal*,
which keeps imports named in ``__all__``, quoted annotations,
``getattr``/``globals`` lookups and doctests. Only whole statements that own
their line(s) are removed — never a single alias out of a multi-name import —
and ``from __future__`` imports, star imports, function/class-level imports
and lines marked ``noqa`` are never touched.
"""

from __future__ import annotations

import ast
import re

from .base import Transform

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NOQA = re.compile(r"#\s*noqa", re.IGNORECASE)


def import_bindings(stmt: ast.Import | ast.ImportFrom) -> list[str] | None:
    """Names the statement binds, or ``None`` when unknowable (star import)."""
    if isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names):
        return None
    return [a.asname or a.name.split(".")[0] for a in stmt.names]


def referenced_names(tree: ast.AST) -> frozenset[str]:
    """Every name the module could plausibly reference at runtime.

    Identifiers (``ast.Name``), ``global``/``nonlocal`` targets, and every
    identifier-shaped word inside every string constant. Strings count so
    that ``__all__`` entries, quoted annotations and dynamic lookups keep
    their imports. Comments cannot affect runtime, so they do not count.
    ``ast.alias`` nodes produce no ``Name`` nodes, so an import statement is
    not a reference to itself.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            names.update(node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.update(_IDENTIFIER.findall(node.value))
    return frozenset(names)


def _own_lines_span(stmt: ast.stmt, lines: list[str]) -> tuple[int, int] | None:
    """0-based inclusive line span, if deleting those lines deletes exactly ``stmt``.

    The statement must start its first line (so ``x = 1; import os`` is out),
    nothing but whitespace or a plain comment may follow it on its last line
    (so ``import os; x = 1`` is out), and no line may carry a ``noqa`` marker
    (a deliberate keep, e.g. an ``__init__.py`` re-export).
    """
    if stmt.end_lineno is None or stmt.end_col_offset is None or stmt.col_offset != 0:
        return None
    start, end = stmt.lineno - 1, stmt.end_lineno - 1
    # ast column offsets count UTF-8 bytes, so slice the tail in bytes.
    tail = lines[end].encode("utf-8")[stmt.end_col_offset :].decode("utf-8").strip()
    if tail and not tail.startswith("#"):
        return None
    if any(_NOQA.search(lines[i]) for i in range(start, end + 1)):
        return None
    return start, end


def _remove_unused_imports(text: str) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    referenced = referenced_names(tree)
    lines = text.splitlines(keepends=True)
    dead: set[int] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Import | ast.ImportFrom):
            continue
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
            continue
        bindings = import_bindings(stmt)
        if bindings is None or any(name in referenced for name in bindings):
            continue
        span = _own_lines_span(stmt, lines)
        if span is not None:
            dead.update(range(span[0], span[1] + 1))
    if not dead:
        return text
    return "".join(line for i, line in enumerate(lines) if i not in dead)


REMOVE_UNUSED_IMPORTS = Transform(
    "remove_unused_imports",
    "Remove module-level Python imports that nothing references",
    False,
    _remove_unused_imports,
    note=(
        "Structural: importing a module runs its top-level code, so removing even an "
        "unreferenced import can change behaviour when it was imported for side "
        "effects. Proof-gated: the change is discarded (even under --force) unless "
        "the removal is proven to be the only difference and every removed name is "
        "unreferenced, including inside string literals."
    ),
)

#: Operations the pipeline routes through a dedicated structural proof instead
#: of the token/AST-equality proof (which structural edits fail by design).
STRUCTURAL_CODE_OPS = frozenset({REMOVE_UNUSED_IMPORTS.id})
