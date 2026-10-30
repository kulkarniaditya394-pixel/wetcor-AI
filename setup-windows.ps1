<#
.SYNOPSIS
  One-time (and repeatable) setup of WETCOR AI on Windows. No administrator rights needed.
.DESCRIPTION
  Checks Node.js/npm and Python, creates backend\.venv, installs pinned Python and npm dependencies,
  creates the local data folders, initialises (or safely upgrades) the SQLite database, writes the
  frontend API URL and builds the production frontend. It never installs unrelated software.
.EXAMPLE
  .\setup-windows.ps1
  .\setup-windows.ps1 -BackendPort 8100 -SkipFrontendBuild
#>
[CmdletBinding()]
param(
  [int]$BackendPort = 8100,
  [switch]$SkipFrontendBuild
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Backend ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"

function Step([string]$m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok([string]$m) { Write-Host "    OK  $m" -ForegroundColor Green }
function Fail([string]$m) { Write-Host "`nSETUP FAILED: $m" -ForegroundColor Red; exit 1 }
function Run([string]$exe, [string[]]$argv, [string]$what) {
  & $exe @argv
  if ($LASTEXITCODE -ne 0) { Fail "$what (exit code $LASTEXITCODE). See the output above." }
}

Write-Host "WETCOR AI - Windows setup" -ForegroundColor White
Write-Host "Folder: $Root"

# 1. Node.js and npm ---------------------------------------------------------
Step "Checking Node.js and npm"
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail "Node.js was not found. Install Node.js LTS (22 or 24, minimum 20.9) from https://nodejs.org, then open a NEW PowerShell window and rerun this script." }
$nodeVer = [version]((& node --version).Trim().TrimStart("v"))
if ($nodeVer -lt [version]"20.9.0") { Fail "Node.js $nodeVer is too old; Next.js 16 requires 20.9 or newer." }
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) { Fail "npm was not found next to Node.js. Reinstall Node.js LTS." }
Ok "Node.js $nodeVer, npm $((& npm.cmd --version).Trim())"

# 2. Python --------------------------------------------------------------------
Step "Checking Python (3.11, 3.12 or 3.13)"
function Test-Python([string]$exe, [string[]]$pre) {
  try {
    $out = & $exe @pre -c "import sys; print('%d.%d|%s' % (sys.version_info[0], sys.version_info[1], sys.executable))" 2>$null
    if ($LASTEXITCODE -eq 0 -and $out -match '^(\d+\.\d+)\|(.+)$') { return @{ Version = [version]$Matches[1]; Path = $Matches[2].Trim() } }
  } catch { }
  return $null
}
$python = $null
if (Test-Path $VenvPy) { $python = Test-Python $VenvPy @() }
if (-not $python) {
  $candidates = @()
  if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += @(@("py", "-3.11"), @("py", "-3.12"), @("py", "-3.13")) }
  $candidates += @(, @("python")); $candidates += @(, @("python3"))
  foreach ($c in $candidates) {
    $p = Test-Python $c[0] @($c | Select-Object -Skip 1)
    if ($p -and $p.Version -ge [version]"3.11" -and $p.Version -lt [version]"3.14" -and $p.Path -notmatch "WindowsApps") { $python = $p; break }
  }
  if (-not $python -and (Get-Command uv -ErrorAction SilentlyContinue)) {
    $uvPy = (& uv python find 3.11 2>$null)
    if ($LASTEXITCODE -eq 0 -and $uvPy) { $python = Test-Python $uvPy.Trim() @() }
  }
}
if (-not $python) {
  Fail "No supported Python found. Install Python 3.11 or 3.12 (64-bit) from https://www.python.org/downloads/windows/ and tick 'Add python.exe to PATH'. The Microsoft Store 'python' alias is not used."
}
Ok "Python $($python.Version) at $($python.Path)"

# 3. Virtual environment and Python packages -----------------------------------
Step "Creating the backend virtual environment"
if (-not (Test-Path $VenvPy)) { Run $python.Path @("-m", "venv", $Venv) "Creating backend\.venv failed" ; Ok "created backend\.venv" } else { Ok "backend\.venv already exists" }

Step "Installing Python dependencies (pinned in backend\requirements.txt)"
Run $VenvPy @("-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip") "Upgrading pip failed"
Run $VenvPy @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $Backend "requirements.txt")) "Installing Python packages failed (check internet access or proxy)"
Ok "Python packages installed"

# 4. Frontend packages -------------------------------------------------------------
Step "Installing frontend dependencies"
Push-Location $Frontend
try {
  if (Test-Path "package-lock.json") { Run "npm.cmd" @("ci", "--no-audit", "--no-fund") "npm ci failed" } else { Run "npm.cmd" @("install", "--no-audit", "--no-fund") "npm install failed" }
} finally { Pop-Location }
Ok "npm packages installed"

# 5. Data folders and database ---------------------------------------------------
Step "Creating data folders and initialising the database"
Push-Location $Backend
try {
  Run $VenvPy @("-c", "from app.core.config import settings; settings.ensure_dirs(); from app.database.session import init_db; v = init_db(); print('    database schema version', v, 'at', settings.database_path)") "Database initialisation failed (see docs\TROUBLESHOOTING.md: database migration)"
} finally { Pop-Location }
if (-not (Test-Path (Join-Path $Root "data\demo\README.txt"))) { Run $VenvPy @((Join-Path $Root "scripts\generate_demo_files.py")) "Generating demo files failed" }
Ok "data\ ready (database, raw, processed, reports, demo, trash)"

# 6. Configuration ----------------------------------------------------------------
Step "Writing configuration"
$apiUrl = "http://127.0.0.1:$BackendPort"
$envLocal = Join-Path $Frontend ".env.local"
Set-Content -Path $envLocal -Value "NEXT_PUBLIC_API_URL=$apiUrl" -Encoding ascii
$backendEnv = Join-Path $Backend ".env"
if (-not (Test-Path $backendEnv)) { Copy-Item (Join-Path $Backend ".env.example") $backendEnv }
Ok "frontend\.env.local -> $apiUrl ; backend\.env present"

# 7. Production build -------------------------------------------------------------
if (-not $SkipFrontendBuild) {
  Step "Building the production frontend (about a minute)"
  Push-Location $Frontend
  try {
    $env:NEXT_PUBLIC_API_URL = $apiUrl
    Run "npm.cmd" @("run", "build") "Frontend build failed"
    Set-Content -Path (Join-Path $Frontend ".next\wetcor-api-url.txt") -Value $apiUrl -Encoding ascii
  } finally { Pop-Location }
  Ok "frontend built"
}

Write-Host "`nSETUP COMPLETE" -ForegroundColor Green
Write-Host "Start the application with:  .\run-local.ps1"
Write-Host "Optional checks:              backend\.venv\Scripts\python -m pytest backend\tests   and   cd frontend; npm test"
