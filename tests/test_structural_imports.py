"""Structural transform: proof-gated removal of unused Python imports."""

from __future__ import annotations

from pathlib import Path

from litmus.artifact import load_bytes
from litmus.model import Report
from litmus.pipeline import TransformOptions, analyze
from litmus.transform.code_structural import _remove_unused_imports
from litmus.validate.structural import validate_python_import_removal


def _run_code(text: str, name: str = "sample.py", **kwargs: object) -> tuple[Report, bytes]:
    artifact = load_bytes(text.encode("utf-8"), path=Path(name))
    options = TransformOptions(profile="code", **kwargs)  # type: ignore[arg-type]
    return analyze(artifact, options=options)


def _op(report: Report, operation: str) -> object:
    assert report.transformation is not None
    for op in report.transformation.operations:
        if op.operation == operation:
            return op
    raise AssertionError(f"operation {operation} not recorded")


# --- the transform itself ---------------------------------------------------


def test_removes_single_unused_import() -> None:
    src = "import os\n\nprint('hi')\n"
    assert _remove_unused_imports(src) == "\nprint('hi')\n"


def test_keeps_used_import() -> None:
    src = "import os\n\nprint(os.sep)\n"
    assert _remove_unused_imports(src) == src


def test_keeps_multi_alias_statement_when_any_name_is_used() -> None:
    src = "import os, sys\n\nprint(sys.argv)\n"
    assert _remove_unused_imports(src) == src


def test_removes_multi_alias_statement_when_all_names_unused() -> None:
    src = "import os, sys\n\nprint('hi')\n"
    assert _remove_unused_imports(src) == "\nprint('hi')\n"


def test_keeps_future_import() -> None:
    src = "from __future__ import annotations\n\nprint('hi')\n"
    assert _remove_unused_imports(src) == src


def test_keeps_star_import() -> None:
    src = "from os.path import *\n\nprint('hi')\n"
    assert _remove_unused_imports(src) == src


def test_keeps_import_named_in_dunder_all() -> None:
    src = 'from .core import api\n\n__all__ = ["api"]\n'
    assert _remove_unused_imports(src) == src


def test_keeps_import_referenced_in_quoted_annotation() -> None:
    src = 'import typing\n\ndef f(x: "typing.Any") -> None:\n    pass\n'
    assert _remove_unused_imports(src) == src


def test_keeps_noqa_import() -> None:
    src = "from .core import api  # noqa: F401\n"
    assert _remove_unused_imports(src) == src


def test_keeps_function_level_import() -> None:
    src = "def f():\n    import os\n    return 1\n"
    assert _remove_unused_imports(src) == src


def test_keeps_import_sharing_a_line_with_other_code() -> None:
    src = "import os; x = 1\n\nprint(x)\n"
    assert _remove_unused_imports(src) == src


def test_removes_multiline_from_import() -> None:
    src = "from os.path import (\n    join,\n    split,\n)\n\nprint('hi')\n"
    assert _remove_unused_imports(src) == "\nprint('hi')\n"


def test_asname_binding_is_what_counts() -> None:
    # `np` is the binding; using the module name `numpy` elsewhere as an
    # identifier does not exist here, so the import goes.
    src = "import numpy as np\n\nprint('hi')\n"
    assert _remove_unused_imports(src) == "\nprint('hi')\n"
    used = "import numpy as np\n\nprint(np.pi)\n"
    assert _remove_unused_imports(used) == used


def test_non_python_input_is_untouched() -> None:
    src = "const os = require('os');\n"
    assert _remove_unused_imports(src) == src


def test_transform_is_deterministic_and_idempotent() -> None:
    src = "import os\nimport sys\n\nprint('hi')\n"
    once = _remove_unused_imports(src)
    assert once == _remove_unused_imports(src)
    assert _remove_unused_imports(once) == once


# --- the proof --------------------------------------------------------------


def test_proof_passes_for_genuine_removal() -> None:
    before = "import os\n\nprint('hi')\n"
    after = "\nprint('hi')\n"
    vr = validate_python_import_removal(before, after)
    assert vr.all_passed is True
    names = {c.name: c.passed for c in vr.checks}
    assert names["structural_output_parses"] is True
    assert names["structural_delta_is_import_removal_only"] is True
    assert names["removed_imports_unreferenced"] is True


def test_proof_rejects_removal_of_referenced_import() -> None:
    before = "import os\n\nprint(os.sep)\n"
    after = "\nprint(os.sep)\n"
    vr = validate_python_import_removal(before, after)
    assert vr.all_passed is False


def test_proof_rejects_smuggled_extra_edit() -> None:
    before = "import os\n\nprint('hi')\n"
    after = "\nprint('bye')\n"
    vr = validate_python_import_removal(before, after)
    assert vr.all_passed is False


def test_proof_rejects_added_code() -> None:
    before = "import os\n\nprint('hi')\n"
    after = "\nprint('hi')\nx = 1\n"
    vr = validate_python_import_removal(before, after)
    assert vr.all_passed is False


def test_proof_rejects_broken_output() -> None:
    before = "import os\n\nprint('hi')\n"
    after = "\nprint('hi'\n"
    vr = validate_python_import_removal(before, after)
    assert vr.all_passed is False


def test_proof_rejects_future_import_removal() -> None:
    before = "from __future__ import annotations\n\nprint('hi')\n"
    after = "\nprint('hi')\n"
    vr = validate_python_import_removal(before, after)
    assert vr.all_passed is False


# --- pipeline integration ---------------------------------------------------


def test_pipeline_accepts_proven_removal() -> None:
    report, data = _run_code("import os\n\nprint('hi')\n")
    assert report.transformation is not None and report.transformation.accepted is True
    assert data.decode("utf-8") == "\nprint('hi')\n"
    op = _op(report, "remove_unused_imports")
    assert op.applied is True  # type: ignore[attr-defined]
    assert report.validation is not None
    check_names = [c.name for c in report.validation.checks]
    assert "structural_delta_is_import_removal_only" in check_names
    assert report.validation.all_passed is True


def test_pipeline_skips_structural_op_for_non_python() -> None:
    report, data = _run_code("# just a doc\n", name="notes.md")
    op = _op(report, "remove_unused_imports")
    assert op.applied is False  # type: ignore[attr-defined]
    assert "skipped" in op.details  # type: ignore[attr-defined]
    assert data == b"# just a doc\n"


def test_pipeline_leaves_used_imports_alone() -> None:
    src = "import os\n\nprint(os.sep)\n"
    report, data = _run_code(src)
    assert data.decode("utf-8") == src
    assert report.transformation is not None and report.transformation.accepted is True


def test_code_profile_still_normalizes_characters() -> None:
    # The zero-width sits in a comment, where its removal is provably safe.
    # (Inside a string it would be a proven program change and be refused.)
    src = "import os\n\nprint('hi')  # zero\u200bwidth\n"
    report, data = _run_code(src)
    out = data.decode("utf-8")
    assert "\u200b" not in out
    assert "import os" not in out
    assert report.transformation is not None and report.transformation.accepted is True


def test_operation_note_names_the_side_effect_caveat() -> None:
    report, _ = _run_code("import os\n\nprint('hi')\n")
    op = _op(report, "remove_unused_imports")
    note = str(op.details.get("note", ""))  # type: ignore[attr-defined]
    assert "side" in note and "--force" in note
