#!/usr/bin/env python3
"""Capital-constrained sleeve NAV from actual forward-paper fills and exits.

Unlike the legacy fixed-return curve, this simulator reserves cash while a
position is open, never redistributes risk-clamped/unused cash, uses evaluated
net PnL (already including configured execution costs), and isolates strategy
fingerprints.  Same-day exit proceeds are not recycled into new entries.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
EVALUATIONS = ROOT / "data" / "virtual_trade_evaluations.csv"
OUT = ROOT / "reports" / "strategy_sleeve_nav_v2.json"

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")
FORWARD_SOURCES = {"FORWARD_PAPER_TRADE", "MANUAL_REVIEWED"}
PLAN_ONLY_SESSIONS = {"PREMARKET_PLAN", "INTRADAY_CHECK"}
LEGACY_FINGERPRINT = "LEGACY_UNFINGERPRINTED"
START_NAV = 100.0
POSITION_FRACTION = 0.10


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except UnicodeDecodeError:
            continue
    return []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        raw = _text(value).replace(",", "")
        return float(raw) if raw and raw.lower() not in {"nan", "none", "null", "-"} else None
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return _text(value).lower() in {"true", "1", "yes", "y"}


def _decision_id(row: dict[str, Any]) -> str:
    existing = _text(row.get("decision_unit_id"))
    if existing:
        return existing
    raw = "|".join(_text(row.get(key)).lower() for key in ("as_of_date", "market", "symbol"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _latest_evaluations(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        journal_id = _text(row.get("journal_id"))
        if not journal_id:
            continue
        previous = latest.get(journal_id)
        if previous is None or _text(row.get("evaluated_at")) >= _text(previous.get("evaluated_at")):
            latest[journal_id] = row
    return latest


def _max_drawdown(curve: list[dict[str, Any]]) -> float:
    peak = START_NAV
    drawdown = 0.0
    for point in curve:
        nav = float(point["nav"])
        peak = max(peak, nav)
        if peak > 0:
            drawdown = max(drawdown, (peak - nav) / peak * 100.0)
    return round(drawdown, 4)


def _select_latest_fingerprint(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    identified = [row for row in rows if _text(row.get("strategy_fingerprint"))]
    if not identified:
        return rows, LEGACY_FINGERPRINT
    latest: dict[str, str] = {}
    for row in identified:
        fingerprint = _text(row.get("strategy_fingerprint"))
        latest[fingerprint] = max(latest.get(fingerprint, ""), _text(row.get("as_of_date"))[:10])
    selected = max(latest, key=lambda fingerprint: latest[fingerprint])
    return [row for row in identified if _text(row.get("strategy_fingerprint")) == selected], selected


def _dedupe_within_sleeve(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _decision_id(row)
        previous = selected.get(key)
        if previous is None:
            selected[key] = row
            continue
        previous_score = _num(previous.get("final_rank_score"))
        score = _num(row.get("final_rank_score"))
        if (score if score is not None else float("-inf")) > (
            previous_score if previous_score is not None else float("-inf")
        ):
            selected[key] = row
    return list(selected.values()), len(rows) - len(selected)


def _simulate(trades: list[dict[str, Any]]) -> dict[str, Any]:
    events: list[tuple[str, int, float, str, dict[str, Any]]] = []
    for index, trade in enumerate(trades):
        trade_id = f"{_text(trade.get('journal_id'))}:{index}"
        # Entry first, exit second: proceeds from an intraday/same-day exit are
        # conservatively unavailable to another signal on that date.
        score = _num(trade.get("final_rank_score"))
        entry_rank = -(score if score is not None else float("-inf"))
        events.append((_text(trade.get("fill_date"))[:10], 0, entry_rank, trade_id, trade))
        events.append((_text(trade.get("exit_date"))[:10], 1, 0.0, trade_id, trade))
    events.sort(key=lambda event: (event[0], event[1], event[2], event[3]))

    cash = START_NAV
    open_positions: dict[str, dict[str, Any]] = {}
    curve: list[dict[str, Any]] = []
    realized: list[float] = []
    dollar_gains = 0.0
    dollar_losses = 0.0
    capacity_rejected = 0
    max_invested_pct = 0.0

    for event_date, event_type, _rank, trade_id, trade in events:
        if event_type == 0:
            nav = cash + sum(position["allocated"] for position in open_positions.values())
            allocation = min(cash, nav * POSITION_FRACTION)
            if allocation <= 1e-9:
                capacity_rejected += 1
                continue
            cash -= allocation
            open_positions[trade_id] = {"allocated": allocation, "trade": trade}
        else:
            position = open_positions.pop(trade_id, None)
            if position is None:
                continue
            pnl_pct = float(trade["net_pnl_pct"])
            pnl_amount = position["allocated"] * pnl_pct / 100.0
            cash += position["allocated"] + pnl_amount
            realized.append(pnl_pct)
            if pnl_amount > 0:
                dollar_gains += pnl_amount
            elif pnl_amount < 0:
                dollar_losses += abs(pnl_amount)
            nav = cash + sum(item["allocated"] for item in open_positions.values())
            curve.append({
                "date": event_date,
                "nav": round(nav, 4),
                "cash": round(cash, 4),
                "openPositions": len(open_positions),
                "symbol": trade.get("symbol"),
                "market": trade.get("market"),
                "netPnlPct": round(pnl_pct, 4),
            })

        nav = cash + sum(position["allocated"] for position in open_positions.values())
        invested = sum(position["allocated"] for position in open_positions.values())
        if nav > 0:
            max_invested_pct = max(max_invested_pct, invested / nav * 100.0)

    final_nav = cash + sum(position["allocated"] for position in open_positions.values())
    wins = sum(1 for value in realized if value > 0)
    gains = [value for value in realized if value > 0]
    losses = [value for value in realized if value <= 0]
    avg_gain = sum(gains) / len(gains) if gains else None
    avg_loss = sum(losses) / len(losses) if losses else None
    return {
        "trades": len(realized),
        "candidateTrades": len(trades),
        "capacityRejectedTrades": capacity_rejected,
        "nav": round(final_nav, 4),
        "cash": round(cash, 4),
        "openPositions": len(open_positions),
        "totalReturnPct": round((final_nav / START_NAV - 1.0) * 100.0, 4),
        "winRate": round(wins / len(realized), 4) if realized else None,
        "avgNetPnlPct": round(sum(realized) / len(realized), 4) if realized else None,
        "payoffRatio": round(abs(avg_gain / avg_loss), 4) if avg_gain is not None and avg_loss not in {None, 0} else None,
        "profitFactor": round(dollar_gains / dollar_losses, 4) if dollar_losses > 0 else None,
        "maxDrawdownPct": _max_drawdown(curve),
        "maxInvestedPct": round(max_invested_pct, 4),
        "curve": curve,
    }


def build() -> dict[str, Any]:
    evaluations = _latest_evaluations(_read_csv(EVALUATIONS))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded = defaultdict(int)

    for journal_row in _read_csv(JOURNAL):
        source = _text(journal_row.get("source_type")).upper()
        if source not in FORWARD_SOURCES:
            excluded["nonForwardSource"] += 1
            continue
        if _text(journal_row.get("journal_session")).upper() in PLAN_ONLY_SESSIONS:
            excluded["planOnlySession"] += 1
            continue
        evaluation = evaluations.get(_text(journal_row.get("journal_id")))
        if not evaluation or _text(evaluation.get("status")).upper() != "EVALUATED":
            excluded["notEvaluated"] += 1
            continue
        if not _truthy(evaluation.get("filled")):
            excluded["notFilled"] += 1
            continue
        net_pnl = _num(evaluation.get("net_pnl_pct"))
        fill_date = _text(evaluation.get("fill_date"))[:10]
        exit_date = _text(evaluation.get("exit_date"))[:10]
        if net_pnl is None:
            excluded["noNetPnl"] += 1
            continue
        if not fill_date or not exit_date or exit_date < fill_date:
            excluded["inexactTiming"] += 1
            continue
        mode = _text(journal_row.get("mode")).lower()
        horizon = _text(journal_row.get("horizon")).lower()
        if mode not in MODES or horizon not in HORIZONS:
            excluded["unknownSleeve"] += 1
            continue
        grouped[f"{mode}_{horizon}"].append({**journal_row, **evaluation, "net_pnl_pct": net_pnl})

    sleeves: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            cohort, fingerprint = _select_latest_fingerprint(grouped.get(key, []))
            deduped, duplicates = _dedupe_within_sleeve(cohort)
            sleeve = _simulate(deduped)
            sleeve["strategyFingerprint"] = fingerprint
            sleeve["duplicateDecisionRowsRemoved"] = duplicates
            sleeve["distinctSignalDates"] = len({_text(row.get("as_of_date"))[:10] for row in deduped})
            sleeves[key] = sleeve

    ranking = sorted(
        [key for key, sleeve in sleeves.items() if sleeve["trades"] > 0],
        key=lambda key: sleeves[key]["totalReturnPct"],
        reverse=True,
    )
    return {
        "status": "OK",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "basis": {
            "startNav": START_NAV,
            "positionFraction": POSITION_FRACTION,
            "capitalConstrained": True,
            "sameDayExitCashReused": False,
            "riskClampRedistribution": False,
            "returnField": "net_pnl_pct",
            "executionCostsAlreadyIncluded": True,
            "forwardSourcesOnly": True,
            "actualFillAndExitDatesRequired": True,
            "cohortPolicy": "LATEST_FINGERPRINT_PER_SLEEVE",
            "sameDayEntryPriority": "HIGHEST_FINAL_RANK_SCORE_FIRST",
        },
        "dataQuality": {"excluded": dict(excluded)},
        "ranking": ranking,
        "sleeves": sleeves,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    report = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "ranking", "dataQuality")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
