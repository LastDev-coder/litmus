"""Human-readable rendering of reports.

Plain text on purpose: no colour libraries, no terminal detection, so piped
output and terminal output are identical and diffable.
"""

from __future__ import annotations

from .model import BatchReport, Report, Severity
from .providers import Capability

_SEVERITY_MARK = {Severity.INFO: "  ", Severity.NOTICE: " *", Severity.WARNING: " !"}

DISCLAIMER = (
    "No finding in this report establishes authorship, and the absence of a finding "
    "does not establish human authorship. Signals that no public detector can check "
    "are listed under 'unknown signals'."
)


def render_report(report: Report, *, verbose: bool = False, include_disclaimer: bool = True) -> str:
    a = report.artifact
    lines: list[str] = []
    lines.append(f"artifact   {a.path or '<stdin>'}")
    lines.append(
        f"           kind={a.kind.value}"
        + (f" language={a.language}" if a.language else "")
        + (f" media_type={a.media_type}" if a.media_type else "")
    )
    lines.append(f"           sha256={a.sha256}  size={a.size_bytes}B")

    lines.append("")
    if report.inspection.findings:
        lines.append(f"findings ({len(report.inspection.findings)})")
        for f in report.inspection.findings:
            mark = _SEVERITY_MARK[f.severity]
            lines.append(f"{mark} [{f.evidence_class.value}] {f.category}: {f.summary}")
            if f.locations and verbose:
                for loc in f.locations[:10]:
                    where = f"{loc.line}:{loc.column}" if loc.line else f"@{loc.offset}"
                    lines.append(f"      {where}  {loc.excerpt or ''}".rstrip())
                if len(f.locations) > 10:
                    lines.append(f"      ... {len(f.locations) - 10} more")
            if f.details and verbose:
                for key, value in f.details.items():
                    lines.append(f"      {key}: {value}")
            if f.removable_by:
                lines.append(f"      removable by: {', '.join(f.removable_by)}")
    else:
        lines.append("findings   none")

    if verbose:
        skipped = [i for i in report.inspection.inspectors if not i.ran]
        if skipped:
            lines.append("")
            lines.append("inspectors not run")
            for status in skipped:
                lines.append(f"   {status.name}: {status.reason}")

    prov = report.inspection.provenance
    lines.append("")
    lines.append(f"provenance confidence={prov.confidence.value}")
    for signal in prov.unknown_signals:
        lines.append(f"   unknown signal: {signal}")
    for note in prov.notes:
        lines.append(f"   note: {note}")

    tr = report.transformation
    if tr.performed or tr.rejected_reason:
        lines.append("")
        applied = [op for op in tr.operations if op.applied]
        lines.append(f"transform  performed={tr.performed} accepted={tr.accepted}")
        if tr.rejected_reason:
            lines.append(f"   rejected: {tr.rejected_reason}")
        for op in applied:
            lines.append(f"   applied {op.operation} ({op.changes} char(s)): {op.description}")
            if op_note := op.details.get("note"):
                lines.append(f"      note: {op_note!s}")
        if tr.performed and not applied:
            lines.append("   no operation changed the content")
        if tr.output_sha256:
            lines.append(f"   output sha256={tr.output_sha256} size={tr.output_size_bytes}B")

    vr = report.validation
    if vr.performed:
        lines.append("")
        lines.append(f"validation all_passed={vr.all_passed}")
        for check in vr.checks:
            state = {True: "pass", False: "FAIL", None: "n/a "}[check.passed]
            lines.append(f"   [{state}] {check.name}: {check.detail}")

    if include_disclaimer:
        lines.append("")
        lines.append(DISCLAIMER)
    return "\n".join(lines)


def render_batch(batch: BatchReport, *, verbose: bool = False) -> str:
    """Render a batch.

    For a multi-artifact scan, clean artifacts are summarised rather than
    printed in full: a per-file repetition of the same provenance caveats
    buries the artifacts that actually have findings. ``--verbose`` prints
    everything. Single-artifact output is always shown in full.
    """
    single = len(batch.reports) == 1 and not batch.errors
    shown = (
        batch.reports
        if single or verbose
        else [r for r in batch.reports if r.has_findings or r.transformation.performed]
    )
    hidden = len(batch.reports) - len(shown)

    blocks = [render_report(r, verbose=verbose, include_disclaimer=single) for r in shown]
    for err in batch.errors:
        blocks.append(f"error      {err.get('path', '?')}: {err.get('error', '')}")

    with_findings = sum(1 for r in batch.reports if r.has_findings)
    summary = [
        f"summary    {len(batch.reports)} artifact(s), {with_findings} with findings, "
        f"{len(batch.errors)} error(s)"
    ]
    if hidden:
        summary.append(f"           {hidden} clean artifact(s) not shown; use --verbose")
    if not single:
        summary.append("")
        summary.append(DISCLAIMER)
    blocks.append("\n".join(summary))
    return "\n\n".join(blocks)


def render_capabilities(rows: list[Capability]) -> str:
    lines = [
        "Provider capability matrix. Every row states whether the signal can actually",
        "be checked by anyone outside the provider. Source URLs back CONFIRMED rows.",
        "",
    ]
    for row in rows:
        lines.append(f"{row.provider}/{row.surface}  [{row.artifact_kind.value}]  {row.signal}")
        marked = {True: "yes", False: "no", None: "unknown"}[row.marked]
        lines.append(
            f"   class={row.evidence_class.value}  marked={marked}  "
            f"detectability={row.detectability.value}  evidence={row.label.value}"
        )
        if row.notes:
            lines.append(f"   {row.notes}")
        if row.source:
            lines.append(f"   source: {row.source}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
