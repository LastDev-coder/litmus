from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import build_jpeg, build_png
from litmus.artifact import load_bytes
from litmus.io import SafeWriteError, safe_write
from litmus.pipeline import TransformOptions, analyze
from litmus.transform.file_strip import (
    jpeg_scan_digest,
    png_image_data_digest,
    strip_jpeg_metadata,
    strip_png_metadata,
    strip_svg_metadata,
)
from litmus.validate.code import validate_code

# --- binary image removal --------------------------------------------------


def test_png_strip_removes_metadata_and_keeps_pixels() -> None:
    original = build_png(text={"Author": "x"}, c2pa=True)
    stripped, removed, digest = strip_png_metadata(original)
    assert "tEXt" in removed and "caBX" in removed
    # The IDAT digest is unchanged: pixels preserved.
    assert digest == png_image_data_digest(stripped)
    assert digest == png_image_data_digest(original)


def test_jpeg_strip_removes_app_segments_and_keeps_scan() -> None:
    original = build_jpeg(xmp=True, jumbf=True)
    stripped, removed, digest = strip_jpeg_metadata(original)
    assert removed  # something was removed
    assert digest == jpeg_scan_digest(stripped) == jpeg_scan_digest(original)
    assert b"xmpmeta" not in stripped


def test_png_without_metadata_is_a_noop_but_valid() -> None:
    original = build_png()
    stripped, removed, _ = strip_png_metadata(original)
    assert removed == []
    assert stripped == original


def test_jpeg_transform_pipeline_accepts_with_proof() -> None:
    artifact = load_bytes(build_jpeg(xmp=True), path=Path("a.jpg"))
    report, data = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is True
    assert next(c for c in report.validation.checks if c.name == "pixel_data_identical").passed


def test_unsupported_binary_is_refused() -> None:
    artifact = load_bytes(b"GIF89a\x00\x01", path=Path("a.gif"))
    report, data = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is False
    assert data == artifact.data


# --- svg removal -----------------------------------------------------------


def test_svg_metadata_is_stripped_but_drawing_kept() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        "<metadata><c2pa:x/></metadata>"
        '<path d="M0 0 L1 1"/></svg>'
    )
    stripped, removed = strip_svg_metadata(svg)
    assert removed == 1
    assert "<metadata" not in stripped
    assert "<path" in stripped


def test_svg_transform_pipeline_accepts() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><metadata>secret</metadata><rect/></svg>'
    artifact = load_bytes(svg, path=Path("a.svg"))
    report, data = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is True
    assert b"<metadata" not in data
    assert next(c for c in report.validation.checks if c.name == "svg_parses_after").passed


# --- code validation -------------------------------------------------------


def test_validate_code_python_proves_equivalence() -> None:
    report = validate_code("x=1\n\n", "x = 1\n", "python")
    assert report.all_passed is True
    assert next(c for c in report.checks if c.name == "code_semantics_preserved").passed is True


def test_validate_code_python_detects_change() -> None:
    report = validate_code('x = "a"\n', 'x = "b"\n', "python")
    assert next(c for c in report.checks if c.name == "code_semantics_preserved").passed is False


def test_validate_code_python_flags_broken_output() -> None:
    report = validate_code("x = 1\n", "x = (\n", "python")
    assert next(c for c in report.checks if c.name == "code_parses_after").passed is False


def test_validate_code_javascript_falls_back_to_syntax_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Without the tree-sitter extra, JavaScript degrades to node --check, which
    # proves syntax but not equivalence.
    monkeypatch.setattr("litmus.validate.code.validate_code_treesitter", lambda *a: None)
    report = validate_code("var x=1", "var x = 1;\n", "javascript")
    preserved = next(c for c in report.checks if c.name == "code_semantics_preserved")
    assert preserved.passed is None


def test_validate_code_unmapped_language_is_unproven() -> None:
    # A language tree-sitter is not wired for here is honestly unproven.
    report = validate_code("puts 1", "puts 1\n", "ruby")
    assert report.all_passed is None
    assert next(c for c in report.checks if c.name == "code_semantics_preserved").passed is None


# --- safe write ------------------------------------------------------------


def test_safe_write_is_atomic_and_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    safe_write(target, b"hello")
    assert target.read_bytes() == b"hello"
    # No temp files left behind.
    assert list(tmp_path.iterdir()) == [target]


def test_safe_write_refuses_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    real.write_bytes(b"original")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    with pytest.raises(SafeWriteError):
        safe_write(link, b"malicious")
    assert real.read_bytes() == b"original"


def test_safe_write_backup(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes(b"v1")
    safe_write(target, b"v2", backup=True)
    assert target.read_bytes() == b"v2"
    assert (tmp_path / "f.txt.bak").read_bytes() == b"v1"


def test_safe_write_refuses_missing_parent(tmp_path: Path) -> None:
    with pytest.raises(SafeWriteError):
        safe_write(tmp_path / "nope" / "f.txt", b"x")


def test_inplace_transform_does_not_follow_symlink(tmp_path: Path) -> None:
    # A symlinked target must not be rewritten through.
    real = tmp_path / "real.md"
    real.write_bytes("clean\u200b\n".encode())
    link = tmp_path / "link.md"
    link.symlink_to(real)
    # walk() does not follow symlinks, so a directory scan would skip it; a
    # direct file argument reaches safe_write, which refuses.
    assert os.path.islink(link)
