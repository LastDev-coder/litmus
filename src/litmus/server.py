"""A fully-local web UI for drag-and-drop inspection and cleaning.

Design constraints that follow from the project's privacy stance (brief §14):

* **Standard library only.** No web framework, so the base install stays
  dependency-light and has nothing network-capable beyond this opt-in server.
* **Loopback by default.** Binds ``127.0.0.1``; a non-loopback host must be
  requested explicitly and prints a warning.
* **In-memory only.** Uploaded bytes are analysed in RAM and never written to
  disk by the server. The browser downloads the cleaned result itself.

The request logic lives in ``build_result`` as a pure function so it can be
unit-tested without sockets; the HTTP handler is a thin shell over it.
"""

from __future__ import annotations

import base64
import contextlib
import errno
import json
import logging
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .artifact import load_bytes
from .model import Report
from .pipeline import TransformOptions, analyze, inspect
from .web_ui import INDEX_HTML

log = logging.getLogger("litmus.server")

#: Upload ceiling for the browser path. Smaller than the CLI's file cap because
#: base64 in a JSON body is memory-heavy and a browser tool is interactive.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024


def build_result(
    name: str,
    data: bytes,
    *,
    mode: str,
    profile: str = "standard",
    force: bool = False,
) -> dict[str, Any]:
    """Analyse an uploaded artifact. Pure function; no I/O, no globals.

    ``mode`` is ``"inspect"`` (report only) or ``"clean"`` (transform too).
    """
    artifact = load_bytes(data, path=Path(name) if name else None)

    if mode == "clean":
        options = TransformOptions(profile=profile, force_code=force)
        report, output = analyze(artifact, options=options)
        result: dict[str, Any] = {"report": report.model_dump(mode="json")}
        if report.transformation.accepted and output != data:
            result["output_base64"] = base64.b64encode(output).decode("ascii")
            result["output_name"] = name or "cleaned"
        return result

    report = Report(artifact=artifact.ref, inspection=inspect(artifact))
    return {"report": report.model_dump(mode="json")}


class _Handler(BaseHTTPRequestHandler):
    # Keep response headers quiet: no tool version, no Python version.
    server_version = "litmus"
    sys_version = ""

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "img-src data:; connect-src 'self'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter, to our logger
        log.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if self.path != "/api/analyze":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > MAX_UPLOAD_BYTES:
            self._send_json(413, {"error": f"file exceeds {MAX_UPLOAD_BYTES} byte limit"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            data = base64.b64decode(payload["data_base64"])
            if len(data) > MAX_UPLOAD_BYTES:
                self._send_json(413, {"error": "file too large"})
                return
            result = build_result(
                str(payload.get("name", "")),
                data,
                mode=str(payload.get("mode", "inspect")),
                profile=str(payload.get("profile", "standard")),
                force=bool(payload.get("force", False)),
            )
        except (KeyError, ValueError, TypeError) as exc:
            self._send_json(400, {"error": f"{type(exc).__name__}: {exc}"})
            return
        except Exception as exc:  # noqa: BLE001 - a bad upload must not kill the server
            log.exception("analyze failed")
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(200, result)


#: How many consecutive ports to try before giving up, starting at the one
#: requested. Keeps auto-selection bounded and deterministic.
_PORT_PROBE_LIMIT = 20


def _bind_free_port(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    """Bind to ``port``, or the next free port after it, and return the server.

    A busy port is a normal situation (another copy is already running, or an
    unrelated service holds it), so litmus steps to the next free port instead
    of crashing. Raises ``SystemExit`` with a friendly message if a whole band
    of ports is occupied.
    """
    for candidate in range(port, port + _PORT_PROBE_LIMIT):
        try:
            return ThreadingHTTPServer((host, candidate), _Handler), candidate
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                continue  # try the next port
            raise SystemExit(f"litmus :: could not start the web UI: {exc}") from exc
    raise SystemExit(
        f"litmus :: ports {port}-{port + _PORT_PROBE_LIMIT - 1} are all in use. "
        f"Free one up, or choose another with --port."
    )


def serve(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> None:
    """Start the local server. Blocks until interrupted."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "binding to %s exposes this tool beyond your machine; it processes files "
            "locally but has no authentication",
            host,
        )
    httpd, port = _bind_free_port(host, port)
    url = f"http://{host}:{port}/"
    print(f"litmus web UI at {url}  (Ctrl-C to stop; nothing is uploaded off this machine)")
    if open_browser:
        # A headless box has no browser; failing to open one is not fatal.
        with contextlib.suppress(Exception):
            webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
