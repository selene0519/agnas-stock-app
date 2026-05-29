param(
  [string]$RepoRoot = (Get-Location).Path
)

Set-Location $RepoRoot

$pathsToRemove = @(
  "mone-web-app\frontend\.next",
  "mone-web-app\frontend\node_modules"
)

foreach ($path in $pathsToRemove) {
  if (Test-Path $path) {
    Write-Host "Remove local artifact: $path"
    Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
  }
}

# Stop tracking sensitive/local-only files if they were accidentally staged/tracked.
$resetPaths = @(
  ".env",
  ".env.local",
  "mone-web-app\backend\.env",
  "mone-web-app\backend\.env.local",
  "mone-web-app\frontend\.env.local",
  "mone-web-app\frontend\.next",
  "mone-web-app\frontend\node_modules"
)

foreach ($path in $resetPaths) {
  git reset -- $path 2>$null
}

Write-Host "Sanitize complete. Review git status before committing."
git status --short
