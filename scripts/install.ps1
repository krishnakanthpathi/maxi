#
# Maxi Universal Windows Installer ⚡
# Usage: irm https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install.ps1 | iex
#

$ErrorActionPreference = "Stop"

Write-Host @"
  __  __              _ 
 |  \/  | __ ___  __ (_)
 | |\/| |/ _` \ \/ / | |
 | |  | | (_| |>  <  | |
 |_|  |_|\__,_/_/\_\ |_|
"@ -ForegroundColor Cyan

Write-Host "⚡ Maxi Universal Workstation Daemon Installer (Windows)" -ForegroundColor Green
Write-Host ""

# 1. Detect Python
$pythonCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$matches[1]
            if ($minor -ge 10) {
                $pythonCmd = $cmd
                Write-Host "🐍 Found Python: $ver ($cmd)" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "❌ Python 3.10+ was not found on your system." -ForegroundColor Red
    Write-Host "👉 Install Python from https://www.python.org/downloads/ or via winget:" -ForegroundColor Yellow
    Write-Host "   winget install Python.Python.3.12" -ForegroundColor Cyan
    exit 1
}

# 2. Setup Directories
$maxiDir = Join-Path $HOME ".maxi"
$venvDir = Join-Path $maxiDir "venv"
$srcDir = Join-Path $maxiDir "src"

if (-not (Test-Path $maxiDir)) {
    New-Item -ItemType Directory -Path $maxiDir -Force | Out-Null
}

# 3. Source Code Resolution
$scriptPath = $MyInvocation.MyCommand.Path
if ($scriptPath -and (Test-Path (Join-Path (Split-Path -Parent (Split-Path -Parent $scriptPath)) "pyproject.toml"))) {
    $sourcePath = Split-Path -Parent (Split-Path -Parent $scriptPath)
} else {
    Write-Host "🌐 Fetching latest Maxi source from GitHub..." -ForegroundColor Cyan
    if (Test-Path (Join-Path $srcDir ".git")) {
        git -C $srcDir pull --quiet
    } else {
        git clone --quiet "https://github.com/krishnakanthpathi/maxi.git" $srcDir
    }
    $sourcePath = $srcDir
}

# 4. Copy Default .env
$envTarget = Join-Path $maxiDir ".env"
$envSrc = Join-Path $sourcePath ".env"
$envExample = Join-Path $sourcePath ".env.example"

if (-not (Test-Path $envTarget)) {
    if (Test-Path $envSrc) {
        Copy-Item $envSrc $envTarget
        Write-Host "🔑 Initialized config at $envTarget" -ForegroundColor Cyan
    } elseif (Test-Path $envExample) {
        Copy-Item $envExample $envTarget
        Write-Host "🔑 Initialized default config at $envTarget" -ForegroundColor Cyan
    }
}

# Copy sounds and assets if present
$srcMaxiDir = Join-Path $sourcePath ".maxi"
if (Test-Path $srcMaxiDir) {
    Copy-Item -Path "$srcMaxiDir\*" -Destination $maxiDir -Recurse -Force -ErrorAction SilentlyContinue
}

# 5. Virtual Environment Setup
Write-Host "📦 Setting up isolated virtual environment at $venvDir..." -ForegroundColor Cyan
$hasUv = (Get-Command "uv" -ErrorAction SilentlyContinue) -ne $null

if ($hasUv) {
    Write-Host "⚡ Using uv for high-speed package management..." -ForegroundColor Green
    uv venv --allow-existing --python $pythonCmd $venvDir
    Write-Host "🔧 Installing Maxi package with voice support..." -ForegroundColor Cyan
    try {
        uv pip install -e "$sourcePath[voice]" --python $venvDir
    } catch {
        Write-Host "⚠️ Voice extras failed. Installing core chat package..." -ForegroundColor Yellow
        uv pip install -e "$sourcePath" --python $venvDir
    }
} else {
    & $pythonCmd -m venv $venvDir
    $venvPip = Join-Path $venvDir "Scripts\pip.exe"
    & $venvPip install --upgrade --quiet pip setuptools wheel
    Write-Host "🔧 Installing Maxi package with voice support..." -ForegroundColor Cyan
    try {
        & $venvPip install --quiet -e "$sourcePath[voice]"
    } catch {
        Write-Host "⚠️ Voice extras failed. Installing core chat package..." -ForegroundColor Yellow
        & $venvPip install --quiet -e "$sourcePath"
    }
}

$venvMaxi = Join-Path $venvDir "Scripts\maxi.exe"

# 6. Global CLI shim in user PATH
$localBin = Join-Path $HOME ".local\bin"
if (-not (Test-Path $localBin)) {
    New-Item -ItemType Directory -Path $localBin -Force | Out-Null
}

$batShim = Join-Path $localBin "maxi.cmd"
"@echo off`n`"$venvMaxi`" %*" | Out-File -FilePath $batShim -Encoding ascii
Write-Host "🔗 Linked CLI to $batShim" -ForegroundColor Green

# Ensure .local\bin is in User Environment PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$localBin*") {
    [Environment]::SetEnvironmentVariable("Path", "$localBin;$userPath", "User")
    $env:Path = "$localBin;$env:Path"
    Write-Host "⚙️ Added $localBin to User PATH." -ForegroundColor Cyan
}

Write-Host ""
Write-Host "🎉 Maxi successfully installed on Windows!" -ForegroundColor Green
Write-Host ""
Write-Host "Commands:"
Write-Host "  • Start daemon:   maxi start" -ForegroundColor Cyan
Write-Host "  • Open Web HUD:   maxi hud" -ForegroundColor Cyan
Write-Host "  • Configure LLM:  maxi config" -ForegroundColor Cyan
Write-Host "  • Check status:   maxi status" -ForegroundColor Cyan
Write-Host "  • Stop daemon:    maxi stop" -ForegroundColor Cyan
Write-Host ""
Write-Host "Hotkey:"
Write-Host "  • Hold Control + Space to speak (or use Web HUD to chat without mic)."
Write-Host ""
