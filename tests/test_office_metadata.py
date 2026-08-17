"""Office Open XML metadata inspection and proof-gated removal (feature 1)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from conftest import build_docx
from litmus.artifact import load_bytes
from litmus.office import (
    is_ooxml,
    ooxml_kind,
    read_properties,
    strip_office_metadata,
)
from litmus.pipeline import TransformOptions, analyze
from litmus.validate.office import validate_office_strip

# --- detection --------------------------------------------------------------


def test_detects_ooxml() -> None:
    assert is_ooxml(build_docx()) is True
    assert ooxml_kind(build_docx()) == "docx"


def test_plain_zip_is_not_ooxml() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "hi")
    assert is_ooxml(buf.getvalue()) is False


def test_non_zip_is_not_ooxml() -> None:
    assert is_ooxml(b"\x89PNG\r\n\x1a\n....") is False
    assert is_ooxml(b"plain text") is False


# --- inspection -------------------------------------------------------------


def test_reads_author_company_and_custom() -> None:
    props = read_properties(build_docx(author="Jane Doe", company="Acme Corp"))
    assert props["core"]["creator"] == "Jane Doe"
    assert props["core"]["lastModifiedBy"] == "Jane Doe"
    assert props["app"]["Company"] == "Acme Corp"
    assert props["custom"]["ClientCode"] == "SECRET-42"


def test_inspect_surfaces_office_metadata_finding() -> None:
    artifact = load_bytes(build_docx(), path=Path("report.docx"))
    report, _ = analyze(artifact)
    office = [f for f in report.inspection.findings if f.category == "office_metadata"]
    assert len(office) == 1
    assert office[0].severity.value == "warning"  # author/company present
    assert "strip_office_metadata" in office[0].removable_by


# --- transform + proof ------------------------------------------------------


def test_strip_removes_metadata_but_keeps_document() -> None:
    original = build_docx()
    stripped, removed = strip_office_metadata(original)
    assert "docProps/custom.xml" in removed
    props = read_properties(stripped)
    assert props["core"] == {}
    assert props["app"] == {}
    assert props["custom"] == {}
    # the document body must be byte-identical
    with zipfile.ZipFile(io.BytesIO(original)) as a, zipfile.ZipFile(io.BytesIO(stripped)) as b:
        assert a.read("word/document.xml") == b.read("word/document.xml")


def test_proof_passes_for_genuine_strip() -> None:
    original = build_docx()
    stripped, _ = strip_office_metadata(original)
    vr = validate_office_strip(original, stripped)
    assert vr.all_passed is True
    names = {c.name: c.passed for c in vr.checks}
    assert names["office_parses_after"] is True
    assert names["document_content_identical"] is True


def test_proof_rejects_a_changed_document_part() -> None:
    original = build_docx()
    # tamper with the body to simulate an unsafe strip
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            payload = src.read(info.filename)
            if info.filename == "word/document.xml":
                payload = payload.replace(b"Hello world.", b"Tampered.")
            dst.writestr(info, payload)
    vr = validate_office_strip(original, tampered.getvalue())
    assert vr.all_passed is False


def test_pipeline_accepts_and_cleans_docx() -> None:
    artifact = load_bytes(build_docx(), path=Path("report.docx"))
    report, output = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is True
    assert output != artifact.data
    assert read_properties(output)["core"] == {}
    assert report.validation.all_passed is True


def test_strip_is_deterministic() -> None:
    original = build_docx()
    assert strip_office_metadata(original)[0] == strip_office_metadata(original)[0]


def test_strip_is_idempotent() -> None:
    once, _ = strip_office_metadata(build_docx())
    twice, _ = strip_office_metadata(once)
    # a second pass finds nothing left to remove and re-emits the same bytes
    assert read_properties(twice)["core"] == {}
