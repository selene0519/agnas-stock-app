"""Backfill long daily OHLCV history for US symbols with yfinance.

The app's live collectors keep recent prices fresh, but regime/pattern
research needs a much longer local history.  This script merges Yahoo Finance
daily bars into data/market/ohlcv/us_{symbol}_daily.csv without dropping any
existing rows that are not returned by the backfill source.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OHLCV_DIR = REPO / "data" / "market" / "ohlcv"
STOCKAPP = REPO / "data" / "stockapp"
REPORTS = REPO / "reports"

DEFAULT_DAYS = 6000
DEFAULT_LIMIT = 180
MAX_SYMBOL_LEN = 16
OHLCV_FIELDS = [
    "date", "market", "symbol", "open", "high", "low", "close",
    "volume", "tradingValue", "source", "updatedAt",
]


def _ensure_yfinance() -> bool:
    try:
        import yfinance  # noqa: F401
        return True
    except Exception:
        pass
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
        import yfinance  # noqa: F401
        return True
    except Exception as exc:
        print(f"[WARN] cannot install/import yfinance: {exc}")
        return False


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as fh:
                return [dict(row) for row in csv.DictReader(fh)]
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OHLCV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in OHLCV_FIELDS})


def _clean_symbol(value: object) -> str:
    sym = str(value or "").strip().upper().replace("$", "").replace(".US", "")
    if not sym or len(sym) > MAX_SYMBOL_LEN:
        return ""
    if sym.startswith("^") or "=" in sym:
        return ""
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,15}", sym):
        return ""
    return sym


def _add_symbol(symbols: list[str], value: object) -> None:
    sym = _clean_symbol(value)
    if sym and sym not in symbols:
        symbols.append(sym)


def _target_universe(limit: int) -> list[str]:
    symbols: list[str] = []
    for sym in ("SPY", "QQQ", "DIA", "IWM", "RSP", "SQQQ", "SOXS", "TLT", "HYG", "LQD"):
        _add_symbol(symbols, sym)
    paths = [
        STOCKAPP / "price_collection_universe_us.csv",
        STOCKAPP / "kis_collection_targets_us.csv",
        REPO / "data" / "candidate_universe_us.csv",
        REPO / "candidate_universe_us.csv",
        REPO / "data" / "watchlist_us.csv",
        REPO / "watchlist_us.csv",
    ]
    paths.extend(sorted(REPORTS.glob("mone_v36_final_recommendations_us_*.csv")))
    for path in paths:
        for row in _read_csv(path):
            market = str(row.get("market") or row.get("Market") or "us").strip().lower()
            if market not in {"", "us"}:
                continue
            _add_symbol(symbols, row.get("symbol") or row.get("ticker") or row.get("code"))
    return symbols[:max(1, int(limit))]


def _existing_rows(symbol: str) -> list[dict[str, Any]]:
    return _read_csv(OHLCV_DIR / f"us_{symbol}_daily.csv")


def _safe_float(value: Any) -> float | None:
    try:
        if value == "" or value is None:
            return None
        number = float(value)
        return number if number == number else None
    except Exception:
        return None


def _frame_rows(symbol: str, frame: Any, updated_at: str) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    if getattr(frame.columns, "nlevels", 1) > 1:
        try:
            if symbol in frame.columns.get_level_values(-1):
                frame = frame.xs(symbol, level=-1, axis=1)
            else:
                frame.columns = [str(col[0]) for col in frame.columns]
        except Exception:
            frame.columns = [str(col[0]) if isinstance(col, tuple) else str(col) for col in frame.columns]
    frame = frame.reset_index()
    rows: list[dict[str, Any]] = []
    for _, rec in frame.iterrows():
        date_text = str(rec.get("Date") or rec.get("Datetime") or "")[:10]
        close = _safe_float(rec.get("Close"))
        if not date_text or not close or close <= 0:
            continue
        rows.append({
            "date": date_text,
            "market": "us",
            "symbol": symbol,
            "open": rec.get("Open", ""),
            "high": rec.get("High", ""),
            "low": rec.get("Low", ""),
            "close": rec.get("Close", ""),
            "volume": rec.get("Volume", ""),
            "tradingValue": "",
            "source": "Yahoo Finance daily",
            "updatedAt": updated_at,
        })
    return rows


def _merge_and_save(symbol: str, new_rows: list[dict[str, Any]]) -> dict[str, int]:
    if not new_rows:
        return {"added": 0, "total": len(_existing_rows(symbol))}
    existing = {str(row.get("date") or ""): row for row in _existing_rows(symbol) if row.get("date")}
    before = len(existing)
    for row in new_rows:
        date_text = str(row.get("date") or "")
        if date_text:
            existing[date_text] = row
    merged = sorted(existing.values(), key=lambda row: str(row.get("date") or ""))
    _write_csv(OHLCV_DIR / f"us_{symbol}_daily.csv", merged)
    return {"added": len(merged) - before, "total": len(merged)}


def backfill(symbols: list[str], days: int) -> list[dict[str, Any]]:
    if not _ensure_yfinance():
        return []
    import yfinance as yf  # type: ignore

    end = datetime.now()
    start = end - timedelta(days=max(365, int(days)))
    updated_at = datetime.now().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []
    for idx, symbol in enumerate(symbols, 1):
        try:
            frame = yf.download(
                symbol,
                start=start.strftime("%Y-%m-%d"),
                end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            rows = _frame_rows(symbol, frame, updated_at)
            merged = _merge_and_save(symbol, rows)
            result = {
                "symbol": symbol,
                "fetched": len(rows),
                "added": merged["added"],
                "total": merged["total"],
                "ok": bool(rows),
            }
        except Exception as exc:
            result = {"symbol": symbol, "fetched": 0, "added": 0, "total": len(_existing_rows(symbol)), "ok": False, "error": str(exc)[:120]}
        results.append(result)
        tag = "OK" if result.get("added", 0) > 0 else ("==" if result.get("ok") else "NG")
        print(f"  {tag} {idx:3d}/{len(symbols):3d} {symbol:10s} fetched={result['fetched']:4d} added={result['added']:4d} total={result['total']:4d}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill long US OHLCV daily history")
    parser.add_argument("--symbol", action="append", default=[], help="US ticker to backfill; can be repeated")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="calendar days to request")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="max symbols when using universe")
    parser.add_argument("--all", action="store_true", dest="force_all", help="use configured US universe")
    args = parser.parse_args()

    symbols: list[str] = []
    for value in args.symbol:
        _add_symbol(symbols, value)
    if args.force_all or not symbols:
        for sym in _target_universe(args.limit):
            _add_symbol(symbols, sym)

    print(f"[backfill-us] target={len(symbols)} days={args.days}")
    results = backfill(symbols, args.days)
    ok = sum(1 for item in results if item.get("ok"))
    err = len(results) - ok
    print(f"[backfill-us] done ok={ok} err={err}")


if __name__ == "__main__":
    main()
