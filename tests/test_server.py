from __future__ import annotations

import base64
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from conftest import build_png
from litmus.server import _Handler, build_result

# --- pure core logic (no sockets) ------------------------------------------


def test_build_result_inspect_reports_findings() -> None:
    result = build_result("note.txt", "hi\u200bthere".encode(), mode="inspect")
    cats = [f["category"] for f in result["report"]["inspection"]["findings"]]
    assert "zero_width" in cats
    assert "output_base64" not in result  # inspect never returns bytes


def test_build_result_clean_returns_downloadable_output() -> None:
    result = build_result("note.txt", "hi\u200bthere".encode(), mode="clean")
    assert result["report"]["transformation"]["accepted"] is True
    decoded = base64.b64decode(result["output_base64"]).decode("utf-8")
    assert decoded == "hithere\n"  # standard profile also ensures a final newline
    assert result["output_name"] == "note.txt"


def test_build_result_clean_noop_offers_no_download() -> None:
    result = build_result("clean.txt", b"already clean\n", mode="clean")
    # Nothing changed, so there is nothing to download.
    assert "output_base64" not in result


def test_build_result_clean_image_strips_metadata() -> None:
    png = build_png(text={"Author": "x"}, c2pa=True)
    result = build_result("a.png", png, mode="clean")
    assert result["report"]["transformation"]["accepted"] is True
    out = base64.b64decode(result["output_base64"])
    assert b"Author" not in out and len(out) < len(png)


def test_build_result_clean_code_refused_stays_report_only() -> None:
    result = build_result("a.py", 'x = "a\u200bb"\n'.encode(), mode="clean")
    assert result["report"]["transformation"]["accepted"] is False
    assert "output_base64" not in result


# --- one real HTTP round-trip ----------------------------------------------


def test_http_round_trip() -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # index page
        with urllib.request.urlopen(f"{base}/", timeout=5) as resp:  # noqa: S310 - loopback only
            assert resp.status == 200
            assert b"litmus" in resp.read()
        # analyze endpoint
        body = json.dumps(
            {
                "name": "n.txt",
                "data_base64": base64.b64encode("a\u200bb".encode()).decode(),
                "mode": "clean",
            }
        ).encode()
        req = urllib.request.Request(
            f"{base}/api/analyze", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback only
            payload = json.loads(resp.read())
        assert base64.b64decode(payload["output_base64"]).decode() == "ab\n"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_bad_json_is_a_400() -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analyze",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)  # noqa: S310 - loopback only
            raised = False
        except urllib.error.HTTPError as exc:
            raised = exc.code == 400
        assert raised
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
