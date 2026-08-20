[CmdletBinding()]
param(
    [ValidateSet('all', 'journal', 'paper')]
    [string]$Only = 'all',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonScript = Join-Path $PSScriptRoot 'configure_cron_job_org.py'

function Read-SecretPlainText {
    param([Parameter(Mandatory)][string]$Prompt)
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$cronKey = $null
$githubToken = $null
try {
    Write-Host '비밀값은 화면과 명령 기록에 표시되지 않습니다.'
    $cronKey = Read-SecretPlainText 'cron-job.org API key'
    $githubToken = Read-SecretPlainText 'GitHub fine-grained token (Actions: write)'
    if ([string]::IsNullOrWhiteSpace($cronKey) -or [string]::IsNullOrWhiteSpace($githubToken)) {
        throw '두 비밀값이 모두 필요합니다.'
    }

    $env:CRON_JOB_ORG_API_KEY = $cronKey
    $env:MONE_CRON_GITHUB_TOKEN = $githubToken
    $arguments = @($pythonScript, '--only', $Only)
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    Push-Location $repoRoot
    try {
        & python @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "cron-job.org 설정 실패 (exit code $LASTEXITCODE)"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Remove-Item Env:CRON_JOB_ORG_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:MONE_CRON_GITHUB_TOKEN -ErrorAction SilentlyContinue
    $cronKey = $null
    $githubToken = $null
}
