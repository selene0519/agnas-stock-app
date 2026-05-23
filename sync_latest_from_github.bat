@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Syncing latest data/code from GitHub...
where git >nul 2>nul
if errorlevel 1 (
  echo [WARN] git command was not found. Please install GitHub Desktop or Git for Windows.
  exit /b 1
)
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo [WARN] This folder is not a GitHub cloned repository. Skipping git pull.
  exit /b 0
)
git pull --ff-only
if errorlevel 1 (
  echo [WARN] git pull failed. If GitHub Desktop has uncommitted changes, commit or stash first.
  exit /b 1
)
echo [INFO] Sync complete.
exit /b 0
