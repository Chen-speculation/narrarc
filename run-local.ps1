# Run Backend + Client locally. Auto-install: uv, Node.js (portable to .node)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# --- Proxy for faster downloads (local tunnel) ---
$Env:http_proxy = "http://127.0.0.1:7890"
$Env:https_proxy = "http://127.0.0.1:7890"

# --- Ensure uv in PATH ---
$uvBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $uvBin) {
  $env:Path = $uvBin + ";" + $env:Path
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv..." -ForegroundColor Yellow
  Invoke-Expression "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = (Join-Path $env:USERPROFILE ".local\bin") + ";" + $env:Path
}

# --- Ensure Node.js / npm available; else download portable to .node ---
function Add-NodeToPath {
  $candidates = @(
    (Join-Path $env:ProgramFiles "nodejs"),
    (Join-Path ${env:ProgramFiles(x86)} "nodejs"),
    (Join-Path $root ".node\node-v20.18.0-win-x64")
  )
  foreach ($p in $candidates) {
    if (Test-Path $p) { $env:Path = $p + ";" + $env:Path }
  }
}

Add-NodeToPath
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Host "Node.js not found. Downloading portable to .node ..." -ForegroundColor Yellow
  $nodeVersion = "v20.18.0"
  $nodeZip = "node-" + $nodeVersion + "-win-x64.zip"
  $nodeUrl = "https://nodejs.org/dist/" + $nodeVersion + "/" + $nodeZip
  $nodeDir = Join-Path $root ".node"
  $nodeExtract = Join-Path $nodeDir ("node-" + $nodeVersion + "-win-x64")
  if (-not (Test-Path $nodeExtract)) {
    New-Item -ItemType Directory -Path $nodeDir -Force | Out-Null
    $zipPath = Join-Path $nodeDir $nodeZip
    try {
      [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
      Invoke-WebRequest -Uri $nodeUrl -OutFile $zipPath -UseBasicParsing
    }
    catch {
      Write-Host "Download failed. Install Node.js from https://nodejs.org and retry." -ForegroundColor Red
      exit 1
    }
    Expand-Archive -Path $zipPath -DestinationPath $nodeDir -Force
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
  }
  $env:Path = $nodeExtract + ";" + $env:Path
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Host "Node still not found. Install from https://nodejs.org and retry." -ForegroundColor Red
  exit 1
}

# --- Ensure Rust (cargo) for Tauri ---
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $cargoBin) { $env:Path = $cargoBin + ";" + $env:Path }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
  Write-Host "Rust not found. Installing via rustup..." -ForegroundColor Yellow
  $rustupExe = Join-Path $env:TEMP "rustup-init.exe"
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe" -OutFile $rustupExe -UseBasicParsing
  }
  catch {
    Write-Host "Rust download failed. Install from https://rustup.rs and retry." -ForegroundColor Red
    exit 1
  }
  & $rustupExe -y --default-toolchain stable
  $env:Path = $cargoBin + ";" + $env:Path
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
  Write-Host "Cargo still not found. Close this window, open a new one, and run again." -ForegroundColor Red
  exit 1
}

# --- Ensure MSVC (link.exe) for Tauri on Windows ---
function Find-Vcvars {
  $paths = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"),
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat")
  )
  foreach ($p in $paths) { if (Test-Path $p) { return $p } }
  return $null
}

$vcvars = Find-Vcvars
if (-not $vcvars) {
  Write-Host "MSVC not found. Installing Build Tools (large download, may take 10+ min)..." -ForegroundColor Yellow
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget) {
    & winget install -e --id Microsoft.VisualStudio.2022.BuildTools --accept-source-agreements --accept-package-agreements --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
  }
  $vcvars = Find-Vcvars
}
if (-not $vcvars) {
  Write-Host "MSVC still not found. Install Build Tools from: https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Red
  exit 1
}

# --- 1) Backend ---
Write-Host "`n== Backend (uv sync) ==" -ForegroundColor Cyan
Push-Location (Join-Path $root "backend")
try {
  & uv sync
  if (-not (Test-Path "data")) { New-Item -ItemType Directory -Path "data" -Force | Out-Null }
}
finally {
  Pop-Location
}

# --- 2) Client deps ---
Write-Host "`n== Client (npm install) ==" -ForegroundColor Cyan
Push-Location (Join-Path $root "client")
try {
  & npm install
}
finally {
  Pop-Location
}

# --- 3) Start Tauri (with MSVC env so link.exe is found) ---
Write-Host "`n== Client (tauri:dev) ==" -ForegroundColor Cyan
# Use UTF-8 so backend build logs (topic names etc.) render correctly
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$clientDir = Join-Path $root "client"
$tauriCmd = "call `"$vcvars`" && chcp 65001 >nul && cd /d `"$clientDir`" && npm run tauri:dev"
cmd /c $tauriCmd
