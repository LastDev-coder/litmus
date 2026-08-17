from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from litmus.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, app

runner = CliRunner()


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_inspect_clean_file_exits_zero(tmp_path: Path, clean_text: str) -> None:
    path = _write(tmp_path, "a.md", clean_text)
    result = runner.invoke(app, ["inspect", str(path)])
    assert result.exit_code == EXIT_OK
    assert "findings   none" in result.stdout


def test_inspect_json_is_parseable(tmp_path: Path, dirty_text: str) -> None:
    path = _write(tmp_path, "a.md", dirty_text)
    result = runner.invoke(app, ["inspect", str(path), "--json"])
    assert result.exit_code == EXIT_OK
    payload = json.loads(result.stdout)
    assert payload["artifact"]["kind"] == "text"
    assert any(f["category"] == "zero_width" for f in payload["inspection"]["findings"])


def test_fail_on_warning_gates_ci(tmp_path: Path, dirty_text: str, clean_text: str) -> None:
    dirty = _write(tmp_path, "dirty.md", dirty_text)
    clean = _write(tmp_path, "clean.md", clean_text)
    assert runner.invoke(app, ["inspect", str(dirty), "--fail-on", "warning"]).exit_code == (
        EXIT_FINDINGS
    )
    assert runner.invoke(app, ["inspect", str(clean), "--fail-on", "warning"]).exit_code == EXIT_OK


def test_missing_path_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["inspect", str(tmp_path / "nope.md")])
    assert result.exit_code == EXIT_ERROR


def test_invalid_fail_on_exits_two(tmp_path: Path, dirty_text: str) -> None:
    path = _write(tmp_path, "a.md", dirty_text)
    result = runner.invoke(app, ["inspect", str(path), "--fail-on", "banana"])
    assert result.exit_code == EXIT_ERROR


def test_transform_writes_to_stdout_by_default(tmp_path: Path, dirty_text: str) -> None:
    path = _write(tmp_path, "a.md", dirty_text)
    result = runner.invoke(app, ["transform", str(path)])
    assert result.exit_code == EXIT_OK
    assert "\u200b" not in result.stdout
    # The input file is untouched unless --in-place is given. Compare bytes:
    # read_text() would silently translate the CRLF line endings under test.
    assert path.read_bytes() == dirty_text.encode("utf-8")


def test_transform_in_place(tmp_path: Path, dirty_text: str) -> None:
    path = _write(tmp_path, "a.md", dirty_text)
    result = runner.invoke(app, ["transform", str(path), "--in-place", "--json"])
    assert result.exit_code == EXIT_OK
    assert "\u200b" not in path.read_text(encoding="utf-8")


def test_transform_of_source_code_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.py", "x = 1\u200b\n")
    result = runner.invoke(app, ["transform", str(path), "--in-place"])
    assert result.exit_code == EXIT_FINDINGS
    assert path.read_bytes() == "x = 1\u200b\n".encode()
    assert "Refusing to write transformed source code" in result.stdout


def test_transform_of_source_code_with_force(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.py", "x = 1\u200b\n")
    result = runner.invoke(app, ["transform", str(path), "--in-place", "--force"])
    assert result.exit_code == EXIT_OK
    assert path.read_text(encoding="utf-8") == "x = 1\n"


def test_unknown_operation_exits_two(tmp_path: Path, clean_text: str) -> None:
    path = _write(tmp_path, "a.md", clean_text)
    result = runner.invoke(app, ["transform", str(path), "--op", "nope"])
    assert result.exit_code == EXIT_ERROR


def test_capabilities_json_lists_providers() -> None:
    result = runner.invoke(app, ["capabilities", "--json"])
    assert result.exit_code == EXIT_OK
    rows = json.loads(result.stdout)
    assert {row["provider"] for row in rows} >= {"anthropic", "openai"}


def test_operations_command_lists_profiles() -> None:
    result = runner.invoke(app, ["operations", "--json"])
    payload = json.loads(result.stdout)
    assert "standard" in payload["profiles"]
    assert "strip_zero_width" in payload["operations"]


def test_report_command_renders_saved_json(tmp_path: Path, dirty_text: str) -> None:
    source = _write(tmp_path, "a.md", dirty_text)
    saved = tmp_path / "report.json"
    saved.write_text(
        runner.invoke(app, ["inspect", str(source), "--json"]).stdout, encoding="utf-8"
    )
    result = runner.invoke(app, ["report", str(saved)])
    assert result.exit_code == EXIT_OK
    assert "zero_width" in result.stdout


def test_report_command_rejects_garbage(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert runner.invoke(app, ["report", str(bad)]).exit_code == EXIT_ERROR


def test_validate_command_on_a_pair(tmp_path: Path) -> None:
    before = _write(tmp_path, "before.md", "hello\u200b world\n")
    after = _write(tmp_path, "after.md", "hello world\n")
    result = runner.invoke(app, ["validate", str(before), str(after), "--json"])
    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout)["all_passed"] is True


def test_validate_command_flags_a_bad_pair(tmp_path: Path) -> None:
    before = _write(tmp_path, "before.md", "hello world\n")
    after = _write(tmp_path, "after.md", "goodbye everyone\n")
    result = runner.invoke(app, ["validate", str(before), str(after)])
    assert result.exit_code == EXIT_FINDINGS


def test_multi_file_scan_hides_clean_artifacts(
    tmp_path: Path, clean_text: str, dirty_text: str
) -> None:
    _write(tmp_path, "clean1.md", clean_text)
    _write(tmp_path, "clean2.md", clean_text)
    _write(tmp_path, "dirty.md", dirty_text)
    result = runner.invoke(app, ["inspect", str(tmp_path)])
    assert "clean1.md" not in result.stdout
    assert "dirty.md" in result.stdout
    assert "2 clean artifact(s) not shown" in result.stdout


def test_verbose_multi_file_scan_shows_everything(
    tmp_path: Path, clean_text: str, dirty_text: str
) -> None:
    _write(tmp_path, "clean1.md", clean_text)
    _write(tmp_path, "dirty.md", dirty_text)
    result = runner.invoke(app, ["inspect", str(tmp_path), "-v"])
    assert "clean1.md" in result.stdout
    assert "not shown" not in result.stdout
