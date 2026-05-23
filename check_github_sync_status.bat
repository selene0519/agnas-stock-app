@echo off
setlocal
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo [WARN] git command was not found.
  exit /b 1
)
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo [WARN] Not a git repository.
  exit /b 1
)
echo [INFO] Current branch:
git branch --show-current
echo [INFO] Last commit:
git log -1 --oneline
echo [INFO] Remote status:
git status -sb
