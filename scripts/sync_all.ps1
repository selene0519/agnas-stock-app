# MONE holdings sync runner for Windows Task Scheduler.
# Writes a dated log and runs each broker sync with a bounded timeout.

$ErrorActionPreference = "Continue"
$RepoRoot = "C:\dev\agnas-stock-app"
$Python = "C:\Users\minbo\AppData\Local\Programs\Python\Python312\python.exe"
$BackendUrl = "https://agnas-stock-app.onrender.com"
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir ("sync_all_{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$StepTimeoutSec = 600

Set-Location $RepoRoot
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Add-FileToLog {
    param([string]$Path)
    if (Test-Path $Path) {
        Get-Content -Path $Path -ErrorAction SilentlyContinue | ForEach-Object {
            Add-Content -Path $LogFile -Value $_ -Encoding UTF8
        }
    }
}

function Invoke-MoneStep {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )
    Write-Log "START $Name"
    $stamp = "{0}_{1}" -f ((Get-Date).ToString("HHmmss")), ($Name -replace "[^A-Za-z0-9_-]", "_")
    $stdout = Join-Path $env:TEMP "mone_${stamp}.out"
    $stderr = Join-Path $env:TEMP "mone_${stamp}.err"
    $process = Start-Process `
        -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $RepoRoot `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr
    if (-not $process.WaitForExit($StepTimeoutSec * 1000)) {
        try { $process.Kill() } catch {}
        Write-Log "TIMEOUT $Name after ${StepTimeoutSec}s"
        Add-FileToLog $stdout
        Add-FileToLog $stderr
        Remove-Item $stdout,$stderr -ErrorAction SilentlyContinue
        return $false
    }
    $process.WaitForExit()
    $process.Refresh()
    $exitCode = $process.ExitCode
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
    Add-FileToLog $stdout
    Add-FileToLog $stderr
    Remove-Item $stdout,$stderr -ErrorAction SilentlyContinue
    Write-Log "END $Name exit=$exitCode"
    return ($exitCode -eq 0)
}

Write-Log "============================================================"
Write-Log "sync_all start"
Write-Log "RepoRoot=$RepoRoot"
Write-Log "Python=$Python"

$ok = $true
$ok = (Invoke-MoneStep -Name "KIS_1" -Arguments @("scripts\sync_kis_holdings.py", "--upload", "--backend-url", $BackendUrl)) -and $ok
Start-Sleep -Seconds 5
$ok = (Invoke-MoneStep -Name "KIS_2" -Arguments @("scripts\sync_kis_holdings.py", "--prefix", "KIS_2", "--upload", "--backend-url", $BackendUrl)) -and $ok
Start-Sleep -Seconds 5
$ok = (Invoke-MoneStep -Name "Toss" -Arguments @("scripts\sync_toss_holdings.py", "--upload", "--backend-url", $BackendUrl)) -and $ok

if ($ok) {
    Write-Log "sync_all completed OK"
    exit 0
}

Write-Log "sync_all completed with errors"
exit 1
