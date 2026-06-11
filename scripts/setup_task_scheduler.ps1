# MONE 로컬 수집기 - 작업 스케줄러 등록
# 사용법: PowerShell에서 .\scripts\setup_task_scheduler.ps1
# (권한 오류 시 관리자 PowerShell로 재실행)

$repoRoot = Split-Path $PSScriptRoot -Parent
$python   = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = "python" }
$script   = Join-Path $repoRoot "scripts\local_data_collector.py"

Write-Host "[MONE] 작업 스케줄러 등록..." -ForegroundColor Cyan
Write-Host "  RepoRoot : $repoRoot"
Write-Host "  Python   : $python"
Write-Host ""

# 기존 작업 제거
"MONE_Morning_Collect","MONE_Evening_Collect","MONE_KR_Morning","MONE_KR_Close","MONE_US_Collect" | ForEach-Object {
    Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue
}

$settings = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable -StartWhenAvailable
$weekdays = "Monday","Tuesday","Wednesday","Thursday","Friday"

# [06:00] 미장 전날 종가 수집 + 예측
#   미장 마감: 04:00~05:00 KST → 06:00에 수집하면 전날 종가 반영됨
$actionUS = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`" --push --market us --days 5" `
    -WorkingDirectory $repoRoot
$triggerUS = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "06:00"
Register-ScheduledTask -TaskName "MONE_US_Collect" -Action $actionUS -Trigger $triggerUS -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "[OK] 미장 수집 + 예측 등록 (평일 06:00 KST) — 전날 종가 기반" -ForegroundColor Green

# [07:30] 국장 당일 오전 예측
$actionKR = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`" --push --market kr --days 5" `
    -WorkingDirectory $repoRoot
$triggerKRMorning = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "07:30"
Register-ScheduledTask -TaskName "MONE_KR_Morning" -Action $actionKR -Trigger $triggerKRMorning -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "[OK] 국장 오전 예측 등록  (평일 07:30 KST) — 전일 종가 기반" -ForegroundColor Green

# [16:30] 국장 마감 후 데이터 업데이트
$triggerKRClose = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "16:30"
Register-ScheduledTask -TaskName "MONE_KR_Close" -Action $actionKR -Trigger $triggerKRClose -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "[OK] 국장 마감 업데이트 등록 (평일 16:30 KST) — 당일 종가 반영" -ForegroundColor Green

Write-Host ""
Write-Host "=== 등록된 작업 ===" -ForegroundColor Cyan
Get-ScheduledTask | Where-Object { $_.TaskName -like "MONE_*" } |
    Select-Object TaskName, State |
    Format-Table -AutoSize

Write-Host "수동 테스트 실행:"
Write-Host "  Start-ScheduledTask -TaskName 'MONE_US_Collect'" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName 'MONE_KR_Morning'" -ForegroundColor Yellow
