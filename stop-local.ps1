<#
.SYNOPSIS
  Stop only the WETCOR AI processes started by run-local.ps1.
.DESCRIPTION
  Reads the process IDs in .run\, confirms each process is still the WETCOR backend (uvicorn app.main:app)
  or frontend (next start/dev) before stopping it together with its child processes. Other Node.js or
  Python processes on the computer are never touched.
#>
[CmdletBinding()]
param([switch]$Quiet)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunDir = Join-Path $Root ".run"
$expect = @{ backend = "*uvicorn*app.main:app*"; frontend = "*next*" }
$stopped = 0
foreach ($name in @("backend", "frontend")) {
  $pidFile = Join-Path $RunDir "$name.pid"
  if (-not (Test-Path $pidFile)) { continue }
  $procId = [int](Get-Content $pidFile)
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -like $expect[$name]) {
    & taskkill.exe /PID $procId /T /F | Out-Null
    $stopped++
    if (-not $Quiet) { Write-Host "Stopped WETCOR $name (PID $procId)" -ForegroundColor Green }
  } elseif (-not $Quiet) {
    Write-Host "WETCOR $name (PID $procId) is not running; nothing to stop." -ForegroundColor DarkGray
  }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
if (-not $Quiet -and $stopped -eq 0) { Write-Host "No running WETCOR AI processes were found." }
