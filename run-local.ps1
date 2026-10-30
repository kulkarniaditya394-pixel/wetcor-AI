<#
.SYNOPSIS
  Start the WETCOR AI backend (FastAPI) and frontend (Next.js) on the loopback interface.
.DESCRIPTION
  Starts both services as background processes, records their process IDs in .run\, waits for the
  backend health check and the frontend page to respond, and only then reports success. Logs go to
  .run\*.log. Stop with .\stop-local.ps1.
.EXAMPLE
  .\run-local.ps1
  .\run-local.ps1 -BackendPort 8200 -FrontendPort 3200
  .\run-local.ps1 -Dev        # Next.js development server (hot reload)
#>
[CmdletBinding()]
param(
  [int]$BackendPort = 8100,
  [int]$FrontendPort = 3100,
  [switch]$Dev,
  [int]$TimeoutSec = 120
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$RunDir = Join-Path $Root ".run"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Fail([string]$m) { Write-Host "`nSTART FAILED: $m" -ForegroundColor Red; exit 1 }
function Test-Port([int]$port) {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $c.Connect("127.0.0.1", $port); return $true } catch { return $false } finally { $c.Dispose() }
}
function Test-Ours([string]$name) {
  $pidFile = Join-Path $RunDir "$name.pid"
  if (-not (Test-Path $pidFile)) { return $false }
  return [bool](Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue)
}
function Get-Url([string]$url) {
  try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5; return $r } catch { return $null }
}
function Show-Log([string]$name) {
  foreach ($f in @("$name.err.log", "$name.log")) {
    $p = Join-Path $RunDir $f
    if (Test-Path $p) { Write-Host "--- last lines of .run\$f ---" -ForegroundColor DarkGray; Get-Content $p -Tail 15 }
  }
}

if (-not (Test-Path $VenvPy)) { Fail "backend\.venv not found. Run .\setup-windows.ps1 first." }
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail "Node.js not found on PATH. Install Node.js LTS or open a new PowerShell window." }
if ((Test-Ours "backend") -or (Test-Ours "frontend")) { Fail "WETCOR AI already appears to be running (see .run\*.pid). Run .\stop-local.ps1 first." }
if (Test-Port $BackendPort) { Fail "Port $BackendPort is already in use by another program. Choose another: .\run-local.ps1 -BackendPort 8200" }
if (Test-Port $FrontendPort) { Fail "Port $FrontendPort is already in use by another program. Choose another: .\run-local.ps1 -FrontendPort 3200" }

$apiUrl = "http://127.0.0.1:$BackendPort"
$env:WETCOR_HOST = "127.0.0.1"
$env:WETCOR_PORT = "$BackendPort"
$env:WETCOR_CORS_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
$env:NEXT_PUBLIC_API_URL = $apiUrl

# ---- backend -------------------------------------------------------------------
Write-Host "Starting backend on $apiUrl ..." -ForegroundColor Cyan
$be = Start-Process -FilePath $VenvPy -WorkingDirectory $Backend -WindowStyle Hidden -PassThru `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
  -RedirectStandardOutput (Join-Path $RunDir "backend.log") -RedirectStandardError (Join-Path $RunDir "backend.err.log")
Set-Content -Path (Join-Path $RunDir "backend.pid") -Value $be.Id
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$healthy = $false
while ((Get-Date) -lt $deadline) {
  if ($be.HasExited) { Show-Log "backend"; Fail "Backend exited during start-up (exit code $($be.ExitCode))." }
  $r = Get-Url "$apiUrl/api/health"
  if ($r -and $r.StatusCode -eq 200 -and $r.Content -match '"database":"ok"') { $healthy = $true; break }
  Start-Sleep -Milliseconds 700
}
if (-not $healthy) { Show-Log "backend"; & (Join-Path $Root "stop-local.ps1") -Quiet; Fail "Backend health check did not pass within $TimeoutSec s." }
Write-Host "    backend healthy: $((Get-Url "$apiUrl/api/health").Content)" -ForegroundColor Green

# ---- frontend ------------------------------------------------------------------
$nextBin = Join-Path $Frontend "node_modules\next\dist\bin\next"
if (-not (Test-Path $nextBin)) { & (Join-Path $Root "stop-local.ps1") -Quiet; Fail "frontend\node_modules missing. Run .\setup-windows.ps1." }
if (-not $Dev) {
  $marker = Join-Path $Frontend ".next\wetcor-api-url.txt"
  $buildId = Join-Path $Frontend ".next\BUILD_ID"
  $built = (Test-Path $buildId) -and (Test-Path $marker) -and ((Get-Content $marker -ErrorAction SilentlyContinue) -eq $apiUrl)
  if ($built) {  # rebuild when any frontend source is newer than the build
    $newest = Get-ChildItem -Path (@("app", "components", "hooks", "lib", "schemas") | ForEach-Object { Join-Path $Frontend $_ }) -Recurse -File |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest -and $newest.LastWriteTime -gt (Get-Item $buildId).LastWriteTime) { $built = $false }
  }
  if (-not $built) {
    Write-Host "Building frontend for $apiUrl (first run or port change) ..." -ForegroundColor Cyan
    Push-Location $Frontend
    try {
      & $node.Source $nextBin build
      if ($LASTEXITCODE -ne 0) { throw "build failed" }
      Set-Content -Path $marker -Value $apiUrl -Encoding ascii
    } catch { Pop-Location; & (Join-Path $Root "stop-local.ps1") -Quiet; Fail "Frontend build failed." }
    Pop-Location
  }
}
$mode = if ($Dev) { "dev" } else { "start" }
Write-Host "Starting frontend ($mode) on http://127.0.0.1:$FrontendPort ..." -ForegroundColor Cyan
$fe = Start-Process -FilePath $node.Source -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru `
  -ArgumentList @("`"$nextBin`"", $mode, "-p", "$FrontendPort", "-H", "127.0.0.1") `
  -RedirectStandardOutput (Join-Path $RunDir "frontend.log") -RedirectStandardError (Join-Path $RunDir "frontend.err.log")
Set-Content -Path (Join-Path $RunDir "frontend.pid") -Value $fe.Id
$ready = $false
while ((Get-Date) -lt $deadline.AddSeconds(60)) {
  if ($fe.HasExited) { Show-Log "frontend"; & (Join-Path $Root "stop-local.ps1") -Quiet; Fail "Frontend exited during start-up (exit code $($fe.ExitCode))." }
  $r = Get-Url "http://127.0.0.1:$FrontendPort/dashboard"
  if ($r -and $r.StatusCode -eq 200) { $ready = $true; break }
  Start-Sleep -Milliseconds 800
}
if (-not $ready) { Show-Log "frontend"; & (Join-Path $Root "stop-local.ps1") -Quiet; Fail "Frontend did not respond on port $FrontendPort." }

Write-Host ""
Write-Host "WETCOR AI IS RUNNING" -ForegroundColor Green
Write-Host "  Open in Chrome or Edge:  http://localhost:$FrontendPort   (or http://127.0.0.1:$FrontendPort)"
Write-Host "  Backend API:             $apiUrl   (interactive docs: $apiUrl/docs)"
Write-Host "  Logs:                    .run\backend.log, .run\frontend.log"
Write-Host "  Stop:                    .\stop-local.ps1"
Write-Host "Grant camera permission when the browser asks (Wettability Lab -> Start camera)."
