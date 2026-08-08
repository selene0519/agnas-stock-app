"""Fetch and validate benchmark OHLCV used by market-regime calculations."""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
REPORTS_DIR = ROOT / "reports"
OHLCV_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

BENCHMARKS = [
    {"symbol": "KOSPI", "ticker": "^KS11", "fdr_ticker": "KS11", "pykrx_ticker": "1001", "market": "kr", "critical": True},
    {"symbol": "KOSDAQ", "ticker": "^KQ11", "fdr_ticker": "KQ11", "pykrx_ticker": "2001", "market": "kr", "critical": True},
    {"symbol": "SPY", "ticker": "SPY", "market": "us"},
    {"symbol": "QQQ", "ticker": "QQQ", "market": "us"},
    {"symbol": "SP500", "ticker": "^GSPC", "market": "us"},
    {"symbol": "USDKRW", "ticker": "KRW=X", "fdr_ticker": "USD/KRW", "market": "fx"},
]

HISTORY_PERIOD = "15y"
HISTORY_DAYS = 365 * 15 + 7
RECENT_OVERLAP_DAYS = 14


def _scalar(value: Any) -> float:
    """Convert a pandas scalar or one-element Series without warnings."""
    if hasattr(value, "iloc"):
        value = value.iloc[0]
    return float(value)


def _safe_int(value: Any) -> int:
    try:
        number = _scalar(value)
        return int(number) if math.isfinite(number) and number >= 0 else 0
    except Exception:
        return 0


def _valid_bar(row: dict[str, Any]) -> bool:
    try:
        open_, high, low, close = (_scalar(row[key]) for key in ("open", "high", "low", "close"))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    values = (open_, high, low, close)
    return (
        all(math.isfinite(value) and value > 0 for value in values)
        and high >= max(open_, close, low)
        and low <= min(open_, close, high)
    )


def _row(date_value: Any, source: str, open_: Any, high: Any, low: Any, close: Any, volume: Any = 0) -> dict[str, Any] | None:
    try:
        item = {
            "date": str(date_value.date() if hasattr(date_value, "date") else date_value)[:10],
            "open": round(_scalar(open_), 2),
            "high": round(_scalar(high), 2),
            "low": round(_scalar(low), 2),
            "close": round(_scalar(close), 2),
            "volume": _safe_int(volume),
            "source": source,
        }
    except Exception:
        return None
    return item if len(item["date"]) == 10 and _valid_bar(item) else None


def fetch_yfinance(ticker: str, period: str = HISTORY_PERIOD) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if df is None or df.empty:
            return []
        rows = [
            _row(day, "yfinance", row.get("Open"), row.get("High"), row.get("Low"), row.get("Close"), row.get("Volume", 0))
            for day, row in df.iterrows()
        ]
        return [row for row in rows if row is not None]
    except Exception as exc:
        print(f"  yfinance error for {ticker}: {exc}")
        return []


def fetch_fdr(ticker: str, period_days: int = HISTORY_DAYS) -> list[dict[str, Any]]:
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
        df = fdr.DataReader(ticker, start=start)
        if df is None or df.empty:
            return []
        rows = [
            _row(day, "FinanceDataReader", row.get("Open"), row.get("High"), row.get("Low"), row.get("Close"), row.get("Volume", 0))
            for day, row in df.iterrows()
        ]
        return [row for row in rows if row is not None]
    except Exception as exc:
        print(f"  FinanceDataReader error for {ticker}: {exc}")
        return []


def fetch_pykrx_index(ticker: str, period_days: int = HISTORY_DAYS) -> list[dict[str, Any]]:
    try:
        from pykrx import stock
        start = (datetime.now() - timedelta(days=period_days)).strftime("%Y%m%d")
        end = datetime.now().strftime("%Y%m%d")
        df = stock.get_index_ohlcv_by_date(start, end, ticker)
        if df is None or df.empty:
            return []
        rows = [
            _row(day, "pykrx", row.get("시가"), row.get("고가"), row.get("저가"), row.get("종가"), row.get("거래량", 0))
            for day, row in df.iterrows()
        ]
        return [row for row in rows if row is not None]
    except Exception as exc:
        print(f"  pykrx error for {ticker}: {exc}")
        return []


def _read_existing(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists() or path.stat().st_size == 0:
        return [], 0
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            raw = [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return [], 0
    newest = max(
        (str(row.get("date") or row.get("Date") or "")[:10] for row in raw),
        default="",
    )
    recent_cutoff = (
        (datetime.fromisoformat(newest) - timedelta(days=RECENT_OVERLAP_DAYS)).strftime("%Y-%m-%d")
        if newest
        else ""
    )
    valid: list[dict[str, Any]] = []
    invalid = 0
    for row in raw:
        day = str(row.get("date") or row.get("Date") or "")[:10]
        normalized = {
            "date": day,
            "open": row.get("open") or row.get("Open"),
            "high": row.get("high") or row.get("High"),
            "low": row.get("low") or row.get("Low"),
            "close": row.get("close") or row.get("Close"),
            "volume": _safe_int(row.get("volume") or row.get("Volume") or 0),
            "source": row.get("source") or "existing",
            "updatedAt": row.get("updatedAt") or "",
        }
        # Preserve immutable old history even when a legacy provider stored an
        # incomplete bar.  Recent invalid rows are dropped and replaced from
        # the current provider so a cleanup cannot silently shrink 15 years.
        is_recent = not recent_cutoff or day >= recent_cutoff
        if _valid_bar(normalized) or not is_recent:
            valid.append(normalized)
        else:
            invalid += 1
    return valid, invalid


def _merge_recent(existing: list[dict[str, Any]], fetched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed = {str(row["date"]): row for row in existing}
    newest = max(keyed, default="")
    cutoff = (datetime.fromisoformat(newest) - timedelta(days=RECENT_OVERLAP_DAYS)).strftime("%Y-%m-%d") if newest else ""
    for row in fetched:
        day = str(row.get("date") or "")[:10]
        if day and _valid_bar(row) and (not cutoff or day >= cutoff or day not in keyed):
            keyed[day] = row
    return [keyed[key] for key in sorted(keyed)]


def write_csv(path: Path, rows: list[dict[str, Any]], symbol: str, market: str) -> None:
    fields = ["date", "market", "symbol", "open", "high", "low", "close", "volume", "source", "updatedAt"]
    now = datetime.now().isoformat(timespec="seconds")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "date": row["date"], "market": market, "symbol": symbol,
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
                "volume": row.get("volume", 0), "source": row.get("source") or "unknown",
                "updatedAt": row.get("updatedAt") or now,
            })


def _fetch(bm: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    rows = fetch_yfinance(str(bm["ticker"]))
    if rows:
        return rows, "yfinance"
    rows = fetch_fdr(str(bm.get("fdr_ticker") or bm["ticker"]))
    if rows:
        return rows, "FinanceDataReader"
    if bm["market"] == "kr":
        rows = fetch_pykrx_index(str(bm["pykrx_ticker"]))
        if rows:
            return rows, "pykrx"
    return [], "unavailable"


def main() -> int:
    results: list[dict[str, Any]] = []
    critical_failures = 0
    for bm in BENCHMARKS:
        symbol, market = str(bm["symbol"]), str(bm["market"])
        output = OHLCV_DIR / f"{market}_{symbol}_daily.csv"
        print(f"Fetching {symbol} ({bm['ticker']})...")
        existing, removed_invalid = _read_existing(output)
        fetched, source = _fetch(bm)
        merged = _merge_recent(existing, fetched) if fetched else existing
        ok = bool(fetched and merged and _valid_bar(merged[-1]))
        if ok:
            write_csv(output, merged, symbol, market)
            print(f"  saved {output.name} ({len(merged)} rows, latest={merged[-1]['date']}, source={source})")
        else:
            print(f"  no valid fresh data: {symbol}; existing history preserved")
        critical = bool(bm.get("critical"))
        critical_failures += int(critical and not ok)
        results.append({
            "symbol": symbol, "market": market, "rows": len(merged), "fetchedRows": len(fetched),
            "latestDate": merged[-1]["date"] if merged else None, "source": source,
            "removedInvalidRows": removed_invalid, "critical": critical, "ok": ok,
        })

    status = {
        "status": "ERROR" if critical_failures else "OK",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "criticalFailures": critical_failures,
        "benchmarks": results,
    }
    (REPORTS_DIR / "benchmark_fetch_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print("completed:", json.dumps(results, ensure_ascii=False))
    return 1 if critical_failures else 0


if __name__ == "__main__":
    sys.exit(main())
