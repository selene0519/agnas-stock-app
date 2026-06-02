"""
벤치마크 지수 OHLCV 수집 스크립트.
KOSPI (^KS11), KOSDAQ (^KQ11), S&P500 (^GSPC) 일별 데이터를 저장합니다.

출력: data/market/ohlcv/kr_KOSPI_daily.csv
      data/market/ohlcv/kr_KOSDAQ_daily.csv
      data/market/ohlcv/us_SP500_daily.csv
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT     = Path(__file__).resolve().parents[1]
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
OHLCV_DIR.mkdir(parents=True, exist_ok=True)

BENCHMARKS = [
    {"symbol": "KOSPI",  "ticker": "^KS11",  "market": "kr"},
    {"symbol": "KOSDAQ", "ticker": "^KQ11",  "market": "kr"},
    {"symbol": "SP500",  "ticker": "^GSPC",  "market": "us"},
]


def fetch_yfinance(ticker: str, period: str = "2y") -> list[dict[str, Any]]:
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if df.empty:
            return []
        rows = []
        for date, row in df.iterrows():
            rows.append({
                "date":   str(date.date()),
                "open":   round(float(row["Open"]), 2),
                "high":   round(float(row["High"]), 2),
                "low":    round(float(row["Low"]), 2),
                "close":  round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return rows
    except Exception as e:
        print(f"  yfinance error for {ticker}: {e}")
        return []


def fetch_fdr(ticker: str, period_days: int = 730) -> list[dict[str, Any]]:
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
        df = fdr.DataReader(ticker, start=start)
        if df is None or df.empty:
            return []
        rows = []
        for date, row in df.iterrows():
            rows.append({
                "date":   str(date.date()),
                "open":   round(float(row.get("Open", 0)), 2),
                "high":   round(float(row.get("High", 0)), 2),
                "low":    round(float(row.get("Low",  0)), 2),
                "close":  round(float(row.get("Close", 0)), 2),
                "volume": int(row.get("Volume", 0)),
            })
        return rows
    except Exception as e:
        print(f"  FinanceDataReader error for {ticker}: {e}")
        return []


def write_csv(path: Path, rows: list[dict[str, Any]], symbol: str, market: str) -> None:
    fieldnames = ["date", "market", "symbol", "open", "high", "low", "close", "volume", "source", "updatedAt"]
    now = datetime.now().isoformat(timespec="seconds")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({
                "date":      row["date"],
                "market":    market,
                "symbol":    symbol,
                "open":      row["open"],
                "high":      row["high"],
                "low":       row["low"],
                "close":     row["close"],
                "volume":    row["volume"],
                "source":    "yfinance/fdr",
                "updatedAt": now,
            })


def main() -> None:
    results = []
    for bm in BENCHMARKS:
        sym    = bm["symbol"]
        ticker = bm["ticker"]
        market = bm["market"]
        out    = OHLCV_DIR / f"{market}_{sym}_daily.csv"

        print(f"Fetching {sym} ({ticker})...")
        rows = fetch_yfinance(ticker) or fetch_fdr(ticker)

        if rows:
            write_csv(out, rows, sym, market)
            print(f"  저장: {out.name}  ({len(rows)}행)")
            results.append({"symbol": sym, "rows": len(rows), "ok": True})
        else:
            print(f"  데이터 없음: {sym}")
            results.append({"symbol": sym, "rows": 0, "ok": False})

    status = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "benchmarks": results,
    }
    (ROOT / "reports" / "benchmark_fetch_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("완료:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
