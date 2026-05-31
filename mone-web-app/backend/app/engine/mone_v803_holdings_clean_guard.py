from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Query
from fastapi.routing import APIRoute


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "reports").exists() and (parent / "mone-web-app").exists():
            return parent
    return here.parents[4]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _text(row: dict[str, Any], keys: list[str], default: str = "") -> str:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] is not None and str(row[key]).strip():
            return str(row[key]).strip()
        low_key = key.lower()
        if low_key in lower and lower[low_key] is not None and str(lower[low_key]).strip():
            return str(lower[low_key]).strip()
    return default


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


def _load_position_rows(market: str) -> list[dict[str, Any]]:
    root = _repo_root()
    markets = ["kr", "us"] if market == "all" else [market]
    rows: list[dict[str, Any]] = []
    for item_market in markets:
        path = root / "reports" / f"v93_position_cards_{item_market}.csv"
        for row in _read_csv(path):
            symbol = str(_text(row, ["symbol", "ticker", "code", "종목코드"], "")).upper()
            if not symbol:
                continue
            rows.append({
                "id": f"{item_market}-{symbol}",
                "symbol": symbol,
                "name": _text(row, ["name", "종목명"], symbol),
                "market": item_market,
                "quantity": _num(_text(row, ["quantity", "보유수량"], "0")),
                "avgPrice": _num(_text(row, ["avg_price", "avgPrice", "평균단가"], "0")),
                "currentPrice": _num(_text(row, ["current_price", "last_price", "currentPrice", "현재가"], "0")),
                "currentPriceText": _text(row, ["현재가", "currentPriceText"], ""),
                "changePctText": _text(row, ["수익률", "changePctText"], ""),
                "pnlText": _text(row, ["평가손익", "pnlText"], ""),
                "source": path.name,
                "quoteSource": _text(row, ["가격출처", "quote_source_label"], ""),
                "dataStatus": _text(row, ["data_status", "price_data_status"], "NORMAL"),
            })
    return rows


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


@lru_cache(maxsize=12)
def _fallback_payload_cached(market: str, limit: int) -> dict[str, Any]:
    items = [_enrich_item(item) for item in _dedupe(_load_position_rows(market))]
    items = items[: max(1, min(limit, 1000))]
    return {
        "status": "OK" if items else "NO_DATA",
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
        return _fallback_payload_cached(market, limit)
