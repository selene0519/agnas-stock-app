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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OHLCV_DIR = REPO / "data" / "market" / "ohlcv"
REPORTS = REPO / "reports"
DATA_STOCKAPP = REPO / "data" / "stockapp"

# ET 기준 오늘 날짜 (미국 현지 날짜)
def _et_today() -> str:
    et = datetime.now(timezone(timedelta(hours=-4)))  # EDT (summer)
    return et.strftime("%Y-%m-%d")

TARGET_DATE = os.environ.get("MONE_US_CLOSE_DATE") or _et_today()


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


def _target_symbols(limit: int = 200) -> list[str]:
    """기존 OHLCV 파일 목록 + watchlist/holdings/추천 파일에서 심볼 수집."""
    symbols: set[str] = set()

    # 기존 OHLCV 파일에서 심볼 추출
    for p in OHLCV_DIR.glob("us_*_daily.csv"):
        m = re.match(r"us_(.+)_daily\.csv", p.name)
        if m:
            sym = _valid_us_symbol(m.group(1))
            if sym:
                symbols.add(sym)

    # watchlist/holdings/추천 파일에서 추가
    extra_paths = [
        REPO / "watchlist_us.csv",
        REPO / "watchlist_us_growth.csv",
        REPO / "holdings_us.csv",
        REPO / "candidate_universe_us.csv",
        DATA_STOCKAPP / "price_collection_universe_us.csv",
        REPORTS / "virtual_prediction_ledger.csv",
        REPORTS / "virtual_validation_results.csv",
    ]
    extra_paths.extend(sorted(REPORTS.glob("mone_v36_final_recommendations_us_*.csv")))
    for path in extra_paths:
        for row in _read_csv(path):
            sym = _valid_us_symbol(row.get("symbol") or row.get("ticker"))
            if sym:
                symbols.add(sym)

    return sorted(symbols)[:limit]


def _existing_latest_date(symbol: str) -> str:
    path = OHLCV_DIR / f"us_{symbol}_daily.csv"
    rows = _read_csv(path)
    if not rows:
        return ""
    dates = [str(r.get("date") or r.get("Date") or "")[:10] for r in rows]
    return max((d for d in dates if d), default="")


def _fetch_yfinance(symbol: str, start: str) -> list[dict] | None:
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return None
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, interval="1d", auto_adjust=False)
        if df is None or df.empty:
            return None
        df = df.reset_index()
        rows = []
        for _, rec in df.iterrows():
            date_val = str(rec.get("Date") or rec.get("Datetime") or "")[:10]
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


FIELDNAMES = ["date", "market", "symbol", "name", "open", "high", "low", "close", "volume", "source"]


def _merge_and_save(symbol: str, new_rows: list[dict]) -> None:
    path = OHLCV_DIR / f"us_{symbol}_daily.csv"
    existing = _read_csv(path)
    keyed: dict[str, dict] = {
        str(r.get("date") or r.get("Date") or "")[:10]: r
        for r in existing
        if str(r.get("date") or r.get("Date") or "")[:10]
    }
    for row in new_rows:
        d = str(row.get("date") or "")[:10]
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
    if latest >= TARGET_DATE:
        return {"symbol": symbol, "status": "SKIP", "latestDate": latest}

    # 기존 데이터가 없거나 오래되면 최근 9개월 전체 수집, 그 외엔 3일치만
    fetch_start = latest if latest else "2025-09-01"
    new_rows = _fetch_yfinance(symbol, fetch_start)
    if not new_rows:
        return {"symbol": symbol, "status": "NO_DATA", "latestDate": latest}

    _merge_and_save(symbol, new_rows)
    new_latest = max((r["date"] for r in new_rows), default=latest)
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

    status = {
        "status": "OK" if ok > 0 else ("SKIP" if skip > 0 else "NO_DATA"),
        "market": "us",
        "targetDate": TARGET_DATE,
        "targetCount": len(symbols),
        "updatedCount": ok,
        "skippedCount": skip,
        "failedCount": failed,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "message": f"US OHLCV {ok}종목 갱신, {skip}종목 스킵(최신), {failed}종목 실패",
    }
    (REPORTS / "us_close_ohlcv_refresh_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
