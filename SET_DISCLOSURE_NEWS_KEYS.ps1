$items = @(
  @{ Name = "DART_API_KEY";  Label = "DART_API_KEY 입력, 없으면 Enter" },
  @{ Name = "SEC_API_KEY";   Label = "SEC_API_KEY 입력, 없으면 Enter" },
  @{ Name = "GNEWS_API_KEY"; Label = "GNEWS_API_KEY 입력, 없으면 Enter" },
  @{ Name = "APIFY_TOKEN";   Label = "APIFY_TOKEN 입력, 없으면 Enter" }
)

foreach ($item in $items) {
  $name = $item.Name
  $value = Read-Host $item.Label

  if ($value -and $value.Trim()) {
    [Environment]::SetEnvironmentVariable($name, $value.Trim(), "User")
    Set-Item -Path "Env:$name" -Value $value.Trim()
    Write-Host "[OK] $name saved"
  } else {
    Write-Host "[SKIP] $name empty"
  }
}

Write-Host ""
Write-Host "저장 확인:"
foreach ($k in @("KIS_APP_KEY","KIS_APP_SECRET","FINNHUB_API_KEY","DART_API_KEY","SEC_API_KEY","GNEWS_API_KEY","APIFY_TOKEN")) {
  $v = [Environment]::GetEnvironmentVariable($k, "User")
  if ($v) {
    Write-Host "[OK] $k exists"
  } else {
    Write-Host "[MISSING] $k"
  }
}
