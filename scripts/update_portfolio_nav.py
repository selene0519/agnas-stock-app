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


def _row_market(row: dict, path: Path) -> str:
    """행의 market 컬럼을 우선한다. toss_holdings_kr.csv처럼 파일명은 kr인데
    안에 us 종목이 섞인 브로커 원장이 있어 파일명만 믿으면 안 된다."""
    m = str(row.get("market") or "").strip().lower()
    if m in ("kr", "us"):
        return m
    stem = path.stem.lower()
    return "us" if stem.endswith("_us") or "_us_" in stem else "kr"


# ── 보유종목 로드 ─────────────────────────────────────────────────────

# 앱(mone_v802_holdings_clean)과 동일한 원장 우선순위:
#   1순위 루트 원장(사용자 편집본) → 2순위 브로커 자동수집본(fallback).
#   fallback 행은 루트 원장에 이미 있는 심볼이면 건너뛴다(중복 방지).
_PRIMARY_LEDGERS = (
    "holdings_kr.csv",
    "data/holdings_kr.csv",
    "holdings_us.csv",
    "data/holdings_us.csv",
)
_FALLBACK_LEDGERS = (
    "data/kis_2_holdings_kr.csv",
    "data/kis_holdings_kr.csv",
    "data/toss_holdings_kr.csv",
    "data/kis_2_holdings_us.csv",
    "data/kis_holdings_us.csv",
    "data/toss_holdings_us.csv",
)


def load_holdings() -> list[dict]:
    """실제 보유 원장(루트 + 브로커 fallback)을 합산해 반환.

    과거엔 거의 빈 holdings_kr.csv/holdings_us.csv만 읽어 NAV가 실제 계좌를
    반영하지 못했다. 이제 앱 보유 화면과 같은 소스를 읽는다."""
    holdings: list[dict] = []
    seen: set[str] = set()  # 앱과 동일하게 심볼 기준(마켓 무관) dedup

    def _consume(path: Path, skip_syms: set[str]) -> None:
        for row in _read_csv(path):
            mkt = _row_market(row, path)
            sym = _row_symbol(row, mkt)
            qty = _num(row.get("quantity") or row.get("qty"), 0)
            avg = _num(row.get("avgPrice") or row.get("avg_price") or row.get("averagePrice"), 0)
            if not sym or qty <= 0:
                continue
            if sym in skip_syms or sym in seen:
                continue
            seen.add(sym)
            holdings.append({
                "symbol": sym,
                "market": mkt,
                "quantity": qty,
                "avgPrice": avg,
                # 브로커 원장이 마지막 sync 때의 현재가를 들고 있으면 최후 폴백으로 쓴다
                # (현재가 파일·OHLCV에도 없는 종목이 NAV에서 0으로 빠지는 것 방지).
                "ledgerPrice": _num(row.get("currentPrice") or row.get("current_price"), 0),
                "name": str(row.get("name") or sym).strip(),
            })

    for name in _PRIMARY_LEDGERS:
        _consume(ROOT / name, skip_syms=set())
    primary_syms = set(seen)
    for name in _FALLBACK_LEDGERS:
        _consume(ROOT / name, skip_syms=primary_syms)
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


# ── 환율(USD/KRW) 인덱스 ──────────────────────────────────────────────
# 미국 보유 평가액은 달러라, 원화 KR 보유와 합산하려면 환산이 필요하다.
# 매일 fetch_benchmark_data.py가 fx_USDKRW_daily.csv를 갱신한다. 파일이 없으면
# DEFAULT_USDKRW(레포 매크로 뉴스 기준 최근 원/달러)로 폴백한다.
DEFAULT_USDKRW = _num(os.environ.get("USDKRW_RATE"), 1477.6) or 1477.6
FX_PATH = ROOT / "data" / "market" / "ohlcv" / "fx_USDKRW_daily.csv"


def load_fx_index() -> dict[str, float]:
    idx: dict[str, float] = {}
    for row in _read_csv(FX_PATH):
        date = str(row.get("date") or row.get("Date") or "").strip()[:10]
        rate = _num(row.get("close") or row.get("Close"), 0)
        if date and rate > 0:
            idx[date] = rate
    return idx


def fx_rate_for(fx_index: dict[str, float], date: str, use_latest: bool = False) -> float:
    """해당 날짜(또는 최신)의 원/달러 환율. 없으면 직전 유효일 → 전체 최신 →
    최초일 → 상수 순으로 폴백."""
    if not fx_index:
        return DEFAULT_USDKRW
    if use_latest:
        return fx_index[max(fx_index)]
    if date in fx_index:
        return fx_index[date]
    prior = [d for d in fx_index if d <= date]
    if prior:
        return fx_index[max(prior)]
    return fx_index[min(fx_index)]


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
    fx_index: dict[str, float] | None = None,
) -> dict:
    kr_value = 0.0
    us_value_usd = 0.0  # 달러 원본 — 마지막에 환율로 원화 환산
    for h in holdings:
        sym = h["symbol"]
        mkt = h["market"]
        qty = h["quantity"]
        if use_current:
            price = price_index.get(sym, 0)
            if price <= 0:
                # 현재가 파일에 없으면 최신 OHLCV 종가로 폴백 (보유 ETF처럼
                # 추천 유니버스 밖 종목은 현재가 수집 대상이 아닐 수 있다).
                ohlcv = load_ohlcv_close(sym, mkt)
                if ohlcv:
                    price = ohlcv[max(ohlcv)]
            if price <= 0:
                # 그래도 없으면 원장의 마지막 sync 현재가 사용.
                price = h.get("ledgerPrice", 0)
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
            us_value_usd += val

    # 미국 보유(달러)를 원화로 환산해 KR과 합산. today는 최신 환율, 백필은 그날 환율.
    rate = fx_rate_for(fx_index or {}, date, use_latest=use_current)
    us_value = us_value_usd * rate
    total = kr_value + us_value
    return {
        "total_value": round(total, 2),
        "kr_value": round(kr_value, 2),
        "us_value": round(us_value, 2),      # 원화 환산액
        "us_value_usd": round(us_value_usd, 2),
        "fx_rate": round(rate, 4),
    }


# ── 메인 ─────────────────────────────────────────────────────────────

def main(backfill_days: int = 0, dry_run: bool = False) -> None:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    holdings = load_holdings()
    price_index = load_price_index()
    kospi_returns = load_kospi_returns()
    fx_index = load_fx_index()

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

    # 오늘 데이터 — 항상 최신가로 재계산해 덮어쓴다. 워크플로가 하루 두 번
    # (장전/장마감 후) 도니 두 번째 실행이 종가로 갱신돼야 하고, 보유 원장이
    # 바뀌면(예: 잘못 들어간 종목 제거) 오늘 값도 즉시 반영돼야 한다. 과거
    # 실제행은 아래 백필에서 건드리지 않으므로 오늘만 갱신된다.
    nav = calc_nav_for_date(holdings, today, price_index, use_current=True, fx_index=fx_index)
    if nav["total_value"] > 0:
        existing[today] = make_row(today, nav, is_backfill=False)
        print(f"[NAV] {today}: 실제 {nav['total_value']:,.0f}원")

    # 백필
    if backfill_days > 0:
        for i in range(1, backfill_days + 1):
            date = (datetime.now(KST) - timedelta(days=i)).strftime("%Y-%m-%d")
            if date in existing and str(existing[date].get("is_backfill", "")).lower() == "false":
                continue  # 실제 데이터 있으면 덮어쓰지 않음
            nav = calc_nav_for_date(holdings, date, price_index, use_current=False, fx_index=fx_index)
            if nav["total_value"] > 0:
                existing[date] = make_row(date, nav, is_backfill=True)
                print(f"[NAV-백필] {date}: 추정 {nav['total_value']:,.0f}원")

    # 날짜순 정렬
    rows = [existing[d] for d in sorted(existing.keys())]

    # 파생지표(일간·누적수익률·MDD) 일괄 재계산 — 시리즈 전체를 한 기준으로 통일한다.
    # make_row가 행별로 계산하던 방식은 base_value가 "첫 실제행"에 묶여 있어, 옛
    # 보유(잘못 섞인 종목 등) 기준으로 찍힌 과거 실제행이 base가 되면 누적수익률이
    # 통째로 왜곡됐다(예: -90% 절벽). 최종 시리즈의 가장 이른 유효 NAV를 base로
    # 삼아 모든 행을 다시 계산하면 리빌드/보유변경에도 일관된 곡선이 나온다.
    base = next((_num(r["total_value"], 0) for r in rows if _num(r["total_value"], 0) > 0), 0.0)
    peak = 0.0
    prev: float | None = None
    for r in rows:
        tv = _num(r["total_value"], 0)
        r["cumulative_return"] = round((tv - base) / base * 100, 6) if base > 0 else 0.0
        r["daily_return"] = round((tv - prev) / prev * 100, 6) if prev and prev > 0 else 0.0
        peak = tv if peak <= 0 else max(peak, tv)
        r["max_drawdown_pct"] = round((tv - peak) / peak * 100, 4) if peak > 0 and tv < peak else 0.0
        prev = tv

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
