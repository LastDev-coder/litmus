"""EXIF/GPS surfacing for photos (feature 2)."""

from __future__ import annotations

from pathlib import Path

from conftest import build_jpeg, build_jpeg_with_gps
from litmus.artifact import load_bytes
from litmus.exif import parse_exif_from_app1
from litmus.pipeline import TransformOptions, analyze


def _exif_payload(jpeg: bytes) -> bytes:
    # pull the APP1 payload back out for a direct parser test
    i = jpeg.index(b"\xff\xe1")
    length = int.from_bytes(jpeg[i + 2 : i + 4], "big")
    return jpeg[i + 4 : i + 2 + length]


def test_parser_extracts_gps_and_make() -> None:
    exif = parse_exif_from_app1(_exif_payload(build_jpeg_with_gps("Nikon")))
    assert exif["camera make"] == "Nikon"
    assert abs(float(exif["gps_latitude"]) - 37.8) < 0.001  # type: ignore[arg-type]
    assert abs(float(exif["gps_longitude"]) - (-122.416667)) < 0.001  # type: ignore[arg-type]


def test_parser_returns_empty_on_non_exif() -> None:
    assert parse_exif_from_app1(b"not exif") == {}
    assert parse_exif_from_app1(b"Exif\x00\x00garbage") == {}


def test_inspect_flags_photo_location_as_warning() -> None:
    artifact = load_bytes(build_jpeg_with_gps(), path=Path("holiday.jpg"))
    report, _ = analyze(artifact)
    loc = [f for f in report.inspection.findings if f.category == "photo_location"]
    assert len(loc) == 1
    assert loc[0].severity.value == "warning"
    assert "gps_latitude" in loc[0].details
    assert "strip_image_metadata" in loc[0].removable_by


def test_jpeg_without_exif_has_no_location_finding() -> None:
    artifact = load_bytes(build_jpeg(), path=Path("plain.jpg"))
    report, _ = analyze(artifact)
    cats = {f.category for f in report.inspection.findings}
    assert "photo_location" not in cats
    assert "photo_exif" not in cats


def test_cleaning_removes_the_location() -> None:
    artifact = load_bytes(build_jpeg_with_gps(), path=Path("holiday.jpg"))
    report, output = analyze(artifact, options=TransformOptions())
    assert report.transformation.accepted is True
    # re-inspect the cleaned bytes: no EXIF, no location finding
    cleaned = load_bytes(output, path=Path("holiday.jpg"))
    report2, _ = analyze(cleaned)
    cats = {f.category for f in report2.inspection.findings}
    assert "photo_location" not in cats
