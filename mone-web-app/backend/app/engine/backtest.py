from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.engine import session
from app.engine.symbols import display_name, normalize_market, normalize_symbol
from app.services import final_engine


def _pct(value: Any) -> float:
    text = str(value or "").replace("%", "").replace("+", "").replace(",", "").strip()
    try:
        return float(text)
    except Exception:
        return 0.0


def _is_win(row: dict[str, Any]) -> bool:
    exit_status = str(row.get("exitStatus") or row.get("result") or "")
    return "목표" in exit_status or "익절" in exit_status or _pct(row.get("pnlText") or row.get("returnPct")) > 0


def _is_loss(row: dict[str, Any]) -> bool:
    exit_status = str(row.get("exitStatus") or row.get("result") or "")
    reason = str(row.get("executionReason") or row.get("failureReason") or "")
    return "손절" in exit_status or "손절" in reason or _pct(row.get("pnlText") or row.get("returnPct")) < 0


def _is_executed(row: dict[str, Any]) -> bool:
    status = str(row.get("executionStatus") or row.get("is_executed") or "")
    return status in {"체결", "True", "true", "1"} or bool(row.get("isExecuted"))


def _normalize_trade(row: dict[str, Any], market: str) -> dict[str, Any]:
    symbol = normalize_symbol(row.get("symbol"), market)
    name = display_name(symbol, row.get("name"), market)
    executed = _is_executed(row)
    pnl = _pct(row.get("pnlText") or row.get("returnPct"))
    win = _is_win(row)
    loss = _is_loss(row)
    if not executed:
        result = "미체결"
        failure = "당일 고가/저가 범위가 추천 진입가를 터치하지 않음"
    elif win:
        result = "익절"
        failure = ""
    elif loss:
        result = "손절"
        failure = row.get("executionReason") or row.get("failureReason") or "손절가 이탈"
    else:
        result = "보유"
        failure = ""
    return {
        **row,
        "symbol": symbol,
        "name": name,
        "is_executed": executed,
        "is_win": win,
        "is_loss": loss,
        "virtual_return_pct": pnl,
        "result": result,
        "failure_reason": failure,
    }


def trades(
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    limit: int = 250,
) -> dict[str, Any]:
    normalized_market = normalize_market(market)
    payload = final_engine.trade_validation(normalized_market, mode, horizon)
    rows = payload.get("items") or []
    normalized = [_normalize_trade(row, normalized_market) for row in rows[:limit]]
    return {
        "status": "OK",
        "market": normalized_market,
        "mode": mode,
        "horizon": horizon,
        "rule": "추천 진입가가 당일 저가와 고가 사이에 실제로 존재한 경우만 가상 체결 처리",
        "count": len(normalized),
        "items": normalized,
        "generatedAt": datetime.now(session.KST).isoformat(),
    }


def summary(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    trade_payload = trades(market, mode, horizon, limit=500)
    rows = trade_payload.get("items") or []
    executed = [row for row in rows if row.get("is_executed")]
    wins = [row for row in executed if row.get("is_win")]
    losses = [row for row in executed if row.get("is_loss")]
    total_return = sum(float(row.get("virtual_return_pct") or 0) for row in executed)
    avg_win = sum(float(row.get("virtual_return_pct") or 0) for row in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(float(row.get("virtual_return_pct") or 0) for row in losses) / len(losses)) if losses else 0.0
    profit_loss_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else (round(avg_win, 2) if avg_win else 0.0)
    win_rate = round(len(wins) / len(executed) * 100, 1) if executed else 0.0

    return {
        "status": "OK",
        "market": trade_payload["market"],
        "mode": mode,
        "horizon": horizon,
        "total_trades": len(rows),
        "executed_trades": len(executed),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": win_rate,
        "virtual_win_rate": win_rate,
        "profit_loss_ratio": profit_loss_ratio,
        "total_return_pct": round(total_return, 2),
        "summaryText": f"가상 체결 {len(executed)}건 · 승률 {win_rate}% · 누적 {round(total_return, 2)}%",
        "items": rows[:30],
        "generatedAt": datetime.now(session.KST).isoformat(),
    }
