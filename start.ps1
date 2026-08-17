# One-command setup + launch for litmus (Windows PowerShell).
#
#   .\start.ps1              install everything, then open the local web UI
#   .\start.ps1 inspect x    install (if needed), then run any CLI command
#
# The first run installs into a local .venv; later runs are instant.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "litmus :: preparing environment (first run installs; later runs are instant)"

if (Get-Command uv -ErrorAction SilentlyContinue) {
    if (-not (Test-Path ".venv")) { uv venv --python 3.12 .venv }
    uv pip install --quiet -e ".[code]"
} else {
    $py = $null
    foreach ($c in @("python", "python3")) {
        if (Get-Command $c -ErrorAction SilentlyContinue) {
            & $c -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)"
            if ($LASTEXITCODE -eq 0) { $py = $c; break }
        }
    }
    if (-not $py) {
        Write-Error "Python 3.11+ not found. Install uv (https://astral.sh/uv) or Python 3.11+."
        exit 1
    }
    if (-not (Test-Path ".venv")) { & $py -m venv .venv }
    & ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    & ".venv\Scripts\python.exe" -m pip install --quiet -e ".[code]"
}

Write-Host "litmus :: ready"
$bin = ".venv\Scripts\litmus.exe"
if ($args.Count -gt 0) { & $bin @args } else {
    Write-Host "litmus :: launching the web UI (Ctrl-C to stop)"
    & $bin serve
}
