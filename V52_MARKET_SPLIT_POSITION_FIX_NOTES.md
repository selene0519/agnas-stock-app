# v52 market split / position value fix

## Fixes
- Removed the combined market option from general screens. Only `국장` and `미장` are shown.
- Standardized `매수 위험·제외` to one canonical report to avoid inconsistent counts from old hard-block-only pages.
- Rebuilt the position sizing report from actual holdings files first, then fallback reports.
- Position rows are not removed just because price is missing. Current price is filled from saved quote reports, yfinance, or FinanceDataReader where possible.
- Placeholder rows such as `None/nan` without a real symbol are excluded because they are not real holdings.

## How to run
`START_HERE_V52_FIXED.bat`

## Manual update
`run_v52_daily_update.bat`
