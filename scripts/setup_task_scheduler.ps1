# MONE local collection tasks - Windows Task Scheduler registration
# Usage: PowerShell에서 .\scripts\setup_task_scheduler.ps1

$repoRoot = Split-Path $PSScriptRoot -Parent
$preferredPython = "C:\Users\minbo\AppData\Local\Programs\Python\Python312\python.exe"
$python = if (Test-Path $preferredPython) { $preferredPython } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) { $python = "python" }
$collector = Join-Path $repoRoot "scripts\local_data_collector.py"
$syncAll = Join-Path $repoRoot "sync_all.bat"
$weekdays = "Monday","Tuesday","Wednesday","Thursday","Friday"

Write-Host "[MONE] 작업 스케줄러 등록..." -ForegroundColor Cyan
Write-Host "  RepoRoot : $repoRoot"
Write-Host "  Python   : $python"
Write-Host ""

$taskNames = @(
    "MONE_Morning_Collect",
    "MONE_Evening_Collect",
    "MONE_KR_PreMarket",
    "MONE_KR_PostMarket",
    "MONE_US_PreMarket",
    "MONE_US_PostMarket",
    "MONE_sync_holdings",
    "MONE_KR_Morning",
    "MONE_KR_Close",
    "MONE_US_Collect"
)
$taskNames | ForEach-Object {
    Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

function Register-MoneCollectorTask {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$At,
        [Parameter(Mandatory=$true)][string]$Arguments
    )
    $action = New-ScheduledTaskAction `
        -Execute $python `
        -Argument "`"$collector`" $Arguments" `
        -WorkingDirectory $repoRoot
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $At
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
    Write-Host "[OK] $Name 등록 ($At)" -ForegroundColor Green
}

Register-MoneCollectorTask -Name "MONE_Morning_Collect" -At "07:30" -Arguments "--push --days 5"
Register-MoneCollectorTask -Name "MONE_KR_PreMarket" -At "08:30" -Arguments "--market kr --push --days 5"
Register-MoneCollectorTask -Name "MONE_Evening_Collect" -At "16:30" -Arguments "--push --days 5"
Register-MoneCollectorTask -Name "MONE_KR_PostMarket" -At "16:40" -Arguments "--market kr --push --days 5"
Register-MoneCollectorTask -Name "MONE_US_PostMarket" -At "06:20" -Arguments "--market us --push --days 5"
Register-MoneCollectorTask -Name "MONE_US_PreMarket" -At "21:50" -Arguments "--market us --push --days 5"

$syncAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$syncAll`"" -WorkingDirectory $repoRoot
$syncTrigger = New-ScheduledTaskTrigger -Daily -At "08:00"
Register-ScheduledTask -TaskName "MONE_sync_holdings" -Action $syncAction -Trigger $syncTrigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "[OK] MONE_sync_holdings 등록 (매일 08:00)" -ForegroundColor Green

Write-Host ""
Write-Host "=== 등록된 작업 ===" -ForegroundColor Cyan
Get-ScheduledTask | Where-Object { $_.TaskName -like "MONE_*" } |
    Select-Object TaskName, State |
    Format-Table -AutoSize

Write-Host "수동 테스트 실행:"
Write-Host "  Start-ScheduledTask -TaskName 'MONE_US_PreMarket'" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName 'MONE_sync_holdings'" -ForegroundColor Yellow
