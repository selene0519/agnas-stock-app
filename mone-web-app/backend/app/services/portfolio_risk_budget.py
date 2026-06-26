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
    # 상관계수 |r| >= 이 값이면 "같은 방향으로 움직이는 묶음"으로 간주.
    # 섹터 라벨이 달라도 실제로 같이 움직이는 종목들(예: 금리민감 성장주)을 잡아내기 위함.
    "highCorrelationThreshold": 0.7,
    "maxCorrelatedClusterWeightPct": 40.0,
    "correlationLookbackDays": 60,
}


def _daily_returns(market: str, symbol: str, lookback_days: int) -> dict[str, float]:
    """날짜→일간수익률. OHLCV는 이미 로컬에 수집되어 있어 추가 데이터 없이 계산 가능."""
    from app.engine.quant_scanner import load_ohlcv

    rows = load_ohlcv(REPO_ROOT, market, symbol)
    if len(rows) < 2:
        return {}
    rows = rows[-(lookback_days + 1):]
    out: dict[str, float] = {}
    prev_close: float | None = None
    for row in rows:
        date_key = str(row.get("date") or row.get("Date") or "").strip()
        close = _num(row.get("close") or row.get("Close"))
        if not date_key or close <= 0:
            continue
        if prev_close and prev_close > 0:
            out[date_key] = (close - prev_close) / prev_close
        prev_close = close
    return out


def _pairwise_correlation(series_a: dict[str, float], series_b: dict[str, float]) -> float | None:
    common_dates = sorted(set(series_a) & set(series_b))
    if len(common_dates) < 20:
        return None
    a = [series_a[d] for d in common_dates]
    b = [series_b[d] for d in common_dates]
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a <= 0 or var_b <= 0:
        return None
    return cov / math.sqrt(var_a * var_b)


def _correlation_risk(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """보유 종목 간 상관계수를 계산해, 섹터 라벨로는 안 보이는 동행성 집중 위험을 잡아낸다.
    예: '반도체'와 'IT서비스'로 섹터는 다르지만 둘 다 금리민감 성장주라 같이 빠지는 경우."""
    lookback = int(POLICY["correlationLookbackDays"])
    returns_by_key: dict[str, dict[str, float]] = {}
    for pos in positions:
        key = f"{pos['market']}:{pos['symbol']}"
        series = _daily_returns(pos["market"], pos["symbol"], lookback)
        if series:
            returns_by_key[key] = series

    keys = [f"{p['market']}:{p['symbol']}" for p in positions if f"{p['market']}:{p['symbol']}" in returns_by_key]
    weight_by_key = {f"{p['market']}:{p['symbol']}": p["weightPct"] for p in positions}

    pairs: list[dict[str, Any]] = []
    # union-find로 고상관 종목을 클러스터로 묶어 "묶음 비중"을 계산
    parent = {k: k for k in keys}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    threshold = float(POLICY["highCorrelationThreshold"])
    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1:]:
            corr = _pairwise_correlation(returns_by_key[key_a], returns_by_key[key_b])
            if corr is None:
                continue
            if abs(corr) >= threshold:
                pairs.append({
                    "symbolA": key_a.split(":", 1)[1],
                    "symbolB": key_b.split(":", 1)[1],
                    "correlation": round(corr, 3),
                })
                union(key_a, key_b)

    clusters: dict[str, float] = {}
    for key in keys:
        root = find(key)
        clusters[root] = clusters.get(root, 0.0) + weight_by_key.get(key, 0.0)
    cluster_warnings = [
        {"members": [k.split(":", 1)[1] for k in keys if find(k) == root], "combinedWeightPct": round(weight, 3)}
        for root, weight in clusters.items()
        if weight > POLICY["maxCorrelatedClusterWeightPct"] and sum(1 for k in keys if find(k) == root) > 1
    ]

    return {
        "lookbackDays": lookback,
        "highCorrelationPairs": sorted(pairs, key=lambda p: -abs(p["correlation"]))[:20],
        "concentratedClusters": cluster_warnings,
        "status": "OK" if keys else "NO_DATA",
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
    try:
        correlation = _correlation_risk(items) if len(items) > 1 else {"status": "NOT_ENOUGH_POSITIONS"}
    except Exception:
        correlation = {"status": "ERROR"}

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
    if correlation.get("concentratedClusters"):
        status = "OVER_BUDGET"
        cluster = correlation["concentratedClusters"][0]
        warnings.append(
            f"{'·'.join(cluster['members'])} 상관계수 높음 — 섹터는 달라도 같이 움직일 가능성 높음 "
            f"(합산 비중 {cluster['combinedWeightPct']:.1f}% > {POLICY['maxCorrelatedClusterWeightPct']:.0f}%)"
        )

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
        "correlation": correlation,
        "items": items,
    }
