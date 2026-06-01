from __future__ import annotations

import csv
import re
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
    if not path.is_file() or path.stat().st_size <= 0:
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
        lk = key.lower()
        if lk in lower and lower[lk] is not None and str(lower[lk]).strip():
            return str(lower[lk]).strip()
    return default


def _num(value: Any) -> float:
    try:
        raw = str(value if value is not None else "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-", "데이터 없음", "확인 필요"}:
            return 0.0
        raw = raw.replace(",", "").replace("USD", "").replace("KRW", "").replace("$", "").replace("원", "").replace("%", "")
        raw = re.sub(r"[^0-9.\-+]", "", raw)
        return float(raw) if raw not in {"", "-", "+", "."} else 0.0
    except Exception:
        return 0.0


def _symbol(value: Any, market: str) -> str:
    raw = str(value or "").strip().upper()
    if raw.endswith(".0"):
        raw = raw[:-2]
    raw = re.sub(r"\.(KS|KQ|KR)$", "", raw)
    raw = re.sub(r"[^0-9A-Z.\-]", "", raw)
    if market == "kr":
        digits = re.sub(r"\D", "", raw)
        return digits.zfill(6)[-6:] if digits else ""
    return raw


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


def _quote_files(market: str) -> list[Path]:
    root = _repo_root()
    candidates = [
        root / "data" / "stockapp" / f"kis_current_price_{market}.csv",
        root / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv",
        root / "data" / "stockapp" / f"intraday_realtime_snapshot_{market}.csv",
        root / "reports" / f"kis_current_price_{market}.csv",
        root / "reports" / f"intraday_quote_snapshot_{market}.csv",
        root / "reports" / f"intraday_realtime_snapshot_{market}.csv",
    ]
    return [path for path in candidates if path.is_file() and path.stat().st_size > 0]


@lru_cache(maxsize=8)
def _quote_index(market: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in _quote_files(market):
        for row in _read_csv(path):
            symbol = _symbol(_text(row, ["symbol", "ticker", "code", "종목코드"], ""), market)
            if symbol and symbol not in out:
                out[symbol] = {**row, "_source_file": path.name}
    return out


@lru_cache(maxsize=4)
def _position_index(market: str) -> dict[str, dict[str, Any]]:
    root = _repo_root()
    out: dict[str, dict[str, Any]] = {}
    for path in [root / "reports" / f"v93_position_cards_{market}.csv"]:
        for row in _read_csv(path):
            symbol = _symbol(_text(row, ["symbol", "ticker", "code", "종목코드"], ""), market)
            if symbol:
                out[symbol] = {**row, "_source_file": path.name}
    return out


def _holding_files(market: str) -> list[Path]:
    root = _repo_root()
    return [
        root / f"holdings_{market}.csv",
        root / "data" / f"holdings_{market}.csv",
    ]


def _load_holding_rows(market: str) -> list[dict[str, Any]]:
    markets = ["kr", "us"] if market == "all" else [market]
    names: dict[str, dict[str, Any]] = {}
    for item_market in markets:
        for path in _holding_files(item_market):
            for row in _read_csv(path):
                symbol = _symbol(_text(row, ["symbol", "ticker", "code", "종목코드"], ""), item_market)
                if not symbol:
                    continue
                key = f"{item_market}-{symbol}"
                if key in names:
                    continue
                name = _text(row, ["name", "stock_name", "companyName", "종목명"], symbol)
                names[key] = {
                    "id": key,
                    "symbol": symbol,
                    "name": name,
                    "market": item_market,
                    "quantity": _num(_text(row, ["quantity", "qty", "보유수량"], "0")),
                    "avgPrice": _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "평균단가", "매수가"], "0")),
                    "currentPrice": _num(_text(row, ["currentPrice", "current_price", "last_price", "현재가"], "0")),
                    "prevClose": _num(_text(row, ["prevClose", "prev_close", "전일종가"], "0")),
                    "source": path.name,
                    "sourcePath": str(path),
                    "holdingAuthority": path.name,
                }
    return list(names.values())



def _enrich_item(item: dict[str, Any]) -> dict[str, Any]:
    market = str(item.get("market") or "kr").lower()
    symbol = str(item.get("symbol") or "").upper()
    quote = _quote_index(market).get(symbol, {})
    position = _position_index(market).get(symbol, {})
    computed: list[str] = []

    quantity = _num(item.get("quantity"))
    avg = _num(item.get("avgPrice"))

    quote_current = _num(_text(quote, ["currentPrice", "current_price", "last_price", "price", "현재가"], "0"))
    current = quote_current or _num(item.get("currentPrice")) or _num(_text(position, ["currentPrice", "current_price", "last_price", "현재가"], "0"))

    prev_close = (
        _num(_text(quote, ["prevClose", "previousClose", "prev_close", "basePrice", "stck_prdy_clpr", "전일종가", "기준가"], "0"))
        or _num(item.get("prevClose"))
        or _num(_text(position, ["prevClose", "prev_close", "전일종가"], "0"))
    )
    raw_change = _num(_text(quote, ["changePct", "changeRate", "prdy_ctrt", "등락률"], "0"))

    valuation = quantity * current if quantity > 0 and current > 0 else 0.0
    cost = quantity * avg if quantity > 0 and avg > 0 else 0.0
    pnl = valuation - cost if valuation > 0 and cost > 0 else 0.0
    pnl_pct = pnl / cost * 100 if cost > 0 else 0.0
    if valuation > 0:
        computed.append("valuation_from_holdings_current")
    if pnl_pct:
        computed.append("pnl_from_holdings_avg_current")

    stop = _num(_text(position, ["stopPrice", "stop", "stop_loss", "손절가"], "0"))
    target = _num(_text(position, ["targetPrice", "target", "target_price", "목표가"], "0"))
    base = avg if avg > 0 else current
    if stop <= 0 and base > 0:
        stop = base * 0.92
        computed.append("stop_from_risk_rule")
    if target <= 0 and base > 0:
        target = base * 1.12
        computed.append("target_from_risk_rule")

    change_pct = raw_change if raw_change else ((current - prev_close) / prev_close * 100 if current > 0 and prev_close > 0 else None)
    stop_gap = (current - stop) / current * 100 if current > 0 and stop > 0 else None
    target_gap = (target - current) / current * 100 if current > 0 and target > 0 else None

    risk_status = "NORMAL"
    if stop_gap is not None and stop_gap <= 3:
        risk_status = "WATCH"
    if stop_gap is not None and stop_gap <= 0:
        risk_status = "HIGH"

    missing = []
    if current <= 0:
        missing.append("currentPrice")
    if current > 0 and prev_close <= 0 and change_pct is None:
        missing.append("prevClose")

    return {
        **item,
        "quantity": quantity,
        "avgPrice": avg,
        "currentPrice": current,
        "prevClose": prev_close if prev_close > 0 else None,
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
        "prevCloseText": _fmt_price(prev_close, market) if prev_close > 0 else "",
        "avgPriceText": _fmt_price(avg, market),
        "valuationText": _fmt_money(valuation, market),
        "pnlText": _fmt_money(pnl, market),
        "pnlPctText": _fmt_pct(pnl_pct),
        "stopText": _fmt_price(stop, market),
        "targetText": _fmt_price(target, market),
        "changePctText": _fmt_pct(change_pct) if change_pct is not None else "",
        "quoteSource": _text(quote, ["priceSource", "source", "_source_file"], "") if quote_current > 0 else "",
        "priceSource": _text(quote, ["priceSource", "source", "_source_file"], "") if quote_current > 0 else "",
        "quoteTimestamp": _text(quote, ["timestamp", "updatedAt", "priceTime", "quoteTimestamp"], ""),
        "dataStatus": "NORMAL" if current > 0 else "PRICE_PENDING",
        "computedFields": computed,
        "missingFields": missing,
        "enrichSource": _text(position, ["_source_file"], ""),
    }

def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_value = sum(_num(item.get("valuation")) for item in items)
    total_pnl = sum(_num(item.get("pnl")) for item in items)
    total_cost = sum(_num(item.get("cost")) for item in items)
    risk_count = sum(1 for item in items if str(item.get("riskStatus") or "").upper() in {"WATCH", "HIGH"})
    missing_count = sum(1 for item in items if item.get("missingFields"))
    pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0.0
    return {
        "holdingCount": len(items),
        "riskCount": risk_count,
        "missingCount": missing_count,
        "totalValue": total_value,
        "totalPnl": total_pnl,
        "totalPnlPct": pnl_pct,
        "totalValueText": _fmt_money(total_value, "kr"),
        "totalPnlText": _fmt_money(total_pnl, "kr"),
        "totalPnlPctText": _fmt_pct(pnl_pct),
    }


@lru_cache(maxsize=12)
def _fallback_payload_cached(market: str, limit: int) -> dict[str, Any]:
    market = market if market in {"kr", "us", "all"} else "all"
    items = [_enrich_item(item) for item in _load_holding_rows(market)]
    items = items[: max(1, min(limit, 1000))]
    return {
        "status": "OK" if items else "NO_DATA",
        "routeVersion": "v80.3-holdings-authority",
        "market": market,
        "count": len(items),
        "uniqueCount": len(items),
        "items": items,
        "summary": _summary(items),
        "compatFallback": True,
        "holdingAuthority": "holdings_kr/us.csv",
        "compatReason": "보유종목 원장은 holdings_kr/us.csv만 사용하고 v93_position_cards는 보강값으로만 사용합니다.",
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
        return _fallback_payload_cached(str(market or "all").lower(), limit)
