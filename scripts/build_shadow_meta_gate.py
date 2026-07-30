#!/usr/bin/env python3
"""Build a non-mutating TAKE/WAIT/REJECT recommendation challenger.

The gate refuses to interpret an uncalibrated model score as a probability.
It uses independent forward-paper outcomes per strategy cell, after-cost
expectancy, profit factor, date coverage, and basic trade constraints.  It is
shadow-only and can return zero TAKE decisions.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
EVALUATIONS = ROOT / "data" / "virtual_trade_evaluations.csv"
REPORTS = ROOT / "reports"
OUT = REPORTS / "shadow_meta_gate.json"

FORWARD_SOURCES = {"FORWARD_PAPER_TRADE", "MANUAL_REVIEWED"}
PLAN_ONLY_SESSIONS = {"PREMARKET_PLAN", "INTRADAY_CHECK"}
MIN_INDEPENDENT_DECISIONS = 100
MIN_DISTINCT_SIGNAL_DATES = 30
MIN_RISK_REWARD = 1.5
MAX_TAKE = 3
PROBABILITY_BINS = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 101))


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
        raw = _text(value).replace(",", "").replace("%", "")
        return float(raw) if raw and raw.lower() not in {"nan", "none", "null", "-"} else None
    except (TypeError, ValueError):
        return None


def _latest_evaluations() -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in _read_csv(EVALUATIONS):
        journal_id = _text(row.get("journal_id"))
        if not journal_id:
            continue
        previous = latest.get(journal_id)
        if previous is None or _text(row.get("evaluated_at")) >= _text(previous.get("evaluated_at")):
            latest[journal_id] = row
    return latest


def _independent_rows() -> list[dict[str, Any]]:
    evaluations = _latest_evaluations()
    selected: dict[str, dict[str, Any]] = {}
    for journal in _read_csv(JOURNAL):
        if _text(journal.get("source_type")).upper() not in FORWARD_SOURCES:
            continue
        if _text(journal.get("journal_session")).upper() in PLAN_ONLY_SESSIONS:
            continue
        evaluation = evaluations.get(_text(journal.get("journal_id")))
        if not evaluation or _text(evaluation.get("status")).upper() not in {"EVALUATED", "CANCELLED"}:
            continue
        pnl = _num(evaluation.get("net_pnl_pct"))
        if pnl is None:
            continue
        row = {**journal, **evaluation, "net_pnl_pct": pnl}
        key = "|".join(
            _text(row.get(field)).lower()
            for field in ("as_of_date", "market", "symbol", "mode", "horizon")
        )
        previous = selected.get(key)
        previous_score = _num(previous.get("final_rank_score")) if previous else None
        score = _num(row.get("final_rank_score"))
        if previous is None or (score if score is not None else float("-inf")) > (
            previous_score if previous_score is not None else float("-inf")
        ):
            selected[key] = row
    return list(selected.values())


def _wilson_lower(wins: int, total: int, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    p = wins / total
    denominator = 1 + z * z / total
    center = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (center - margin) / denominator)


def _calibration_bins(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None]:
    buckets: list[dict[str, Any]] = []
    brier_terms: list[float] = []
    for low, high in PROBABILITY_BINS:
        selected = []
        for row in rows:
            probability = _num(row.get("probability"))
            if probability is not None and low <= probability < high:
                selected.append((probability, float(row["net_pnl_pct"]) > 0))
        if not selected:
            continue
        wins = sum(1 for _, won in selected if won)
        mean_prediction = sum(probability for probability, _ in selected) / len(selected) / 100.0
        actual = wins / len(selected)
        brier_terms.extend((probability / 100.0 - float(won)) ** 2 for probability, won in selected)
        buckets.append({
            "band": f"{low}-{min(high, 100)}",
            "samples": len(selected),
            "meanPredicted": round(mean_prediction, 4),
            "actualWinRate": round(actual, 4),
            "calibrationGap": round(mean_prediction - actual, 4),
            "wilsonLower95": round(_wilson_lower(wins, len(selected)) or 0.0, 4),
        })
    return buckets, round(sum(brier_terms) / len(brier_terms), 6) if brier_terms else None


def _cell_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = "|".join(_text(row.get(field)).lower() for field in ("market", "mode", "horizon"))
        grouped[key].append(row)
    out: dict[str, dict[str, Any]] = {}
    for key, cell_rows in grouped.items():
        pnls = [float(row["net_pnl_pct"]) for row in cell_rows]
        wins = sum(1 for pnl in pnls if pnl > 0)
        gross_profit = sum(pnl for pnl in pnls if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
        dates = {_text(row.get("as_of_date"))[:10] for row in cell_rows if _text(row.get("as_of_date"))}
        bins, brier = _calibration_bins(cell_rows)
        avg_pnl = sum(pnls) / len(pnls)
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        reasons: list[str] = []
        if len(cell_rows) < MIN_INDEPENDENT_DECISIONS:
            reasons.append("LOW_INDEPENDENT_DECISIONS")
        if len(dates) < MIN_DISTINCT_SIGNAL_DATES:
            reasons.append("LOW_DISTINCT_SIGNAL_DATES")
        if avg_pnl <= 0:
            reasons.append("NON_POSITIVE_AFTER_COST_EXPECTANCY")
        if profit_factor is None or profit_factor <= 1.0:
            reasons.append("PROFIT_FACTOR_NOT_ABOVE_ONE")
        evidence_status = "PASS" if not reasons else (
            "REJECT" if "NON_POSITIVE_AFTER_COST_EXPECTANCY" in reasons or "PROFIT_FACTOR_NOT_ABOVE_ONE" in reasons else "WAIT"
        )
        out[key] = {
            "independentDecisions": len(cell_rows),
            "distinctSignalDates": len(dates),
            "winRate": round(wins / len(cell_rows), 4),
            "winRateWilsonLower95": round(_wilson_lower(wins, len(cell_rows)) or 0.0, 4),
            "avgNetPnlPct": round(avg_pnl, 4),
            "profitFactor": round(profit_factor, 4) if profit_factor is not None else None,
            "brierScore": brier,
            "probabilityCalibration": bins,
            "evidenceStatus": evidence_status,
            "blockingReasons": reasons,
        }
    return out


def _recommendation_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = str(REPORTS / "mone_v36_final_recommendations_*.csv")
    for raw_path in sorted(glob.glob(pattern)):
        path = Path(raw_path)
        for row in _read_csv(path):
            row.setdefault("recommendationSource", path.name)
            rows.append(row)
    return rows


def _candidate_decision(row: dict[str, Any], cell: dict[str, Any] | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    data_status = _text(row.get("dataStatus") or row.get("data_status")).upper()
    expected_value = _num(row.get("expectedValue") or row.get("expected_value"))
    risk_reward = _num(row.get("rrActual") or row.get("riskRewardRatio") or row.get("risk_reward_ratio"))
    if data_status not in {"NORMAL", "OK"}:
        reasons.append("DATA_NOT_NORMAL")
    if expected_value is None or expected_value <= 0:
        reasons.append("EV_NOT_POSITIVE")
    if risk_reward is None or risk_reward < MIN_RISK_REWARD:
        reasons.append("RISK_REWARD_TOO_LOW")
    if cell is None:
        reasons.append("NO_FORWARD_EVIDENCE")
        return "WAIT", reasons
    reasons.extend(cell.get("blockingReasons") or [])
    if any(reason in reasons for reason in (
        "DATA_NOT_NORMAL",
        "EV_NOT_POSITIVE",
        "RISK_REWARD_TOO_LOW",
        "NON_POSITIVE_AFTER_COST_EXPECTANCY",
        "PROFIT_FACTOR_NOT_ABOVE_ONE",
    )):
        return "REJECT", reasons
    if cell.get("evidenceStatus") != "PASS":
        return "WAIT", reasons
    return "TAKE", reasons


def build() -> dict[str, Any]:
    cells = _cell_stats(_independent_rows())
    decisions: list[dict[str, Any]] = []
    for row in _recommendation_rows():
        market = _text(row.get("market")).lower()
        mode = _text(row.get("mode")).lower()
        horizon = _text(row.get("horizon")).lower()
        cell_key = f"{market}|{mode}|{horizon}"
        decision, reasons = _candidate_decision(row, cells.get(cell_key))
        decisions.append({
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "symbol": _text(row.get("symbol")),
            "name": _text(row.get("name")),
            "decision": decision,
            "reasons": list(dict.fromkeys(reasons)),
            "score": _num(row.get("finalRankScore") or row.get("finalScore")),
            "expectedValue": _num(row.get("expectedValue")),
            "riskRewardRatio": _num(row.get("rrActual") or row.get("riskRewardRatio")),
            "modelProbabilityDisplayOnly": _num(row.get("probability")),
            "recommendationSource": row.get("recommendationSource"),
        })
    decisions.sort(key=lambda row: row.get("score") if row.get("score") is not None else float("-inf"), reverse=True)
    take = [row for row in decisions if row["decision"] == "TAKE"][:MAX_TAKE]
    return {
        "status": "SHADOW_ONLY",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "maxTake": MAX_TAKE,
            "minIndependentDecisions": MIN_INDEPENDENT_DECISIONS,
            "minDistinctSignalDates": MIN_DISTINCT_SIGNAL_DATES,
            "minRiskRewardRatio": MIN_RISK_REWARD,
            "requiresPositiveAfterCostExpectancy": True,
            "requiresProfitFactorAboveOne": True,
            "uncalibratedProbabilityCanTriggerTake": False,
        },
        "summary": {
            "candidates": len(decisions),
            "take": len(take),
            "wait": sum(1 for row in decisions if row["decision"] == "WAIT"),
            "reject": sum(1 for row in decisions if row["decision"] == "REJECT"),
            "abstain": len(take) == 0,
        },
        "take": take,
        "decisions": decisions,
        "cellEvidence": cells,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    report = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
