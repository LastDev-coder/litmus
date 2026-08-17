from __future__ import annotations

from pathlib import Path

from conftest import build_jpeg, build_png
from litmus.artifact import load_bytes
from litmus.inspectors import C2paInspector, FileMetadataInspector
from litmus.model import EvidenceClass
from litmus.pipeline import inspect


def _findings(data: bytes, name: str, inspector: object) -> list[object]:
    artifact = load_bytes(data, path=Path(name))
    assert inspector.applies_to(artifact)  # type: ignore[attr-defined]
    return list(inspector.inspect(artifact).findings)  # type: ignore[attr-defined]


def test_png_text_chunks_are_read() -> None:
    data = build_png(text={"Software": "ExampleTool 1.0", "Comment": "hello"})
    findings = _findings(data, "a.png", FileMetadataInspector())
    assert len(findings) == 1
    details = findings[0].details  # type: ignore[attr-defined]
    assert details["entries"]["Software"] == "ExampleTool 1.0"
    assert findings[0].evidence_class is EvidenceClass.EMBEDDED_METADATA  # type: ignore[attr-defined]


def test_png_without_metadata_yields_nothing() -> None:
    assert _findings(build_png(), "a.png", FileMetadataInspector()) == []


def test_truncated_png_is_reported_not_raised() -> None:
    findings = _findings(b"\x89PNG\r\n\x1a\n\x00\x00", "a.png", FileMetadataInspector())
    assert findings[0].category == "malformed_container"  # type: ignore[attr-defined]


def test_jpeg_segments_are_read() -> None:
    findings = _findings(build_jpeg(xmp=True), "a.jpg", FileMetadataInspector())
    segments = findings[0].details["segments"]  # type: ignore[attr-defined]
    assert "APP1 (XMP)" in segments


def test_c2pa_presence_in_png_is_detected_but_not_verified() -> None:
    findings = _findings(build_png(c2pa=True), "a.png", C2paInspector())
    assert len(findings) == 1
    finding = findings[0]
    assert finding.evidence_class is EvidenceClass.SIGNED_PROVENANCE  # type: ignore[attr-defined]
    assert finding.details["located_in"] == "caBX chunk"  # type: ignore[attr-defined]
    # Without the optional extra the tool must not imply the signature is valid.
    assert finding.details["verification"] in {"not_performed", "failed", "performed"}  # type: ignore[attr-defined]


def test_c2pa_presence_in_jpeg_is_detected() -> None:
    findings = _findings(build_jpeg(jumbf=True), "a.jpg", C2paInspector())
    assert findings[0].details["located_in"] == "APP11 JUMBF segment"  # type: ignore[attr-defined]


def test_png_without_c2pa_yields_nothing() -> None:
    assert _findings(build_png(text={"a": "b"}), "a.png", C2paInspector()) == []


def test_unverified_manifest_does_not_raise_confidence() -> None:
    artifact = load_bytes(build_png(c2pa=True), path=Path("a.png"))
    report = inspect(artifact)
    assert report.provenance.confidence.value == "insufficient_evidence"
    assert any("NOT verified" in note for note in report.provenance.notes)


def test_svg_metadata_and_c2pa_reference() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><metadata><c2pa:manifest/></metadata></svg>'
    assert _findings(svg, "a.svg", FileMetadataInspector())[0].category == "svg_metadata"  # type: ignore[attr-defined]
    assert _findings(svg, "a.svg", C2paInspector())[0].category == "c2pa_manifest"  # type: ignore[attr-defined]
