"""OHLCV 히스토리 백필 스크립트

신규 종목 또는 DATA_PENDING(OHLCV 30일 미만) 종목에 대해
FinanceDataReader 또는 pykrx로 최대 120일치 일봉 데이터를 한 번에 수집합니다.

사용법:
  python scripts/backfill_ohlcv_history.py              # 기본 (30행 미만 종목 대상)
  python scripts/backfill_ohlcv_history.py --min-rows 60  # 60행 미만 종목 대상
  python scripts/backfill_ohlcv_history.py --symbol 005930  # 특정 종목만
  python scripts/backfill_ohlcv_history.py --all            # 전종목 강제 백필
  python scripts/backfill_ohlcv_history.py --days 250       # 250일치
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

REPO = Path(__file__).resolve().parents[1]
STOCKAPP = REPO / "data" / "stockapp"
OHLCV_DIR = REPO / "data" / "market" / "ohlcv"
REPORTS = REPO / "reports"
DEFAULT_DAYS = 120
DEFAULT_MIN_ROWS = 30
MAX_WORKERS = 4


def _ensure_pkg(package: str, import_name: str | None = None) -> bool:
    import_name = import_name or package
    try:
        __import__(import_name)
        return True
    except Exception:
        pass
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])
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


def _target_universe() -> list[dict]:
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
            sym = _norm_kr_symbol(
                row.get("symbol") or row.get("ticker") or row.get("code") or row.get("종목코드")
            )
            if not sym:
                continue
            name = str(row.get("name") or row.get("companyName") or row.get("종목명") or sym).strip()
            item = keyed.setdefault(sym, {"symbol": sym, "name": name})
            if name and item.get("name") == sym:
                item["name"] = name
    return list(keyed.values())


def _existing_rows(symbol: str) -> list[dict]:
    path = OHLCV_DIR / f"kr_{symbol}_daily.csv"
    rows = _read_csv(path)
    if not rows:
        alt = REPORTS / f"kr_{symbol}_daily.csv"
        rows = _read_csv(alt)
    return rows


def _fetch_history_fdr(symbol: str, start: str, end: str) -> list[dict]:
    """FinanceDataReader로 start~end 전체 히스토리 반환."""
    if not _ensure_pkg("finance-datareader", "FinanceDataReader"):
        return []
    try:
        import FinanceDataReader as fdr  # type: ignore
        df = fdr.DataReader(symbol, start, end)
        if df is None or df.empty:
            return []
        df = df.reset_index()
        rows = []
        for _, row in df.iterrows():
            date_val = row.get("Date") or row.get("date")
            date_text = str(date_val)[:10]
            if not date_text or date_text < "2000-01-01":
                continue
            rows.append({
                "date": date_text,
                "market": "kr",
                "symbol": symbol,
                "open": row.get("Open", ""),
                "high": row.get("High", ""),
                "low": row.get("Low", ""),
                "close": row.get("Close", ""),
                "volume": row.get("Volume", ""),
                "tradingValue": row.get("Amount", row.get("Change", "")),
                "source": "FinanceDataReader",
                "updatedAt": datetime.now().isoformat(timespec="seconds"),
            })
        return rows
    except Exception as exc:
        print(f"[WARN] FDR history {symbol}: {exc}")
        return []


def _fetch_history_pykrx(symbol: str, start: str, end: str) -> list[dict]:
    """pykrx로 start~end 전체 히스토리 반환."""
    if not _ensure_pkg("pykrx"):
        return []
    try:
        from pykrx import stock  # type: ignore
        start_yyyymmdd = start.replace("-", "")
        end_yyyymmdd = end.replace("-", "")
        df = stock.get_market_ohlcv_by_date(start_yyyymmdd, end_yyyymmdd, symbol)
        if df is None or df.empty:
            return []
        df = df.reset_index()
        rows = []
        for _, row in df.iterrows():
            date_val = row.get("날짜") or row.get("Date")
            date_text = str(date_val)[:10]
            if not date_text or date_text < "2000-01-01":
                continue
            rows.append({
                "date": date_text,
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
            })
        return rows
    except Exception as exc:
        print(f"[WARN] pykrx history {symbol}: {exc}")
        return []


OHLCV_FIELDS = ["date", "market", "symbol", "open", "high", "low", "close", "volume", "tradingValue", "source", "updatedAt"]


def _merge_and_save(symbol: str, new_rows: list[dict]) -> int:
    """기존 CSV와 병합 후 날짜 기준 dedup·정렬 저장. 추가된 행 수 반환."""
    if not new_rows:
        return 0
    existing = {row["date"]: row for row in _existing_rows(symbol) if row.get("date")}
    before = len(existing)
    for row in new_rows:
        if row.get("date"):
            existing[row["date"]] = row
    merged = sorted(existing.values(), key=lambda r: r["date"])
    _write_csv(OHLCV_DIR / f"kr_{symbol}_daily.csv", merged, OHLCV_FIELDS)
    return len(merged) - before


def backfill_symbol(symbol: str, days: int) -> dict:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")

    rows = _fetch_history_fdr(symbol, start, end)
    source = "FDR"
    if not rows:
        rows = _fetch_history_pykrx(symbol, start, end)
        source = "pykrx"

    added = _merge_and_save(symbol, rows)
    total = len(_existing_rows(symbol))
    return {"symbol": symbol, "fetched": len(rows), "added": added, "total": total, "source": source}


def main() -> None:
    parser = argparse.ArgumentParser(description="OHLCV 히스토리 백필")
    parser.add_argument("--symbol", default="", help="특정 종목코드만 백필")
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS, help="이 행 수 미만인 종목만 처리")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="수집할 일수 (기본 120)")
    parser.add_argument("--all", action="store_true", dest="force_all", help="행 수 무관 전종목 처리")
    args = parser.parse_args()

    if args.symbol:
        targets = [{"symbol": _norm_kr_symbol(args.symbol), "name": args.symbol}]
    else:
        universe = _target_universe()
        if args.force_all:
            targets = universe
        else:
            targets = [
                t for t in universe
                if len(_existing_rows(t["symbol"])) < args.min_rows
            ]

    print(f"[backfill] 대상 종목: {len(targets)}개 / days={args.days} / min_rows={args.min_rows}")
    if not targets:
        print("[backfill] 백필할 종목 없음 — 모든 종목이 기준 이상 보유 중")
        return

    ok = err = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(backfill_symbol, t["symbol"], args.days): t for t in targets}
        for future in as_completed(futures):
            t = futures[future]
            try:
                result = future.result()
                tag = "✓" if result["added"] > 0 else "="
                print(f"  {tag} {result['symbol']:8s} fetched={result['fetched']:4d} added={result['added']:4d} total={result['total']:4d} [{result['source']}]")
                ok += 1
            except Exception as exc:
                print(f"  ✗ {t['symbol']:8s} ERROR: {exc}")
                err += 1

    print(f"[backfill] 완료: 성공 {ok}, 오류 {err}")


if __name__ == "__main__":
    main()
