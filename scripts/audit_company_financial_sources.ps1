# scripts/audit_company_financial_sources.ps1
# Strict ASCII-only audit script for MONE company/financial CSV sources.
# This script intentionally avoids non-ASCII column literals to prevent Windows PowerShell parse errors.
#
# Usage:
#   cd C:\dev\agnas-stock-app
#   powershell -ExecutionPolicy Bypass -File .\scripts\audit_company_financial_sources.ps1 -Market kr -Symbols 005930,000660,005380,035420,131970

param(
  [string]$Market = "kr",
  [string[]]$Symbols = @("005930","000660","005380","035420","131970")
)

$ErrorActionPreference = "Continue"

$Repo = "C:\dev\agnas-stock-app"
Set-Location $Repo

Write-Host "=== MONE company financial source audit ===" -ForegroundColor Cyan
Write-Host ("Market: {0}" -f $Market)
Write-Host ("Symbols: {0}" -f ($Symbols -join ", "))

$CandidatePatterns = @(
  ".\reports\v3_company_integrated_kr.csv",
  ".\reports\v3_company_integrated_us.csv",
  ".\reports\v92_financial_statement_kr.csv",
  ".\reports\v92_financial_statement_us.csv",
  ".\reports\v92_financial_ratios_kr.csv",
  ".\reports\v92_financial_ratios_us.csv",
  ".\reports\mone_v36_final_data_center_kr.csv",
  ".\reports\mone_v36_final_data_center_us.csv",
  ".\reports\*.csv",
  ".\data\company\*.csv",
  ".\data\financial\*.csv",
  ".\data\dart\*.csv",
  ".\data\stockapp\*.csv"
)

$Files = @()
foreach ($pattern in $CandidatePatterns) {
  $Files += Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue
}
$Files = $Files | Where-Object { $_.Extension -eq ".csv" } | Sort-Object FullName -Unique

if (!$Files -or $Files.Count -eq 0) {
  Write-Warning "No candidate CSV files found."
  exit 0
}

# ASCII-only expected column aliases.
$SymbolColumns = @("symbol","ticker","code","stock_code","stockCode","Symbol","Ticker")
$NameColumns = @("name","companyName","company_name","corp_name","corpName","Company","company")
$FinancialColumns = @(
  "eps","EPS",
  "per","PER",
  "pbr","PBR",
  "roe","ROE",
  "revenue","sales",
  "operatingProfit","operating_profit","op",
  "netIncome","net_income",
  "debtRatio","debt_ratio",
  "fundamentalScore","fundamental_score"
)

function Get-FirstValue($row, $cols) {
  foreach ($c in $cols) {
    if ($row.PSObject.Properties.Name -contains $c) {
      $v = [string]$row.$c
      if ($null -ne $v -and $v.Trim() -ne "") {
        return $v.Trim()
      }
    }
  }
  return ""
}

function Normalize-Symbol($s) {
  $v = ([string]$s).Trim()
  if ($v -match '^\d+$') {
    return $v.PadLeft(6, '0')
  }
  return $v.ToUpper()
}

function Looks-Like-Symbol-Column($columnName) {
  $c = ([string]$columnName).ToLower()
  if ($c -match "symbol|ticker|code|stock") { return $true }
  return $false
}

function Looks-Like-Financial-Column($columnName) {
  $c = ([string]$columnName).ToLower()
  if ($c -match "eps|per|pbr|roe|revenue|sales|profit|income|debt|ratio|financial|fundamental") {
    return $true
  }
  return $false
}

function Looks-Like-Symbol-Value($value) {
  $v = ([string]$value).Trim()
  if ($Market -eq "kr" -and $v -match '^\d{1,6}$') { return $true }
  if ($Market -eq "us" -and $v -match '^[A-Za-z][A-Za-z\.\-]{0,11}$') { return $true }
  return $false
}

function Get-Symbol-From-Row($row, $symbolCandidates) {
  $sym = Get-FirstValue $row $SymbolColumns

  if ($sym -eq "" -and $symbolCandidates.Count -gt 0) {
    foreach ($sc in $symbolCandidates) {
      $v = [string]$row.$sc
      if ($v.Trim() -ne "") {
        $sym = $v.Trim()
        break
      }
    }
  }

  if ($sym -eq "") {
    foreach ($prop in $row.PSObject.Properties) {
      if (Looks-Like-Symbol-Value $prop.Value) {
        $sym = [string]$prop.Value
        break
      }
    }
  }

  return Normalize-Symbol $sym
}

$TargetSymbols = @()
foreach ($s in $Symbols) {
  foreach ($part in ([string]$s -split ",")) {
    if ($part.Trim() -ne "") {
      $TargetSymbols += Normalize-Symbol $part
    }
  }
}

Write-Host ""
Write-Host "## Candidate file summary" -ForegroundColor Yellow

$summary = @()

foreach ($file in $Files) {
  $rows = @()
  try {
    $rows = Import-Csv $file.FullName
  } catch {
    Write-Warning ("Import failed: {0}" -f $file.FullName)
    continue
  }

  $rowCount = 0
  if ($rows) { $rowCount = $rows.Count }

  if ($rowCount -eq 0) {
    $summary += [PSCustomObject]@{
      File = $file.FullName
      Rows = 0
      HasSymbol = $false
      HasFinancialCols = $false
      MatchedRows = 0
      FinancialColumnsFound = ""
      AllColumnsSample = ""
    }
    continue
  }

  $cols = @($rows[0].PSObject.Properties.Name)

  $symbolCandidates = @()
  foreach ($c in $cols) {
    if (($SymbolColumns -contains $c) -or (Looks-Like-Symbol-Column $c)) {
      $symbolCandidates += $c
    }
  }

  $financialHits = @()
  foreach ($c in $cols) {
    if (($FinancialColumns -contains $c) -or (Looks-Like-Financial-Column $c)) {
      $financialHits += $c
    }
  }

  $matchedCount = 0
  foreach ($row in $rows) {
    $sym = Get-Symbol-From-Row $row $symbolCandidates
    if ($TargetSymbols -contains $sym) {
      $matchedCount += 1
    }
  }

  $summary += [PSCustomObject]@{
    File = $file.FullName
    Rows = $rowCount
    HasSymbol = ($symbolCandidates.Count -gt 0)
    HasFinancialCols = ($financialHits.Count -gt 0)
    MatchedRows = $matchedCount
    FinancialColumnsFound = (($financialHits | Select-Object -Unique | Select-Object -First 20) -join ",")
    AllColumnsSample = (($cols | Select-Object -First 20) -join ",")
  }
}

$summary |
  Sort-Object HasFinancialCols, MatchedRows, Rows -Descending |
  Format-Table -AutoSize

Write-Host ""
Write-Host "## Matched rows and available financial values" -ForegroundColor Yellow

foreach ($file in $Files) {
  $rows = @()
  try {
    $rows = Import-Csv $file.FullName
  } catch {
    continue
  }

  if (!$rows -or $rows.Count -eq 0) { continue }

  $cols = @($rows[0].PSObject.Properties.Name)

  $symbolCandidates = @()
  foreach ($c in $cols) {
    if (($SymbolColumns -contains $c) -or (Looks-Like-Symbol-Column $c)) {
      $symbolCandidates += $c
    }
  }

  $financialHits = @()
  foreach ($c in $cols) {
    if (($FinancialColumns -contains $c) -or (Looks-Like-Financial-Column $c)) {
      $financialHits += $c
    }
  }

  $matched = @()
  foreach ($row in $rows) {
    $sym = Get-Symbol-From-Row $row $symbolCandidates
    if ($TargetSymbols -contains $sym) {
      $matched += $row
    }
  }

  if ($matched.Count -eq 0) { continue }

  Write-Host ""
  Write-Host ("[FILE] {0}" -f $file.FullName) -ForegroundColor Green

  foreach ($row in ($matched | Select-Object -First 20)) {
    $sym = Get-Symbol-From-Row $row $symbolCandidates
    $nm = Get-FirstValue $row $NameColumns

    $obj = [ordered]@{
      symbol = $sym
      name = $nm
    }

    foreach ($c in $financialHits) {
      if ($row.PSObject.Properties.Name -contains $c) {
        $v = [string]$row.$c
        if ($null -ne $v -and $v.Trim() -ne "") {
          $obj[$c] = $v.Trim()
        }
      }
    }

    [PSCustomObject]$obj | Format-List
  }
}

Write-Host ""
Write-Host "## Diagnosis guide" -ForegroundColor Yellow
Write-Host "MatchedRows = 0 means symbol mapping or stock coverage is missing."
Write-Host "HasFinancialCols = False means no EPS/PER/PBR/revenue-style columns were detected."
Write-Host "Values printed here but app still says connection needed means backend mapping needs patch."
Write-Host "No values printed means source collection probably lacks financial data."

Write-Host ""
Write-Host "=== Audit finished ===" -ForegroundColor Cyan
