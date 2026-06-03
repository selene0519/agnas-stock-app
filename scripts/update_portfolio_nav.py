"""
포트폴리오 NAV 일별 스냅샷 누적 스크립트.

매일 장마감 후 실행하면 data/portfolio/portfolio_daily_nav.csv 에 1행을 append합니다.
- 실제 누적(actual): 오늘 이후 매일 append
- 추정 백필(backfill): 과거 OHLCV × 현재 보유수량으로 역산 (보유종목이 변하지 않았다고 가정)
  isBackfill=True 로 표시해 실제 데이터와 구분

실행:
    python scripts/update_portfolio_nav.py [--backfill DAYS] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NAV_PATH = ROOT / "data" / "portfolio" / "portfolio_daily_nav.csv"
NAV_PATH.parent.mkdir(parents=True, exist_ok=True)

KST = timezone(timedelta(hours=9))

FIELDNAMES = [
    "date", "updated_at",
    "total_value", "cash", "holdings_value",
    "daily_return", "cumulative_return",
    "kr_value", "us_value",
    "max_drawdown_pct", "position_count",
    "kospi_return", "benchmark_return",
    "is_backfill",
]


# ── 유틸 ──────────────────────────────────────────────────────────────

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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        s = str(v or "").replace(",", "").replace("₩", "").replace("$", "").strip()
        return float(s) if s not in ("", "-", "None", "nan") else default
    except Exception:
        return default


def _row_symbol(row: dict, market: str) -> str:
    raw = str(row.get("symbol") or row.get("ticker") or row.get("code") or "").strip()
    if market == "kr":
        digits = re.sub(r"\D", "", raw)
        return digits.zfill(6)[-6:] if digits else ""
    return raw.upper()


# ── 보유종목 로드 ─────────────────────────────────────────────────────

def load_holdings() -> list[dict]:
    holdings = []
    seen = set()
    for market in ("kr", "us"):
        path = ROOT / f"holdings_{market}.csv"
        for row in _read_csv(path):
            sym = _row_symbol(row, market)
            qty = _num(row.get("quantity") or row.get("qty"), 0)
            avg = _num(row.get("avgPrice") or row.get("avg_price") or row.get("averagePrice"), 0)
            if not sym or qty <= 0:
                continue
            key = f"{market}-{sym}"
            if key in seen:
                continue
            seen.add(key)
            holdings.append({
                "symbol": sym,
                "market": market,
                "quantity": qty,
                "avgPrice": avg,
                "name": str(row.get("name") or sym).strip(),
            })
    return holdings


# ── 현재가 인덱스 ──────────────────────────────────────────────────────

def load_price_index() -> dict[str, float]:
    """CSV 현재가 파일에서 symbol → price 매핑 반환."""
    index: dict[str, float] = {}
    price_files = [
        ROOT / "data" / "stockapp" / "kis_current_price_kr.csv",
        ROOT / "reports" / "kis_current_price_kr.csv",
        ROOT / "data" / "stockapp" / "kis_current_price_us.csv",
        ROOT / "reports" / "kis_current_price_us.csv",
        ROOT / "data" / "stockapp" / "intraday_realtime_snapshot_kr.csv",
        ROOT / "reports" / "intraday_realtime_snapshot_kr.csv",
    ]
    for path in price_files:
        for row in _read_csv(path):
            market = "us" if "us" in path.stem else "kr"
            sym = _row_symbol(row, market)
            price = _num(row.get("currentPrice") or row.get("current_price") or row.get("last_price"), 0)
            if sym and price > 0 and sym not in index:
                index[sym] = price
    return index


# ── OHLCV close 인덱스 (날짜별 백필용) ───────────────────────────────

def load_ohlcv_close(symbol: str, market: str) -> dict[str, float]:
    """date → close 매핑 반환."""
    paths = [
        ROOT / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv",
        ROOT / "data" / "stockapp" / f"{market}_{symbol}_daily.csv",
    ]
    for path in paths:
        rows = _read_csv(path)
        if rows:
            result = {}
            for row in rows:
                date = str(row.get("date") or row.get("Date") or "").strip()
                close = _num(row.get("close") or row.get("Close"), 0)
                if date and close > 0:
                    result[date] = close
            return result
    return {}


# ── KOSPI 수익률 인덱스 ───────────────────────────────────────────────

def load_kospi_returns() -> dict[str, float]:
    """date → 기준일 대비 KOSPI 누적 수익률(%) 반환."""
    path = ROOT / "data" / "market" / "ohlcv" / "kr_KOSPI_daily.csv"
    rows = sorted(_read_csv(path), key=lambda r: r.get("date", ""))
    if not rows:
        return {}
    base_close = _num(rows[0].get("close") or rows[0].get("Close"), 0)
    if base_close <= 0:
        return {}
    result = {}
    for row in rows:
        date = str(row.get("date") or "").strip()
        close = _num(row.get("close") or row.get("Close"), 0)
        if date and close > 0:
            result[date] = (close - base_close) / base_close * 100
    return result


# ── NAV 계산 ─────────────────────────────────────────────────────────

def calc_nav_for_date(
    holdings: list[dict],
    date: str,
    price_index: dict[str, float],
    use_current: bool = False,
) -> dict:
    kr_value = 0.0
    us_value = 0.0
    for h in holdings:
        sym = h["symbol"]
        mkt = h["market"]
        qty = h["quantity"]
        if use_current:
            price = price_index.get(sym, 0)
        else:
            ohlcv = load_ohlcv_close(sym, mkt)
            price = ohlcv.get(date, 0)
            if price <= 0:
                # 날짜보다 이전 최근 데이터 사용
                dates = sorted(d for d in ohlcv if d <= date)
                price = ohlcv[dates[-1]] if dates else 0
        val = price * qty
        if mkt == "kr":
            kr_value += val
        else:
            us_value += val

    total = kr_value + us_value
    return {
        "total_value": round(total, 2),
        "kr_value": round(kr_value, 2),
        "us_value": round(us_value, 2),
    }


# ── 메인 ─────────────────────────────────────────────────────────────

def main(backfill_days: int = 0, dry_run: bool = False) -> None:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    holdings = load_holdings()
    price_index = load_price_index()
    kospi_returns = load_kospi_returns()

    # 기존 NAV 로드
    existing = {r["date"]: r for r in _read_csv(NAV_PATH)}

    # base_value: 첫 실제 데이터 기준
    actual_rows = sorted(
        [r for r in existing.values() if str(r.get("is_backfill", "")).lower() not in ("true", "1")],
        key=lambda r: r["date"]
    )
    base_value = _num(actual_rows[0]["total_value"], 0) if actual_rows else 0

    def make_row(date: str, nav: dict, is_backfill: bool) -> dict:
        total = nav["total_value"]
        prev_dates = sorted(d for d in existing if d < date)
        prev_total = _num(existing[prev_dates[-1]]["total_value"], total) if prev_dates else total
        daily_ret = (total - prev_total) / prev_total * 100 if prev_total > 0 else 0.0

        bv = base_value if base_value > 0 else total
        cum_ret = (total - bv) / bv * 100 if bv > 0 else 0.0

        # max drawdown
        peak = max((_num(existing[d]["total_value"], 0) for d in existing if d <= date), default=total)
        mdd = (total - peak) / peak * 100 if peak > 0 and total < peak else 0.0

        return {
            "date": date,
            "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "total_value": round(total, 2),
            "cash": 0.0,
            "holdings_value": round(total, 2),
            "daily_return": round(daily_ret, 6),
            "cumulative_return": round(cum_ret, 6),
            "kr_value": round(nav["kr_value"], 2),
            "us_value": round(nav["us_value"], 2),
            "max_drawdown_pct": round(mdd, 4),
            "position_count": len([h for h in holdings if h["quantity"] > 0]),
            "kospi_return": round(kospi_returns.get(date, 0), 4),
            "benchmark_return": round(kospi_returns.get(date, 0), 4),
            "is_backfill": "true" if is_backfill else "false",
        }

    # 오늘 데이터
    if today not in existing or str(existing[today].get("is_backfill", "")).lower() not in ("false", ""):
        nav = calc_nav_for_date(holdings, today, price_index, use_current=True)
        if nav["total_value"] > 0:
            existing[today] = make_row(today, nav, is_backfill=False)
            print(f"[NAV] {today}: 실제 {nav['total_value']:,.0f}원")

    # 백필
    if backfill_days > 0:
        for i in range(1, backfill_days + 1):
            date = (datetime.now(KST) - timedelta(days=i)).strftime("%Y-%m-%d")
            if date in existing and str(existing[date].get("is_backfill", "")).lower() == "false":
                continue  # 실제 데이터 있으면 덮어쓰지 않음
            nav = calc_nav_for_date(holdings, date, price_index, use_current=False)
            if nav["total_value"] > 0:
                existing[date] = make_row(date, nav, is_backfill=True)
                print(f"[NAV-백필] {date}: 추정 {nav['total_value']:,.0f}원")

    # 날짜순 정렬 후 저장
    rows = [existing[d] for d in sorted(existing.keys())]
    if not dry_run:
        _write_csv(NAV_PATH, rows)
        print(f"[NAV] {NAV_PATH} 저장 완료 ({len(rows)}행)")
    else:
        print(f"[NAV] dry-run: {len(rows)}행 (저장 안 함)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", type=int, default=90, help="백필할 과거 일수 (기본 90일)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(backfill_days=args.backfill, dry_run=args.dry_run)
