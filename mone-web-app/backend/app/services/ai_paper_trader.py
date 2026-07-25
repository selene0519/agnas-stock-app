from __future__ import annotations

import csv
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services import paper_trading

REPO_ROOT = Path(__file__).resolve().parents[4]
REPORTS = REPO_ROOT / "reports"
PAPER_DIR = Path(os.getenv("AI_PAPER_DIR", str(REPO_ROOT / "data" / "paper")))
AI_TRADES_CSV = PAPER_DIR / "ai_paper_trades.csv"
AI_NAV_CSV = PAPER_DIR / "ai_paper_nav.csv"
AI_BALANCE_JSON = PAPER_DIR / "ai_paper_balance.json"
AI_STOPS_JSON = PAPER_DIR / "ai_paper_stops.json"
AI_STATE_JSON = PAPER_DIR / "ai_paper_state.json"

AGENT_POOL: tuple[dict[str, str], ...] = (
    {"id": "ml_rank_balanced_mid", "label": "ML Rank Balanced Mid", "mode": "balanced", "horizon": "mid"},
    {"id": "ml_rank_conservative_mid", "label": "ML Rank Conservative Mid", "mode": "conservative", "horizon": "mid"},
    {"id": "ml_rank_balanced_swing", "label": "ML Rank Balanced Swing", "mode": "balanced", "horizon": "swing"},
    {"id": "ml_rank_aggressive_mid", "label": "ML Rank Aggressive Mid", "mode": "aggressive", "horizon": "mid"},
    {"id": "ml_rank_conservative_swing", "label": "ML Rank Conservative Swing", "mode": "conservative", "horizon": "swing"},
)

MAX_POSITIONS = int(os.getenv("AI_PAPER_MAX_POSITIONS", "5"))
MAX_POSITION_PCT = float(os.getenv("AI_PAPER_MAX_POSITION_PCT", "0.20"))
RISK_PER_TRADE_PCT = float(os.getenv("AI_PAPER_RISK_PER_TRADE_PCT", "0.01"))
MIN_TRADE_KR = float(os.getenv("AI_PAPER_MIN_TRADE_KR", "10000"))
MIN_TRADE_US = float(os.getenv("AI_PAPER_MIN_TRADE_US", "10"))
LENS_EXPERIMENT_SIZE_MULT = float(os.getenv("AI_PAPER_LENS_EXPERIMENT_SIZE_MULT", "0.25"))

TRADE_FIELDS = [
    "id", "createdAt", "market", "agentId", "agentLabel", "generation",
    "symbol", "name", "action", "price", "quantity", "totalValue", "memo",
]

NAV_FIELDS = [
    "date", "createdAt", "market", "agentId", "agentLabel", "generation",
    "state", "seed", "cash", "valuation", "portfolioValue", "totalPnl",
    "totalReturnPct", "survivalPct", "positionCount", "tradeCount",
    "buyCount", "sellCount", "proofStatus",
]


def _ensure_dirs() -> None:
    PAPER_DIR.mkdir(parents=True, exist_ok=True)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    _ensure_dirs()
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{k: row.get(k, "") for k in fields} for row in rows])


def _append_csv(path: Path, row: dict[str, Any], fields: list[str]) -> None:
    _ensure_dirs()
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fields})


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    _ensure_dirs()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _num(value: Any) -> float:
    try:
        text = str(value or "").strip()
        if not text:
            return 0.0
        cleaned = re.sub(r"[^0-9.+-]", "", text.replace(",", ""))
        if cleaned in ("", "+", "-", ".", "+.", "-."):
            return 0.0
        return float(cleaned)
    except Exception:
        return 0.0


def _market_list(market: str) -> list[str]:
    mk = str(market or "all").lower()
    return ["kr", "us"] if mk == "all" else [mk if mk in {"kr", "us"} else "kr"]


def _seed_for(market: str) -> float:
    return paper_trading.SEED_KR if market == "kr" else paper_trading.SEED_US


def _agent_by_id(agent_id: str) -> dict[str, str]:
    for agent in AGENT_POOL:
        if agent["id"] == agent_id:
            return dict(agent)
    return dict(AGENT_POOL[0])


def _default_state() -> dict[str, Any]:
    return {
        "activeAgents": {
            "kr": {"agentId": AGENT_POOL[0]["id"], "generation": 1, "startedAt": datetime.now().isoformat(timespec="seconds")},
            "us": {"agentId": AGENT_POOL[0]["id"], "generation": 1, "startedAt": datetime.now().isoformat(timespec="seconds")},
        },
        "lastRun": {},
    }


def _load_state() -> dict[str, Any]:
    state = _read_json(AI_STATE_JSON, {})
    if not isinstance(state, dict):
        state = {}
    default = _default_state()
    state.setdefault("activeAgents", {})
    state.setdefault("lastRun", {})
    for mk in ("kr", "us"):
        state["activeAgents"].setdefault(mk, default["activeAgents"][mk])
    return state


def _load_balance() -> dict[str, dict[str, float]]:
    raw = _read_json(AI_BALANCE_JSON, {})
    if not isinstance(raw, dict):
        raw = {}
    for mk in ("kr", "us"):
        raw.setdefault(mk, {})
    return raw


def _cash_for(market: str, agent_id: str) -> float:
    balance = _load_balance()
    if agent_id not in balance.get(market, {}):
        balance.setdefault(market, {})[agent_id] = _seed_for(market)
        _write_json(AI_BALANCE_JSON, balance)
    return float(balance[market][agent_id])


def _set_cash(market: str, agent_id: str, cash: float) -> None:
    balance = _load_balance()
    balance.setdefault(market, {})[agent_id] = round(max(cash, 0.0), 2)
    _write_json(AI_BALANCE_JSON, balance)


def _active_context(market: str) -> dict[str, Any]:
    state = _load_state()
    active = dict(state.get("activeAgents", {}).get(market) or {})
    agent = _agent_by_id(str(active.get("agentId") or AGENT_POOL[0]["id"]))
    generation = int(active.get("generation") or 1)
    return {"agent": agent, "agentId": agent["id"], "generation": generation, "state": state}


def _decision_priority(text: str) -> int:
    value = str(text or "")
    if "오늘" in value or "today" in value.lower() or "즉시" in value:
        return 0
    if "조건" in value or "conditional" in value.lower():
        return 1
    if "대기" in value or "관찰" in value or "wait" in value.lower():
        return 2
    return 3


def _is_bad_data_status(text: str) -> bool:
    status = str(text or "").upper()
    return any(token in status for token in ("STALE", "ERROR", "NO_DATA", "INVALID"))


def _is_tradeable_symbol(market: str, symbol: str) -> bool:
    """Reject market indexes and malformed identifiers before paper execution."""
    normalized = str(symbol or "").strip().upper()
    if market == "kr":
        return bool(re.fullmatch(r"\d{6}", normalized))
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", normalized))


def _collect_recommendations(market: str, agent: dict[str, str] | None = None) -> list[dict[str, Any]]:
    agents = [agent] if agent else list(AGENT_POOL)
    seen: dict[str, dict[str, Any]] = {}
    for profile in agents:
        if not profile:
            continue
        mode = profile["mode"]
        horizon = profile["horizon"]
        path = REPORTS / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
        for row in _read_csv(path):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not _is_tradeable_symbol(market, symbol):
                continue
            entry = _num(row.get("entry") or row.get("entryPrice"))
            stop = _num(row.get("stop") or row.get("stopPrice"))
            target = _num(row.get("target") or row.get("targetPrice"))
            current = _num(row.get("currentPrice") or row.get("current") or entry)
            score = _num(row.get("finalRankScore") or row.get("finalScore") or row.get("score"))
            ev = _num(row.get("expectedValue") or row.get("ev"))
            risk_score = _num(row.get("riskScore"))
            block = str(row.get("tradeBlockStatus") or "").upper()
            decision = str(row.get("decisionBucket") or row.get("newEntryDecision") or "")
            data_status = str(row.get("dataStatus") or "")

            if block in {"BLOCK", "CAUTION", "EV_NEGATIVE", "ENSEMBLE_LOW"}:
                continue
            if _is_bad_data_status(data_status):
                continue
            if score < 68 or ev < 1:
                continue
            if risk_score and risk_score < 45:
                continue
            if not (target > entry > stop > 0):
                continue
            if _decision_priority(decision) > 1:
                continue

            item = {
                "market": market,
                "agentId": profile["id"],
                "agentLabel": profile["label"],
                "symbol": symbol,
                "name": str(row.get("name") or row.get("companyName") or symbol).strip(),
                "mode": mode,
                "horizon": horizon,
                "decision": decision,
                "entry": entry,
                "stop": stop,
                "target": target,
                "current": current,
                "score": score,
                "expectedValue": ev,
                "riskScore": risk_score,
                "source": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "generatedAt": str(row.get("generatedAt") or ""),
            }
            old = seen.get(symbol)
            if old is None or (
                _decision_priority(item["decision"]),
                -item["expectedValue"],
                -item["score"],
            ) < (
                _decision_priority(old["decision"]),
                -old["expectedValue"],
                -old["score"],
            ):
                seen[symbol] = item
    if market == "kr":
        for item in _collect_regime_lens_candidates_kr(agent):
            symbol = str(item.get("symbol") or "").upper()
            old = seen.get(symbol)
            if old is None or (
                _decision_priority(item["decision"]),
                -_num(item.get("expectedValue")),
                -_num(item.get("score")),
            ) < (
                _decision_priority(old.get("decision")),
                -_num(old.get("expectedValue")),
                -_num(old.get("score")),
            ):
                seen[symbol] = item
    return sorted(
        seen.values(),
        key=lambda x: (_decision_priority(x["decision"]), -x["expectedValue"], -x["score"]),
    )


def _lens_intraday_context_kr() -> dict[str, dict[str, Any]]:
    path = REPORTS / "lens_intraday_context_kr.csv"
    rows = _read_csv(path)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        old = latest.get(symbol)
        if old is None or str(row.get("updatedAt") or row.get("priceTime") or "") >= str(old.get("updatedAt") or old.get("priceTime") or ""):
            latest[symbol] = row
    return latest


def _collect_regime_lens_candidates_kr(agent: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Feed bear-market rebound/range lens candidates into paper trading only.

    These candidates are intentionally separated from live recommendations.  A
    suppressed lens can still enter the AI paper account with a small size so
    the app collects real forward evidence instead of staying permanently in
    "no trade" mode during difficult regimes.
    """
    path = REPORTS / "regime_lens_candidates_kr.json"
    if not path.exists():
        return []
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if str(report.get("market") or "kr").lower() != "kr":
        return []

    regime = str(report.get("marketRegime") or "SIDE").upper()
    as_of = str(report.get("asOfDate") or "")
    active_agent = agent or AGENT_POOL[0]
    intraday_context = _lens_intraday_context_kr()
    items: list[dict[str, Any]] = []
    for row in report.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        setup = str(row.get("setup") or "").strip().upper()
        if not _is_tradeable_symbol("kr", symbol) or setup not in {"BOTTOM_CATCH", "V_REVERSAL", "DOUBLE_BOTTOM"}:
            continue

        entry = _num(row.get("entryRef") or row.get("entry") or row.get("close"))
        stop = _num(row.get("stop"))
        target = _num(row.get("target"))
        rr = _num(row.get("rrRatio"))
        if not (target > entry > stop > 0) or rr < 1.8:
            continue

        gate = str(row.get("calibrationGate") or "UNCALIBRATED").upper()
        actionable = bool(row.get("actionable")) or gate == "ACTIVE"
        context = intraday_context.get(symbol, {})
        flow_score = _num(context.get("flowScore"))
        bid_ratio = _num(context.get("bidRatio"))
        quote_ok = str(context.get("quoteStatus") or "").upper() in {"OK", "TRUE", "1"}
        orderbook_ok = str(context.get("orderbookStatus") or "").upper() in {"OK", "TRUE", "1"}
        if quote_ok:
            current = _num(context.get("currentPrice"))
            if current > 0:
                entry = current
        if orderbook_ok and bid_ratio > 0 and flow_score <= -2 and bid_ratio < 42:
            # If both the free KIS order book and investor flow disagree, keep
            # the candidate in the ledger/capture path but do not spend even
            # paper capital on this exact intraday setup.
            continue

        # Suppressed candidates are not trusted enough for full sizing, but they
        # are exactly the cases we need to observe forward.  Give them a modest
        # paper-only EV so the paper engine can test them without promoting them
        # to normal recommendations.
        size_mult = _num(row.get("sizeMultiplier")) if actionable else LENS_EXPERIMENT_SIZE_MULT
        size_mult = max(0.05, min(size_mult or LENS_EXPERIMENT_SIZE_MULT, 1.0))
        edge = max(1.01, min(1.80, rr * 0.42 + (0.10 if actionable else 0.0)))
        score = 72.0 if actionable else 68.5
        if flow_score >= 2:
            edge += 0.08
            score += 1.5
            size_mult = min(1.0, size_mult + 0.10)
        elif flow_score <= -2:
            edge -= 0.08
            score -= 1.0
            size_mult = max(0.05, size_mult - 0.10)
        if orderbook_ok and bid_ratio >= 55:
            edge += 0.04
            score += 0.5
        elif orderbook_ok and 0 < bid_ratio < 45:
            edge -= 0.04
            score -= 0.5
        edge = max(1.01, min(1.80, edge))
        if score < 68.0:
            continue

        decision = "today paper-only bear rebound" if regime == "BEAR" else "conditional paper-only range rebound"
        items.append({
            "market": "kr",
            "agentId": active_agent["id"],
            "agentLabel": active_agent["label"],
            "symbol": symbol,
            "name": str(row.get("name") or symbol).strip(),
            "mode": active_agent.get("mode", "balanced"),
            "horizon": "short",
            "decision": decision,
            "entry": entry,
            "stop": stop,
            "target": target,
            "current": entry,
            "score": score,
            "expectedValue": edge,
            "riskScore": 55.0 if actionable else 50.0,
            "source": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "generatedAt": as_of,
            "paperOnly": True,
            "paperSetup": setup,
            "paperRegime": regime,
            "paperSizeMultiplier": size_mult,
            "calibrationGate": gate,
            "flowScore": flow_score if context else "",
            "bidRatio": bid_ratio if context else "",
            "memo": f"KR {regime} {setup} lens paper test gate={gate} rr={rr:.2f}",
        })
    return sorted(items, key=lambda x: (-_num(x.get("expectedValue")), -_num(x.get("score"))))


def _current_price(symbol: str, market: str) -> float | None:
    return paper_trading._get_current_price(symbol, market)  # type: ignore[attr-defined]


def _trades_for(market: str, agent_id: str) -> list[dict[str, Any]]:
    rows = _read_csv(AI_TRADES_CSV)
    return [
        row for row in rows
        if str(row.get("market", "")).lower() == market and str(row.get("agentId") or "") == agent_id
    ]


def _compute_positions(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    positions: dict[str, dict[str, Any]] = {}
    for trade in trades:
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            continue
        price = _num(trade.get("price"))
        qty = _num(trade.get("quantity"))
        action = str(trade.get("action") or "").upper()
        if action not in {"BUY", "SELL"}:
            continue
        item = positions.setdefault(symbol, {
            "symbol": symbol,
            "name": str(trade.get("name") or symbol),
            "quantity": 0.0,
            "totalCost": 0.0,
        })
        if action == "BUY":
            item["quantity"] += qty
            item["totalCost"] += price * qty
        elif action == "SELL":
            prev_qty = item["quantity"]
            if prev_qty > 0:
                cost_per = item["totalCost"] / prev_qty
                item["totalCost"] -= cost_per * min(qty, prev_qty)
            item["quantity"] = max(item["quantity"] - qty, 0.0)
            item["totalCost"] = max(item["totalCost"], 0.0)
    return {k: v for k, v in positions.items() if v["quantity"] > 0.0001}


def _position_items(market: str, agent_id: str) -> list[dict[str, Any]]:
    result = []
    for symbol, pos in _compute_positions(_trades_for(market, agent_id)).items():
        qty = float(pos["quantity"])
        avg_price = float(pos["totalCost"]) / qty if qty > 0 else 0.0
        current = _current_price(symbol, market)
        valuation = (current or 0.0) * qty
        cost = float(pos["totalCost"])
        pnl = valuation - cost
        result.append({
            "market": market,
            "agentId": agent_id,
            "symbol": symbol,
            "name": pos.get("name") or symbol,
            "quantity": round(qty, 4),
            "avgPrice": round(avg_price, 2),
            "currentPrice": round(current, 2) if current else None,
            "cost": round(cost, 2),
            "valuation": round(valuation, 2),
            "pnl": round(pnl, 2),
            "pnlPct": round((pnl / cost * 100), 2) if cost > 0 else 0.0,
        })
    return sorted(result, key=lambda x: abs(x.get("pnl") or 0), reverse=True)


def _summary_for_market(market: str, agent_id: str | None = None) -> dict[str, Any]:
    ctx = _active_context(market)
    agent = _agent_by_id(agent_id or ctx["agentId"])
    generation = ctx["generation"] if agent["id"] == ctx["agentId"] else 0
    cash = _cash_for(market, agent["id"])
    positions = _position_items(market, agent["id"])
    seed = _seed_for(market)
    valuation = sum(float(p.get("valuation") or 0) for p in positions)
    invested = sum(float(p.get("cost") or 0) for p in positions)
    unrealized_pnl = sum(float(p.get("pnl") or 0) for p in positions)
    portfolio_value = cash + valuation
    trades = _trades_for(market, agent["id"])
    return {
        "agentId": agent["id"],
        "agentLabel": agent["label"],
        "generation": generation,
        "seed": round(seed, 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "valuation": round(valuation, 2),
        "portfolioValue": round(portfolio_value, 2),
        "unrealizedPnl": round(unrealized_pnl, 2),
        "totalPnl": round(portfolio_value - seed, 2),
        "totalReturnPct": round((portfolio_value / seed - 1) * 100, 2) if seed > 0 else 0.0,
        "positionCount": len(positions),
        "tradeCount": len(trades),
    }


def _survival_state(market: str, summary: dict[str, Any]) -> dict[str, Any]:
    seed = float(summary.get("seed") if summary.get("seed") is not None else _seed_for(market))
    raw_value = summary.get("portfolioValue")
    value = float(raw_value) if raw_value is not None else seed
    if value <= 0 or value <= seed * 0.01:
        state = "DEAD"
    elif value <= seed * 0.50:
        state = "CRITICAL"
    elif value <= seed * 0.80:
        state = "DANGER"
    else:
        state = "ALIVE"
    return {
        "state": state,
        "seed": round(seed, 2),
        "portfolioValue": round(value, 2),
        "survivalPct": round(value / seed * 100, 2) if seed > 0 else 0.0,
    }


def _stop_key(market: str, agent_id: str, symbol: str) -> str:
    return f"{market}:{agent_id}:{symbol.upper()}"


def _stop_map() -> dict[str, Any]:
    stops = _read_json(AI_STOPS_JSON, {})
    return stops if isinstance(stops, dict) else {}


def _set_stop(market: str, agent_id: str, symbol: str, stop: float, target: float, note: str) -> None:
    stops = _stop_map()
    stops[_stop_key(market, agent_id, symbol)] = {
        "stopPrice": round(stop, 2),
        "targetPrice": round(target, 2),
        "note": note,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json(AI_STOPS_JSON, stops)


def _append_trade(market: str, agent: dict[str, str], generation: int, symbol: str, name: str, action: str, price: float, quantity: float, memo: str) -> dict[str, Any]:
    total = round(price * quantity, 2)
    row = {
        "id": f"ai-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "market": market,
        "agentId": agent["id"],
        "agentLabel": agent["label"],
        "generation": generation,
        "symbol": symbol.upper(),
        "name": name or symbol.upper(),
        "action": action.upper(),
        "price": round(price, 2),
        "quantity": round(quantity, 4),
        "totalValue": total,
        "memo": memo,
    }
    _append_csv(AI_TRADES_CSV, row, TRADE_FIELDS)
    return row


def _quantity_for(market: str, cash: float, equity: float, entry: float, stop: float, slots: int) -> float:
    if cash <= 0 or equity <= 0 or entry <= 0 or slots <= 0:
        return 0.0
    budget = min(cash / slots, equity * MAX_POSITION_PCT)
    risk_budget = equity * RISK_PER_TRADE_PCT
    stop_distance = max(entry - stop, entry * 0.01)
    qty = min(budget / entry, risk_budget / stop_distance)
    if market == "kr":
        return float(int(qty))
    return round(qty, 4)


def _apply_position_multiplier(market: str, quantity: float, multiplier: float) -> float:
    if quantity <= 0:
        return 0.0
    adjusted = quantity * max(0.0, min(multiplier, 1.0))
    if market == "kr":
        return float(max(1, int(adjusted))) if quantity >= 1 and multiplier > 0 else 0.0
    return round(adjusted, 4)


def _sell_triggered_positions(market: str, dry_run: bool) -> list[dict[str, Any]]:
    ctx = _active_context(market)
    agent = ctx["agent"]
    actions: list[dict[str, Any]] = []
    stops = _stop_map()
    for pos in _position_items(market, agent["id"]):
        symbol = str(pos.get("symbol") or "").upper()
        current = _num(pos.get("currentPrice"))
        quantity = _num(pos.get("quantity"))
        if not symbol or current <= 0 or quantity <= 0:
            continue
        stop_info = stops.get(_stop_key(market, agent["id"], symbol), {})
        stop = _num(stop_info.get("stopPrice"))
        target = _num(stop_info.get("targetPrice"))
        reason = ""
        if stop > 0 and current <= stop:
            reason = "STOP_HIT"
        elif target > 0 and current >= target:
            reason = "TARGET_HIT"
        if not reason:
            continue
        result = {"ok": True, "dryRun": dry_run}
        if not dry_run:
            _append_trade(market, agent, ctx["generation"], symbol, str(pos.get("name") or symbol), "SELL", current, quantity, f"AI paper {reason}")
            cash = _cash_for(market, agent["id"])
            _set_cash(market, agent["id"], cash + current * quantity)
        actions.append({
            "action": "SELL",
            "reason": reason,
            "market": market,
            "agentId": agent["id"],
            "agentLabel": agent["label"],
            "symbol": symbol,
            "name": pos.get("name", symbol),
            "price": current,
            "quantity": quantity,
            "result": result,
        })
    return actions


def _buy_candidates(market: str, dry_run: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    ctx = _active_context(market)
    agent = ctx["agent"]
    summary = _summary_for_market(market, agent["id"])
    survival = _survival_state(market, summary)
    if survival["state"] == "DEAD":
        actions.append({
            "action": "SKIP",
            "market": market,
            "agentId": agent["id"],
            "agentLabel": agent["label"],
            "reason": "ACCOUNT_DEAD_PROOF_FAILED",
            "survival": survival,
            "result": {"ok": False, "dryRun": dry_run},
        })
        return actions

    positions = _position_items(market, agent["id"])
    held = {str(p.get("symbol") or "").upper() for p in positions}
    slots = max(0, MAX_POSITIONS - len(positions))
    if slots <= 0:
        return actions

    cash = float(summary.get("cash") or 0)
    equity = float(summary.get("portfolioValue") if summary.get("portfolioValue") is not None else cash)
    min_trade = MIN_TRADE_KR if market == "kr" else MIN_TRADE_US

    for rec in _collect_recommendations(market, agent):
        if slots <= 0 or cash < min_trade:
            break
        symbol = rec["symbol"]
        if symbol in held:
            continue
        qty = _quantity_for(market, cash, equity, rec["entry"], rec["stop"], slots)
        if rec.get("paperOnly"):
            qty = _apply_position_multiplier(market, qty, _num(rec.get("paperSizeMultiplier")) or LENS_EXPERIMENT_SIZE_MULT)
        total = qty * rec["entry"]
        if qty <= 0 or total < min_trade:
            continue
        result = {"ok": True, "dryRun": dry_run}
        if not dry_run:
            _append_trade(
                market,
                agent,
                int(ctx["generation"]),
                symbol,
                rec["name"],
                "BUY",
                rec["entry"],
                qty,
                str(rec.get("memo") or f"AI paper buy {agent['label']} EV={rec['expectedValue']:.2f}"),
            )
            _set_cash(market, agent["id"], cash - total)
            _set_stop(market, agent["id"], symbol, rec["stop"], rec["target"], f"AI paper {agent['label']} {rec['source']}")
        actions.append({
            "action": "BUY",
            "market": market,
            "agentId": agent["id"],
            "agentLabel": agent["label"],
            "symbol": symbol,
            "name": rec["name"],
            "price": rec["entry"],
            "quantity": qty,
            "totalValue": round(total, 2),
            "stopPrice": rec["stop"],
            "targetPrice": rec["target"],
            "expectedValue": rec["expectedValue"],
            "score": rec["score"],
            "decision": rec["decision"],
            "paperOnly": bool(rec.get("paperOnly")),
            "paperSetup": rec.get("paperSetup", ""),
            "paperRegime": rec.get("paperRegime", ""),
            "paperSizeMultiplier": rec.get("paperSizeMultiplier", ""),
            "calibrationGate": rec.get("calibrationGate", ""),
            "result": result,
        })
        if result.get("ok"):
            cash -= total
            held.add(symbol)
            slots -= 1
    return actions


def _append_nav_snapshot(market: str, cycle_actions: list[dict[str, Any]]) -> dict[str, Any]:
    ctx = _active_context(market)
    agent = ctx["agent"]
    summary = _summary_for_market(market, agent["id"])
    survival = _survival_state(market, summary)
    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "market": market,
        "agentId": agent["id"],
        "agentLabel": agent["label"],
        "generation": ctx["generation"],
        "state": survival["state"],
        "seed": summary.get("seed", survival["seed"]),
        "cash": summary.get("cash", 0),
        "valuation": summary.get("valuation", 0),
        "portfolioValue": summary.get("portfolioValue", survival["portfolioValue"]),
        "totalPnl": summary.get("totalPnl", 0),
        "totalReturnPct": summary.get("totalReturnPct", 0),
        "survivalPct": survival["survivalPct"],
        "positionCount": summary.get("positionCount", 0),
        "tradeCount": summary.get("tradeCount", 0),
        "buyCount": sum(1 for a in cycle_actions if a.get("action") == "BUY" and a.get("result", {}).get("ok")),
        "sellCount": sum(1 for a in cycle_actions if a.get("action") == "SELL" and a.get("result", {}).get("ok")),
        "proofStatus": "FAILED" if survival["state"] == "DEAD" else "RUNNING",
    }
    _append_csv(AI_NAV_CSV, row, NAV_FIELDS)
    return row


def _nav_rows_for(market: str, agent_id: str) -> list[dict[str, Any]]:
    rows = [
        row for row in _read_csv(AI_NAV_CSV)
        if str(row.get("market", "")).lower() == market and str(row.get("agentId") or "") == agent_id
    ]
    return sorted(rows, key=lambda row: str(row.get("createdAt") or row.get("date") or ""))


def _live_nav_metrics(market: str, agent_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    rows = _nav_rows_for(market, agent_id)
    values = []
    for row in rows:
        raw_value = row.get("portfolioValue")
        if raw_value not in (None, ""):
            values.append(max(_num(raw_value), 0.0))
    current_value = _num(summary.get("portfolioValue"))
    seed = _num(summary.get("seed")) or _seed_for(market)
    cash = _num(summary.get("cash"))
    if summary.get("portfolioValue") is not None and (not values or abs(values[-1] - current_value) > 0.01):
        values.append(max(current_value, 0.0))

    returns: list[float] = []
    for prev, cur in zip(values, values[1:]):
        if prev > 0:
            returns.append((cur / prev - 1.0) * 100.0)

    peak = values[0] if values else seed
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, (value / peak - 1.0) * 100.0)

    win_rate = (sum(1 for ret in returns if ret > 0) / len(returns) * 100.0) if returns else None
    avg_return = (sum(returns) / len(returns)) if returns else None
    if returns and len(returns) >= 2:
        mean = sum(returns) / len(returns)
        variance = sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        sharpe = (mean / std * math.sqrt(252)) if std > 0 else None
    else:
        sharpe = None

    total_return = (current_value / seed - 1.0) * 100.0 if seed > 0 and current_value > 0 else (_num(summary.get("totalReturnPct")) if summary.get("totalReturnPct") is not None else 0.0)
    cash_pct = (cash / current_value * 100.0) if current_value > 0 else 0.0
    proof_status = "FAILED" if current_value <= seed * 0.01 else ("WARMING_UP" if len(returns) < 5 else "RUNNING")

    return {
        "status": "OK",
        "proofStatus": proof_status,
        "sampleCount": len(returns),
        "navPointCount": len(values),
        "totalReturnPct": round(total_return, 2),
        "mddPct": round(max_drawdown, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "winRate": round(win_rate, 1) if win_rate is not None else None,
        "avgPeriodReturnPct": round(avg_return, 2) if avg_return is not None else None,
        "cashPct": round(cash_pct, 1),
        "peakValue": round(peak, 2),
        "currentValue": round(current_value, 2),
        "lastNavDate": str(rows[-1].get("date") or rows[-1].get("createdAt") or "") if rows else "",
        "recentReturnsPct": [round(ret, 2) for ret in returns[-8:]],
        "equityCurve": [
            {"index": idx, "value": round(value, 2), "returnPct": round((value / seed - 1.0) * 100.0, 2) if seed > 0 else 0.0}
            for idx, value in enumerate(values[-16:])
        ],
    }


def _walkforward_proof_board(market: str, current_agent_id: str) -> dict[str, Any]:
    rows = _read_csv(REPORTS / f"walkforward_results_{market}.csv")
    if not rows:
        return {
            "status": "NO_DATA",
            "method": "walk_forward_oos",
            "message": "walkforward results are not available",
            "rows": [],
        }

    def _metrics(profile: dict[str, str], strategy: str) -> dict[str, Any] | None:
        matched = [
            row for row in rows
            if str(row.get("mode")) == profile["mode"]
            and str(row.get("horizon")) == profile["horizon"]
            and str(row.get("strategy") or "corrected") == strategy
        ]
        if not matched:
            return None
        matched.sort(key=lambda row: _num(row.get("windowIndex")))
        recent = matched[-6:]
        exec_count = sum(_num(row.get("executionCount")) for row in recent)
        win_count = sum(_num(row.get("winCount")) for row in recent)
        avg_pnls = [_num(row.get("avgNetPnlPct")) for row in recent if _num(row.get("executionCount")) > 0]
        weighted_pnl = (
            sum(_num(row.get("avgNetPnlPct")) * _num(row.get("executionCount")) for row in recent) / exec_count
            if exec_count > 0 else 0.0
        )
        win_rate = (win_count / exec_count * 100.0) if exec_count > 0 else 0.0
        positive_rate = (sum(1 for v in avg_pnls if v > 0) / len(avg_pnls) * 100.0) if avg_pnls else 0.0
        mdd = min((_num(row.get("mddPct")) for row in recent), default=0.0)
        proof_score = weighted_pnl * 12.0 + win_rate * 0.35 + positive_rate * 0.25 + max(mdd, -100.0) * 0.12
        return {
            "agentId": profile["id"],
            "agentLabel": profile["label"],
            "mode": profile["mode"],
            "horizon": profile["horizon"],
            "strategy": strategy,
            "sampleCount": int(exec_count),
            "winRate": round(win_rate, 1),
            "avgNetPnlPct": round(weighted_pnl, 2),
            "positiveWindowRate": round(positive_rate, 1),
            "mddPct": round(mdd, 2),
            "proofScore": round(proof_score, 2),
            "lastWindow": str(recent[-1].get("window") or "") if recent else "",
        }

    profile_rows = []
    baseline_rows = []
    for profile in AGENT_POOL:
        corrected = _metrics(profile, "corrected")
        baseline = _metrics(profile, "baseline")
        if corrected:
            profile_rows.append(corrected)
        if baseline:
            baseline_rows.append({**baseline, "agentId": f"baseline_{profile['id']}", "agentLabel": f"Raw baseline {profile['mode']}/{profile['horizon']}"})

    profile_rows.sort(key=lambda row: row.get("proofScore", -9999), reverse=True)
    baseline_rows.sort(key=lambda row: row.get("proofScore", -9999), reverse=True)
    current = next((row for row in profile_rows if row.get("agentId") == current_agent_id), None)
    current_rank = next((idx + 1 for idx, row in enumerate(profile_rows) if row.get("agentId") == current_agent_id), None)
    best_profile = profile_rows[0] if profile_rows else None
    best_baseline = baseline_rows[0] if baseline_rows else None
    beats_best_baseline = bool(current and best_baseline and current.get("proofScore", -9999) > best_baseline.get("proofScore", 9999))
    verdict = "UNPROVEN"
    if current and current.get("sampleCount", 0) >= 30:
        if current_rank == 1 and beats_best_baseline and current.get("avgNetPnlPct", 0) > 0:
            verdict = "PROVING_EDGE"
        elif current.get("avgNetPnlPct", 0) > 0 and beats_best_baseline:
            verdict = "COMPETITIVE"
        else:
            verdict = "NOT_PROVEN"

    return {
        "status": "OK",
        "method": "recent_6_window_walk_forward_oos",
        "verdict": verdict,
        "currentRank": current_rank,
        "profileCount": len(profile_rows),
        "current": current or {},
        "leader": best_profile or {},
        "bestBaseline": best_baseline or {},
        "beatsBestBaseline": beats_best_baseline,
        "rows": profile_rows[:5],
        "baselines": baseline_rows[:3],
    }


def status(market: str = "all") -> dict[str, Any]:
    state = _load_state()
    markets = {}
    for mk in _market_list(market):
        ctx = _active_context(mk)
        agent = ctx["agent"]
        summary = _summary_for_market(mk, agent["id"])
        survival = _survival_state(mk, summary)
        markets[mk] = {
            "activeAgent": agent,
            "generation": ctx["generation"],
            "summary": summary,
            "liveMetrics": _live_nav_metrics(mk, agent["id"], summary),
            "survival": survival,
            "positions": _position_items(mk, agent["id"]),
            "candidateCount": len(_collect_recommendations(mk, agent)),
            "proofFailed": survival["state"] == "DEAD",
            "proofBoard": _walkforward_proof_board(mk, agent["id"]),
        }
    nav_rows = _read_csv(AI_NAV_CSV)
    return {
        "status": "OK",
        "market": market,
        "agentPool": list(AGENT_POOL),
        "markets": markets,
        "lastRun": state.get("lastRun", {}),
        "navRows": len(nav_rows),
        "latestNav": nav_rows[-1] if nav_rows else {},
    }


def run_cycle(market: str = "all", dry_run: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "OK",
        "dryRun": dry_run,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "market": market,
        "markets": {},
    }
    for mk in _market_list(market):
        actions: list[dict[str, Any]] = []
        actions.extend(_sell_triggered_positions(mk, dry_run=dry_run))
        actions.extend(_buy_candidates(mk, dry_run=dry_run))
        nav = {} if dry_run else _append_nav_snapshot(mk, actions)
        ctx = _active_context(mk)
        summary = _summary_for_market(mk, ctx["agentId"])
        result["markets"][mk] = {
            "activeAgent": ctx["agent"],
            "generation": ctx["generation"],
            "actions": actions,
            "summary": summary,
            "liveMetrics": _live_nav_metrics(mk, ctx["agentId"], summary),
            "survival": _survival_state(mk, summary),
            "proofBoard": _walkforward_proof_board(mk, ctx["agentId"]),
            "nav": nav,
        }
    if not dry_run:
        state = _load_state()
        state["lastRun"] = result
        _write_json(AI_STATE_JSON, state)
    return result
