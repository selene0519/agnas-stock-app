from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[1]
STOCKAPP = REPO / "data" / "stockapp"
OHLCV_DIR = REPO / "data" / "market" / "ohlcv"
REPORTS = REPO / "reports"
TARGET_DATE = os.environ.get("MONE_CLOSE_DATE") or datetime.now().strftime("%Y-%m-%d")
TARGET_YYYYMMDD = TARGET_DATE.replace("-", "")


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
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
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


def _norm_kr_symbol(value: object) -> str:
    raw = re.sub(r"\D", "", str(value or ""))
    return raw.zfill(6)[-6:] if raw else ""


def _num(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("₩", "").strip()
    if text in {"", "-", "None", "nan", "NaN"}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _target_universe(limit: int = 200) -> list[dict]:
    paths = [
        STOCKAPP / "price_collection_universe_kr.csv",
        STOCKAPP / "kis_collection_targets_kr.csv",
        REPO / "holdings_kr.csv",
        REPO / "data" / "holdings_kr.csv",
        REPO / "watchlist_kr.csv",
        REPO / "data" / "watchlist_kr.csv",
    ]
    paths.extend(sorted(REPORTS.glob("mone_v36_final_recommendations_kr_*.csv")))
    keyed: dict[str, dict] = {}
    for path in paths:
        for row in _read_csv(path):
            sym = _norm_kr_symbol(row.get("symbol") or row.get("ticker") or row.get("code") or row.get("종목코드"))
            if not sym:
                continue
            name = str(row.get("name") or row.get("companyName") or row.get("종목명") or sym).strip()
            item = keyed.setdefault(sym, {"market": "kr", "symbol": sym, "name": name, "sources": set()})
            if name and item.get("name") == sym:
                item["name"] = name
            item["sources"].add(path.name)
    out = []
    for item in keyed.values():
        item["sources"] = "|".join(sorted(item["sources"]))
        out.append(item)
    return sorted(out, key=lambda r: r["symbol"])[:limit]


def _existing_rows(symbol: str) -> list[dict]:
    path = OHLCV_DIR / f"kr_{symbol}_daily.csv"
    rows = _read_csv(path)
    if not rows:
        alt = REPORTS / f"kr_{symbol}_daily.csv"
        rows = _read_csv(alt)
    return rows


def _fetch_fdr(symbol: str, start: str, end: str) -> dict | None:
    if not _ensure_pkg("finance-datareader", "FinanceDataReader"):
        return None
    try:
        import FinanceDataReader as fdr  # type: ignore
        df = fdr.DataReader(symbol, start, end)
        if df is None or df.empty:
            return None
        df = df.reset_index()
        row = df.iloc[-1].to_dict()
        date_value = row.get("Date") or row.get("date")
        date_text = str(date_value)[:10]
        if date_text != TARGET_DATE:
            return None
        return {
            "date": date_text,
            "market": "kr",
            "symbol": symbol,
            "open": row.get("Open", ""),
            "high": row.get("High", ""),
            "low": row.get("Low", ""),
            "close": row.get("Close", ""),
            "volume": row.get("Volume", ""),
            "tradingValue": row.get("Change", ""),
            "source": "FinanceDataReader",
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as exc:
        print(f"[WARN] FDR {symbol} failed: {exc}")
        return None


def _fetch_pykrx(symbol: str) -> dict | None:
    if not _ensure_pkg("pykrx"):
        return None
    try:
        from pykrx import stock  # type: ignore
        df = stock.get_market_ohlcv_by_date(TARGET_YYYYMMDD, TARGET_YYYYMMDD, symbol)
        if df is None or df.empty:
            return None
        row = df.iloc[-1].to_dict()
        return {
            "date": TARGET_DATE,
            "market": "kr",
            "symbol": symbol,
            "open": row.get("시가", ""),
            "high": row.get("고가", ""),
            "low": row.get("저가", ""),
            "close": row.get("종가", ""),
            "volume": row.get("거래량", ""),
            "tradingValue": row.get("거래대금", ""),
            "source": "pykrx",
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as exc:
        print(f"[WARN] pykrx {symbol} failed: {exc}")
        return None


def _merge_daily(symbol: str, new_row: dict) -> None:
    path = OHLCV_DIR / f"kr_{symbol}_daily.csv"
    rows = _existing_rows(symbol)
    keyed = {str(r.get("date") or r.get("Date") or "")[:10]: r for r in rows if str(r.get("date") or r.get("Date") or "")}
    keyed[TARGET_DATE] = new_row
    fieldnames = ["date", "market", "symbol", "open", "high", "low", "close", "volume", "tradingValue", "source", "updatedAt"]
    normalized = []
    for key in sorted(keyed):
        row = keyed[key]
        normalized.append({
            "date": str(row.get("date") or row.get("Date") or key)[:10],
            "market": "kr",
            "symbol": symbol,
            "open": row.get("open") or row.get("Open") or row.get("시가") or "",
            "high": row.get("high") or row.get("High") or row.get("고가") or "",
            "low": row.get("low") or row.get("Low") or row.get("저가") or "",
            "close": row.get("close") or row.get("Close") or row.get("종가") or "",
            "volume": row.get("volume") or row.get("Volume") or row.get("거래량") or "",
            "tradingValue": row.get("tradingValue") or row.get("거래대금") or "",
            "source": row.get("source") or row.get("Source") or "existing",
            "updatedAt": row.get("updatedAt") or "",
        })
    _write_csv(path, normalized, fieldnames)


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    limit = int(os.environ.get("MONE_KR_CLOSE_OHLCV_LIMIT", "120"))
    workers = max(1, min(int(os.environ.get("MONE_KR_CLOSE_OHLCV_WORKERS", "6")), 12))
    targets = _target_universe(limit=limit)
    rows = []
    success = 0
    failed = 0
    _ensure_pkg("finance-datareader", "FinanceDataReader")
    _ensure_pkg("pykrx")

    def process_target(target: dict) -> dict:
        symbol = target["symbol"]
        fetched = _fetch_fdr(symbol, TARGET_DATE, TARGET_DATE) or _fetch_pykrx(symbol)
        if fetched and all(_num(fetched.get(k)) is not None for k in ("open", "high", "low", "close")):
            _merge_daily(symbol, fetched)
            return {**target, "date": TARGET_DATE, "status": "OK", "dataStatus": "NORMAL", "missingReason": "", "ohlcvSource": fetched.get("source")}
        return {**target, "date": TARGET_DATE, "status": "NO_DATA", "dataStatus": "DATA_PENDING", "missingReason": "close_ohlcv_not_collected", "ohlcvSource": ""}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(process_target, target) for target in targets]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            if row.get("status") == "OK":
                success += 1
            else:
                failed += 1

    rows.sort(key=lambda row: row.get("symbol", ""))
    _write_csv(REPORTS / "kr_close_ohlcv_coverage_audit.csv", rows, ["market", "symbol", "name", "sources", "date", "status", "dataStatus", "missingReason", "ohlcvSource"])
    status = {
        "status": "OK" if success else "NO_DATA",
        "market": "kr",
        "date": TARGET_DATE,
        "targetCount": len(targets),
        "successCount": success,
        "failedCount": failed,
        "workers": workers,
        "message": "KR close OHLCV collected" if success else "오늘 국장 장마감 OHLCV 원본 없음 또는 수집 실패",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    (REPORTS / "kr_close_ohlcv_refresh_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
