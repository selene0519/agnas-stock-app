"""
yfinance로 KR/US 종목 섹터·업종 수집.
출력: data/sector_map_kr.csv, data/sector_map_us.csv

섹터 집중도 경고: generate_*_recommendations.py에서 사용
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"

FIELDNAMES = ["symbol", "name", "market", "sector", "industry", "updatedAt"]

# 수동 섹터 매핑 (yfinance 실패 대비 fallback)
# KOSPI 업종 코드 기반 대분류
SECTOR_FALLBACK_KR: dict[str, str] = {
    # 반도체/IT
    "005930": "Technology", "000660": "Technology", "058470": "Technology",
    "009830": "Technology", "042700": "Technology", "079550": "Technology",
    "056080": "Technology",
    # 디스플레이
    "034220": "Technology", "011070": "Technology",
    # 자동차
    "005380": "Consumer Cyclical", "012330": "Consumer Cyclical",
    "011210": "Consumer Cyclical", "241560": "Consumer Cyclical",
    # 금융
    "055550": "Financial Services", "086790": "Financial Services",
    "105560": "Financial Services", "316140": "Financial Services",
    "032830": "Financial Services",
    # 화학
    "011170": "Basic Materials", "096770": "Basic Materials",
    "010950": "Basic Materials", "051910": "Basic Materials",
    # 바이오/헬스케어
    "207940": "Healthcare", "068270": "Healthcare", "196170": "Healthcare",
    "326030": "Healthcare", "005490": "Healthcare",
    # 에너지
    "096770": "Energy", "267250": "Energy",
    # 통신
    "017670": "Communication Services", "035420": "Communication Services",
    "030200": "Communication Services",
    # 유통/소비
    "139480": "Consumer Defensive", "271560": "Consumer Cyclical",
    # 철강/소재
    "005490": "Basic Materials", "010130": "Basic Materials",
    # 건설
    "000720": "Industrials", "047040": "Industrials",
    # 운송
    "011200": "Industrials", "003490": "Industrials",
    # 조선
    "009540": "Industrials", "010140": "Industrials",
}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows([{k: row.get(k, "") for k in FIELDNAMES} for row in rows])


def _get_symbols(market: str) -> list[str]:
    pattern = f"{market}_*_daily.csv"
    import re
    result = []
    for f in sorted(OHLCV_DIR.glob(pattern)):
        m = re.match(rf"{market}_(.+)_daily\.csv", f.name)
        if m:
            result.append(m.group(1))
    return result


def fetch_sector_yfinance(symbol: str, market: str) -> tuple[str, str]:
    try:
        import yfinance as yf
        suffix = ".KS" if market == "kr" else ""
        ticker_str = f"{symbol.zfill(6)}{suffix}" if market == "kr" else symbol
        info = yf.Ticker(ticker_str).info
        sector   = info.get("sector", "") or ""
        industry = info.get("industry", "") or ""
        return sector, industry
    except Exception:
        return "", ""


def fetch_for_market(market: str) -> list[dict]:
    symbols = _get_symbols(market)
    out_path = ROOT / "data" / f"sector_map_{market}.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 기존 데이터 로드
    existing: dict[str, dict] = {r["symbol"]: r for r in _read_csv(out_path)}

    # 이름 맵
    name_map: dict[str, str] = {}
    for p in [ROOT / f"watchlist_{market}.csv", ROOT / "data" / f"symbol_master_{market}_full.csv"]:
        for row in _read_csv(p):
            sym = str(row.get("symbol") or "").strip()
            name = str(row.get("name") or "").strip()
            if sym and name:
                name_map[sym] = name

    results: list[dict] = []
    updated = 0
    fallback_map = SECTOR_FALLBACK_KR if market == "kr" else {}

    print(f"  {market.upper()} 섹터 수집: {len(symbols)}개")

    for i, sym in enumerate(symbols):
        sym_key = sym.zfill(6) if market == "kr" else sym
        name = name_map.get(sym_key, sym_key)

        # 이미 있으면 재사용
        if sym_key in existing and existing[sym_key].get("sector"):
            results.append(existing[sym_key])
            continue

        # Fallback 먼저 체크
        fallback_sector = fallback_map.get(sym_key, "")
        if fallback_sector:
            results.append({
                "symbol": sym_key, "name": name, "market": market,
                "sector": fallback_sector, "industry": "", "updatedAt": now,
            })
            continue

        # yfinance 조회 (느리므로 없는 것만)
        sector, industry = fetch_sector_yfinance(sym, market)
        time.sleep(0.3)

        results.append({
            "symbol": sym_key, "name": name, "market": market,
            "sector": sector or "Unknown", "industry": industry, "updatedAt": now,
        })
        if sector:
            updated += 1

        if (i + 1) % 20 == 0:
            _write_csv(out_path, results)
            print(f"    {i+1}/{len(symbols)}... (신규: {updated})")

    _write_csv(out_path, results)
    print(f"  {market.upper()} 완료: {updated}개 신규 수집")
    return results


def main() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 섹터 데이터 수집 시작")
    for market in ("kr", "us"):
        fetch_for_market(market)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 완료")


if __name__ == "__main__":
    main()
