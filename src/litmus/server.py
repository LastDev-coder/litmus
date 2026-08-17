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
from .transform import PROFILES

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


# User-facing names for the cleaning levels. The wire value stays the profile
# id; only the label is friendly.
_PROFILE_LABELS = {
    "minimal": "Minimal — invisible characters only",
    "standard": "Standard (recommended)",
    "tidy": "Tidy — also neaten spacing",
    "code": "Code-aware — also remove unused Python imports",
}
_PROFILE_OPTIONS = "".join(
    f'<option value="{p}"{" selected" if p == "standard" else ""}>'
    f"{_PROFILE_LABELS.get(p, p.title())}</option>"
    for p in PROFILES
)

# The web UI. Deliberately self-contained (inline CSS/JS, no external fetches)
# so it satisfies the page's strict CSP and the project's local-only stance.
# Aesthetic: a warm "forensic lab" — dark, dimensional, friendly. All result
# copy is written for non-technical readers; raw identifiers stay available
# in small print so nothing is hidden, only translated.
INDEX_HTML = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>litmus</title>
<style>
:root{
  --bg:#0a0c11; --panel:#10141c; --panel-2:#141a24; --raise:#181f2b;
  --ink:#eaeff6; --dim:#93a0b3; --faint:#5c6879; --line:#1d2532; --line-2:#2b3648;
  --signal:#ffb020; --signal-soft:rgba(255,176,32,.13);
  --good:#3ddc97;   --good-soft:rgba(61,220,151,.12);
  --bad:#ff6b6b;    --bad-soft:rgba(255,107,107,.11);
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --round:ui-rounded,"SF Pro Rounded","Hiragino Maru Gothic ProN","Trebuchet MS",var(--sans);
  --radius:18px;
  --card-shadow:0 1px 0 rgba(255,255,255,.045) inset, 0 -1px 0 rgba(0,0,0,.35) inset,
    0 12px 34px rgba(0,0,0,.42), 0 2px 8px rgba(0,0,0,.3);
  --card-shadow-hover:0 1px 0 rgba(255,255,255,.06) inset, 0 -1px 0 rgba(0,0,0,.35) inset,
    0 20px 48px rgba(0,0,0,.5), 0 3px 10px rgba(0,0,0,.32);
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased;
  background-image:
    linear-gradient(var(--line) 1px,transparent 1px),
    linear-gradient(90deg,var(--line) 1px,transparent 1px);
  background-size:44px 44px;background-position:center;
}
body::before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(60% 40% at 50% 0%,rgba(255,176,32,.05),transparent 70%),
    radial-gradient(120% 80% at 50% -10%,transparent 40%,var(--bg) 100%);
}
.wrap{position:relative;z-index:1;max-width:820px;margin:0 auto;padding:42px 22px 90px}
header{display:flex;align-items:baseline;gap:14px;margin-bottom:6px}
.brand{font-family:var(--mono);font-weight:600;font-size:15px;letter-spacing:.34em;
  text-transform:uppercase;color:var(--ink)}
.brand b{color:var(--signal);font-weight:600}
.ver{font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.1em}
.tagline{color:var(--dim);margin:2px 0 30px;max-width:62ch}
.tagline b{color:var(--ink);font-weight:600}

/* ---- scanner (upload) ---- */
.scanner{position:relative;border:1px solid var(--line-2);border-radius:var(--radius);
  background:linear-gradient(180deg,var(--panel),var(--panel-2));overflow:hidden;
  box-shadow:var(--card-shadow)}
#drop{position:relative;padding:50px 28px;text-align:center;cursor:pointer;
  transition:background .18s ease, box-shadow .18s ease;outline:none}
#drop:focus-visible{box-shadow:inset 0 0 0 2px var(--signal)}
#drop .eye{display:block;margin:0 auto 16px;width:46px;height:46px;color:var(--faint);
  transition:color .2s,transform .25s cubic-bezier(.2,.7,.2,1.4)}
#drop:hover .eye{color:var(--dim);transform:translateY(-2px)}
#drop .big{font-family:var(--round);font-size:16px;color:var(--ink)}
#drop .big u{text-decoration:none;color:var(--signal);border-bottom:1px dashed var(--signal)}
#drop .hint{display:block;margin-top:8px;font-size:12.5px;color:var(--faint);
  font-family:var(--mono);letter-spacing:.04em}
.scanner.over #drop{background:var(--signal-soft)}
.scanner.over #drop .eye{color:var(--signal);transform:scale(1.1)}
.scanner.over::after,.scanner.busy::after{content:"";position:absolute;left:0;right:0;height:2px;top:0;
  background:linear-gradient(90deg,transparent,var(--signal),transparent);
  animation:scan 1.1s linear infinite;z-index:2}
@keyframes scan{0%{top:0;opacity:0}10%{opacity:1}90%{opacity:1}100%{top:100%;opacity:0}}

.controls{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;
  padding:16px 20px;border-top:1px solid var(--line);background:var(--panel)}
.seg{display:inline-flex;border:1px solid var(--line-2);border-radius:10px;overflow:hidden;
  box-shadow:0 1px 0 rgba(255,255,255,.04) inset}
.seg label{padding:7px 16px;font-family:var(--round);font-size:13px;
  color:var(--dim);cursor:pointer;transition:.15s;user-select:none}
.seg input{position:absolute;opacity:0;pointer-events:none}
.seg label:has(input:checked){background:var(--signal);color:#0a0c11;font-weight:700}
.opt{display:inline-flex;gap:7px;align-items:center;font-size:13px;color:var(--dim)}
.opt select{font-family:var(--sans);font-size:12.5px;padding:6px 8px;border-radius:8px;
  border:1px solid var(--line-2);background:var(--panel-2);color:var(--ink)}
#run{margin-left:auto;font-family:var(--round);font-size:13.5px;letter-spacing:.02em;
  background:linear-gradient(180deg,#ffc14d,var(--signal));color:#0a0c11;font-weight:700;
  border:0;border-radius:10px;padding:10px 22px;cursor:pointer;
  box-shadow:0 1px 0 rgba(255,255,255,.35) inset, 0 6px 16px rgba(255,176,32,.25);
  transition:transform .12s ease, box-shadow .12s ease, filter .12s}
#run:hover:not(:disabled){filter:brightness(1.06);transform:translateY(-1px);
  box-shadow:0 1px 0 rgba(255,255,255,.35) inset, 0 10px 22px rgba(255,176,32,.32)}
#run:active:not(:disabled){transform:translateY(1px);box-shadow:0 1px 0 rgba(255,255,255,.2) inset,0 3px 8px rgba(255,176,32,.2)}
#run:disabled{opacity:.35;cursor:not-allowed}
#chosen{font-family:var(--mono);font-size:12px;color:var(--faint);padding:0 20px 14px;background:var(--panel)}
#chosen:not(:empty){padding-top:2px}

/* ---- results ---- */
#out{margin-top:28px;display:grid;gap:18px}
.panel{border:1px solid var(--line-2);border-radius:var(--radius);background:var(--panel);
  overflow:hidden;box-shadow:var(--card-shadow);
  transition:transform .2s cubic-bezier(.2,.7,.2,1), box-shadow .2s;
  animation:rise .45s cubic-bezier(.2,.7,.2,1) both}
.panel:hover{transform:translateY(-2px);box-shadow:var(--card-shadow-hover)}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

/* verdict hero */
.hero{display:flex;gap:20px;align-items:center;padding:26px 26px;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;top:0;left:-60%;width:40%;height:100%;
  background:linear-gradient(105deg,transparent,rgba(255,255,255,.045),transparent);
  animation:sheen 1.6s .35s cubic-bezier(.2,.7,.3,1) both}
@keyframes sheen{to{left:120%}}
.orb{flex:0 0 auto;width:62px;height:62px;border-radius:50%;display:grid;place-items:center;position:relative}
.orb svg{width:30px;height:30px;position:relative;z-index:1}
.orb::before{content:"";position:absolute;inset:0;border-radius:50%;
  background:radial-gradient(circle at 32% 28%,rgba(255,255,255,.5),transparent 42%),var(--orb-c,#2b3648);
  box-shadow:0 8px 20px var(--orb-glow,rgba(0,0,0,.4)), 0 2px 4px rgba(0,0,0,.4),
    0 1px 1px rgba(255,255,255,.25) inset, 0 -6px 12px rgba(0,0,0,.28) inset}
.hero.ok .orb{--orb-c:linear-gradient(180deg,#3ddc97,#1fa76c);--orb-glow:rgba(61,220,151,.35)}
.hero.warn .orb{--orb-c:linear-gradient(180deg,#ffc14d,#e09612);--orb-glow:rgba(255,176,32,.35)}
.hero.no .orb{--orb-c:linear-gradient(180deg,#ff8a8a,#d84a4a);--orb-glow:rgba(255,107,107,.3)}
.hero.ok .orb::after{content:"";position:absolute;inset:-6px;border-radius:50%;
  border:2px solid var(--good);opacity:0;animation:pulse 1s .3s ease-out 2}
@keyframes pulse{0%{transform:scale(.8);opacity:.8}100%{transform:scale(1.5);opacity:0}}
.hero h1{margin:0 0 4px;font-family:var(--round);font-size:22px;line-height:1.2;font-weight:700}
.hero p{margin:0;color:var(--dim);font-size:14px;max-width:52ch}
.hero .kicker{font-family:var(--mono);font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--faint);display:block;margin-bottom:6px}
.hero .num{color:var(--signal);font-variant-numeric:tabular-nums}
.checkdraw{stroke-dasharray:26;stroke-dashoffset:26;animation:draw .5s .25s ease-out forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.heroCta{margin:0 26px 22px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.dl{display:inline-block;text-decoration:none}
.dl button{font-family:var(--round);font-size:14px;font-weight:700;letter-spacing:.02em;
  background:linear-gradient(180deg,#4ce8a6,#26bd7e);color:#07130d;border:0;border-radius:12px;
  padding:12px 22px;cursor:pointer;display:flex;gap:9px;align-items:center;
  box-shadow:0 1px 0 rgba(255,255,255,.4) inset, 0 8px 20px rgba(61,220,151,.28);
  transition:transform .12s, box-shadow .12s, filter .12s}
.dl button:hover{filter:brightness(1.05);transform:translateY(-1px)}
.dl button:active{transform:translateY(1px);box-shadow:0 1px 0 rgba(255,255,255,.25) inset,0 3px 8px rgba(61,220,151,.2)}
.ctaNote{color:var(--faint);font-size:12.5px}

/* findings */
.panel h2{margin:0;padding:14px 20px;font-family:var(--mono);font-size:11.5px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--dim);border-bottom:1px solid var(--line);
  display:flex;justify-content:space-between;align-items:center}
.panel h2 .count{color:var(--signal)}
.cards{padding:14px;display:grid;gap:10px}
.finding{border:1px solid var(--line);border-radius:13px;background:var(--panel-2);
  padding:14px 16px;animation:rise .45s both;transition:border-color .15s, transform .15s}
.finding:hover{border-color:var(--line-2);transform:translateY(-1px)}
.finding .top{display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.fico{flex:0 0 auto;width:34px;height:34px;border-radius:10px;display:grid;place-items:center;
  background:var(--raise);color:var(--signal);border:1px solid var(--line-2);
  box-shadow:0 1px 0 rgba(255,255,255,.05) inset, 0 3px 8px rgba(0,0,0,.3)}
.fico svg{width:17px;height:17px}
.ftitle{font-family:var(--round);font-size:15px;font-weight:700;color:var(--ink)}
.tag{margin-left:auto;font-family:var(--round);font-size:11px;font-weight:700;padding:3px 10px;
  border-radius:999px}
.tag.warning{background:var(--signal-soft);color:var(--signal)}
.tag.notice{background:rgba(147,160,179,.14);color:var(--dim)}
.tag.info{background:rgba(147,160,179,.10);color:var(--faint)}
.fbody{color:var(--dim);margin:7px 0 0;font-size:13.5px;line-height:1.5}
.floc{font-family:var(--mono);font-size:11px;color:var(--faint);margin-top:7px}
.payload{margin-top:10px;font-family:var(--mono);font-size:13px;background:var(--bad-soft);
  border:1px solid var(--bad);border-radius:9px;padding:9px 12px;color:var(--ink)}
.payload span{color:var(--bad);letter-spacing:.05em;text-transform:uppercase;font-size:10.5px;display:block;margin-bottom:3px}
.fix{display:flex;gap:7px;align-items:center;font-family:var(--round);font-size:12.5px;font-weight:600;
  color:var(--good);margin-top:9px}
.fix svg{width:13px;height:13px}
.rawid{font-family:var(--mono);font-size:10px;color:var(--faint);opacity:.7}

.allclear{display:flex;gap:14px;align-items:center;padding:22px 20px;color:var(--dim);font-size:14px}
.allclear svg{color:var(--good);flex:0 0 auto}

/* file strip + fine print */
.meta{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:13px;color:var(--dim);padding:14px 20px;align-items:baseline}
.meta b{color:var(--ink);font-weight:600;font-family:var(--round)}
.meta .fp{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-left:auto}
.notes{padding:14px 20px;color:var(--faint);font-size:12.5px;line-height:1.65}
.notes b{color:var(--dim)}
details.tech{margin-top:8px}
details.tech summary{cursor:pointer;font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.06em}
details.tech div{margin-top:6px;font-family:var(--mono);font-size:11.5px;color:var(--faint);line-height:1.6}
.working{padding:28px 20px;color:var(--dim);font-family:var(--round);font-size:14px}
.working::after{content:"";animation:dots 1.2s steps(4,end) infinite}
@keyframes dots{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:560px){.hero{flex-direction:column;text-align:center;align-items:center}.tag{margin-left:0}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="brand">lit<b>m</b>us</span>
    <span class="ver">100% local &middot; private</span>
  </header>
  <p class="tagline"><b>See what's hiding in your files.</b> Drop one in &mdash; litmus reveals
    invisible characters, hidden file info and content credentials, and can strip them out without
    changing anything you can see. Nothing ever leaves your computer.</p>

  <div class="scanner" id="scanner">
    <div id="drop" role="button" tabindex="0" aria-label="Choose or drop a file to analyse">
      <svg class="eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4">
        <path d="M1.5 12S5 5 12 5s10.5 7 10.5 7-3.5 7-10.5 7S1.5 12 1.5 12Z"/>
        <circle cx="12" cy="12" r="3.2"/>
      </svg>
      <span class="big">Drop a file or <u>browse</u></span>
      <span class="hint">text &middot; code &middot; png &middot; jpeg &middot; svg</span>
      <input id="file" type="file" hidden>
    </div>
    <div class="controls">
      <span class="seg">
        <label><input type="radio" name="mode" value="inspect" checked> Check</label>
        <label><input type="radio" name="mode" value="clean"> Clean</label>
      </span>
      <label class="opt">Cleaning level
        <select id="profile">__PROFILE_OPTIONS__</select>
      </label>
      <label class="opt" title="For source code: apply the clean-up even when litmus cannot verify the program is unchanged. Unverified results are clearly marked.">
        <input type="checkbox" id="force"> allow unverified <span style="color:var(--faint)">(code)</span>
      </label>
      <button id="run" disabled>Check file</button>
    </div>
    <div id="chosen"></div>
  </div>

  <div id="out"></div>
</div>
<script>
const $=(s)=>document.querySelector(s);
const drop=$("#drop"),fileInput=$("#file"),runBtn=$("#run"),out=$("#out"),scanner=$("#scanner");
let picked=null;
function fmtBytes(n){return n<1024?n+" B":n<1048576?(n/1024).toFixed(1)+" KB":(n/1048576).toFixed(1)+" MB"}
function choose(f){picked=f;$("#chosen").textContent=f?`> ${f.name}  ${fmtBytes(f.size)}`:"";runBtn.disabled=!f;}
document.querySelectorAll('input[name=mode]').forEach(el=>el.addEventListener("change",()=>{
  runBtn.textContent=document.querySelector('input[name=mode]:checked').value==="clean"?"Clean file":"Check file";
}));
drop.addEventListener("click",()=>fileInput.click());
drop.addEventListener("keydown",(e)=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();fileInput.click();}});
fileInput.addEventListener("change",(e)=>choose(e.target.files[0]));
["dragover","dragenter"].forEach(ev=>scanner.addEventListener(ev,(e)=>{e.preventDefault();scanner.classList.add("over");}));
["dragleave","drop"].forEach(ev=>scanner.addEventListener(ev,(e)=>{if(ev==="drop")e.preventDefault();scanner.classList.remove("over");}));
scanner.addEventListener("drop",(e)=>{e.preventDefault();scanner.classList.remove("over");if(e.dataTransfer.files[0])choose(e.dataTransfer.files[0]);});
function toBase64(buf){const b=new Uint8Array(buf);let s="";const c=0x8000;for(let i=0;i<b.length;i+=c)s+=String.fromCharCode.apply(null,b.subarray(i,i+c));return btoa(s);}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

/* ---- plain-language translations (raw ids stay visible in small print) ---- */
const ICONS={
  ghost:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3l18 18M10.6 5.1A9.8 9.8 0 0 1 12 5c7 0 10.5 7 10.5 7a17 17 0 0 1-3 3.9M6.6 6.6A16.8 16.8 0 0 0 1.5 12S5 19 12 19a9.9 9.9 0 0 0 5.4-1.6"/></svg>',
  text:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V5h16v2M9 20h6M12 5v15"/></svg>',
  tag:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1.2"/></svg>',
  badge:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="9" r="6"/><path d="m8.5 14.5-2 7 5.5-3 5.5 3-2-7"/></svg>'
};
const CATS={
  zero_width:{t:"Invisible characters",icon:"ghost",b:"Characters hidden between the letters that you can't see. They're sometimes used to secretly mark or track text."},
  unicode_tag_char:{t:"Hidden message characters",icon:"ghost",b:"Special invisible characters that can spell out a secret message inside ordinary-looking text."},
  bidi_control:{t:"Text-direction controls",icon:"ghost",b:"Hidden marks that can silently change the order text is displayed in."},
  exotic_space:{t:"Disguised spaces",icon:"ghost",b:"Spaces that look normal but are actually special characters — a common fingerprint of copy-pasted text."},
  other_invisible:{t:"Hidden formatting marks",icon:"ghost",b:"Invisible characters that don't change what you see on screen."},
  variation_selector:{t:"Invisible symbol modifiers",icon:"ghost",b:"Hidden marks that change how symbols display — and can also carry hidden data."},
  control_char:{t:"Machine control characters",icon:"ghost",b:"Old machine-instruction characters that don't belong in normal text."},
  byte_order_mark:{t:"Hidden file marker",icon:"ghost",b:"An invisible marker at the very start of the file."},
  mixed_script_word:{t:"Look-alike letters",icon:"text",b:"Letters from a different alphabet disguised as normal ones — the word looks right but isn't."},
  unicode_normalization:{t:"Non-standard letterforms",icon:"text",b:"Letters written in an unusual way that looks identical on screen."},
  mixed_line_endings:{t:"Mixed line breaks",icon:"text",b:"The file mixes two styles of line breaks — often a sign it was assembled from different tools."},
  markup_comment:{t:"Hidden comments",icon:"text",b:"Notes embedded in the file that don't show up when it's viewed normally."},
  c2pa_manifest:{t:"Content credentials",icon:"badge",b:"An embedded record of where this file came from — often added by AI tools or cameras. Removing it removes that record, not the picture."},
  png_metadata:{t:"Hidden image info",icon:"tag",b:"Extra information embedded in the image — software names, dates, descriptions — that isn't part of the picture itself."},
  jpeg_metadata:{t:"Hidden image info",icon:"tag",b:"Extra information embedded in the image — software names, dates, descriptions — that isn't part of the picture itself."},
  svg_metadata:{t:"Hidden image info",icon:"tag",b:"Extra information embedded in the graphic that isn't part of what it draws."},
  file_metadata:{t:"Hidden file info",icon:"tag",b:"Extra information embedded in the file that isn't part of its visible content."}
};
const SEV={warning:"Worth removing",notice:"Unusual",info:"Good to know"};
const KINDS={text:"Text",source_code:"Code",binary:"Image / binary"};

runBtn.addEventListener("click",async()=>{
  if(!picked)return;
  const mode=document.querySelector('input[name=mode]:checked').value;
  runBtn.disabled=true;scanner.classList.add("busy");
  out.innerHTML=`<div class="panel"><div class="working">${mode==="clean"?"Cleaning your file":"Reading your file"}</div></div>`;
  const buf=await picked.arrayBuffer();let res;
  try{
    res=await fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:picked.name,data_base64:toBase64(buf),mode,profile:$("#profile").value,force:$("#force").checked})});
  }catch(err){scanner.classList.remove("busy");out.innerHTML=heroCard("no","Something went wrong","We couldn't analyse this file. "+esc(err),"");runBtn.disabled=false;return;}
  const data=await res.json();runBtn.disabled=false;scanner.classList.remove("busy");
  if(!res.ok){out.innerHTML=heroCard("no","Something went wrong",esc(data.error||"Unknown error."),"");return;}
  render(data,mode);
});

const CHECK='<svg viewBox="0 0 24 24" fill="none" stroke="#07130d" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path class="checkdraw" d="M20 6 9 17l-5-5"/></svg>';
const SPARK='<svg viewBox="0 0 24 24" fill="none" stroke="#0a0c11" stroke-width="2.2" stroke-linecap="round"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/></svg>';
const STOP='<svg viewBox="0 0 24 24" fill="none" stroke="#140808" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.4v.2"/></svg>';

function heroCard(kind,title,body,extra,kicker){
  const icon=kind==="ok"?CHECK:kind==="warn"?SPARK:STOP;
  return `<div class="panel"><div class="hero ${kind}"><div class="orb">${icon}</div><div>`+
    (kicker?`<span class="kicker">${kicker}</span>`:"")+
    `<h1>${title}</h1><p>${body}</p></div></div>${extra||""}</div>`;
}

function friendlyReason(raw){
  const s=String(raw||"");
  if(s.includes("could not be proven")||s.includes("No structural validator"))
    return "This code is written in a language litmus can't double-check yet — and it never saves a change it can't verify. Your original is untouched.";
  if(s.includes("provably changed"))
    return "Removing the hidden characters would have changed how this code actually runs, so litmus stopped and kept your original exactly as it was.";
  if(s.includes("no longer parses"))
    return "The clean-up would have broken this file, so litmus refused and kept your original exactly as it was.";
  return "The result couldn't be verified as safe, so litmus kept your original exactly as it was.";
}

function render(data,mode){
  const r=data.report,a=r.artifact,f=r.inspection.findings||[];
  const t=r.transformation;
  let html="";

  /* 1 — verdict hero: the one thing to understand */
  if(mode==="clean"&&t&&t.performed){
    if(t.accepted&&data.output_base64){
      const proven=r.validation&&r.validation.all_passed===true;
      const cta=`<div class="heroCta"><a class="dl" href="data:application/octet-stream;base64,${data.output_base64}" download="${esc(data.output_name)}"><button>&#8595; Download your clean file</button></a><span class="ctaNote">Your original stays untouched on your computer.</span></div>`;
      if(proven)
        html+=heroCard("ok","Your file is clean","Litmus removed the hidden extras, then double-checked that everything you can see stayed exactly the same.",cta,"cleaned &amp; verified");
      else
        html+=heroCard("warn","Cleaned — please review","The clean-up was applied at your request, but litmus couldn't verify the result is unchanged. Give it a look before using it.",cta,"cleaned, not verified");
    }else if(t.accepted){
      html+=heroCard("ok","Nothing to clean","This file was already spotless — no hidden content to remove.","", "all clear");
    }else{
      const details=`<div class="notes"><details class="tech"><summary>technical details</summary><div>${esc(t.rejected_reason||"")}</div></details></div>`;
      html+=heroCard("no","Your file wasn't changed",friendlyReason(t.rejected_reason),details,"stopped for safety");
    }
  }else{
    if(f.length===0)
      html+=heroCard("ok","Nothing hidden here","Litmus checked for invisible characters, hidden info and content credentials, and found none it can detect.","","all clear");
    else{
      const worth=f.some(x=>x.severity==="warning");
      html+=heroCard("warn",`Found <span class="num">${f.length}</span> hidden ${f.length===1?"thing":"things"}`,
        (worth?"Some of it is worth removing. ":"Nothing alarming — just things you can't see. ")+
        "Switch to <b>Clean</b> and litmus will strip out what it can without touching anything visible.","","check complete");
    }
  }

  /* 2 — what we found, in plain words */
  if(f.length){
    html+=`<div class="panel"><h2>What's hiding in there <span class="count">${f.length}</span></h2><div class="cards">`;
    f.forEach((x,i)=>{
      const c=CATS[x.category]||{t:esc(String(x.category).replace(/_/g," ")),icon:"tag",b:esc(x.summary)};
      html+=`<div class="finding" style="animation-delay:${80+i*60}ms"><div class="top">`+
        `<span class="fico">${ICONS[c.icon]}</span><span class="ftitle">${c.t}</span>`+
        `<span class="tag ${esc(x.severity)}">${SEV[x.severity]||esc(x.severity)}</span></div>`+
        `<p class="fbody">${c.b}</p>`;
      if(x.locations&&x.locations[0]&&x.locations[0].line)
        html+=`<div class="floc">first seen at line ${x.locations[0].line}${x.count>1?" &middot; "+x.count+" in total":""}</div>`;
      if(x.details&&x.details.decoded_ascii_payload)
        html+=`<div class="payload"><span>hidden message we decoded</span>${esc(x.details.decoded_ascii_payload)}</div>`;
      if(x.removable_by&&x.removable_by.length)
        html+=`<div class="fix"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M20 6 9 17l-5-5"/></svg> litmus can remove this &mdash; use Clean</div>`;
      html+=`<div class="floc rawid">${esc(x.category)} &middot; ${esc(String(x.evidence_class).replace(/_/g," "))}</div>`;
      html+=`</div>`;
    });
    html+=`</div></div>`;
  }else if(mode!=="clean"){
    html+=`<div class="panel"><h2>What's hiding in there <span class="count">0</span></h2>`+
      `<div class="allclear"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M20 6 9 17l-5-5"/></svg>`+
      `Nothing detectable — no invisible characters, no embedded info, no content credentials.</div></div>`;
  }

  /* 3 — your file, at a glance */
  html+=`<div class="panel" style="animation-delay:.12s"><div class="meta">`+
    `<span><b>${esc(picked?picked.name:"file")}</b></span>`+
    `<span>${KINDS[a.kind]||esc(a.kind)}${a.language?" &middot; "+esc(a.language):""}</span>`+
    `<span>${fmtBytes(a.size_bytes)}</span>`+
    `<span class="fp" title="A unique fingerprint of this exact file's contents">fingerprint ${esc(a.sha256.slice(0,12))}&hellip;</span>`+
    `</div></div>`;

  /* 4 — the honest fine print */
  const p=r.inspection.provenance;
  if(p&&p.notes&&p.notes.length)
    html+=`<div class="panel" style="animation-delay:.18s"><h2>The fine print</h2><div class="notes">${p.notes.map(esc).join("<br><br>")}</div></div>`;

  out.innerHTML=html;
}
</script>
</body>
</html>
""".replace("__PROFILE_OPTIONS__", _PROFILE_OPTIONS)
