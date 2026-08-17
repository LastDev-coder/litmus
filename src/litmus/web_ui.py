"""The litmus web UI: a single self-contained HTML page.

Kept as its own module so ``server.py`` stays focused on HTTP concerns. The
page is deliberately self-contained (inline CSS/JS, no external fetches) to
satisfy its strict Content-Security-Policy and the project's local-only
stance: nothing the browser renders is loaded off the machine.
"""

from __future__ import annotations

from .transform import PROFILES

__all__ = ["INDEX_HTML"]

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
  --bg:#06070d; --bg2:#0a0d16; --panel:rgba(19,25,37,.66); --panel-2:rgba(24,31,46,.6);
  --raise:#1a2233; --ink:#eef2f8; --dim:#9aa7bb; --faint:#5c6879;
  --line:rgba(130,150,185,.12); --line-2:rgba(150,170,205,.2);
  --signal:#ffb020; --signal-2:#ff863a; --signal-soft:rgba(255,176,32,.14); --signal-glow:rgba(255,150,40,.45);
  --good:#3ddc97;   --good-soft:rgba(61,220,151,.13);
  --bad:#ff6b6b;    --bad-soft:rgba(255,107,107,.12);
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --round:ui-rounded,"SF Pro Rounded","Hiragino Maru Gothic ProN","Trebuchet MS",var(--sans);
  --radius:20px;
  --glass:saturate(160%) blur(16px);
  --card-shadow:0 1px 0 rgba(255,255,255,.06) inset, 0 -24px 50px rgba(0,0,0,.22) inset,
    0 28px 64px -22px rgba(0,0,0,.75), 0 8px 24px -14px rgba(0,0,0,.6);
  --card-shadow-hover:0 1px 0 rgba(255,255,255,.10) inset, 0 -24px 50px rgba(0,0,0,.24) inset,
    0 46px 100px -28px rgba(0,0,0,.9), 0 14px 34px -16px rgba(0,0,0,.72);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
html,body{height:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased;overflow-x:hidden;
}
/* layered atmosphere: drifting aurora + masked grid */
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.bg::before{content:"";position:absolute;inset:-25%;
  background:
    radial-gradient(38% 30% at 18% 12%, rgba(255,150,40,.18), transparent 60%),
    radial-gradient(34% 30% at 86% 8%, rgba(96,124,255,.14), transparent 60%),
    radial-gradient(46% 42% at 74% 88%, rgba(61,220,151,.10), transparent 60%),
    radial-gradient(40% 36% at 8% 92%, rgba(255,84,120,.08), transparent 60%);
  filter:blur(38px);animation:aurora 26s ease-in-out infinite alternate}
.bg::after{content:"";position:absolute;inset:0;
  background-image:linear-gradient(rgba(140,160,195,.05) 1px,transparent 1px),
    linear-gradient(90deg,rgba(140,160,195,.05) 1px,transparent 1px);
  background-size:50px 50px;
  -webkit-mask:radial-gradient(120% 82% at 50% 0%,#000 38%,transparent 100%);
  mask:radial-gradient(120% 82% at 50% 0%,#000 38%,transparent 100%)}
@keyframes aurora{0%{transform:translate3d(-2%,-1%,0) scale(1.05) rotate(0deg)}
  100%{transform:translate3d(2%,3%,0) scale(1.18) rotate(5deg)}}
/* film grain */
body::before{content:"";position:fixed;inset:0;z-index:1;pointer-events:none;opacity:.4;mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.82' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  background-size:150px}
/* pointer-follow glow */
body::after{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(300px circle at var(--mx,50%) var(--my,-20%), rgba(255,176,32,.10), transparent 72%)}
.wrap{position:relative;z-index:2;max-width:840px;margin:0 auto;padding:54px 22px 120px}
header{display:flex;align-items:center;gap:14px;margin-bottom:6px}
.brand{font-family:var(--mono);font-weight:600;font-size:16px;letter-spacing:.36em;text-transform:uppercase;
  background:linear-gradient(90deg,#ffffff,#c4cfe0);-webkit-background-clip:text;background-clip:text;color:transparent}
.brand b{background:linear-gradient(90deg,var(--signal),var(--signal-2));-webkit-background-clip:text;background-clip:text;
  color:transparent;text-shadow:0 0 18px var(--signal-glow)}
.ver{font-family:var(--mono);font-size:10.5px;color:var(--dim);letter-spacing:.12em;
  padding:4px 11px;border:1px solid var(--line-2);border-radius:999px;
  background:rgba(255,255,255,.03);-webkit-backdrop-filter:var(--glass);backdrop-filter:var(--glass)}
.tagline{color:var(--dim);margin:16px 0 34px;max-width:60ch;font-size:16.5px;line-height:1.6;
  animation:fadeUp .8s .05s cubic-bezier(.2,.7,.2,1) both}
.tagline b{color:var(--ink);font-weight:700}
@keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}

/* ---- scanner (upload) ---- */
.scanner{position:relative;border:1px solid var(--line-2);border-radius:var(--radius);
  background:linear-gradient(180deg,var(--panel),var(--panel-2));overflow:hidden;
  box-shadow:var(--card-shadow);-webkit-backdrop-filter:var(--glass);backdrop-filter:var(--glass);
  transform-style:preserve-3d;transition:transform .18s cubic-bezier(.2,.7,.2,1), box-shadow .3s;
  animation:fadeUp .9s .1s cubic-bezier(.2,.7,.2,1) both}
.scanner::before{content:"";position:absolute;inset:0;border-radius:var(--radius);pointer-events:none;
  background:linear-gradient(140deg,rgba(255,255,255,.06),transparent 30%,transparent 70%,rgba(255,255,255,.03));
  -webkit-mask:linear-gradient(#000,#000) content-box,linear-gradient(#000,#000);mask-composite:exclude;padding:1px;opacity:.7}
.scanner:hover{box-shadow:var(--card-shadow-hover)}
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
  -webkit-backdrop-filter:var(--glass);backdrop-filter:var(--glass);
  transition:transform .35s cubic-bezier(.2,.7,.2,1), box-shadow .35s, opacity .6s;}
.panel:hover{transform:translateY(-3px);box-shadow:var(--card-shadow-hover)}
/* scroll-reveal: panels rise into view as you scroll */
.panel,.footnote,.resetrow{opacity:0;transform:translateY(28px) scale(.985);
  transition:opacity .7s cubic-bezier(.2,.7,.2,1),transform .7s cubic-bezier(.2,.7,.2,1);
  transition-delay:calc(var(--i,0)*70ms)}
.panel.in,.footnote.in,.resetrow.in{opacity:1;transform:none}
.panel.in:hover{transform:translateY(-3px)}
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
.footnote{max-width:60ch;margin:14px auto 2px;padding:0 20px;text-align:center;
  color:var(--faint);font-size:12px;line-height:1.6}
details.tech{margin-top:8px}
details.tech summary{cursor:pointer;font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.06em}
details.tech div{margin-top:6px;font-family:var(--mono);font-size:11.5px;color:var(--faint);line-height:1.6}
.working{padding:28px 20px;color:var(--dim);font-family:var(--round);font-size:14px}
.working::after{content:"";animation:dots 1.2s steps(4,end) infinite}
@keyframes dots{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}

/* input-source toggle + paste box */
.source{display:flex;gap:4px;padding:12px 12px 0}
.source button{flex:0 0 auto;font-family:var(--round);font-size:13px;font-weight:600;color:var(--dim);
  background:transparent;border:0;border-radius:9px 9px 0 0;padding:9px 16px;cursor:pointer;transition:.15s}
.source button[aria-selected="true"]{color:var(--ink);background:var(--panel);box-shadow:inset 0 -2px 0 var(--signal)}
#paste{width:calc(100% - 24px);margin:12px;min-height:150px;resize:vertical;
  font-family:var(--mono);font-size:13px;line-height:1.5;color:var(--ink);
  background:var(--panel-2);border:1px solid var(--line-2);border-radius:12px;padding:14px;outline:none}
#paste:focus{box-shadow:inset 0 0 0 2px var(--signal-soft),0 0 0 1px var(--signal)}
#paste::placeholder{color:var(--faint)}
.hidden{display:none!important}

/* C2PA / verification verdict on a finding */
.verify{display:inline-flex;gap:6px;align-items:center;margin-top:9px;font-family:var(--round);
  font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px}
.verify.genuine{background:var(--good-soft);color:var(--good)}
.verify.unver{background:var(--signal-soft);color:var(--signal)}
.verify.invalid{background:var(--bad-soft);color:var(--bad)}

/* before/after reveal (diff) */
.reveal{padding:14px 18px 18px}
.reveal .lead{color:var(--dim);font-size:13px;margin:0 0 10px}
.reveal pre{margin:0;padding:14px;border-radius:12px;background:var(--panel-2);border:1px solid var(--line-2);
  font-family:var(--mono);font-size:12.5px;line-height:1.7;white-space:pre-wrap;word-break:break-word;
  max-height:260px;overflow:auto;color:var(--ink)}
.chip-hidden{display:inline-block;background:var(--bad);color:#180a0a;font-family:var(--mono);font-size:9.5px;
  font-weight:700;letter-spacing:.03em;border-radius:5px;padding:1px 5px;margin:0 1px;vertical-align:middle;transform:translateY(-1px)}

/* copy-text output (paste mode) */
.copywrap{padding:0 18px 18px}
.copybtn{font-family:var(--round);font-size:13px;font-weight:700;background:var(--raise);color:var(--ink);
  border:1px solid var(--line-2);border-radius:10px;padding:9px 16px;cursor:pointer;display:inline-flex;gap:8px;align-items:center;transition:.15s}
.copybtn:hover{border-color:var(--signal);color:var(--signal)}
.copybtn.done{background:var(--good-soft);color:var(--good);border-color:var(--good)}

/* start-over / reset */
.resetrow{text-align:center;margin-top:4px}
.resetbtn{font-family:var(--round);font-size:13.5px;font-weight:600;color:var(--dim);background:var(--panel);
  border:1px solid var(--line-2);border-radius:11px;padding:10px 22px;cursor:pointer;display:inline-flex;gap:8px;align-items:center;
  box-shadow:var(--card-shadow);transition:transform .12s,border-color .15s,color .15s}
.resetbtn:hover{color:var(--ink);border-color:var(--signal);transform:translateY(-1px)}
.resetbtn:active{transform:translateY(1px)}
.resetbtn svg{width:15px;height:15px}

/* batch (multi-file) summary + rows */
.batch{padding:8px 14px 14px;display:grid;gap:8px}
.brow{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid var(--line);
  border-radius:12px;background:var(--panel-2);transition:border-color .15s}
.brow:hover{border-color:var(--line-2)}
.brow .dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto}
.brow .dot.ok{background:var(--good)} .brow .dot.warn{background:var(--signal)} .brow .dot.no{background:var(--bad)}
.brow .bname{font-family:var(--round);font-weight:600;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.brow .bstat{margin-left:auto;font-size:12.5px;color:var(--dim);flex:0 0 auto}
.brow a.mini{margin-left:10px;text-decoration:none}
.brow a.mini button{font-family:var(--round);font-size:12px;font-weight:700;background:var(--good);color:#07130d;
  border:0;border-radius:8px;padding:6px 12px;cursor:pointer}
/* premium finishing details */
::selection{background:rgba(255,176,32,.28);color:#fff}
::-webkit-scrollbar{width:12px;height:12px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:linear-gradient(var(--line-2),var(--raise));border-radius:99px;
  border:3px solid transparent;background-clip:padding-box}
::-webkit-scrollbar-thumb:hover{background:linear-gradient(var(--signal-soft),var(--line-2));background-clip:padding-box}
html{scrollbar-color:var(--line-2) transparent}
.hero .orb{animation:float 5s ease-in-out infinite}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important;scroll-behavior:auto!important}
  .panel,.footnote,.resetrow{opacity:1!important;transform:none!important}
  .bg::before{animation:none!important}
}
@media (max-width:560px){.hero{flex-direction:column;text-align:center;align-items:center}.tag{margin-left:0}}
</style>
</head>
<body>
<div class="bg" aria-hidden="true"></div>
<div class="wrap">
  <header>
    <span class="brand">lit<b>m</b>us</span>
    <span class="ver">100% local &middot; private</span>
  </header>
  <p class="tagline"><b>See what's hiding in your files.</b> Drop one in &mdash; litmus reveals
    invisible characters, hidden file info and content credentials, and can strip them out without
    changing anything you can see. Nothing ever leaves your computer.</p>

  <div class="scanner" id="scanner">
    <div class="source" role="tablist">
      <button id="tab-file" role="tab" aria-selected="true">Files</button>
      <button id="tab-text" role="tab" aria-selected="false">Paste text</button>
    </div>
    <div id="drop" role="button" tabindex="0" aria-label="Choose or drop files to analyse">
      <svg class="eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4">
        <path d="M1.5 12S5 5 12 5s10.5 7 10.5 7-3.5 7-10.5 7S1.5 12 1.5 12Z"/>
        <circle cx="12" cy="12" r="3.2"/>
      </svg>
      <span class="big">Drop files or <u>browse</u></span>
      <span class="hint">text &middot; code &middot; png &middot; jpeg &middot; svg &middot; docx / xlsx / pptx &middot; select several at once</span>
      <input id="file" type="file" multiple hidden>
    </div>
    <textarea id="paste" class="hidden" placeholder="Paste text here — litmus will reveal and remove any hidden characters, without changing a single word you can see."></textarea>
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
const paste=$("#paste"),tabFile=$("#tab-file"),tabText=$("#tab-text");
const MAX_FILE=16*1024*1024, MAX_FILES=300;
let picked=[];        // File[] in file mode
let source="file";    // "file" | "text"
function fmtBytes(n){return n<1024?n+" B":n<1048576?(n/1024).toFixed(1)+" KB":(n/1048576).toFixed(1)+" MB"}
function modeVerb(){return document.querySelector('input[name=mode]:checked').value==="clean"?"Clean":"Check";}
function refreshRun(){
  if(source==="text"){runBtn.disabled=paste.value.length===0;runBtn.textContent=modeVerb()+" text";}
  else{runBtn.disabled=picked.length===0;runBtn.textContent=modeVerb()+(picked.length>1?` ${picked.length} files`:" file");}
}
function baseName(f){return (f.webkitRelativePath||f.name||"").split("/").pop();}
function isJunk(f){const b=baseName(f);return b===".DS_Store"||b==="Thumbs.db"||b.startsWith("._")||b==="";}
function choose(files){
  const all=Array.from(files||[]).filter(f=>!isJunk(f));
  const oversized=all.filter(f=>f.size>MAX_FILE).length;
  const usable=all.filter(f=>f.size<=MAX_FILE);   // empty files are allowed
  picked=usable.slice(0,MAX_FILES);
  const capped=usable.length-picked.length;
  const el=$("#chosen");
  if(!picked.length){
    el.textContent=(files&&files.length)
      ? `> nothing to analyse (${files.length} item(s) selected; ${oversized} over ${fmtBytes(MAX_FILE)}, rest were system files)`
      : "";
  }else if(picked.length<=6){
    el.textContent="> "+picked.map(f=>`${baseName(f)} (${fmtBytes(f.size)})`).join("  ·  ");
  }else{
    el.textContent=`> ${picked.length} files selected`
      +(oversized?`  ·  ${oversized} skipped (over ${fmtBytes(MAX_FILE)})`:"")
      +(capped?`  ·  ${capped} beyond the ${MAX_FILES}-file limit`:"");
  }
  refreshRun();
}
function setSource(s){source=s;
  tabFile.setAttribute("aria-selected",s==="file");tabText.setAttribute("aria-selected",s==="text");
  drop.classList.toggle("hidden",s!=="file");$("#chosen").classList.toggle("hidden",s!=="file");
  paste.classList.toggle("hidden",s!=="text");refreshRun();}
tabFile.addEventListener("click",()=>setSource("file"));
tabText.addEventListener("click",()=>setSource("text"));
paste.addEventListener("input",refreshRun);
document.querySelectorAll('input[name=mode]').forEach(el=>el.addEventListener("change",refreshRun));
drop.addEventListener("click",()=>fileInput.click());
drop.addEventListener("keydown",(e)=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();fileInput.click();}});
fileInput.addEventListener("change",(e)=>choose(e.target.files));
["dragover","dragenter"].forEach(ev=>scanner.addEventListener(ev,(e)=>{e.preventDefault();scanner.classList.add("over");}));
["dragleave","drop"].forEach(ev=>scanner.addEventListener(ev,(e)=>{if(ev==="drop")e.preventDefault();scanner.classList.remove("over");}));
scanner.addEventListener("drop",(e)=>{e.preventDefault();scanner.classList.remove("over");if(e.dataTransfer.files.length)choose(e.dataTransfer.files);});
function toBase64(buf){const b=new Uint8Array(buf);let s="";const c=0x8000;for(let i=0;i<b.length;i+=c)s+=String.fromCharCode.apply(null,b.subarray(i,i+c));return btoa(s);}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

/* clear all input + result state without a browser refresh */
function resetAll(){
  picked=[];fileInput.value="";paste.value="";window.__cleaned=undefined;
  $("#chosen").textContent="";out.innerHTML="";refreshRun();
  (source==="text"?paste:drop).focus&&(source==="text"?paste.focus():drop.focus());
  window.scrollTo({top:0,behavior:"smooth"});
}
const RESET_ROW='<div class="resetrow"><button class="resetbtn" id="resetbtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg> Start over &mdash; check another</button></div>';
const REDUCED=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// reveal result panels as they scroll into view
function revealPanels(){
  const els=out.querySelectorAll(".panel:not(.seen),.footnote:not(.seen),.resetrow:not(.seen)");
  if(REDUCED||!("IntersectionObserver" in window)){els.forEach(el=>el.classList.add("seen","in"));return;}
  const io=new IntersectionObserver((ents,obs)=>{ents.forEach(en=>{
    if(en.isIntersecting){en.target.classList.add("in");obs.unobserve(en.target);}});},{rootMargin:"0px 0px -6% 0px"});
  els.forEach((el,i)=>{el.classList.add("seen");el.style.setProperty("--i",Math.min(i,6));io.observe(el);});
}
// wire buttons that live inside freshly-rendered results
function wireResults(){
  const rb=$("#resetbtn");if(rb)rb.addEventListener("click",resetAll);
  const cb=$("#copybtn");
  if(cb)cb.addEventListener("click",async()=>{
    try{await navigator.clipboard.writeText(window.__cleaned||"");cb.classList.add("done");cb.textContent="Copied ✓";}
    catch(e){cb.textContent="Copy failed — select the text above";}
  });
  revealPanels();
}

/* reveal hidden characters in a string as labelled chips (before/after view) */
function hiddenLabel(cp){
  if(cp===0x200B)return"ZWSP";if(cp===0x200C)return"ZWNJ";if(cp===0x200D)return"ZWJ";
  if(cp===0x2060)return"WJ";if(cp===0xFEFF)return"BOM";
  if(cp===0x200E)return"LRM";if(cp===0x200F)return"RLM";
  if((cp>=0x202A&&cp<=0x202E)||(cp>=0x2066&&cp<=0x2069))return"BIDI";
  if(cp===0x00AD)return"SHY";if(cp===0x034F)return"CGJ";if(cp===0x2800)return"BRAILLE";
  if(cp>=0xE0000&&cp<=0xE007F)return"TAG";
  if((cp>=0xFE00&&cp<=0xFE0F)||(cp>=0xE0100&&cp<=0xE01EF))return"VS";
  if(cp===0x00A0)return"NBSP";
  if((cp>=0x2000&&cp<=0x200A)||cp===0x202F||cp===0x205F||cp===0x3000)return"SPACE";
  if((cp<0x20&&cp!==0x09&&cp!==0x0A&&cp!==0x0D)||(cp>=0x7F&&cp<=0x9F))return"CTRL";
  return null;
}
function revealHidden(text){
  let html="",count=0;
  for(const ch of text){const cp=ch.codePointAt(0),label=hiddenLabel(cp);
    if(label){count++;html+=`<span class="chip-hidden" title="U+${cp.toString(16).toUpperCase().padStart(4,"0")}">${label}</span>`;}
    else html+=esc(ch);}
  return {html,count};
}

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

async function analyzeOne(name,b64,mode){
  const res=await fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name,data_base64:b64,mode,profile:$("#profile").value,force:$("#force").checked})});
  const data=await res.json();
  if(!res.ok)throw new Error(data.error||"Unknown error.");
  return data;
}
runBtn.addEventListener("click",async()=>{
  const mode=document.querySelector('input[name=mode]:checked').value;
  runBtn.disabled=true;scanner.classList.add("busy");
  const busyWord=mode==="clean"?"Cleaning":"Reading";
  try{
    if(source==="text"){
      const txt=paste.value;
      out.innerHTML=`<div class="panel"><div class="working">${busyWord} your text</div></div>`;
      const bytes=new TextEncoder().encode(txt);
      const data=await analyzeOne("pasted.txt",toBase64(bytes.buffer),mode);
      renderSingle(data,mode,{name:"pasted text",originalText:txt});
    }else{
      const items=picked.slice();
      out.innerHTML=`<div class="panel"><div class="working">${busyWord} ${items.length>1?items.length+" files":"your file"}</div></div>`;
      const results=[];
      for(const f of items){
        const label=f.webkitRelativePath||f.name;
        const buf=await f.arrayBuffer();
        let originalText=null;
        try{if(f.size<2_000_000)originalText=new TextDecoder("utf-8",{fatal:true}).decode(buf);}catch(e){}
        const data=await analyzeOne(f.name,toBase64(buf),mode);
        results.push({name:label,data,originalText});
      }
      if(results.length===1)renderSingle(results[0].data,mode,{name:results[0].name,originalText:results[0].originalText});
      else renderBatch(results,mode);
    }
  }catch(err){out.innerHTML=heroCard("no","Something went wrong",esc(String(err&&err.message||err)),"");}
  finally{runBtn.disabled=false;scanner.classList.remove("busy");}
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

function findingCard(x,i){
  const c=CATS[x.category]||{t:esc(String(x.category).replace(/_/g," ")),icon:"tag",b:esc(x.summary)};
  let html=`<div class="finding" style="animation-delay:${80+i*60}ms"><div class="top">`+
    `<span class="fico">${ICONS[c.icon]}</span><span class="ftitle">${c.t}</span>`+
    `<span class="tag ${esc(x.severity)}">${SEV[x.severity]||esc(x.severity)}</span></div>`+
    `<p class="fbody">${c.b}</p>`;
  if(x.locations&&x.locations[0]&&x.locations[0].line)
    html+=`<div class="floc">first seen at line ${x.locations[0].line}${x.count>1?" &middot; "+x.count+" in total":""}</div>`;
  if(x.details&&x.details.decoded_ascii_payload)
    html+=`<div class="payload"><span>hidden message we decoded</span>${esc(x.details.decoded_ascii_payload)}</div>`;
  // C2PA / content-credential verification verdict (feature 3)
  if(x.category==="c2pa_manifest"){
    const d=x.details||{},v=d.verification;
    if(v==="performed"&&d.validity==="valid")
      html+=`<div class="verify genuine">&#10003; signature verified — genuine credential</div>`;
    else if(v==="performed"&&d.validity==="invalid")
      html+=`<div class="verify invalid">&#9888; signature invalid — this credential may be tampered</div>`;
    else if(v==="performed")
      html+=`<div class="verify genuine">&#10003; manifest read and verified</div>`;
    else if(v==="failed")
      html+=`<div class="verify unver">present, but its signature could not be verified</div>`;
    else
      html+=`<div class="verify unver">present, signature not verified <span style="opacity:.7">(install the c2pa extra to verify)</span></div>`;
  }
  // GPS location call-out (feature 2)
  if(x.category==="photo_location"&&x.details&&x.details.gps_latitude!=null)
    html+=`<div class="payload"><span>location this photo reveals</span>${esc(x.details.gps_latitude)}, ${esc(x.details.gps_longitude)}</div>`;
  if(x.removable_by&&x.removable_by.length)
    html+=`<div class="fix"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M20 6 9 17l-5-5"/></svg> litmus can remove this &mdash; use Clean</div>`;
  html+=`<div class="floc rawid">${esc(x.category)} &middot; ${esc(String(x.evidence_class).replace(/_/g," "))}</div></div>`;
  return html;
}

function renderSingle(data,mode,ctx){
  ctx=ctx||{};
  const r=data.report,a=r.artifact,f=r.inspection.findings||[];
  const t=r.transformation;
  const isText=a.kind==="text"||a.kind==="source_code";
  let html="";

  /* 1 — verdict hero */
  if(mode==="clean"&&t&&t.performed){
    if(t.accepted&&data.output_base64){
      const proven=r.validation&&r.validation.all_passed===true;
      const cta=`<div class="heroCta"><a class="dl" href="data:application/octet-stream;base64,${data.output_base64}" download="${esc(data.output_name)}"><button>&#8595; Download your clean file</button></a><span class="ctaNote">Your original stays untouched on your computer.</span></div>`;
      if(proven)
        html+=heroCard("ok","Your file is clean","Litmus removed the hidden extras, then double-checked that everything you can see stayed exactly the same.",cta,"cleaned &amp; verified");
      else
        html+=heroCard("warn","Cleaned — please review","The clean-up was applied at your request, but litmus couldn't verify the result is unchanged. Give it a look before using it.",cta,"cleaned, not verified");
    }else if(t.accepted){
      html+=heroCard("ok","Nothing to clean","This was already spotless — no hidden content to remove.","","all clear");
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

  /* 2 — reveal / before-after (feature 5): show WHERE the hidden characters are */
  if(ctx.originalText){
    const rev=revealHidden(ctx.originalText);
    if(rev.count>0)
      html+=`<div class="panel"><h2>Where the hidden characters are <span class="count">${rev.count}</span></h2>`+
        `<div class="reveal"><p class="lead">Your text with every invisible character revealed as a red chip. The visible words are exactly as you'll keep them.</p>`+
        `<pre>${rev.html}</pre></div></div>`;
  }

  /* 3 — findings */
  if(f.length){
    html+=`<div class="panel"><h2>What's hiding in there <span class="count">${f.length}</span></h2><div class="cards">`+
      f.map(findingCard).join("")+`</div></div>`;
  }else if(mode!=="clean"){
    html+=`<div class="panel"><h2>What's hiding in there <span class="count">0</span></h2>`+
      `<div class="allclear"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M20 6 9 17l-5-5"/></svg>`+
      `Nothing detectable — no invisible characters, no embedded info, no content credentials.</div></div>`;
  }

  /* 4 — cleaned text output with copy button (feature 6, paste mode) */
  if(mode==="clean"&&isText&&t&&t.accepted&&data.output_base64){
    const cleaned=new TextDecoder().decode(Uint8Array.from(atob(data.output_base64),c=>c.charCodeAt(0)));
    window.__cleaned=cleaned;
    html+=`<div class="panel"><h2>Your clean text</h2><div class="reveal"><pre id="cleanout">${esc(cleaned)}</pre></div>`+
      `<div class="copywrap"><button class="copybtn" id="copybtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg> Copy clean text</button></div></div>`;
  }

  /* 5 — at a glance */
  html+=`<div class="panel" style="animation-delay:.12s"><div class="meta">`+
    `<span><b>${esc(ctx.name||"file")}</b></span>`+
    `<span>${KINDS[a.kind]||esc(a.kind)}${a.language?" &middot; "+esc(a.language):""}</span>`+
    `<span>${fmtBytes(a.size_bytes)}</span>`+
    `<span class="fp" title="A unique fingerprint of this exact input's contents">fingerprint ${esc(a.sha256.slice(0,12))}&hellip;</span>`+
    `</div></div>`;

  /* 6 — fine print */
  const p=r.inspection.provenance;
  if(p&&p.notes&&p.notes.length)
    html+=`<p class="footnote">litmus only checks what it can verify on your machine. A clean result means nothing hidden was found — not that a file is safe or that it proves who (or what) made it.</p>`;

  html+=RESET_ROW;
  out.innerHTML=html;
  wireResults();
}

/* multi-file batch view (feature 4) */
function renderBatch(results,mode){
  let withFindings=0,cleaned=0;
  const rows=results.map((it,i)=>{
    const r=it.data.report,f=r.inspection.findings||[],t=r.transformation;
    let dot="ok",stat="clean";
    if(mode==="clean"&&t&&t.performed){
      if(t.accepted&&it.data.output_base64){dot="ok";stat="cleaned";cleaned++;}
      else if(t.accepted){dot="ok";stat="already clean";}
      else{dot="no";stat="kept unchanged";}
    }else{
      if(f.length){dot=f.some(x=>x.severity==="warning")?"warn":"warn";stat=`${f.length} hidden`;withFindings++;}
      else{dot="ok";stat="nothing hidden";}
    }
    if(f.length&&mode!=="clean")withFindings=withFindings; // counted above
    const dl=(mode==="clean"&&it.data.output_base64)
      ? `<a class="mini" href="data:application/octet-stream;base64,${it.data.output_base64}" download="${esc(it.data.output_name||it.name)}"><button>&#8595; Download</button></a>`:"";
    return `<div class="brow" style="animation-delay:${i*40}ms"><span class="dot ${dot}"></span>`+
      `<span class="bname">${esc(it.name)}</span><span class="bstat">${esc(stat)}</span>${dl}</div>`;
  }).join("");

  const total=results.length;
  const anyFindings=results.reduce((n,it)=>n+((it.data.report.inspection.findings||[]).length),0);
  let html;
  if(mode==="clean")
    html=heroCard(cleaned?"ok":"ok",`Cleaned <span class="num">${cleaned}</span> of ${total} files`,
      cleaned?"Download each cleaned file below. Every original stays untouched on your computer.":"None of these needed changes — they were already clean.","","batch complete");
  else
    html=heroCard(anyFindings?"warn":"ok",
      anyFindings?`Found hidden content in <span class="num">${withFindings}</span> of ${total} files`:`All <span class="num">${total}</span> files look clean`,
      anyFindings?"Here's the per-file breakdown. Switch to Clean to strip what litmus can.":"No invisible characters, embedded info or content credentials detected in any of them.","","batch complete");
  html+=`<div class="panel"><h2>Per-file results <span class="count">${total}</span></h2><div class="batch">${rows}</div></div>`;
  html+=RESET_ROW;
  out.innerHTML=html;
  wireResults();
}

setSource("file");

/* ambient depth: pointer-follow glow + subtle 3D tilt on the scanner card */
if(!REDUCED){
  let raf=0,mx=innerWidth/2,my=-40;
  addEventListener("pointermove",(e)=>{mx=e.clientX;my=e.clientY;
    if(!raf)raf=requestAnimationFrame(()=>{raf=0;
      document.body.style.setProperty("--mx",mx+"px");document.body.style.setProperty("--my",my+"px");});
  },{passive:true});
  const TILT=6;
  scanner.addEventListener("pointermove",(e)=>{
    const r=scanner.getBoundingClientRect();
    const px=(e.clientX-r.left)/r.width-.5, py=(e.clientY-r.top)/r.height-.5;
    scanner.style.transform=`perspective(1100px) rotateX(${(-py*TILT).toFixed(2)}deg) rotateY(${(px*TILT).toFixed(2)}deg)`;
  });
  scanner.addEventListener("pointerleave",()=>{scanner.style.transform="";});
}
</script>
</body>
</html>
""".replace("__PROFILE_OPTIONS__", _PROFILE_OPTIONS)
