<#
.SYNOPSIS
    ClipCraft - One-Click Task Runner for Windows PowerShell.

.DESCRIPTION
    Convenient launcher for starting the ClipCraft Web UI, executing the CLI,
    running unit tests, and maintaining dependencies.

.EXAMPLE
    .\run.ps1 web                # Start web server on port 8000
    .\run.ps1 clip "https://..." # Clip a video via CLI
    .\run.ps1 test               # Run all test suites
    .\run.ps1 install            # Install Python requirements
    .\run.ps1 clean              # Clear cache & temp downloads
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet("web", "server", "clip", "test", "install", "config", "clean", "help")]
    [string]$Command = "web",

    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path $ScriptDir

# Auto-activate .venv if exists
$VenvActivate = Join-Path $ScriptDir ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    Write-Host "[ClipCraft] Activating virtual environment (.venv)..." -ForegroundColor Cyan
    & $VenvActivate
}

# Ensure Python is on PATH
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    Write-Host "[ERROR] Python was not found on your system PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from python.org and add it to PATH." -ForegroundColor Yellow
    exit 1
}

function Show-Header {
    Write-Host @"
   _____ _ _         _____            __ _   
  / ____| (_)       / ____|          / _| |  
 | |    | |_ _ __  | |     _ __ __ _| |_| |_ 
 | |    | | | '_ \ | |    | '__/ _` |  _| __|
 | |____| | | |_) || |____| | | (_| | | | |_ 
  \_____|_|_| .__/  \_____|_|  \__,_|_|  \__|
            | |                              
            |_|   Universal AI Shorts Engine ⚡
"@ -ForegroundColor Cyan
}

switch ($Command) {
    "web" {
        Show-Header
        Write-Host "[ClipCraft] Launching Web Dashboard on http://localhost:8000..." -ForegroundColor Green
        python main.py web $RemainingArgs
    }
    "server" {
        Show-Header
        Write-Host "[ClipCraft] Launching Web Dashboard on http://localhost:8000..." -ForegroundColor Green
        python main.py web $RemainingArgs
    }
    "clip" {
        Show-Header
        if (-not $RemainingArgs -or $RemainingArgs.Count -eq 0) {
            Write-Host "[ERROR] Missing source URL or file path." -ForegroundColor Red
            Write-Host "Usage: .\run.ps1 clip <source-url-or-path> [-c podcast|gaming|general] [-n 3]" -ForegroundColor Yellow
            exit 1
        }
        python main.py clip $RemainingArgs
    }
    "test" {
        Write-Host "[ClipCraft] Running test suite..." -ForegroundColor Cyan
        python -m unittest discover -s tests -p "test_*.py" -v
    }
    "install" {
        Write-Host "[ClipCraft] Installing requirements from requirements.txt..." -ForegroundColor Cyan
        pip install -r requirements.txt
        Write-Host "[ClipCraft] Dependencies installed successfully!" -ForegroundColor Green
    }
    "config" {
        python main.py config $RemainingArgs
    }
    "clean" {
        Write-Host "[ClipCraft] Cleaning temporary downloads and caches..." -ForegroundColor Yellow
        $downloads = Join-Path $ScriptDir "downloads"
        if (Test-Path $downloads) {
            Remove-Item -Path "$downloads\*" -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "Cleared $downloads" -ForegroundColor Gray
        }
        Write-Host "[ClipCraft] Cleanup completed!" -ForegroundColor Green
    }
    "help" {
        Show-Header
        Write-Host @"
Commands:
  .\run.ps1 web                  Start FastAPI web server (http://localhost:8000)
  .\run.ps1 clip <source> [opts] Generate viral shorts from URL or local file
  .\run.ps1 test                 Run the automated test suite
  .\run.ps1 install              Install Python dependencies
  .\run.ps1 config               View current configuration & hardware
  .\run.ps1 clean                Clear temporary audio & video cache
"@ -ForegroundColor White
    }
}

