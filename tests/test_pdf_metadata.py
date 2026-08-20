from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from conftest import build_pdf
from litmus.artifact import load_bytes
from litmus.cli import EXIT_FINDINGS, EXIT_OK, app
from litmus.pdf import (
    info_value_spans,
    is_encrypted,
    is_pdf,
    read_info_fields,
    read_xmp_summary,
    strip_pdf_metadata,
    xmp_packet_spans,
)
from litmus.pipeline import TransformOptions, analyze
from litmus.validate.pdf import validate_pdf_strip

runner = CliRunner()


def _pdf_artifact(data: bytes):  # type: ignore[no-untyped-def]
    return load_bytes(data, path=Path("doc.pdf"))


# --- detection ---------------------------------------------------------------


def test_is_pdf_and_encryption_detection() -> None:
    assert is_pdf(build_pdf())
    assert not is_pdf(b"%PDX-1.7")
    assert is_encrypted(build_pdf(encrypted=True))
    assert not is_encrypted(build_pdf())


def test_info_fields_are_read() -> None:
    fields = read_info_fields(build_pdf(author="Jane Doe", producer="Acme PDF 1.0"))
    assert fields["Author"] == "Jane Doe"
    assert fields["Producer"] == "Acme PDF 1.0"
    assert fields["CreationDate"].startswith("D:2024")


def test_hex_string_author_is_read() -> None:
    fields = read_info_fields(build_pdf(author="Jane Doe", hex_author=True))
    assert fields["Author"] == "Jane Doe"


def test_nested_parentheses_in_literal_string() -> None:
    data = build_pdf(author="Jane (Janey) Doe")
    fields = read_info_fields(data)
    assert fields["Author"] == "Jane (Janey) Doe"
    spans = [s for s in info_value_spans(data) if s[2] == "Author"]
    assert len(spans) == 1
    start, end, _ = spans[0]
    assert data[start:end] == b"Jane (Janey) Doe"


def test_title_outside_info_object_is_not_a_span() -> None:
    # An outline-style /Title in an unrelated object must never be touched.
    data = build_pdf().replace(b"<< /Type /Pages", b"<< /OutlineTitleDecoy true /Type /Pages")
    data += b"7 0 obj\n<< /Title (Chapter One) /Type /Outlines >>\nendobj\n"
    assert all(key != "Title" for _, _, key in info_value_spans(data))
    new_data, _ = strip_pdf_metadata(data)
    assert b"(Chapter One)" in new_data


def test_xmp_packet_is_found() -> None:
    data = build_pdf(xmp=True)
    assert len(xmp_packet_spans(data)) == 1
    summary = read_xmp_summary(data)
    assert summary["packets"] == 1
    assert summary["creator_tool"] == "SneakyWriter 9000"


# --- stripping and its proof -------------------------------------------------


def test_strip_blanks_values_and_preserves_everything_else() -> None:
    data = build_pdf(xmp=True)
    new_data, removed = strip_pdf_metadata(data)
    assert len(new_data) == len(data)
    assert b"Jane Doe" not in new_data
    assert b"Acme PDF 1.0" not in new_data
    assert b"SneakyWriter" not in new_data
    assert b"(Hello world) Tj" in new_data  # page content untouched
    assert {"info:Author", "info:Producer", "info:CreationDate", "xmp_packet"} == set(removed)
    assert validate_pdf_strip(data, new_data).all_passed is True


def test_strip_is_idempotent() -> None:
    once, _ = strip_pdf_metadata(build_pdf(xmp=True))
    twice, removed = strip_pdf_metadata(once)
    assert twice == once
    assert removed == []


def test_encrypted_pdf_is_left_unchanged() -> None:
    data = build_pdf(encrypted=True)
    new_data, removed = strip_pdf_metadata(data)
    assert new_data == data
    assert removed == []


def test_validator_rejects_a_change_outside_metadata() -> None:
    data = build_pdf()
    tampered = bytearray(strip_pdf_metadata(data)[0])
    at = tampered.index(b"Hello world")
    tampered[at : at + 5] = b"HELLO"
    result = validate_pdf_strip(data, bytes(tampered))
    assert result.all_passed is False
    failing = [c.name for c in result.checks if c.passed is False]
    assert failing == ["pdf_changes_confined_to_metadata"]


def test_validator_rejects_a_size_change() -> None:
    data = build_pdf()
    assert validate_pdf_strip(data, data + b" ").all_passed is False


def test_decoy_info_object_inside_a_stream_is_never_blanked() -> None:
    # An uncompressed content stream carrying bytes that mimic the real Info
    # object ("5 0 obj ... /Author (...)") must not be mistaken for metadata:
    # blanking it would alter visible content.
    base = build_pdf()
    decoy = b"5 0 obj << /Author (VisibleText) >> endobj"
    data = base.replace(b"BT /F1 12 Tf", b"BT " + decoy + b" /F1 12 Tf")
    new_data, removed = strip_pdf_metadata(data)
    assert b"(VisibleText)" in new_data
    assert removed.count("info:Author") == 1  # only the real Info object
    assert b"Jane Doe" not in new_data


def test_decoy_xpacket_begin_cannot_span_stream_boundaries() -> None:
    # A decoy "<?xpacket begin" planted in page content must not pair with the
    # real packet's end marker: that span would cross endstream/object
    # boundaries and corrupt the file structure.
    data = build_pdf(xmp=True)
    attacked = data.replace(b"(Hello world) Tj", b"(x) Tj <?xpacket begin='' id='f'?>")
    new_data, _ = strip_pdf_metadata(attacked)
    assert new_data.count(b"endstream") == attacked.count(b"endstream")
    assert b"/Type /Metadata /Subtype /XML" in new_data
    assert b"(x) Tj" in new_data  # page content untouched
    assert b"SneakyWriter" not in new_data  # the real packet was still cleaned
    assert validate_pdf_strip(attacked, new_data).all_passed is True


def test_incremental_update_second_info_object_is_also_blanked() -> None:
    # An incremental update appends a new Info object and trailer; both the
    # original and the updated Info values must be blanked.
    base = build_pdf()
    update = (
        b"7 0 obj\n<< /Author (Second Author) /Producer (LaterTool 2.0) >>\nendobj\n"
        b"trailer\n<< /Size 8 /Root 1 0 R /Info 7 0 R /Prev 100 >>\n"
        b"startxref\n0\n%%EOF\n"
    )
    data = base + update
    new_data, removed = strip_pdf_metadata(data)
    assert b"Jane Doe" not in new_data
    assert b"Second Author" not in new_data
    assert b"LaterTool" not in new_data
    assert removed.count("info:Author") == 2
    assert validate_pdf_strip(data, new_data).all_passed is True


def test_compressed_xmp_is_honestly_out_of_scope_and_untouched() -> None:
    # Modern writers may store metadata flate-compressed. The byte scan cannot
    # see inside; the packet must be left alone (never corrupted), while the
    # uncompressed Info dictionary is still cleaned.
    import zlib

    data = build_pdf(xmp=True)
    start = data.find(b"<?xpacket")
    end = data.find(b'<?xpacket end="w"?>') + len(b'<?xpacket end="w"?>')
    modern = data[:start] + zlib.compress(data[start:end]) + data[end:]
    assert xmp_packet_spans(modern) == []
    new_data, removed = strip_pdf_metadata(modern)
    assert "info:Author" in removed
    assert "xmp_packet" not in removed
    assert len(new_data) == len(modern)
    assert validate_pdf_strip(modern, new_data).all_passed is True


# --- pipeline integration ----------------------------------------------------


def test_inspection_reports_info_and_xmp() -> None:
    report, _ = analyze(_pdf_artifact(build_pdf(xmp=True)))
    categories = {f.category for f in report.inspection.findings}
    assert {"pdf_info_dictionary", "pdf_xmp_metadata"} <= categories
    info = next(f for f in report.inspection.findings if f.category == "pdf_info_dictionary")
    assert info.severity.value == "warning"  # Author present
    assert info.removable_by == ["strip_pdf_metadata"]


def test_inspection_skips_encrypted_pdf() -> None:
    report, _ = analyze(_pdf_artifact(build_pdf(encrypted=True)))
    status = next(i for i in report.inspection.inspectors if i.name == "pdf_metadata")
    assert status.ran is False
    assert "encrypted" in (status.reason or "")


def test_transform_pipeline_accepts_and_cleans() -> None:
    data = build_pdf(xmp=True)
    report, output = analyze(_pdf_artifact(data), options=TransformOptions())
    assert report.transformation.accepted is True
    assert report.validation.all_passed is True
    assert len(output) == len(data)
    assert b"Jane Doe" not in output
    # And the cleaned file no longer yields metadata findings.
    report2, _ = analyze(_pdf_artifact(output))
    assert not [f for f in report2.inspection.findings if f.detector == "pdf_metadata"]


def test_transform_pipeline_rejects_encrypted() -> None:
    data = build_pdf(encrypted=True)
    report, output = analyze(_pdf_artifact(data), options=TransformOptions())
    assert report.transformation.accepted is False
    assert "encrypted" in (report.transformation.rejected_reason or "")
    assert output == data


def test_ascii_pdf_is_never_routed_to_text_transforms() -> None:
    # A pure-ASCII PDF decodes as UTF-8; the pipeline must still treat it as a
    # PDF, because text normalization would corrupt its byte offsets.
    data = build_pdf().replace(b"%\xe2\xe3\xcf\xd3\n", b"%comment\n\n")
    artifact = load_bytes(data, path=Path("doc.pdf"))
    assert artifact.text is not None  # it really is decodable text
    report, output = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is True
    assert len(output) == len(data)
    ops = [op.operation for op in report.transformation.operations]
    assert ops == ["strip_pdf_metadata"]


def test_c2pa_presence_is_detected_in_pdf() -> None:
    data = build_pdf() + b"\n8 0 obj\n<< /AFRelationship /C2PA_Manifest >>\nendobj\n"
    report, _ = analyze(_pdf_artifact(data))
    c2pa = [f for f in report.inspection.findings if f.category == "c2pa_manifest"]
    assert len(c2pa) == 1
    assert c2pa[0].details["container"] == "pdf"


# --- CLI end-to-end ----------------------------------------------------------


def test_cli_inspect_and_transform_pdf(tmp_path: Path) -> None:
    path = tmp_path / "report.pdf"
    path.write_bytes(build_pdf(xmp=True))

    result = runner.invoke(app, ["inspect", str(path), "--fail-on", "warning"])
    assert result.exit_code == EXIT_FINDINGS
    assert "pdf_info_dictionary" in result.stdout

    result = runner.invoke(app, ["transform", str(path), "--in-place", "--json"])
    assert result.exit_code == EXIT_OK
    cleaned = path.read_bytes()
    assert b"Jane Doe" not in cleaned
    assert runner.invoke(app, ["inspect", str(path), "--fail-on", "warning"]).exit_code == EXIT_OK
