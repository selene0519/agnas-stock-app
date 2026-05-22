from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ERROR_LOG_PATH = Path("logs") / "error_log.csv"
ERROR_LOG_COLUMNS = [
    "time_kst",
    "section",
    "level",
    "function_name",
    "market",
    "ticker",
    "message",
    "resolution",
]


def _now_kst() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_intraday_quote_event(
    section: str,
    level: str,
    *,
    function_name: str = "kis_us_quote",
    market: str = "",
    ticker: str = "",
    message: str = "",
    resolution: str = "",
) -> None:
    """logs/error_log.csv — KIS/Finnhub quote 실패·보조 수신 기록."""
    if not str(message or "").strip():
        return
    path = ERROR_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "time_kst": _now_kst(),
        "section": str(section or "intraday_quote"),
        "level": str(level or "warning"),
        "function_name": function_name,
        "market": market,
        "ticker": ticker,
        "message": str(message)[:500],
        "resolution": str(resolution)[:300],
    }
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ERROR_LOG_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
