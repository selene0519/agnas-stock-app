from __future__ import annotations

import json
import math
from typing import Any

from app.services import data_loader as data


REPO_ROOT = data.REPO_ROOT
KELLY_JSON = REPO_ROOT / "reports" / "kelly_position_sizes.json"

POLICY = {
    "maxPortfolioLossPct": 6.0,
    "maxPositionWeightPct": 20.0,
    "maxPositionLossPct": 2.0,
    "maxSectorWeightPct": 35.0,
    "defaultStopLossPct": 8.0,
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value or "").replace(",", "").replace("$", "").strip()
        x = float(text)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _market_value(row: dict[str, Any]) -> float:
    value = _num(row.get("marketValue") or row.get("evalAmount") or row.get("eval_amount"))
    if value > 0:
        return value
    qty = _num(row.get("quantity") or row.get("shares"))
    price = _num(row.get("currentPrice") or row.get("current_price") or row.get("avgPrice") or row.get("avg_price"))
    return max(0.0, qty * price)


def _current_price(row: dict[str, Any]) -> float:
    return _num(row.get("currentPrice") or row.get("current_price") or row.get("avgPrice") or row.get("avg_price"))


def _stop_price(row: dict[str, Any], current: float) -> float:
    stop = _num(row.get("stopPrice") or row.get("stop_price") or row.get("stop"))
    if stop > 0:
        return stop
    return current * (1 - POLICY["defaultStopLossPct"] / 100) if current > 0 else 0.0


def _load_kelly() -> dict[str, Any]:
    if not KELLY_JSON.exists():
        return {}
    try:
        data_obj = json.loads(KELLY_JSON.read_text(encoding="utf-8"))
        return data_obj if isinstance(data_obj, dict) else {}
    except Exception:
        return {}


def _holding_rows(market: str, user_id: str = "") -> list[dict[str, Any]]:
    if user_id:
        try:
            from app import db

            return db.get_holdings(user_id, market)
        except Exception:
            return []
    try:
        from app.services.exit_signal import _holdings_items

        markets = ["kr", "us"] if str(market).lower() == "all" else [market]
        rows: list[dict[str, Any]] = []
        for mk in markets:
            for row in _holdings_items(mk):
                if isinstance(row, dict):
                    rows.append({**row, "market": row.get("market") or mk})
        return rows
    except Exception:
        return []


def risk_budget(market: str = "all", user_id: str = "") -> dict[str, Any]:
    rows = _holding_rows(market, user_id=user_id)
    total_value = sum(_market_value(row) for row in rows)
    kelly = _load_kelly()
    items: list[dict[str, Any]] = []
    sector_weights: dict[str, float] = {}
    total_loss_budget = 0.0
    missing_stop_count = 0

    for row in rows:
        mk = "us" if str(row.get("market") or market).lower() == "us" else "kr"
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        qty = _num(row.get("quantity") or row.get("shares"))
        current = _current_price(row)
        value = _market_value(row)
        weight = (value / total_value * 100) if total_value > 0 else 0.0
        stop = _stop_price(row, current)
        explicit_stop = _num(row.get("stopPrice") or row.get("stop_price") or row.get("stop")) > 0
        if not explicit_stop:
            missing_stop_count += 1
        if current > 0 and qty > 0 and stop > 0:
            loss_amount = max(0.0, (current - stop) * qty)
        else:
            loss_amount = value * POLICY["defaultStopLossPct"] / 100
        loss_pct = (loss_amount / total_value * 100) if total_value > 0 else 0.0
        total_loss_budget += loss_pct
        sector = str(row.get("sector") or row.get("industry") or "UNKNOWN").strip() or "UNKNOWN"
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
        mode = str(row.get("mode") or "balanced").lower()
        horizon = str(row.get("horizon") or "swing").lower()
        kelly_entry = kelly.get(f"{mode}_{horizon}") or kelly.get("balanced_swing") or {}
        kelly_pct = _num(kelly_entry.get("recommendedPct"), 0.0)
        target_weight = min(
            POLICY["maxPositionWeightPct"],
            kelly_pct if kelly_pct > 0 else POLICY["maxPositionWeightPct"],
        )
        reduce_to_pct = min(weight, target_weight)
        action = "HOLD"
        reasons: list[str] = []
        if weight > POLICY["maxPositionWeightPct"]:
            action = "REDUCE"
            reasons.append(f"position weight {weight:.1f}% > {POLICY['maxPositionWeightPct']:.0f}%")
        if loss_pct > POLICY["maxPositionLossPct"]:
            action = "REDUCE"
            reasons.append(f"loss budget {loss_pct:.1f}% > {POLICY['maxPositionLossPct']:.0f}%")
        if not explicit_stop:
            reasons.append("default stop used")
        items.append(
            {
                "market": mk,
                "symbol": symbol,
                "name": row.get("name") or symbol,
                "sector": sector,
                "value": round(value, 2),
                "weightPct": round(weight, 3),
                "currentPrice": current,
                "stopPrice": round(stop, 4) if stop else None,
                "lossBudgetPct": round(loss_pct, 3),
                "kellyTargetPct": round(target_weight, 3),
                "recommendedWeightPct": round(reduce_to_pct, 3),
                "action": action,
                "reasons": reasons or ["within budget"],
            }
        )

    sector_items = [
        {
            "sector": sector,
            "weightPct": round(weight, 3),
            "status": "OVER" if weight > POLICY["maxSectorWeightPct"] else "OK",
        }
        for sector, weight in sorted(sector_weights.items(), key=lambda kv: kv[1], reverse=True)
    ]
    status = "OK"
    warnings: list[str] = []
    if total_loss_budget > POLICY["maxPortfolioLossPct"]:
        status = "OVER_BUDGET"
        warnings.append(f"portfolio loss budget {total_loss_budget:.1f}% > {POLICY['maxPortfolioLossPct']:.0f}%")
    if any(item["status"] == "OVER" for item in sector_items):
        status = "OVER_BUDGET"
        warnings.append("sector concentration over budget")
    if missing_stop_count:
        warnings.append(f"{missing_stop_count} holdings use default stop")

    items.sort(key=lambda item: (item["action"] != "REDUCE", -item["lossBudgetPct"], -item["weightPct"]))
    return {
        "status": status,
        "market": market,
        "policy": POLICY,
        "totalValue": round(total_value, 2),
        "totalLossBudgetPct": round(total_loss_budget, 3),
        "missingStopCount": missing_stop_count,
        "warnings": warnings,
        "sectors": sector_items[:12],
        "items": items,
    }
