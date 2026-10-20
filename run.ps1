# One-click: check deps, refresh data if needed, start the API, open the board.
#
#   .\run.ps1              start (ingests only if the database is missing)
#   .\run.ps1 -Refresh     force a full data refresh first
#   .\run.ps1 -Port 9000   use another port
#   .\run.ps1 -NoBrowser   do not open a window

[CmdletBinding()]
param(
    [switch]$Refresh,
    [switch]$NoBrowser,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $root "src"
$db = Join-Path $root "data\macroboard.db"

function Find-Python {
    $candidates = @()
    if ($env:MACRO_PYTHON) { $candidates += $env:MACRO_PYTHON }
    $dsh = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $dsh) { $candidates += $dsh }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }
    foreach ($c in $candidates) {
        if (-not (Test-Path $c)) { continue }
        $v = & $c -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
        if ($v -and [int]$v -ge 310) { return $c }
    }
    throw "No Python 3.10+ found. Set MACRO_PYTHON to an interpreter path."
}

Write-Host ""
Write-Host "  Macro State Board" -ForegroundColor Yellow
Write-Host "  -----------------" -ForegroundColor DarkGray

$python = Find-Python
Write-Host ("  python : " + $python) -ForegroundColor DarkGray

$env:PYTHONPATH = $src
$env:PYTHONIOENCODING = "utf-8"

# --- dependencies ----------------------------------------------------------
$missing = & $python -c "import importlib.util as u;print(','.join(m for m in ('fastapi','uvicorn') if u.find_spec(m) is None))"
if ($missing) {
    Write-Host ("  installing: " + $missing) -ForegroundColor DarkGray
    & $python -m pip install --quiet --disable-pip-version-check $missing.Split(",")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

# --- database --------------------------------------------------------------
& $python -m macroboard init | Out-Null

if ($Refresh -or -not (Test-Path $db)) {
    Write-Host "  refreshing data (this takes ~40s cold, ~5s warm)..." -ForegroundColor DarkGray
    & $python -m macroboard refresh
    if ($LASTEXITCODE -ne 0) { Write-Host "  refresh finished with warnings" -ForegroundColor Yellow }
} else {
    Write-Host "  database present - skipping ingest (use -Refresh to update)" -ForegroundColor DarkGray
}

# --- serve -----------------------------------------------------------------
$url = "http://127.0.0.1:$Port/"
Write-Host ""
Write-Host "  board  : $url" -ForegroundColor Green
Write-Host "  api    : ${url}api/overview" -ForegroundColor DarkGray
Write-Host "  docs   : ${url}docs" -ForegroundColor DarkGray
Write-Host "  stop   : Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($u)
        Start-Sleep -Seconds 3
        Start-Process $u
    } -ArgumentList $url | Out-Null
}

& $python -m macroboard serve --port $Port
