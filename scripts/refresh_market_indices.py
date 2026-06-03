"""
시장 지수 OHLCV 일별 수집 스크립트.
기존 fetch_benchmark_data.py 는 월 1회 실행이라 비교차트에 쓰기 어려움.
이 스크립트는 매일 실행 → 지수 CSV를 최신 상태로 유지.

저장 위치:
    data/market/ohlcv/kr_KOSPI_daily.csv
    data/market/ohlcv/kr_KOSDAQ_daily.csv
    data/market/ohlcv/us_SPY_daily.csv
    data/market/ohlcv/us_QQQ_daily.csv
    data/market/ohlcv/us_SP500_daily.csv
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT      = Path(__file__).resolve().parents[1]
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
OHLCV_DIR.mkdir(parents=True, exist_ok=True)

KST = timezone(timedelta(hours=9))

INDICES = [
    # KR
    {"symbol": "KOSPI",  "ticker": "^KS11",  "market": "kr"},
    {"symbol": "KOSDAQ", "ticker": "^KQ11",  "market": "kr"},
    # US (ETF: daily updated)
    {"symbol": "SPY",    "ticker": "SPY",    "market": "us"},
    {"symbol": "QQQ",    "ticker": "QQQ",    "market": "us"},
    {"symbol": "SP500",  "ticker": "^GSPC",  "market": "us"},
]

FIELDNAMES = ["date", "open", "high", "low", "close", "volume", "source"]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
                "open":   round(float(row["Open"].iloc[0] if hasattr(row["Open"], "iloc") else row["Open"]), 2),
                "high":   round(float(row["High"].iloc[0] if hasattr(row["High"], "iloc") else row["High"]), 2),
                "low":    round(float(row["Low"].iloc[0] if hasattr(row["Low"], "iloc") else row["Low"]), 2),
                "close":  round(float(row["Close"].iloc[0] if hasattr(row["Close"], "iloc") else row["Close"]), 2),
                "volume": int(row["Volume"].iloc[0] if hasattr(row["Volume"], "iloc") else row["Volume"]),
                "source": "yfinance",
            })
        return sorted(rows, key=lambda r: r["date"])
    except Exception as e:
        print(f"  yfinance {ticker}: {e}")
        return []


def fetch_pykrx(symbol: str) -> list[dict[str, Any]]:
    """pykrx로 KOSPI/KOSDAQ 지수 데이터 수집 (KRX 공식)."""
    try:
        from pykrx import stock
        # 최근 2년치
        end = datetime.now(KST).strftime("%Y%m%d")
        start = (datetime.now(KST) - timedelta(days=730)).strftime("%Y%m%d")
        ticker_map = {"KOSPI": "1001", "KOSDAQ": "2001", "KOSPI200": "1028"}
        ticker = ticker_map.get(symbol)
        if not ticker:
            return []
        df = stock.get_index_ohlcv_by_date(start, end, ticker)
        if df is None or df.empty:
            return []
        rows = []
        for date, row in df.iterrows():
            rows.append({
                "date":   str(date.date()),
                "open":   round(float(row.get("시가", row.get("Open", 0))), 2),
                "high":   round(float(row.get("고가", row.get("High", 0))), 2),
                "low":    round(float(row.get("저가", row.get("Low", 0))), 2),
                "close":  round(float(row.get("종가", row.get("Close", 0))), 2),
                "volume": int(row.get("거래량", row.get("Volume", 0))),
                "source": "pykrx",
            })
        return sorted(rows, key=lambda r: r["date"])
    except Exception as e:
        print(f"  pykrx {symbol}: {e}")
        return []


def merge_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    """기존 + 신규 병합 (날짜 기준 dedup, 최신 우선)."""
    by_date = {r["date"]: r for r in existing}
    for r in new_rows:
        by_date[r["date"]] = r  # 신규 덮어쓰기
    return sorted(by_date.values(), key=lambda r: r["date"])


def refresh_index(symbol: str, ticker: str, market: str) -> bool:
    path = OHLCV_DIR / f"{market}_{symbol}_daily.csv"
    existing = _read_csv(path)
    today = datetime.now(KST).strftime("%Y-%m-%d")

    # 오늘 데이터가 이미 있으면 skip
    if existing and existing[-1].get("date") == today:
        print(f"  [{symbol}] 이미 최신 ({today})")
        return True

    # KR 지수: pykrx 우선, 실패 시 yfinance
    if market == "kr" and symbol in ("KOSPI", "KOSDAQ"):
        new_rows = fetch_pykrx(symbol)
        if not new_rows:
            new_rows = fetch_yfinance(ticker)
    else:
        new_rows = fetch_yfinance(ticker)

    if not new_rows:
        print(f"  [{symbol}] 데이터 없음")
        return False

    merged = merge_rows(existing, new_rows)
    _write_csv(path, merged)
    print(f"  [{symbol}] {path.name} 저장 ({len(merged)}행, 최신 {merged[-1]['date']})")
    return True


def main() -> None:
    print(f"[지수수집] {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST")
    results = {}
    for idx in INDICES:
        ok = refresh_index(idx["symbol"], idx["ticker"], idx["market"])
        results[idx["symbol"]] = "OK" if ok else "FAIL"
    print(f"[지수수집] 결과: {results}")


if __name__ == "__main__":
    main()
