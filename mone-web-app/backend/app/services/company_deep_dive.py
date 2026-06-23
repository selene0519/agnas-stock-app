from __future__ import annotations

import math
import re
from typing import Any


Number = float | int


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return float(value)
        return None
    text = _clean_text(value)
    if not text or text.lower() in {"nan", "none", "null", "na", "-", "data_pending"}:
        return None
    text = text.replace("%", "").replace(",", "").replace("$", "").replace("₩", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        out = float(match.group(0))
    except Exception:
        return None
    return -out if negative else out


def _money(value: Any) -> float | None:
    """Parse human financial strings into raw currency units where possible."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(float(value)) else None
    text = _clean_text(value)
    base = _num(text)
    if base is None:
        return None
    if "조" in text:
        return base * 1_0000_0000_0000
    if "억" in text:
        return base * 100_000_000
    if "trillion" in text.lower():
        return base * 1_000_000_000_000
    if "billion" in text.lower() or text.upper().endswith("B"):
        return base * 1_000_000_000
    if "million" in text.lower() or text.upper().endswith("M"):
        return base * 1_000_000
    return base


def _pick(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if _clean_text(value) and _num(value) is not None:
            return value
    return None


def _pct(value: Any) -> float | None:
    out = _num(value)
    if out is None:
        return None
    if abs(out) <= 1:
        return out * 100
    return out


def _status_label(status: str) -> str:
    return {
        "NORMAL": "계산 가능",
        "PARTIAL": "부분 계산",
        "DATA_PENDING": "데이터 대기",
        "ASSUMPTION_REQUIRED": "가정 필요",
    }.get(status, status)


def _method(
    key: str,
    label: str,
    status: str,
    fair_value: float | None,
    current_price: float | None,
    assumptions: list[str],
    missing: list[str],
    note: str,
) -> dict[str, Any]:
    upside = None
    if fair_value is not None and current_price and current_price > 0:
        upside = round((fair_value - current_price) / current_price * 100, 1)
    return {
        "key": key,
        "label": label,
        "status": status,
        "statusLabel": _status_label(status),
        "fairValue": round(fair_value, 2) if fair_value is not None else None,
        "upsidePct": upside,
        "assumptions": assumptions,
        "missingFields": missing,
        "note": note,
    }


def _derive_eps(row: dict[str, Any], current_price: float | None) -> float | None:
    eps = _num(_pick(row, ["eps", "EPS", "basicEps", "dilutedEps"]))
    if eps and eps > 0:
        return eps
    per = _num(_pick(row, ["per", "PER", "trailingPE", "forwardPE"]))
    if current_price and per and per > 0:
        return current_price / per
    return None


def _intrinsic_valuation(row: dict[str, Any], current_price: float | None, market: str) -> dict[str, Any]:
    eps = _derive_eps(row, current_price)
    per = _num(_pick(row, ["per", "PER", "trailingPE", "forwardPE"]))
    pbr = _num(_pick(row, ["pbr", "PBR", "priceToBook"]))
    roe = _pct(_pick(row, ["roe", "ROE", "returnOnEquity"]))
    growth = _pct(_pick(row, ["epsGrowth", "eps_growth", "revenueGrowth", "revenue_growth"]))
    cost = 9.0 if market == "kr" else 8.5
    terminal_growth = 2.0 if market == "kr" else 2.5
    growth_assumption = max(-5.0, min((growth if growth is not None else terminal_growth), 8.0))

    methods: list[dict[str, Any]] = []

    if eps and current_price:
        cashflow = eps * 0.82
        fair = 0.0
        for year in range(1, 6):
            projected = cashflow * ((1 + growth_assumption / 100) ** year)
            fair += projected / ((1 + cost / 100) ** year)
        terminal = (cashflow * ((1 + growth_assumption / 100) ** 5) * (1 + terminal_growth / 100))
        terminal /= max((cost - terminal_growth) / 100, 0.01)
        fair += terminal / ((1 + cost / 100) ** 5)
        methods.append(_method(
            "dcf",
            "DCF",
            "PARTIAL",
            fair,
            current_price,
            [f"자본비용 {cost:.1f}%", f"5년 성장률 {growth_assumption:.1f}%", "EPS 기반 오너이익 82%"],
            ["실제 FCF", "주식수/희석효과"],
            "실제 현금흐름이 없어 EPS를 보수적 현금흐름 대용치로 사용했습니다.",
        ))
    else:
        missing = []
        if not current_price:
            missing.append("현재가")
        if not eps:
            missing.append("EPS 또는 PER")
        methods.append(_method(
            "dcf",
            "DCF",
            "DATA_PENDING",
            None,
            current_price,
            [f"자본비용 {cost:.1f}%"],
            missing,
            "현재가와 EPS/PER가 있어야 주당 현금흐름 프록시를 만들 수 있습니다.",
        ))

    if current_price and pbr and pbr > 0 and roe is not None:
        bvps = current_price / pbr
        spread = (roe - cost) / 100
        residual = 0.0
        for year in range(1, 6):
            fade = max(0.2, 1 - (year - 1) * 0.18)
            residual += (bvps * spread * fade) / ((1 + cost / 100) ** year)
        fair = max(0.0, bvps + residual)
        methods.append(_method(
            "rim",
            "RIM",
            "PARTIAL",
            fair,
            current_price,
            [f"자본비용 {cost:.1f}%", "초과 ROE 5년 페이드"],
            ["정확한 BVPS"],
            "PBR로 장부가치를 역산해 잔여이익을 추정했습니다.",
        ))
    else:
        missing = []
        if not current_price:
            missing.append("현재가")
        if not pbr or pbr <= 0:
            missing.append("PBR")
        if roe is None:
            missing.append("ROE")
        methods.append(_method(
            "rim",
            "RIM",
            "DATA_PENDING",
            None,
            current_price,
            [f"자본비용 {cost:.1f}%"],
            missing,
            "잔여이익모형은 현재가/PBR/ROE가 함께 필요합니다.",
        ))

    operating_margin = _pct(_pick(row, ["operatingMargin", "operating_margin"]))
    debt_ratio = _pct(_pick(row, ["debtRatio", "debt_ratio", "debtToEquity"]))
    quality = _num(_pick(row, ["qualityScore", "quality_score", "fundamentalScore"]))
    eva_note = "투하자본과 세후영업이익이 없어 EVA 금액은 계산하지 않았습니다."
    eva_status = "DATA_PENDING"
    if operating_margin is not None or debt_ratio is not None or quality is not None:
        eva_status = "PARTIAL"
        eva_note = "EVA 금액 대신 영업마진, 부채비율, 품질점수로 경제적 이익 가능성을 점검합니다."
    methods.append(_method(
        "eva",
        "EVA",
        eva_status,
        None,
        current_price,
        ["WACC 8.5~9.0% 기준"],
        ["NOPAT", "투하자본", "WACC"],
        eva_note,
    ))

    available = [m for m in methods if m.get("fairValue") is not None]
    consensus = None
    consensus_upside = None
    if available:
        consensus = round(sum(float(m["fairValue"]) for m in available) / len(available), 2)
        if current_price:
            consensus_upside = round((consensus - current_price) / current_price * 100, 1)
    status = "PARTIAL" if available else "DATA_PENDING"
    return {
        "status": status,
        "scoreBearing": False,
        "currentPrice": current_price,
        "consensusFairValue": consensus,
        "consensusUpsidePct": consensus_upside,
        "methods": methods,
        "disclaimer": "절대가치 평가는 보조 진단이며 MONE 추천 점수에는 반영하지 않습니다.",
    }


def _bankruptcy_risk(row: dict[str, Any]) -> dict[str, Any]:
    working_capital = _money(_pick(row, ["workingCapital", "working_capital"]))
    total_assets = _money(_pick(row, ["totalAssets", "total_assets", "assets"]))
    retained_earnings = _money(_pick(row, ["retainedEarnings", "retained_earnings"]))
    ebit = _money(_pick(row, ["ebit", "EBIT", "operatingIncome", "operatingProfit"]))
    market_value_equity = _money(_pick(row, ["marketCap", "market_value_equity"]))
    total_liabilities = _money(_pick(row, ["totalLiabilities", "total_liabilities", "liabilities"]))
    sales = _money(_pick(row, ["revenue", "sales", "totalRevenue"]))
    missing = []
    for label, value in [
        ("workingCapital", working_capital),
        ("totalAssets", total_assets),
        ("retainedEarnings", retained_earnings),
        ("EBIT", ebit),
        ("marketValueEquity", market_value_equity),
        ("totalLiabilities", total_liabilities),
        ("sales", sales),
    ]:
        if value is None:
            missing.append(label)

    z_score = None
    zone = "DATA_PENDING"
    zone_label = "Altman 계산 대기"
    if not missing and total_assets and total_liabilities:
        z_score = (
            1.2 * (working_capital / total_assets)
            + 1.4 * (retained_earnings / total_assets)
            + 3.3 * (ebit / total_assets)
            + 0.6 * (market_value_equity / total_liabilities)
            + 1.0 * (sales / total_assets)
        )
        if z_score >= 2.99:
            zone, zone_label = "SAFE", "안전권"
        elif z_score >= 1.81:
            zone, zone_label = "GRAY", "관찰권"
        else:
            zone, zone_label = "DISTRESS", "위험권"

    debt_ratio = _pct(_pick(row, ["debtRatio", "debt_ratio", "debtToEquity"]))
    operating_margin = _pct(_pick(row, ["operatingMargin", "operating_margin"]))
    net_margin = _pct(_pick(row, ["netMargin", "net_margin"]))
    quality = _num(_pick(row, ["qualityScore", "quality_score", "fundamentalScore"]))
    proxy: list[dict[str, str]] = []

    if debt_ratio is not None:
        if debt_ratio <= 80:
            proxy.append({"type": "positive", "text": f"부채비율 {debt_ratio:.1f}%로 부담이 낮은 편입니다."})
        elif debt_ratio <= 180:
            proxy.append({"type": "neutral", "text": f"부채비율 {debt_ratio:.1f}%로 추가 확인이 필요합니다."})
        else:
            proxy.append({"type": "warning", "text": f"부채비율 {debt_ratio:.1f}%로 재무 레버리지 부담이 큽니다."})
    if operating_margin is not None:
        if operating_margin >= 10:
            proxy.append({"type": "positive", "text": f"영업마진 {operating_margin:.1f}%로 이익 방어력이 있습니다."})
        elif operating_margin <= 3:
            proxy.append({"type": "warning", "text": f"영업마진 {operating_margin:.1f}%로 비용 충격에 취약할 수 있습니다."})
        else:
            proxy.append({"type": "neutral", "text": f"영업마진 {operating_margin:.1f}%는 보통권입니다."})
    if net_margin is not None and net_margin < 2:
        proxy.append({"type": "warning", "text": f"순이익률 {net_margin:.1f}%로 최종 수익성이 얇습니다."})
    if quality is not None:
        if quality >= 70:
            proxy.append({"type": "positive", "text": f"품질점수 {quality:.0f}/100으로 재무 안정성 신호가 양호합니다."})
        elif quality < 50:
            proxy.append({"type": "warning", "text": f"품질점수 {quality:.0f}/100으로 재무 안정성 점검이 필요합니다."})

    warning_count = sum(1 for item in proxy if item["type"] == "warning")
    if z_score is not None:
        grade = "LOW" if zone == "SAFE" else "MEDIUM" if zone == "GRAY" else "HIGH"
    elif warning_count >= 2:
        grade = "HIGH"
    elif warning_count == 1 or proxy:
        grade = "MEDIUM"
    else:
        grade = "UNKNOWN"

    return {
        "grade": grade,
        "altman": {
            "status": "NORMAL" if z_score is not None else "DATA_PENDING",
            "score": round(z_score, 2) if z_score is not None else None,
            "zone": zone,
            "zoneLabel": zone_label,
            "missingFields": missing,
        },
        "proxySignals": proxy,
        "scoreBearing": False,
    }


def _leverage_analysis(row: dict[str, Any]) -> dict[str, Any]:
    revenue = _money(_pick(row, ["revenue", "sales", "totalRevenue"]))
    operating_income = _money(_pick(row, ["operatingIncome", "operatingProfit", "EBIT", "ebit"]))
    interest = _money(_pick(row, ["interestExpense", "interest_expense"]))
    contribution_margin = _money(_pick(row, ["contributionMargin", "contribution_margin"]))
    metrics: list[dict[str, Any]] = []

    if contribution_margin and operating_income and operating_income != 0:
        dol = contribution_margin / operating_income
        metrics.append({
            "key": "dol",
            "label": "DOL",
            "value": round(dol, 2),
            "status": "NORMAL",
            "note": "매출 변화가 영업이익에 확대되는 정도입니다.",
            "missingFields": [],
        })
    else:
        metrics.append({
            "key": "dol",
            "label": "DOL",
            "value": None,
            "status": "DATA_PENDING",
            "note": "공헌이익 또는 고정비 구조 데이터가 필요합니다.",
            "missingFields": ["contributionMargin", "operatingIncome"],
        })

    if operating_income and interest is not None and (operating_income - interest) != 0:
        dfl = operating_income / (operating_income - interest)
        metrics.append({
            "key": "dfl",
            "label": "DFL",
            "value": round(dfl, 2),
            "status": "NORMAL",
            "note": "영업이익 변화가 순이익에 확대되는 정도입니다.",
            "missingFields": [],
        })
    else:
        metrics.append({
            "key": "dfl",
            "label": "DFL",
            "value": None,
            "status": "DATA_PENDING",
            "note": "이자비용 데이터가 필요합니다.",
            "missingFields": ["operatingIncome", "interestExpense"],
        })

    dol_value = next((m["value"] for m in metrics if m["key"] == "dol" and m["value"] is not None), None)
    dfl_value = next((m["value"] for m in metrics if m["key"] == "dfl" and m["value"] is not None), None)
    if dol_value is not None and dfl_value is not None:
        metrics.append({
            "key": "dcl",
            "label": "DCL",
            "value": round(float(dol_value) * float(dfl_value), 2),
            "status": "NORMAL",
            "note": "영업 레버리지와 재무 레버리지를 합친 민감도입니다.",
            "missingFields": [],
        })
    else:
        metrics.append({
            "key": "dcl",
            "label": "DCL",
            "value": None,
            "status": "DATA_PENDING",
            "note": "DOL과 DFL이 모두 계산되어야 합니다.",
            "missingFields": ["DOL", "DFL"],
        })

    available = [m for m in metrics if m["value"] is not None]
    status = "NORMAL" if len(available) == 3 else "PARTIAL" if available else "DATA_PENDING"
    proxy_note = None
    if revenue and operating_income:
        margin = operating_income / revenue * 100
        proxy_note = f"현재 확보 데이터 기준 영업이익률은 약 {margin:.1f}%입니다."
    return {
        "status": status,
        "metrics": metrics,
        "proxyNote": proxy_note,
        "scoreBearing": False,
    }


def _challenge_question(
    intrinsic: dict[str, Any],
    bankruptcy: dict[str, Any],
    leverage: dict[str, Any],
    reco: dict[str, Any],
) -> dict[str, Any]:
    ev = _num(reco.get("expectedValue"))
    final_score = _num(reco.get("finalScore"))
    upside = intrinsic.get("consensusUpsidePct")
    if bankruptcy.get("grade") == "HIGH":
        question = "재무위험 신호가 먼저 악화돼도 이 종목을 계속 들고 갈 기준이 명확한가요?"
        reason = "부도위험 대체지표에서 경고가 감지되었습니다."
        severity = "warning"
    elif isinstance(upside, (int, float)) and upside < -10:
        question = "절대가치 보조모형이 현재가보다 낮게 보이는데, 가격 상승을 정당화할 별도 촉매가 있나요?"
        reason = "DCF/RIM 보조 평균이 현재가 대비 낮습니다."
        severity = "warning"
    elif ev is not None and ev < 0:
        question = "기대값이 음수인데도 진입하려는 이유가 뉴스나 익숙한 이름 때문은 아닌가요?"
        reason = "추천 엔진의 기대값이 음수입니다."
        severity = "warning"
    elif intrinsic.get("status") == "DATA_PENDING":
        question = "절대가치 계산에 필요한 핵심 재무값이 비어 있는데, 이 공백을 감수할 만큼 강한 근거가 있나요?"
        reason = "DCF/RIM/EVA 계산 데이터가 부족합니다."
        severity = "caution"
    elif leverage.get("status") == "DATA_PENDING":
        question = "매출 둔화가 이익에 얼마나 크게 번질지 모르는 상태에서 포지션 크기는 충분히 보수적인가요?"
        reason = "레버리지 민감도 데이터가 부족합니다."
        severity = "caution"
    elif final_score is not None and final_score >= 75:
        question = "점수가 높다는 사실 말고, 이 종목이 틀렸다고 판단할 반증 조건을 하나 적어둘 수 있나요?"
        reason = "높은 점수일수록 확증편향 점검이 필요합니다."
        severity = "caution"
    else:
        question = "이 종목을 매수하지 않는다면 가장 설득력 있는 반대 근거는 무엇인가요?"
        reason = "투자 논리를 한 번 반대로 검토합니다."
        severity = "neutral"
    return {
        "severity": severity,
        "question": question,
        "reason": reason,
    }


def build_company_deep_dive(
    company_item: dict[str, Any] | None,
    recommendation: dict[str, Any] | None,
    current_price: Number | None,
    market: str,
) -> dict[str, Any]:
    row = dict(company_item or {})
    reco = dict(recommendation or {})
    for key, value in reco.items():
        row.setdefault(key, value)

    price = float(current_price) if current_price is not None else _num(row.get("currentPrice"))
    intrinsic = _intrinsic_valuation(row, price, market)
    bankruptcy = _bankruptcy_risk(row)
    leverage = _leverage_analysis(row)
    challenge = _challenge_question(intrinsic, bankruptcy, leverage, reco)
    coverage_parts = [
        intrinsic.get("status") != "DATA_PENDING",
        bankruptcy.get("altman", {}).get("status") == "NORMAL" or bool(bankruptcy.get("proxySignals")),
        leverage.get("status") != "DATA_PENDING",
    ]
    return {
        "status": "PARTIAL" if any(coverage_parts) else "DATA_PENDING",
        "scoreBearing": False,
        "coverage": {
            "availableBlocks": sum(1 for item in coverage_parts if item),
            "totalBlocks": len(coverage_parts),
        },
        "intrinsicValuation": intrinsic,
        "bankruptcyRisk": bankruptcy,
        "leverageAnalysis": leverage,
        "challengeQuestion": challenge,
    }
