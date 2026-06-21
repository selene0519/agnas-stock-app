"""
MONE 절대가치 점검 / 부도위험·레버리지 분석
- DCF / RIM / EVA(proxy) 절대가치 평가
- Altman Z-score 부도위험 진단
- DOL/DFL/DCL 레버리지 민감도

원천 데이터: reports/dart_financial_data_kr.csv (scripts/fetch_dart_financials.py가 채움)
모든 계산은 가정(할인율·성장률·세율)을 명시하고, 필요 데이터가 없으면
값을 지어내지 않고 누락 사유를 그대로 반환한다 (MONE 데이터 투명성 원칙).
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

_APP_DIR = Path(__file__).resolve().parents[3]  # backend/app/services → backend/app → backend → mone-web-app
REPO_ROOT = Path(os.environ.get("MONE_REPO_ROOT", _APP_DIR.parent)).resolve()
DART_CSV = REPO_ROOT / "reports" / "dart_financial_data_kr.csv"

# ── 가정값 (명시적으로 고정, 추후 조정 가능) ──────────────────────────
DISCOUNT_RATE = 0.10     # DCF 요구수익률
PERPETUAL_GROWTH = 0.03  # DCF 영구성장률
COST_OF_EQUITY = 0.09    # RIM 자기자본 비용
TAX_RATE = 0.22          # 법인세 실효세율 가정 (DFL 역산용)


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        s = str(v).strip()
        if s in ("", "nan", "None", "-"):
            return None
        return float(s.replace(",", ""))
    except Exception:
        return None


_dart_cache: dict[str, Any] = {"mtime": None, "by_symbol": {}}


def _load_dart_csv_grouped() -> dict[str, list[dict[str, Any]]]:
    """DART CSV 전체를 1회 로드 후 심볼별로 그룹화 (mtime 변경 시 재로딩)."""
    if not DART_CSV.exists():
        return {}
    mtime = DART_CSV.stat().st_mtime
    if _dart_cache["mtime"] == mtime:
        return _dart_cache["by_symbol"]

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with DART_CSV.open(encoding=enc, newline="") as f:
                for row in csv.DictReader(f):
                    sym6 = str(row.get("symbol", "")).strip().zfill(6)
                    if sym6:
                        by_symbol.setdefault(sym6, []).append(row)
            break
        except Exception:
            continue

    for rows in by_symbol.values():
        rows.sort(key=lambda r: str(r.get("year", "")), reverse=True)

    _dart_cache["mtime"] = mtime
    _dart_cache["by_symbol"] = by_symbol
    return by_symbol


def _read_dart_rows(symbol: str) -> list[dict[str, Any]]:
    """심볼의 전체 연도 행(2024/2023 등)을 그대로 반환 (연도 내림차순)."""
    sym6 = symbol.strip().zfill(6)
    return _load_dart_csv_grouped().get(sym6, [])


def _dcf(eps: float | None, price: float | None) -> dict[str, Any]:
    if not eps or eps <= 0:
        return {"fairValue": None, "gapPct": None, "status": "DATA_PENDING",
                "missing": ["eps"], "note": "EPS가 없어 계산할 수 없습니다."}
    fair_value = round(eps * (1 + PERPETUAL_GROWTH) / (DISCOUNT_RATE - PERPETUAL_GROWTH), 0)
    gap_pct = round((fair_value - price) / price * 100, 1) if price else None
    return {
        "fairValue": fair_value,
        "gapPct": gap_pct,
        "status": "PARTIAL",
        "missing": [],
        "note": f"실제 현금흐름이 없어 EPS를 보수적 현금흐름 대용치로 사용했습니다 (할인율 {DISCOUNT_RATE*100:.0f}%, 영구성장률 {PERPETUAL_GROWTH*100:.0f}% 가정).",
    }


def _rim(roe: float | None, equity: float | None, shares: float | None, price: float | None) -> dict[str, Any]:
    missing = []
    if roe is None:
        missing.append("roe")
    if not equity:
        missing.append("totalEquity")
    if not shares:
        missing.append("sharesOutstanding")
    if missing:
        return {"fairValue": None, "gapPct": None, "status": "DATA_PENDING",
                "missing": missing, "note": "잔여이익모형은 ROE·자본총계·유통주식수가 함께 필요합니다."}

    bvps = equity / shares
    fair_pbr = max(0.0, (roe / 100) / COST_OF_EQUITY)
    fair_value = round(bvps * fair_pbr, 0)
    gap_pct = round((fair_value - price) / price * 100, 1) if price else None
    return {
        "fairValue": fair_value,
        "gapPct": gap_pct,
        "status": "PARTIAL",
        "missing": [],
        "note": f"적정 PBR = ROE/자기자본비용({COST_OF_EQUITY*100:.0f}% 가정)으로 추정한 근사치입니다.",
    }


def _eva_proxy(operating_margin: float | None, debt_ratio: float | None, quality_score: float | None) -> dict[str, Any]:
    missing = []
    if operating_margin is None:
        missing.append("operatingMargin")
    if debt_ratio is None:
        missing.append("debtRatio")
    if quality_score is None:
        missing.append("qualityScore")
    if missing:
        return {"score": None, "label": None, "status": "DATA_PENDING",
                "missing": missing, "note": "EVA 금액 대신 영업마진·부채비율·품질점수로 경제적 이익 가능성을 점검합니다."}

    margin_score = max(0.0, min(40.0, operating_margin * 1.2))
    debt_score = max(0.0, min(30.0, (150 - debt_ratio) * 0.2))
    quality_part = quality_score * 0.3
    score = round(max(0.0, min(100.0, margin_score + debt_score + quality_part)), 1)
    label = "높음" if score >= 65 else "중간" if score >= 40 else "낮음"
    return {
        "score": score,
        "label": label,
        "status": "OK",
        "missing": [],
        "note": "NOPAT/WACC 대신 영업마진·부채비율·품질점수 가중합으로 산출한 경제적 이익 가능성 점수입니다 (실제 EVA 금액 아님).",
    }


def _altman_z(
    current_assets: float | None, current_liabilities: float | None,
    total_assets: float | None, retained_earnings: float | None,
    operating_income: float | None, market_cap: float | None,
    total_debt: float | None, revenue: float | None,
) -> dict[str, Any]:
    missing = []
    if current_assets is None:
        missing.append("currentAssets")
    if current_liabilities is None:
        missing.append("currentLiabilities")
    if not total_assets:
        missing.append("totalAssets")
    if retained_earnings is None:
        missing.append("retainedEarnings")
    if operating_income is None:
        missing.append("operatingIncome (EBIT 대용)")
    if not market_cap:
        missing.append("marketCap")
    if not total_debt:
        missing.append("totalLiabilities")
    if revenue is None:
        missing.append("revenue")
    if missing:
        return {"score": None, "zone": None, "status": "DATA_PENDING",
                "missing": missing, "note": "Altman Z-score는 자산총계/유동자산/유동부채/이익잉여금/영업이익/시가총액/부채총계/매출이 모두 필요합니다."}

    working_capital = current_assets - current_liabilities
    a = working_capital / total_assets
    b = retained_earnings / total_assets
    c = operating_income / total_assets
    d = market_cap / total_debt
    e = revenue / total_assets

    z = round(1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e, 2)
    zone = "안전" if z > 2.99 else "회색" if z >= 1.81 else "위험"
    return {
        "score": z,
        "zone": zone,
        "status": "OK",
        "missing": [],
        "note": "EBIT은 영업이익으로 대용했습니다. 2.99 초과: 안전 / 1.81~2.99: 회색지대 / 1.81 미만: 부도위험 높음.",
    }


def _leverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 2:
        return {"dol": None, "dfl": None, "dcl": None, "status": "DATA_PENDING",
                "missing": ["prevYearFinancials"], "note": "DOL 계산에는 최소 2개년 매출·영업이익이 필요합니다."}

    cur, prev = rows[0], rows[1]
    rev_cur, rev_prev = _f(cur.get("revenue")), _f(prev.get("revenue"))
    oi_cur, oi_prev = _f(cur.get("operating_income")), _f(prev.get("operating_income"))
    net_income = _f(cur.get("net_income"))

    missing = []
    if not rev_cur or not rev_prev:
        missing.append("revenue(2개년)")
    if not oi_cur or not oi_prev:
        missing.append("operatingIncome(2개년)")
    if missing:
        return {"dol": None, "dfl": None, "dcl": None, "status": "DATA_PENDING",
                "missing": missing, "note": "2개년 매출·영업이익 데이터가 부족합니다."}

    sales_chg_pct = (rev_cur - rev_prev) / abs(rev_prev)
    ebit_chg_pct = (oi_cur - oi_prev) / abs(oi_prev)
    dol = round(ebit_chg_pct / sales_chg_pct, 2) if sales_chg_pct != 0 else None

    dfl = None
    if net_income and oi_cur:
        pretax_income = net_income / (1 - TAX_RATE)
        if pretax_income != 0:
            dfl = round(oi_cur / pretax_income, 2)

    dcl = round(dol * dfl, 2) if dol is not None and dfl is not None else None

    return {
        "dol": dol,
        "dfl": dfl,
        "dcl": dcl,
        "status": "OK" if dol is not None and dfl is not None else "PARTIAL",
        "missing": [],
        "note": f"DFL은 법인세율 {TAX_RATE*100:.0f}% 가정으로 세전이익을 역산한 근사치입니다.",
    }


def compute_valuation(symbol: str, market: str, current_price: float | None) -> dict[str, Any]:
    """절대가치 점검 + 부도위험/레버리지 전체 결과."""
    if market != "kr":
        return {
            "status": "DATA_UNAVAILABLE",
            "note": "현재 DART 기반 절대가치/부도위험 분석은 국내(KR) 종목만 지원합니다.",
            "dcf": None, "rim": None, "eva": None, "altmanZ": None, "leverage": None,
        }

    rows = _read_dart_rows(symbol)
    if not rows:
        return {
            "status": "DATA_PENDING",
            "note": "DART 재무 데이터가 아직 수집되지 않았습니다 (매주 자동 갱신).",
            "dcf": None, "rim": None, "eva": None, "altmanZ": None, "leverage": None,
        }

    row = rows[0]
    eps = _f(row.get("eps"))
    roe = _f(row.get("roe"))
    equity = _f(row.get("total_equity"))
    shares = _f(row.get("shares_outstanding"))
    op_margin = _f(row.get("operating_margin"))
    debt_ratio = _f(row.get("debt_ratio"))
    quality_score = _f(row.get("quality_score"))
    current_assets = _f(row.get("current_assets"))
    current_liabilities = _f(row.get("current_liabilities"))
    total_assets = _f(row.get("total_assets"))
    retained_earnings = _f(row.get("retained_earnings"))
    operating_income = _f(row.get("operating_income"))
    market_cap = _f(row.get("market_cap"))
    total_debt = _f(row.get("total_debt"))
    revenue = _f(row.get("revenue"))

    if not total_assets and equity is not None and total_debt is not None:
        total_assets = equity + total_debt  # 자산 = 자본 + 부채 (보강)
    if not market_cap and current_price and shares:
        market_cap = round(current_price * shares, 0)

    return {
        "status": "OK",
        "year": row.get("year"),
        "note": "절대가치 평가는 보조 진단이며 MONE 추천 점수에는 반영하지 않습니다.",
        "dcf": _dcf(eps, current_price),
        "rim": _rim(roe, equity, shares, current_price),
        "eva": _eva_proxy(op_margin, debt_ratio, quality_score),
        "altmanZ": _altman_z(
            current_assets, current_liabilities, total_assets, retained_earnings,
            operating_income, market_cap, total_debt, revenue,
        ),
        "leverage": _leverage(rows),
    }
