from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services import paper_trading

REPO_ROOT = Path(__file__).resolve().parents[4]
REPORTS = REPO_ROOT / "reports"
PAPER_DIR = REPO_ROOT / "data" / "paper"
AI_NAV_CSV = PAPER_DIR / "ai_paper_nav.csv"
AI_STATE_JSON = PAPER_DIR / "ai_paper_state.json"

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

MAX_POSITIONS = int(os.getenv("AI_PAPER_MAX_POSITIONS", "5"))
MAX_POSITION_PCT = float(os.getenv("AI_PAPER_MAX_POSITION_PCT", "0.20"))
RISK_PER_TRADE_PCT = float(os.getenv("AI_PAPER_RISK_PER_TRADE_PCT", "0.01"))
MIN_TRADE_KR = float(os.getenv("AI_PAPER_MIN_TRADE_KR", "10000"))
MIN_TRADE_US = float(os.getenv("AI_PAPER_MIN_TRADE_US", "10"))


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


def _decision_priority(text: str) -> int:
    value = str(text or "")
    if "오늘" in value or "today" in value.lower():
        return 0
    if "조건" in value or "conditional" in value.lower():
        return 1
    if "대기" in value or "관찰" in value or "wait" in value.lower():
        return 2
    return 3


def _is_bad_data_status(text: str) -> bool:
    status = str(text or "").upper()
    return any(token in status for token in ("STALE", "ERROR", "NO_DATA", "INVALID"))


def _collect_recommendations(market: str) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        for horizon in HORIZONS:
            path = REPORTS / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
            for row in _read_csv(path):
                symbol = str(row.get("symbol") or "").strip().upper()
                if not symbol:
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
    return sorted(
        seen.values(),
        key=lambda x: (_decision_priority(x["decision"]), -x["expectedValue"], -x["score"]),
    )


def _summary_for_market(market: str) -> dict[str, Any]:
    summary = paper_trading.get_summary(market)
    return dict(summary.get("markets", {}).get(market, {}))


def _position_items(market: str) -> list[dict[str, Any]]:
    return list(paper_trading.get_positions(market).get("items", []) or [])


def _stop_map(market: str) -> dict[str, Any]:
    return dict(paper_trading.get_stops(market).get("stops", {}) or {})


def _seed_for(market: str) -> float:
    return paper_trading.SEED_KR if market == "kr" else paper_trading.SEED_US


def _survival_state(market: str, summary: dict[str, Any]) -> dict[str, Any]:
    seed = float(summary.get("seed") or _seed_for(market))
    value = float(summary.get("portfolioValue") or seed)
    if value <= 0:
        state = "DEAD"
    elif value <= seed * 0.01:
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


def _quantity_for(market: str, cash: float, equity: float, entry: float, stop: float, slots: int) -> float:
    if cash <= 0 or equity <= 0 or entry <= 0 or slots <= 0:
        return 0.0
    budget = min(cash / slots, equity * MAX_POSITION_PCT)
    risk_budget = equity * RISK_PER_TRADE_PCT
    stop_distance = max(entry - stop, entry * 0.01)
    qty_by_risk = risk_budget / stop_distance
    qty_by_budget = budget / entry
    qty = min(qty_by_budget, qty_by_risk)
    if market == "kr":
        return float(int(qty))
    return round(qty, 4)


def _sell_triggered_positions(market: str, dry_run: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    stops = _stop_map(market)
    for pos in _position_items(market):
        symbol = str(pos.get("symbol") or "").upper()
        current = _num(pos.get("currentPrice"))
        quantity = _num(pos.get("quantity"))
        if not symbol or current <= 0 or quantity <= 0:
            continue
        stop_info = stops.get(f"{market}:{symbol}", {})
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
            result = paper_trading.sell(symbol, market, quantity, price=current, memo=f"AI paper {reason}")
        actions.append({
            "action": "SELL",
            "reason": reason,
            "market": market,
            "symbol": symbol,
            "name": pos.get("name", symbol),
            "price": current,
            "quantity": quantity,
            "result": result,
        })
    return actions


def _buy_candidates(market: str, dry_run: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    summary = _summary_for_market(market)
    survival = _survival_state(market, summary)
    if survival["state"] == "DEAD":
        return [{
            "action": "SKIP",
            "market": market,
            "reason": "ACCOUNT_DEAD",
            "survival": survival,
        }]

    positions = _position_items(market)
    held = {str(p.get("symbol") or "").upper() for p in positions}
    slots = max(0, MAX_POSITIONS - len(positions))
    if slots <= 0:
        return []

    cash = float(summary.get("cash") or 0)
    equity = float(summary.get("portfolioValue") or cash or _seed_for(market))
    min_trade = MIN_TRADE_KR if market == "kr" else MIN_TRADE_US

    for rec in _collect_recommendations(market):
        if slots <= 0 or cash < min_trade:
            break
        symbol = rec["symbol"]
        if symbol in held:
            continue
        qty = _quantity_for(market, cash, equity, rec["entry"], rec["stop"], slots)
        total = qty * rec["entry"]
        if qty <= 0 or total < min_trade:
            continue
        result = {"ok": True, "dryRun": dry_run}
        stop_result = {"ok": True, "dryRun": dry_run}
        if not dry_run:
            result = paper_trading.buy(
                symbol=symbol,
                market=market,
                quantity=qty,
                price=rec["entry"],
                name=rec["name"],
                memo=f"AI paper buy {rec['mode']}/{rec['horizon']} EV={rec['expectedValue']:.2f}",
            )
            if result.get("ok"):
                stop_result = paper_trading.update_stop(
                    market,
                    symbol,
                    stop_price=rec["stop"],
                    target_price=rec["target"],
                    note=f"AI paper {rec['mode']}/{rec['horizon']} {rec['source']}",
                )
        actions.append({
            "action": "BUY",
            "market": market,
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
            "result": result,
            "stopResult": stop_result,
        })
        if result.get("ok"):
            cash -= total
            held.add(symbol)
            slots -= 1
    return actions


def _append_nav_snapshot(market: str, cycle_actions: list[dict[str, Any]]) -> dict[str, Any]:
    fields = [
        "date", "createdAt", "market", "state", "seed", "cash", "valuation",
        "portfolioValue", "totalPnl", "totalReturnPct", "survivalPct",
        "positionCount", "tradeCount", "buyCount", "sellCount",
    ]
    summary = _summary_for_market(market)
    survival = _survival_state(market, summary)
    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "market": market,
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
    }
    rows = _read_csv(AI_NAV_CSV)
    rows.append(row)
    _write_csv(AI_NAV_CSV, rows, fields)
    return row


def _save_state(payload: dict[str, Any]) -> None:
    _ensure_dirs()
    AI_STATE_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def status(market: str = "all") -> dict[str, Any]:
    markets = {}
    for mk in _market_list(market):
        summary = _summary_for_market(mk)
        markets[mk] = {
            "summary": summary,
            "survival": _survival_state(mk, summary),
            "positions": _position_items(mk),
            "candidateCount": len(_collect_recommendations(mk)),
        }
    state = {}
    if AI_STATE_JSON.exists():
        try:
            state = json.loads(AI_STATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    nav_rows = _read_csv(AI_NAV_CSV)
    return {
        "status": "OK",
        "market": market,
        "markets": markets,
        "lastRun": state,
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
        summary = _summary_for_market(mk)
        result["markets"][mk] = {
            "actions": actions,
            "summary": summary,
            "survival": _survival_state(mk, summary),
            "nav": nav,
        }
    if not dry_run:
        _save_state(result)
    return result
