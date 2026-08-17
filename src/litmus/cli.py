"""Command-line interface.

Exit codes (stable, CI-suitable):

* ``0`` success, nothing at or above the ``--fail-on`` threshold
* ``1`` findings at or above the threshold, or a rejected transformation
* ``2`` usage error, unreadable input, or unknown option
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

from .artifact import Artifact, ArtifactError, load_path, walk
from .io import SafeWriteError, safe_write
from .model import TOOL_VERSION, ArtifactKind, BatchReport, Report, Severity
from .pipeline import TransformOptions, analyze
from .providers import capabilities as provider_capabilities
from .reporting import render_batch, render_capabilities, render_report
from .transform import PROFILES, TRANSFORMS
from .validate import DEFAULT_MIN_LEXICAL_SIMILARITY, validate_text

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

_SEVERITY_ORDER = {Severity.INFO: 0, Severity.NOTICE: 1, Severity.WARNING: 2}

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "AI provenance inspector and quality-preserving transformation system. "
        "Runs entirely locally; no artifact leaves this machine."
    ),
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"litmus {TOOL_VERSION}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """AI provenance inspector and quality-preserving transformation system."""


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if not path.exists():
            typer.echo(f"error: no such path: {path}", err=True)
            raise typer.Exit(EXIT_ERROR)
        files.extend(walk(path))
    return files


def _load(path: Path) -> Artifact:
    return load_path(path)


def _threshold_hit(report: Report, fail_on: str) -> bool:
    if fail_on == "never":
        return False
    try:
        minimum = _SEVERITY_ORDER[Severity(fail_on)]
    except ValueError:
        typer.echo(f"error: invalid --fail-on value: {fail_on}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    return any(_SEVERITY_ORDER[f.severity] >= minimum for f in report.inspection.findings)


def _emit(batch: BatchReport, as_json: bool, verbose: bool) -> None:
    if as_json:
        payload = batch if len(batch.reports) != 1 or batch.errors else batch.reports[0]
        typer.echo(payload.model_dump_json(indent=2))
    else:
        typer.echo(render_batch(batch, verbose=verbose))


@app.command("inspect")
def inspect_cmd(
    paths: list[Path] = typer.Argument(..., help="Files or directories to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Emit the machine-readable report."),
    fail_on: str = typer.Option(
        "never",
        "--fail-on",
        help="Exit 1 when a finding of this severity or higher exists: info|notice|warning|never.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Include locations and details."),
) -> None:
    """Inspect artifacts for locally detectable provenance signals."""
    _configure_logging(verbose)
    batch = BatchReport()
    for path in _collect(paths):
        try:
            report, _ = analyze(_load(path))
        except ArtifactError as exc:
            batch.errors.append({"path": str(path), "error": str(exc)})
            continue
        batch.reports.append(report)

    _emit(batch, json_output, verbose)
    if batch.errors:
        raise typer.Exit(EXIT_ERROR)
    if any(_threshold_hit(r, fail_on) for r in batch.reports):
        raise typer.Exit(EXIT_FINDINGS)


@app.command("transform")
def transform_cmd(
    paths: list[Path] = typer.Argument(..., help="Files or directories to transform."),
    profile: str = typer.Option(
        "standard", "--profile", help=f"One of: {', '.join(sorted(PROFILES))}."
    ),
    operation: list[str] | None = typer.Option(
        None, "--op", help="Explicit operation id; repeatable. Overrides --profile."
    ),
    in_place: bool = typer.Option(False, "--in-place", help="Rewrite the files on disk."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write the result here. Single input only."
    ),
    backup: bool = typer.Option(
        False, "--backup", help="Write a .bak copy before rewriting in place."
    ),
    force: bool = typer.Option(
        False, "--force", help="Write transformed code even when preservation was not proven."
    ),
    min_similarity: float = typer.Option(
        DEFAULT_MIN_LEXICAL_SIMILARITY,
        "--min-similarity",
        help="Reject the transformation below this lexical similarity.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the machine-readable report."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Apply validated, deterministic normalization.

    Nothing is written unless validation passed. By default the result is
    printed to stdout for a single file; use --in-place or --output to persist.
    """
    _configure_logging(verbose)
    files = _collect(paths)
    if output is not None and len(files) != 1:
        typer.echo("error: --output requires exactly one input file", err=True)
        raise typer.Exit(EXIT_ERROR)
    if output is not None and in_place:
        typer.echo("error: --output and --in-place are mutually exclusive", err=True)
        raise typer.Exit(EXIT_ERROR)

    options = TransformOptions(
        profile=profile,
        operations=list(operation) if operation else None,
        min_lexical_similarity=min_similarity,
        force_code=force,
    )

    batch = BatchReport()
    rejected = False
    for path in files:
        try:
            art = _load(path)
            report, data = analyze(art, options=options)
        except ArtifactError as exc:
            batch.errors.append({"path": str(path), "error": str(exc)})
            continue
        except KeyError as exc:
            typer.echo(f"error: {exc.args[0]}", err=True)
            raise typer.Exit(EXIT_ERROR) from None
        batch.reports.append(report)

        if not report.transformation.accepted:
            rejected = True
            continue
        try:
            if in_place:
                if data != art.data:
                    safe_write(path, data, backup=backup)
            elif output is not None:
                safe_write(output, data, backup=backup)
            elif not json_output and len(files) == 1:
                sys.stdout.buffer.write(data)
                return
        except SafeWriteError as exc:
            batch.errors.append({"path": str(path), "error": str(exc)})

    _emit(batch, json_output, verbose)
    if batch.errors:
        raise typer.Exit(EXIT_ERROR)
    if rejected:
        raise typer.Exit(EXIT_FINDINGS)


@app.command("validate")
def validate_cmd(
    before: Path = typer.Argument(..., help="Original text artifact."),
    after: Path = typer.Argument(..., help="Transformed text artifact."),
    min_similarity: float = typer.Option(DEFAULT_MIN_LEXICAL_SIMILARITY, "--min-similarity"),
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Validate an existing before/after pair produced by any means."""
    _configure_logging(verbose)
    try:
        a, b = _load(before), _load(after)
    except ArtifactError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    if a.text is None or b.text is None:
        typer.echo("error: both inputs must be decodable UTF-8 text", err=True)
        raise typer.Exit(EXIT_ERROR)

    result = validate_text(a.text, b.text, min_lexical_similarity=min_similarity)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"validation all_passed={result.all_passed}")
        for check in result.checks:
            state = {True: "pass", False: "FAIL", None: "n/a "}[check.passed]
            typer.echo(f"   [{state}] {check.name}: {check.detail}")
    if result.all_passed is False:
        raise typer.Exit(EXIT_FINDINGS)


@app.command("capabilities")
def capabilities_cmd(
    provider: str | None = typer.Option(None, "--provider", help="Filter by provider."),
    kind: str | None = typer.Option(
        None, "--kind", help="Filter by artifact kind: text|source_code|binary."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show what each provider marks and whether anyone else can verify it."""
    artifact_kind = None
    if kind is not None:
        try:
            artifact_kind = ArtifactKind(kind)
        except ValueError:
            typer.echo(f"error: invalid --kind: {kind}", err=True)
            raise typer.Exit(EXIT_ERROR) from None
    rows = provider_capabilities(provider, artifact_kind)
    if json_output:
        typer.echo(json.dumps([r.model_dump(mode="json") for r in rows], indent=2))
    else:
        typer.echo(render_capabilities(rows))


@app.command("operations")
def operations_cmd(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List the available transformation operations and profiles."""
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "operations": {
                        t.id: {
                            "description": t.description,
                            "semantics_preserving": t.semantics_preserving,
                            "note": t.note,
                        }
                        for t in TRANSFORMS.values()
                    },
                    "profiles": PROFILES,
                },
                indent=2,
            )
        )
        return
    typer.echo("operations")
    for t in TRANSFORMS.values():
        typer.echo(f"   {t.id}: {t.description}")
        if t.note:
            typer.echo(f"      note: {t.note}")
    typer.echo("")
    typer.echo("profiles")
    for name, ops in PROFILES.items():
        typer.echo(f"   {name}: {', '.join(ops)}")


@app.command("report")
def report_cmd(
    path: Path = typer.Argument(..., help="A JSON report previously written with --json."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Render a saved JSON report as human-readable text."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"error: cannot read report: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    try:
        if "reports" in payload:
            typer.echo(render_batch(BatchReport.model_validate(payload), verbose=verbose))
        else:
            typer.echo(render_report(Report.model_validate(payload), verbose=verbose))
    except Exception as exc:  # noqa: BLE001 - a malformed report is a user error
        typer.echo(f"error: not a valid report: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address; loopback by default."),
    port: int = typer.Option(8765, "--port", help="Port to listen on."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open a browser."),
) -> None:
    """Start a local drag-and-drop web UI. Files are analysed in memory; nothing is uploaded."""
    from .server import serve

    serve(host=host, port=port, open_browser=not no_browser)


def main() -> None:
    app()


__all__ = ["app", "main"]
