# scripts/sync_latest_market_data.ps1
# Safely syncs only market data files from GitHub origin/main.
# It does NOT reset the repo and does NOT checkout app code files.
#
# Usage:
#   cd C:\dev\agnas-stock-app
#   powershell -ExecutionPolicy Bypass -File .\scripts\sync_latest_market_data.ps1
#
# Optional:
#   powershell -ExecutionPolicy Bypass -File .\scripts\sync_latest_market_data.ps1 -CheckApi

param(
  [switch]$CheckApi
)

$ErrorActionPreference = "Continue"

$Repo = "C:\dev\agnas-stock-app"
Set-Location $Repo

Write-Host "=== MONE market data sync ===" -ForegroundColor Cyan
Write-Host "[Repo] $Repo"

function Show-Step($msg) {
  Write-Host ""
  Write-Host "## $msg" -ForegroundColor Yellow
}

Show-Step "Current branch/status"
git status -sb

Show-Step "Fetch origin/main"
git fetch origin main
if ($LASTEXITCODE -ne 0) {
  Write-Warning "git fetch failed. Keeping local data as-is."
  exit 1
}

Show-Step "Files that may change before sync"
git diff --name-only -- data reports predictions.csv holdings_kr.csv holdings_us.csv

Show-Step "Sync data paths from origin/main only"
$targets = @(
  "data",
  "reports",
  "predictions.csv",
  "holdings_kr.csv",
  "holdings_us.csv"
)

foreach ($t in $targets) {
  git cat-file -e "origin/main:$t" 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "[SYNC] $t"
    git checkout origin/main -- $t
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "Failed to sync $t"
    }
  } else {
    Write-Host "[SKIP] $t not found in origin/main" -ForegroundColor DarkGray
  }
}

Show-Step "Changed synced data files"
git status --short -- data reports predictions.csv holdings_kr.csv holdings_us.csv

Show-Step "Date markers in synced files"
$patterns = @("2026-06-01", "20260601", "2026-05-30", "20260530", "2026-05-29", "20260529")
$paths = @(".\data\*.csv", ".\data\**\*.csv", ".\reports\*.csv", ".\reports\**\*.csv", ".\predictions.csv")

foreach ($p in $patterns) {
  Write-Host ""
  Write-Host "[DATE CHECK] $p" -ForegroundColor Green
  Select-String -Path $paths -Pattern $p -ErrorAction SilentlyContinue |
    Select-Object -First 20 Path, LineNumber, Line |
    Format-Table -AutoSize
}

Show-Step "Quick file counts"
$quickFiles = @(
  ".\data\stockapp\kis_current_price_kr.csv",
  ".\data\stockapp\kis_current_price_us.csv",
  ".\reports\kis_current_price_kr.csv",
  ".\reports\kis_current_price_us.csv",
  ".\predictions.csv",
  ".\holdings_kr.csv",
  ".\holdings_us.csv"
)

foreach ($f in $quickFiles) {
  if (Test-Path $f) {
    $count = 0
    try {
      $count = (Import-Csv $f).Count
    } catch {
      $count = -1
    }
    Write-Host ("{0} rows={1}" -f $f, $count)
  } else {
    Write-Host ("{0} missing" -f $f) -ForegroundColor DarkGray
  }
}

if ($CheckApi) {
  Show-Step "API check through frontend proxy"
  try {
    Invoke-RestMethod "http://localhost:3001/mone-api/final/data-quality-live?market=all" |
      Select-Object status,market,dataStatus,priceDataStatus,killSwitch,message |
      Format-List
  } catch {
    Write-Warning "data-quality-live API check failed. Backend/frontend may not be running."
    Write-Warning $_.Exception.Message
  }

  try {
    Invoke-RestMethod "http://localhost:3001/mone-api/final/recommendations?market=kr&mode=balanced&horizon=swing&limit=20" |
      Select-Object status,count,market |
      Format-List
  } catch {
    Write-Warning "KR recommendations API check failed."
  }

  try {
    Invoke-RestMethod "http://localhost:3001/mone-api/final/recommendations?market=us&mode=balanced&horizon=swing&limit=20" |
      Select-Object status,count,market |
      Format-List
  } catch {
    Write-Warning "US recommendations API check failed."
  }
}

Write-Host ""
Write-Host "=== Sync finished ===" -ForegroundColor Cyan
Write-Host "If backend uses cached data, restart backend 8050 and refresh browser with Ctrl+F5."
