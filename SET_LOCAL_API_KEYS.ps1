$kisAppKey = Read-Host "KIS_APP_KEY 입력"
$kisAppSecretSecure = Read-Host "KIS_APP_SECRET 입력" -AsSecureString

$BSTR = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($kisAppSecretSecure)
$kisAppSecret = [Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

$finnhubKey = Read-Host "FINNHUB_API_KEY 입력, 없으면 Enter"
$dartKey = Read-Host "DART_API_KEY 입력, 없으면 Enter"

[Environment]::SetEnvironmentVariable("KIS_APP_KEY", $kisAppKey, "User")
[Environment]::SetEnvironmentVariable("KIS_APP_SECRET", $kisAppSecret, "User")

$env:KIS_APP_KEY = $kisAppKey
$env:KIS_APP_SECRET = $kisAppSecret

if ($finnhubKey -and $finnhubKey.Trim()) {
    [Environment]::SetEnvironmentVariable("FINNHUB_API_KEY", $finnhubKey.Trim(), "User")
    $env:FINNHUB_API_KEY = $finnhubKey.Trim()
}

if ($dartKey -and $dartKey.Trim()) {
    [Environment]::SetEnvironmentVariable("DART_API_KEY", $dartKey.Trim(), "User")
    $env:DART_API_KEY = $dartKey.Trim()
}

Remove-Item ".\data\kis_token_cache.json" -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "환경변수 저장 완료"
Write-Host "KIS_APP_KEY:" $(if ($env:KIS_APP_KEY) {"OK"} else {"MISSING"})
Write-Host "KIS_APP_SECRET:" $(if ($env:KIS_APP_SECRET) {"OK"} else {"MISSING"})
Write-Host "FINNHUB_API_KEY:" $(if ($env:FINNHUB_API_KEY) {"OK"} else {"MISSING"})
Write-Host "DART_API_KEY:" $(if ($env:DART_API_KEY) {"OK"} else {"MISSING"})
Write-Host ""
Write-Host "기존 KIS 토큰 캐시 삭제 완료"
