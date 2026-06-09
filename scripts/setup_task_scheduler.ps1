# MONE 로컬 수집기 - 작업 스케줄러 등록 (현재 사용자 권한)
$repoRoot = Split-Path $PSScriptRoot -Parent
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = "python" }
$script = Join-Path $repoRoot "scripts\local_data_collector.py"

Write-Host "[MONE] 작업 스케줄러 등록..." -ForegroundColor Cyan

# 기존 작업 제거
"MONE_Morning_Collect","MONE_Evening_Collect" | ForEach-Object {
    Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue
}

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`" --push --days 5" -WorkingDirectory $repoRoot
$settings = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable -StartWhenAvailable

# 장전 07:30
$triggerMorning = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "07:30"
Register-ScheduledTask -TaskName "MONE_Morning_Collect" -Action $action -Trigger $triggerMorning -Settings $settings -RunLevel Limited -Force
Write-Host "[OK] 장전 수집 등록 (평일 07:30)" -ForegroundColor Green

# 장후 16:30
$triggerEvening = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "16:30"
Register-ScheduledTask -TaskName "MONE_Evening_Collect" -Action $action -Trigger $triggerEvening -Settings $settings -RunLevel Limited -Force
Write-Host "[OK] 장후 수집 등록 (평일 16:30)" -ForegroundColor Green

Write-Host ""
Write-Host "수동 실행: python `"$script`" --days 5" -ForegroundColor Yellow
Write-Host "push 포함: python `"$script`" --push --days 5" -ForegroundColor Yellow
