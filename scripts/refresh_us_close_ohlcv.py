"""
scripts/refresh_us_close_ohlcv.py
----------------------------------
미국 장 마감 후 US OHLCV 데이터를 yfinance로 갱신한다.
KR의 refresh_kr_close_ohlcv.py에 대응하는 미장 버전.

사용:
  python scripts/refresh_us_close_ohlcv.py
  MONE_US_CLOSE_DATE=2026-06-12 python scripts/refresh_us_close_ohlcv.py

출력:
  data/market/ohlcv/us_{symbol}_daily.csv  (각 종목별 추가/갱신)
  reports/us_close_ohlcv_refresh_status.json
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from scripts.symbol_lifecycle import inactive_symbols
except ModuleNotFoundError:  # direct `python scripts/...py` execution
    from symbol_lifecycle import inactive_symbols

REPO = Path(__file__).resolve().parents[1]
OHLCV_DIR = REPO / "data" / "market" / "ohlcv"
REPORTS = REPO / "reports"
DATA_STOCKAPP = REPO / "data" / "stockapp"

# Internal benchmark labels are valid local filenames and journal symbols, but
# are not Yahoo tickers.  Keep the internal symbol stable while fetching with
# the vendor code.
YAHOO_SYMBOL_ALIASES = {"SP500": "^GSPC", "GSPC": "^GSPC"}

def _normalize_date(value: object) -> str:
    """Return an ISO calendar date, including recovery of compact YYYYMMDD rows."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    else:
        text = text[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except (TypeError, ValueError):
        return ""


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    cursor = date(year, month, 1)
    return cursor + timedelta(days=(weekday - cursor.weekday()) % 7 + (nth - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    cursor = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter_sunday(year: int) -> date:
    """Gregorian Easter (Anonymous Gregorian computus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    month_seed = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * month_seed) // 451
    month = (h + month_seed - 7 * m + 114) // 31
    day = (h + month_seed - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _us_market_holidays(year: int) -> set[date]:
    # Include the observed New Year's Day for the following year because it can
    # fall on December 31 of this year.
    return {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
        _observed(date(year + 1, 1, 1)),
    }


def _is_us_session(day: date) -> bool:
    return day.weekday() < 5 and day not in _us_market_holidays(day.year)


def _latest_completed_us_session(now: datetime | None = None) -> str:
    """Latest session whose regular close should be available from the vendor."""
    utc_now = now or datetime.now(timezone.utc)
    if utc_now.tzinfo is None:
        utc_now = utc_now.replace(tzinfo=timezone.utc)
    try:
        ny_now = utc_now.astimezone(ZoneInfo("America/New_York"))
    except ZoneInfoNotFoundError:  # minimal Windows runners without tzdata
        ny_now = utc_now.astimezone(timezone(timedelta(hours=-5)))
    cursor = ny_now.date()
    if ny_now.time() < time(16, 15):
        cursor -= timedelta(days=1)
    while not _is_us_session(cursor):
        cursor -= timedelta(days=1)
    return cursor.isoformat()


TARGET_DATE = _normalize_date(os.environ.get("MONE_US_CLOSE_DATE")) or _latest_completed_us_session()
# When set, force a full daily-history backfill even when the local file is
# current.  This keeps the normal close-refresh cheap while allowing research
# jobs to build a common pre-2022 sample without a second collector.
HISTORY_START = _normalize_date(os.environ.get("MONE_US_HISTORY_START"))


def _ensure_pkg(package: str, import_name: str | None = None) -> bool:
    import_name = import_name or package
    try:
        __import__(import_name)
        return True
    except Exception:
        pass
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        __import__(import_name)
        return True
    except Exception as exc:
        print(f"[WARN] cannot install/import {package}: {exc}")
        return False


def _read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _num(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "None", "nan", "NaN"}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _valid_us_symbol(value: object) -> str:
    sym = str(value or "").strip().upper()
    if sym in {"", "NAN", "NA", "NONE", "NULL"}:
        return ""
    return sym if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", sym) else ""


def _yahoo_symbol(symbol: str) -> str:
    return YAHOO_SYMBOL_ALIASES.get(symbol.upper(), symbol)


def _target_symbols(limit: int = 200) -> list[str]:
    """기존 OHLCV 파일 목록 + watchlist/holdings/추천 파일에서 심볼 수집."""
    symbols: set[str] = set()
    inactive = inactive_symbols("us")

    # 기존 OHLCV 파일에서 심볼 추출
    for p in OHLCV_DIR.glob("us_*_daily.csv"):
        m = re.match(r"us_(.+)_daily\.csv", p.name)
        if m:
            sym = _valid_us_symbol(m.group(1))
            if sym and sym not in inactive:
                symbols.add(sym)

    # watchlist/holdings/추천 파일에서 추가
    extra_paths = [
        REPO / "watchlist_us.csv",
        REPO / "watchlist_us_growth.csv",
        REPO / "holdings_us.csv",
        # 브로커 원장의 미국 보유(토스 소수점 등)도 포함. toss_holdings_kr.csv는
        # 파일명이 kr이지만 안에 us 종목이 들어 있어 _valid_us_symbol이 걸러낸다.
        REPO / "data" / "holdings_us.csv",
        REPO / "data" / "kis_2_holdings_us.csv",
        REPO / "data" / "kis_holdings_us.csv",
        REPO / "data" / "toss_holdings_us.csv",
        REPO / "data" / "toss_holdings_kr.csv",
        REPO / "candidate_universe_us.csv",
        DATA_STOCKAPP / "price_collection_universe_us.csv",
        REPORTS / "virtual_prediction_ledger.csv",
        REPORTS / "virtual_validation_results.csv",
    ]
    extra_paths.extend(sorted(REPORTS.glob("mone_v36_final_recommendations_us_*.csv")))
    for path in extra_paths:
        for row in _read_csv(path):
            sym = _valid_us_symbol(row.get("symbol") or row.get("ticker"))
            if sym and sym not in inactive:
                symbols.add(sym)

    return sorted(symbols)[:limit]


def _existing_latest_date(symbol: str) -> str:
    path = OHLCV_DIR / f"us_{symbol}_daily.csv"
    rows = _read_csv(path)
    if not rows:
        return ""
    dates = [_normalize_date(r.get("date") or r.get("Date")) for r in rows]
    return max((d for d in dates if d), default="")


def _fetch_yfinance(symbol: str, start: str) -> list[dict] | None:
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return None
    try:
        ticker = yf.Ticker(_yahoo_symbol(symbol))
        df = ticker.history(start=start, interval="1d", auto_adjust=False)
        if df is None or df.empty:
            return None
        df = df.reset_index()
        rows = []
        for _, rec in df.iterrows():
            date_val = _normalize_date(rec.get("Date") or rec.get("Datetime"))
            close = _num(rec.get("Close"))
            if not date_val or close is None or close <= 0:
                continue
            rows.append({
                "date": date_val,
                "symbol": symbol,
                "name": symbol,
                "open": rec.get("Open", ""),
                "high": rec.get("High", ""),
                "low": rec.get("Low", ""),
                "close": close,
                "volume": rec.get("Volume", ""),
                "source": f"Yahoo Finance {symbol}",
            })
        return rows if rows else None
    except Exception as exc:
        print(f"  [WARN] yfinance {symbol}: {exc}")
        return None


def _fetch_yahoo_chart(symbol: str, start: str) -> list[dict] | None:
    """Dependency-free fallback when yfinance parsing/cookies fail for one symbol."""
    try:
        start_day = date.fromisoformat(_normalize_date(start))
        period1 = int(datetime.combine(start_day, time.min, tzinfo=timezone.utc).timestamp())
        period2 = int(datetime.now(timezone.utc).timestamp()) + 86400
        query = urlencode({
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "history",
        })
        request = Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{_yahoo_symbol(symbol)}?{query}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = (((payload.get("chart") or {}).get("result") or [None])[0]) or {}
        timestamps = result.get("timestamp") or []
        quote = ((((result.get("indicators") or {}).get("quote") or [None])[0]) or {})
        rows = []
        for index, timestamp in enumerate(timestamps):
            closes = quote.get("close") or []
            close = _num(closes[index] if index < len(closes) else None)
            if close is None or close <= 0:
                continue

            def value(key: str) -> object:
                values = quote.get(key) or []
                return values[index] if index < len(values) and values[index] is not None else ""

            rows.append({
                "date": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat(),
                "symbol": symbol,
                "name": symbol,
                "open": value("open"),
                "high": value("high"),
                "low": value("low"),
                "close": close,
                "volume": value("volume"),
                "source": f"Yahoo Chart {symbol}",
            })
        return rows or None
    except Exception as exc:
        print(f"  [WARN] yahoo chart {symbol}: {exc}")
        return None


FIELDNAMES = ["date", "market", "symbol", "name", "open", "high", "low", "close", "volume", "source"]


def _merge_and_save(symbol: str, new_rows: list[dict]) -> None:
    path = OHLCV_DIR / f"us_{symbol}_daily.csv"
    existing = _read_csv(path)
    keyed: dict[str, dict] = {}
    for row in existing:
        existing_date = _normalize_date(row.get("date") or row.get("Date"))
        if existing_date:
            normalized = dict(row)
            normalized["date"] = existing_date
            keyed[existing_date] = normalized
    for row in new_rows:
        d = _normalize_date(row.get("date"))
        if d:
            keyed[d] = {
                "date": d,
                "market": "us",
                "symbol": symbol,
                "name": row.get("name", symbol),
                "open": row.get("open") or row.get("Open") or "",
                "high": row.get("high") or row.get("High") or "",
                "low": row.get("low") or row.get("Low") or "",
                "close": row.get("close") or row.get("Close") or "",
                "volume": row.get("volume") or row.get("Volume") or "",
                "source": row.get("source", "Yahoo Finance"),
            }
    sorted_rows = [keyed[k] for k in sorted(keyed)]
    _write_csv(path, sorted_rows, FIELDNAMES)


def _process_symbol(symbol: str) -> dict:
    latest = _existing_latest_date(symbol)
    # 이미 오늘 데이터가 있으면 스킵
    if not HISTORY_START and latest >= TARGET_DATE:
        return {"symbol": symbol, "status": "SKIP", "latestDate": latest}

    # 기존 데이터가 없거나 오래되면 최근 9개월 전체 수집, 그 외엔 3일치만
    fetch_start = HISTORY_START or (latest if latest else "2025-09-01")
    new_rows = _fetch_yfinance(symbol, fetch_start) or _fetch_yahoo_chart(symbol, fetch_start)
    if not new_rows:
        return {"symbol": symbol, "status": "NO_DATA", "latestDate": latest}

    _merge_and_save(symbol, new_rows)
    new_latest = max((_normalize_date(r.get("date")) for r in new_rows), default=latest)
    if not HISTORY_START and new_latest < TARGET_DATE:
        return {"symbol": symbol, "status": "NO_CURRENT_BAR", "latestDate": new_latest}
    return {"symbol": symbol, "status": "OK", "latestDate": new_latest}


def main() -> None:
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    if not _ensure_pkg("yfinance"):
        print("[ERROR] yfinance 설치 실패 — US OHLCV 갱신 불가")
        sys.exit(1)

    limit = int(os.environ.get("MONE_US_CLOSE_OHLCV_LIMIT", "150"))
    workers = max(1, min(int(os.environ.get("MONE_US_CLOSE_OHLCV_WORKERS", "8")), 12))
    symbols = _target_symbols(limit=limit)

    print(f"[refresh_us_close_ohlcv] TARGET_DATE={TARGET_DATE}, symbols={len(symbols)}, workers={workers}")

    results = []
    ok = skip = failed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process_symbol, sym): sym for sym in symbols}
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            if row["status"] == "OK":
                ok += 1
            elif row["status"] == "SKIP":
                skip += 1
            else:
                failed += 1

    failed_items = [
        row for row in sorted(results, key=lambda item: item["symbol"])
        if row["status"] not in {"OK", "SKIP"}
    ]
    overall = "WARN" if failed and (ok or skip) else (
        "NO_DATA" if failed else ("OK" if ok else ("SKIP" if skip else "NO_DATA"))
    )
    status = {
        "status": overall,
        "market": "us",
        "targetDate": TARGET_DATE,
        "historyStart": HISTORY_START or None,
        "targetCount": len(symbols),
        "updatedCount": ok,
        "skippedCount": skip,
        "failedCount": failed,
        "failedItems": failed_items,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "message": f"US OHLCV {ok}종목 갱신, {skip}종목 스킵(최신), {failed}종목 실패",
    }
    (REPORTS / "us_close_ohlcv_refresh_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
