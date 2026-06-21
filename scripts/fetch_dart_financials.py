"""
DART API로 KR 종목 재무 데이터 수집.
PER, EPS, 매출성장률, 영업이익률, 부채비율, ROE → PEG 계산까지.

출력: reports/dart_financial_data_kr.csv
실행: python scripts/fetch_dart_financials.py
GitHub Actions: 주 1회 실행 권장 (DART 일 5000 호출 제한)
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
CORP_MAP = ROOT / "data" / "fundamental" / "dart_corp_map.csv"
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
KIS_PRICE = ROOT / "data" / "stockapp" / "kis_current_price_kr.csv"
OUT = ROOT / "reports" / "dart_financial_data_kr.csv"
STATUS = ROOT / "reports" / "dart_financial_status.json"

DART_KEY = os.environ.get("DART_API_KEY", "")
BASE_URL = "https://opendart.fss.or.kr/api"

# 최근 2년 사업보고서 코드
REPORT_CODE = "11011"   # 사업보고서 (연간)
YEARS = ["2024", "2023"]

FIELDNAMES = [
    "symbol", "corp_code", "name", "year",
    "revenue", "operating_income", "net_income", "total_equity", "total_debt",
    "total_assets", "current_assets", "current_liabilities", "retained_earnings",
    "eps", "eps_prev", "per", "pbr", "shares_outstanding", "market_cap",
    "roe", "debt_ratio", "operating_margin", "net_margin",
    "revenue_growth", "eps_growth", "peg",
    "quality_score", "value_score", "growth_score",
    "updatedAt",
]

ACCOUNT_MAP = {
    "revenue":              ["매출액", "영업수익", "수익(매출액)"],
    "operating_income":     ["영업이익", "영업이익(손실)"],
    "net_income":           ["당기순이익", "당기순이익(손실)", "연결당기순이익"],
    "total_equity":         ["자본총계", "지배기업소유주지분"],
    "total_debt":           ["부채총계"],
    "total_assets":         ["자산총계"],
    "current_assets":       ["유동자산"],
    "current_liabilities":  ["유동부채"],
    "retained_earnings":    ["이익잉여금", "미처분이익잉여금"],
    "eps":                  ["주당순이익", "기본주당순이익(손실)", "기본주당이익(손실)"],
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


def _num(v: Any) -> float | None:
    try:
        raw = re.sub(r"[,\s]", "", str(v or ""))
        if not raw or raw in ("-", "nan", "None"):
            return None
        return float(raw)
    except Exception:
        return None


def _build_corp_map() -> dict[str, str]:
    """symbol → corp_code"""
    result: dict[str, str] = {}
    for row in _read_csv(CORP_MAP):
        stock_code = str(row.get("stock_code", "")).strip().zfill(6)
        corp_code  = str(row.get("corp_code", "")).strip()
        if stock_code and corp_code:
            result[stock_code] = corp_code
    return result


def _get_ohlcv_symbols() -> list[str]:
    return [
        re.match(r"kr_(\w+)_daily", f.name).group(1)
        for f in sorted(OHLCV_DIR.glob("kr_*_daily.csv"))
        if re.match(r"kr_(\w+)_daily", f.name)
    ]


def _load_current_price_map() -> dict[str, float]:
    """symbol → 현재가. KIS 스냅샷 우선, 없으면 OHLCV 최신 종가로 폴백."""
    prices: dict[str, float] = {}
    for row in _read_csv(KIS_PRICE):
        sym = str(row.get("symbol", "")).strip().zfill(6)
        price = _num(row.get("currentPrice") or row.get("current_price") or row.get("last_price"))
        if sym and price:
            prices[sym] = price
    for f in OHLCV_DIR.glob("kr_*_daily.csv"):
        m = re.match(r"kr_(\w+)_daily", f.name)
        if not m:
            continue
        sym = m.group(1).zfill(6)
        if sym in prices:
            continue
        rows = _read_csv(f)
        if rows:
            close = _num(rows[-1].get("close"))
            if close:
                prices[sym] = close
    return prices


def fetch_financials(corp_code: str, year: str) -> dict[str, float | None]:
    """DART 단일기업 재무제표 조회 → 주요 지표 추출"""
    url = f"{BASE_URL}/fnlttSinglAcnt.json"
    params = {"crtfc_key": DART_KEY, "corp_code": corp_code,
              "bsns_year": year, "reprt_code": REPORT_CODE}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception:
        return {}

    if data.get("status") != "000":
        return {}

    # 연결재무제표 우선, 없으면 별도
    items_all = data.get("list", [])
    consol = [r for r in items_all if r.get("fs_div") == "CFS"]
    items = consol if consol else items_all

    result: dict[str, float | None] = {}
    for key, names in ACCOUNT_MAP.items():
        for row in items:
            if any(n in str(row.get("account_nm", "")) for n in names):
                val = _num(row.get("thstrm_amount"))
                if val is not None:
                    result[key] = val
                    break
    return result


def _calc_ratios(cur: dict, prev: dict) -> dict[str, Any]:
    rev  = cur.get("revenue")
    oi   = cur.get("operating_income")
    ni   = cur.get("net_income")
    eq   = cur.get("total_equity")
    debt = cur.get("total_debt")
    eps  = cur.get("eps")
    eps_p = prev.get("eps") if prev else None

    def _div(a, b):
        return round(a / b * 100, 2) if a and b and b != 0 else None

    roe          = _div(ni, eq)
    debt_ratio   = _div(debt, eq)
    op_margin    = _div(oi, rev)
    net_margin   = _div(ni, rev)
    rev_prev     = prev.get("revenue") if prev else None
    rev_growth   = _div(rev - rev_prev, rev_prev) if rev and rev_prev else None
    eps_growth   = _div(eps - eps_p, abs(eps_p)) if eps and eps_p and eps_p != 0 else None

    return {
        "roe": roe, "debt_ratio": debt_ratio,
        "operating_margin": op_margin, "net_margin": net_margin,
        "revenue_growth": rev_growth, "eps_growth": eps_growth,
    }


def _calc_scores(ratios: dict) -> dict[str, float]:
    """ROE/부채비율/영업이익률 기반 품질·가치·성장 점수"""
    roe     = _num(ratios.get("roe"))
    debt    = _num(ratios.get("debt_ratio"))
    op_m    = _num(ratios.get("operating_margin"))
    rev_g   = _num(ratios.get("revenue_growth"))
    eps_g   = _num(ratios.get("eps_growth"))

    quality = 50.0
    if roe is not None:
        quality += min(25.0, max(-15.0, (roe - 10) * 1.5))
    if debt is not None:
        quality += min(15.0, max(-15.0, (100 - debt) * 0.15))
    if op_m is not None:
        quality += min(15.0, max(-10.0, op_m * 0.8))
    quality = max(0.0, min(100.0, round(quality, 1)))

    growth = 50.0
    if rev_g is not None:
        growth += min(25.0, max(-20.0, rev_g * 1.5))
    if eps_g is not None:
        growth += min(20.0, max(-15.0, eps_g * 1.2))
    growth = max(0.0, min(100.0, round(growth, 1)))

    # 가치점수: PEG < 1.0이면 높음 (PEG는 별도 계산)
    value = 50.0
    if roe is not None and roe > 0:
        value += min(20.0, roe * 0.8)
    if debt is not None:
        value += min(10.0, max(-10.0, (100 - debt) * 0.1))
    value = max(0.0, min(100.0, round(value, 1)))

    return {"quality_score": quality, "value_score": value, "growth_score": growth}


def _calc_market_ratios(fin: dict, price: float | None) -> dict[str, float | None]:
    """
    PER/PBR/시가총액/유통주식수를 현재가 기준으로 산출.
    DART 재무제표 API(fnlttSinglAcntAll)는 시장가 기반 비율(PER/PBR)을 제공하지 않으므로,
    EPS·순이익으로 유통주식수를 역산해 현재가와 결합한다.
    유통주식수 = 당기순이익 / EPS (자기주식 등으로 실제 상장주식수와는 약간 차이 가능)
    """
    eps = fin.get("eps")
    net_income = fin.get("net_income")
    equity = fin.get("total_equity")

    shares = None
    if eps and net_income and eps != 0:
        shares = net_income / eps

    per = pbr = market_cap = None
    if price:
        if eps and eps > 0:
            per = round(price / eps, 2)
        if shares:
            market_cap = round(price * shares, 0)
            if equity and equity != 0:
                bvps = equity / shares
                if bvps > 0:
                    pbr = round(price / bvps, 2)

    return {"shares_outstanding": shares, "market_cap": market_cap, "per": per, "pbr": pbr}


def main() -> None:
    if not DART_KEY:
        print("[DART] DART_API_KEY 없음 — skip")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    corp_map = _build_corp_map()
    symbols  = _get_ohlcv_symbols()
    price_map = _load_current_price_map()

    print(f"[{now}] DART 재무 수집 시작: {len(symbols)}개 종목")

    # 기존 데이터 로드 (중복 방지 + 캐시된 행 보존용)
    existing: dict[str, dict] = {}
    out_by_key: dict[str, dict] = {}
    for row in _read_csv(OUT):
        key = f"{row.get('symbol')}_{row.get('year')}"
        existing[key] = row
        out_by_key[key] = row   # 캐시 적중 시에도 결과에서 누락되지 않도록 보존

    success = 0

    for i, sym in enumerate(symbols):
        sym6 = sym.zfill(6)
        corp_code = corp_map.get(sym6)
        if not corp_code:
            continue

        row_out: dict = {"symbol": sym6, "corp_code": corp_code, "updatedAt": now}

        prev_data: dict = {}
        for year in YEARS:
            cache_key = f"{sym6}_{year}"
            if cache_key in existing:
                data_year = {k: existing[cache_key].get(k) for k in ACCOUNT_MAP}
                prev_data = data_year
                continue

            fin = fetch_financials(corp_code, year)
            time.sleep(0.15)   # DART API rate limit 준수

            if fin:
                ratios = _calc_ratios(fin, prev_data if year == YEARS[0] else {})
                scores = _calc_scores(ratios)
                market = _calc_market_ratios(fin, price_map.get(sym6))
                per, pbr = market.get("per"), market.get("pbr")

                # EPS 성장률 기반 PEG (PER 있을 때만)
                peg = None
                if per and ratios.get("eps_growth") and ratios["eps_growth"] > 0:
                    peg = round(per / ratios["eps_growth"], 2)

                row_out.update({
                    "year": year,
                    "revenue": fin.get("revenue", ""),
                    "operating_income": fin.get("operating_income", ""),
                    "net_income": fin.get("net_income", ""),
                    "total_equity": fin.get("total_equity", ""),
                    "total_debt": fin.get("total_debt", ""),
                    "total_assets": fin.get("total_assets", ""),
                    "current_assets": fin.get("current_assets", ""),
                    "current_liabilities": fin.get("current_liabilities", ""),
                    "retained_earnings": fin.get("retained_earnings", ""),
                    "eps": fin.get("eps", ""),
                    "eps_prev": prev_data.get("eps", ""),
                    "per": per or "",
                    "pbr": pbr or "",
                    "shares_outstanding": market.get("shares_outstanding") or "",
                    "market_cap": market.get("market_cap") or "",
                    **{k: ratios.get(k, "") for k in ["roe","debt_ratio","operating_margin","net_margin","revenue_growth","eps_growth"]},
                    "peg": peg or "",
                    **scores,
                })
                out_by_key[cache_key] = dict(row_out)
                existing[cache_key] = row_out
                prev_data = fin
                success += 1
            else:
                prev_data = {}

        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(symbols)} 처리 중... (성공: {success})")
            _write_csv(OUT, list(out_by_key.values()))   # 중간 저장

    results = list(out_by_key.values())
    _write_csv(OUT, results)

    status = {
        "updatedAt": now,
        "total": len(symbols),
        "success": success,
        "outputRows": len(results),
    }
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{now}] DART 재무 수집 완료: {success}/{len(symbols)}개")


if __name__ == "__main__":
    main()
