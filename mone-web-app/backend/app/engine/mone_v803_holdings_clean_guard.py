from __future__ import annotations

from typing import Any

from fastapi import Query
from fastapi.routing import APIRoute


def _num(value: Any) -> float:
    try:
        text = str(value if value is not None else "").replace(",", "").replace("USD", "").replace("$", "").replace("KRW", "").replace("원", "").replace("%", "").strip()
        if not text or text in {"-", "None", "nan", "null"}:
            return 0.0
        return float(text)
    except Exception:
        return 0.0


def _fmt_price(value: float, market: str) -> str:
    if value <= 0:
        return "-"
    if market == "us":
        return f"${value:,.2f}"
    return f"{round(value):,}원"


def _fmt_money(value: float, market: str) -> str:
    if market == "us":
        return f"${value:,.2f}"
    return f"{round(value):,}원"


def _fmt_pct(value: float, signed: bool = True) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.2f}%"


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items or []:
        symbol = str(item.get("symbol") or item.get("code") or item.get("ticker") or "").upper()
        market = str(item.get("market") or ("kr" if symbol.isdigit() and len(symbol) == 6 else "us")).lower()
        key = f"{market}-{symbol}"
        if not symbol or key in seen:
            continue
        seen.add(key)
        out.append({**item, "symbol": symbol, "market": market})
    return out


def _enrich_item(item: dict[str, Any]) -> dict[str, Any]:
    market = str(item.get("market") or "kr").lower()
    computed = list(item.get("computedFields") or [])
    missing = [field for field in list(item.get("missingFields") or []) if field not in {"stop", "target", "valuation", "pnl"}]

    quantity = _num(item.get("quantity") or item.get("qty"))
    avg = _num(item.get("avgPrice") or item.get("buyPrice") or item.get("avgPriceText"))
    current = _num(item.get("currentPrice") or item.get("currentPriceText"))
    prev_close = _num(item.get("prevClose") or item.get("previousClose") or item.get("prevCloseText"))

    valuation = _num(item.get("valuation") or item.get("valuationText"))
    cost = _num(item.get("cost"))
    pnl = _num(item.get("pnl") or item.get("pnlText"))
    pnl_pct = _num(item.get("pnlPct") or item.get("pnlPctText"))

    if quantity > 0 and current > 0:
        valuation = quantity * current
        computed.append("valuation")
    if quantity > 0 and avg > 0:
        cost = quantity * avg
        computed.append("cost")
    if valuation > 0 and cost > 0:
        pnl = valuation - cost
        pnl_pct = pnl / cost * 100
        computed.extend(["pnl", "pnlPct"])

    stop = _num(item.get("stopPrice") or item.get("stop") or item.get("stopText"))
    target = _num(item.get("targetPrice") or item.get("target") or item.get("targetText"))
    base = avg if avg > 0 else current
    if stop <= 0 and base > 0:
        stop = base * 0.92
        computed.append("stop_from_risk_rule")
    if target <= 0 and base > 0:
        target = base * 1.12
        computed.append("target_from_risk_rule")

    stop_gap = None
    target_gap = None
    if current > 0 and stop > 0:
        stop_gap = (current - stop) / current * 100
        computed.append("stopGapPct")
    if current > 0 and target > 0:
        target_gap = (target - current) / current * 100
        computed.append("targetGapPct")

    change_pct = _num(item.get("changePct") or item.get("changePctText"))
    if current > 0 and prev_close > 0:
        change_pct = (current - prev_close) / prev_close * 100
        computed.append("changePct")

    risk_status = str(item.get("riskStatus") or "NORMAL")
    if stop_gap is not None and stop_gap <= 3:
        risk_status = "WATCH"
    if stop_gap is not None and stop_gap <= 0:
        risk_status = "HIGH"

    computed_unique = []
    for field in computed:
        if field and field not in computed_unique:
            computed_unique.append(field)

    return {
        **item,
        "quantity": quantity,
        "avgPrice": avg,
        "currentPrice": current,
        "prevClose": prev_close if prev_close > 0 else item.get("prevClose"),
        "valuation": valuation,
        "cost": cost,
        "pnl": pnl,
        "pnlPct": pnl_pct,
        "stopPrice": stop,
        "targetPrice": target,
        "stopGapPct": stop_gap,
        "targetGapPct": target_gap,
        "changePct": change_pct,
        "riskStatus": risk_status,
        "currentPriceText": _fmt_price(current, market),
        "avgPriceText": _fmt_price(avg, market),
        "valuationText": _fmt_money(valuation, market),
        "pnlText": _fmt_money(pnl, market),
        "pnlPctText": _fmt_pct(pnl_pct),
        "stopText": _fmt_price(stop, market),
        "targetText": _fmt_price(target, market),
        "changePctText": _fmt_pct(change_pct),
        "computedFields": computed_unique,
        "missingFields": missing,
    }


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_value = sum(_num(item.get("valuation")) for item in items)
    total_pnl = sum(_num(item.get("pnl")) for item in items)
    risk_count = sum(1 for item in items if str(item.get("riskStatus") or "").upper() in {"WATCH", "HIGH", "주의", "위험"})
    missing_count = sum(1 for item in items if item.get("missingFields"))
    return {
        "holdingCount": len(items),
        "riskCount": risk_count,
        "missingCount": missing_count,
        "totalValue": total_value,
        "totalPnl": total_pnl,
        "totalValueText": f"{round(total_value):,}원",
        "totalPnlText": f"{round(total_pnl):,}원",
    }


def _fallback_payload(market: str, limit: int) -> dict[str, Any]:
    from app.engine.mone_v77_holdings_risk import holdings_payload

    payload = holdings_payload(market, limit)
    items = [_enrich_item(item) for item in _dedupe(list(payload.get("items") or []))]
    items = items[: max(1, min(limit, 1000))]
    return {
        **payload,
        "status": "OK" if items else payload.get("status", "NO_DATA"),
        "routeVersion": "v80.2-clean",
        "market": market,
        "count": len(items),
        "uniqueCount": len(items),
        "items": items,
        "summary": _summary(items),
        "compatFallback": True,
        "compatReason": "v80.2 원본 정리 루틴 대신 계산 보강 안전 응답을 사용했습니다.",
    }


def register_mone_v803_holdings_clean_guard(app: Any) -> None:
    path = "/api/holdings-clean"
    app.router.routes = [
        route
        for route in app.router.routes
        if not (isinstance(route, APIRoute) and getattr(route, "path", "") == path)
    ]

    @app.get(path)
    def holdings_clean(market: str = Query("all"), limit: int = Query(500)) -> dict[str, Any]:
        return _fallback_payload(market, limit)
