@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === v93 report row counts ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem .\reports\v93_*.csv -ErrorAction SilentlyContinue | Sort-Object Name | ForEach-Object { try { $c=(Import-Csv $_.FullName).Count } catch { $c='ERR' }; '{0} {1} rows {2} bytes' -f $_.Name,$c,$_.Length }"
echo.
echo === GitHub Actions status ===
if exist reports\v93_github_actions_status.json (
  type reports\v93_github_actions_status.json
) else (
  echo reports\v93_github_actions_status.json not found
)
echo.
pause
