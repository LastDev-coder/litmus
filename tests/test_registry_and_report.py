"""Tests that enforce the project's research-integrity rules as code."""

from __future__ import annotations

import json
from pathlib import Path

from litmus.artifact import load_bytes
from litmus.detectors import available_detectors
from litmus.model import ArtifactKind, Confidence, EvidenceLabel, Report
from litmus.pipeline import analyze
from litmus.providers import CAPABILITIES, capabilities, undetectable_signals
from litmus.reporting import render_report

_NAMED_PROVIDERS = {"anthropic", "openai"}


def test_confirmed_provider_claims_all_cite_a_source() -> None:
    for row in CAPABILITIES:
        if row.provider in _NAMED_PROVIDERS and row.label is EvidenceLabel.CONFIRMED:
            assert row.source, f"{row.provider}/{row.signal} claims CONFIRMED with no source"
            assert row.source.startswith("https://")


def test_claude_text_watermark_is_not_claimed_detectable() -> None:
    rows = [
        r
        for r in capabilities("anthropic", ArtifactKind.TEXT)
        if r.signal == "claude_text_watermark"
    ]
    assert rows, "the Claude text watermark must be represented in the matrix"
    for row in rows:
        assert row.detectability.value == "announced_not_available"


def test_no_detectors_are_shipped() -> None:
    # Shipping a stub detector would fabricate results. See detectors/base.py.
    assert available_detectors() == []


def test_undetectable_signals_are_surfaced_for_text() -> None:
    signals = {row.signal for row in undetectable_signals(ArtifactKind.TEXT)}
    assert "claude_text_watermark" in signals


def test_report_never_asserts_authorship(clean_text: str) -> None:
    artifact = load_bytes(clean_text.encode(), path=Path("a.md"))
    report, _ = analyze(artifact)
    rendered = render_report(report, verbose=True).lower()
    for forbidden in (
        "guaranteed",
        "100% human",
        "untraceable",
        "undetectable",
        "human-written",
        "permanent watermark removal",
    ):
        assert forbidden not in rendered


def test_clean_artifact_reports_insufficient_evidence(clean_text: str) -> None:
    artifact = load_bytes(clean_text.encode(), path=Path("a.md"))
    report, _ = analyze(artifact)
    assert report.inspection.provenance.confidence is Confidence.INSUFFICIENT_EVIDENCE
    assert report.inspection.provenance.known_signals_detected == []
    assert report.inspection.provenance.unknown_signals


def test_skipped_inspectors_are_recorded(clean_text: str) -> None:
    artifact = load_bytes(clean_text.encode(), path=Path("a.md"))
    report, _ = analyze(artifact)
    names = {status.name for status in report.inspection.inspectors}
    assert names == {"unicode", "text_markers", "file_metadata", "office_metadata", "c2pa"}
    for status in report.inspection.inspectors:
        assert status.ran or status.reason


def test_report_round_trips_through_json(dirty_text: str) -> None:
    artifact = load_bytes(dirty_text.encode(), path=Path("a.md"))
    report, _ = analyze(artifact)
    payload = json.loads(report.model_dump_json())
    assert Report.model_validate(payload) == report
    assert payload["schema_version"] == "1.0"
    assert payload["artifact"]["sha256"] == artifact.ref.sha256


def test_html_comments_are_reported_in_markdown_but_not_code() -> None:
    md = load_bytes(b"text <!-- hidden note --> more\n", path=Path("a.md"))
    py = load_bytes(b"x = '<!-- not a marker -->'\n", path=Path("a.py"))
    md_report, _ = analyze(md)
    py_report, _ = analyze(py)
    assert any(f.category == "markup_comment" for f in md_report.inspection.findings)
    assert not any(f.category == "markup_comment" for f in py_report.inspection.findings)
