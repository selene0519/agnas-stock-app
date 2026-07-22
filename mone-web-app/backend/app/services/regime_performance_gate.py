"""Forward-only, net-return performance gates by market regime.

The global strategy gate answers whether a mode/horizon has earned money in
aggregate.  It cannot prove that the same strategy works in a bear or range
market.  This module only consumes evaluated forward-paper/manual trades and
therefore fails closed when the relevant regime lacks enough observations.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT / "data"
JOURNAL_CSV = DATA_DIR / "virtual_trade_journal.csv"
EVALUATION_CSV = DATA_DIR / "virtual_trade_evaluations.csv"

MIN_SAMPLES = 20
MIN_WIN_RATE_PCT = 45.0
ELIGIBLE_SOURCES = {"FORWARD_PAPER_TRADE", "MANUAL_REVIEWED"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").replace("%", "").strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _regime(value: Any) -> str:
    raw = _text(value).upper()
    if raw in {"BULL", "RISK_ON", "UPTREND", "BROADENING"}:
        return "BULL"
    if raw in {"BEAR", "RISK_OFF", "DOWNTREND", "CONTRACTION", "SHOCK"}:
        return "BEAR"
    if raw in {"SIDE", "SIDEWAYS", "NEUTRAL", "RANGE", "TRANSITIONAL", "INFLATIONARY"}:
        return "SIDE"
    return "UNKNOWN"


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except Exception:
            continue
    return []


def build_index(
    journal_rows: list[dict[str, Any]] | None = None,
    evaluation_rows: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return market -> mode_horizon -> regime -> realized net metrics."""
    journal_rows = journal_rows if journal_rows is not None else _read_rows(JOURNAL_CSV)
    evaluation_rows = evaluation_rows if evaluation_rows is not None else _read_rows(EVALUATION_CSV)
    journal_by_id = {_text(row.get("journal_id")): row for row in journal_rows if _text(row.get("journal_id"))}
    buckets: dict[tuple[str, str, str], list[float]] = {}

    for evaluation in evaluation_rows:
        journal = journal_by_id.get(_text(evaluation.get("journal_id")))
        if not journal:
            continue
        if _text(journal.get("source_type")).upper() not in ELIGIBLE_SOURCES:
            continue
        # A cancelled row is admissible only when it has a realized net PnL
        # (the missing-PnL cases are filtered immediately below), matching the
        # journal's established performance accounting.
        if _text(evaluation.get("status")).upper() not in {"EVALUATED", "CANCELLED"}:
            continue
        net_pnl = _number(evaluation.get("net_pnl_pct"))
        if net_pnl is None:
            continue
        market = _text(journal.get("market")).lower()
        mode = _text(journal.get("mode")).lower()
        horizon = _text(journal.get("horizon")).lower()
        regime = _regime(evaluation.get("regime_at_entry") or journal.get("market_regime_at_signal"))
        if market not in {"kr", "us"} or not mode or not horizon or regime == "UNKNOWN":
            continue
        buckets.setdefault((market, f"{mode}_{horizon}", regime), []).append(net_pnl)

    index: dict[str, dict[str, dict[str, Any]]] = {}
    for (market, strategy, regime), returns in buckets.items():
        count = len(returns)
        wins = sum(1 for value in returns if value > 0)
        index.setdefault(market, {}).setdefault(strategy, {})[regime] = {
            "sampleCount": count,
            "winRatePct": round(wins / count * 100, 2) if count else None,
            "averageNetReturnPct": round(sum(returns) / count, 4) if count else None,
            "source": "forward_paper_or_manual_reviewed_net_pnl",
        }
    return index


def evaluate(
    market: str,
    mode: str,
    horizon: str,
    regime: Any,
    *,
    index: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    market_key = _text(market).lower()
    strategy = f"{_text(mode).lower()}_{_text(horizon).lower()}"
    regime_key = _regime(regime)
    stats = ((index or build_index()).get(market_key, {}).get(strategy, {}).get(regime_key) or {})
    count = int(_number(stats.get("sampleCount")) or 0)
    win_rate = _number(stats.get("winRatePct"))
    average = _number(stats.get("averageNetReturnPct"))
    base = {
        "market": market_key,
        "strategy": strategy,
        "regime": regime_key,
        "sampleCount": count,
        "winRatePct": win_rate,
        "averageNetReturnPct": average,
        "minimumSamples": MIN_SAMPLES,
        "source": stats.get("source") or "forward_paper_or_manual_reviewed_net_pnl",
    }
    if regime_key == "UNKNOWN":
        return {**base, "status": "REGIME_UNAVAILABLE", "isTradeBlocked": True, "reason": "Current market regime is unavailable; do not infer regime profitability."}
    if count < MIN_SAMPLES:
        return {**base, "status": "INSUFFICIENT_REGIME_SAMPLES", "isTradeBlocked": True, "reason": f"{regime_key} {strategy} has {count}/{MIN_SAMPLES} realized forward net-return samples."}
    if average is None or average <= 0 or win_rate is None or win_rate < MIN_WIN_RATE_PCT:
        return {**base, "status": "REGIME_PERFORMANCE_BLOCKED", "isTradeBlocked": True, "reason": f"{regime_key} {strategy} is not profitable after costs: winRate={win_rate}%, avgNetReturn={average}%."}
    return {**base, "status": "REGIME_PERFORMANCE_OK", "isTradeBlocked": False, "reason": ""}
