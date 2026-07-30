#!/usr/bin/env python3
"""Audit forward recommendation evidence by immutable strategy fingerprint.

Calendar clean windows are insufficient when strategy code or calibration can
change inside the window.  This report groups evaluated signals by the exact
strategy fingerprint and counts independent date/market/symbol decisions.
It never promotes a strategy; it only reports whether the minimum evidence
contract is satisfied.
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
OUT = ROOT / "reports" / "strategy_cohort_audit.json"

FORWARD_SOURCES = {"FORWARD_PAPER_TRADE", "MANUAL_REVIEWED"}
REALIZED_STATUSES = {"EVALUATED", "CANCELLED"}
PLAN_ONLY_SESSIONS = {"PREMARKET_PLAN", "INTRADAY_CHECK"}
LEGACY_FINGERPRINT = "LEGACY_UNFINGERPRINTED"


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


def decision_unit_id(row: dict[str, Any]) -> str:
    existing = _text(row.get("decision_unit_id"))
    if existing:
        return existing
    raw = "|".join(
        _text(row.get(key)).lower()
        for key in ("as_of_date", "market", "symbol")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _merge_latest_evaluations(journal: list[dict[str, str]], evaluations: list[dict[str, str]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, str]] = {}
    for evaluation in evaluations:
        journal_id = _text(evaluation.get("journal_id"))
        if not journal_id:
            continue
        previous = latest.get(journal_id)
        if previous is None or _text(evaluation.get("evaluated_at")) >= _text(previous.get("evaluated_at")):
            latest[journal_id] = evaluation
    return [{**row, **latest.get(_text(row.get("journal_id")), {})} for row in journal]


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = decision_unit_id(row)
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
    return list(selected.values())


def build(min_decisions: int = 200, min_signal_dates: int = 60) -> dict[str, Any]:
    merged = _merge_latest_evaluations(_read_csv(JOURNAL), _read_csv(EVALUATIONS))
    forward = [
        row for row in merged
        if _text(row.get("source_type")).upper() in FORWARD_SOURCES
        and _text(row.get("journal_session")).upper() not in PLAN_ONLY_SESSIONS
    ]
    evaluated = [row for row in forward if _text(row.get("status")).upper() in REALIZED_STATUSES]
    independent = _dedupe(evaluated)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in independent:
        fingerprint = _text(row.get("strategy_fingerprint")) or LEGACY_FINGERPRINT
        groups[fingerprint].append(row)

    raw_decision_fingerprints: dict[str, set[str]] = defaultdict(set)
    for row in evaluated:
        raw_decision_fingerprints[decision_unit_id(row)].add(
            _text(row.get("strategy_fingerprint")) or LEGACY_FINGERPRINT
        )
    mixed_units = sum(1 for fingerprints in raw_decision_fingerprints.values() if len(fingerprints) > 1)

    cohorts: list[dict[str, Any]] = []
    for fingerprint, rows in groups.items():
        dates = sorted({_text(row.get("as_of_date"))[:10] for row in rows if _text(row.get("as_of_date"))})
        pnls = [_num(row.get("net_pnl_pct")) for row in rows]
        pnls = [value for value in pnls if value is not None]
        wins = sum(1 for value in pnls if value > 0)
        reasons: list[str] = []
        if fingerprint == LEGACY_FINGERPRINT:
            reasons.append("LEGACY_IDENTITY")
        if len(rows) < min_decisions:
            reasons.append("LOW_INDEPENDENT_DECISIONS")
        if len(dates) < min_signal_dates:
            reasons.append("LOW_DISTINCT_SIGNAL_DATES")
        if not pnls:
            reasons.append("NO_REALIZED_PNL")
        elif sum(pnls) / len(pnls) <= 0:
            reasons.append("NON_POSITIVE_AFTER_COST_EXPECTANCY")
        cohorts.append({
            "strategyFingerprint": fingerprint,
            "independentDecisions": len(rows),
            "distinctSignalDates": len(dates),
            "dateRange": {"min": dates[0], "max": dates[-1]} if dates else None,
            "realizedPnlSamples": len(pnls),
            "avgNetPnlPct": round(sum(pnls) / len(pnls), 4) if pnls else None,
            "winRate": round(wins / len(pnls), 4) if pnls else None,
            "promotionEvidenceReady": not reasons,
            "blockingReasons": reasons,
        })
    cohorts.sort(key=lambda item: (item["dateRange"] or {}).get("max", ""), reverse=True)

    fingerprinted = sum(
        1 for row in independent
        if _text(row.get("strategy_fingerprint")) not in {"", LEGACY_FINGERPRINT}
    )
    return {
        "status": "OK",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sampleContract": {
            "unit": "UNIQUE_AS_OF_DATE_MARKET_SYMBOL",
            "minIndependentDecisions": min_decisions,
            "minDistinctSignalDates": min_signal_dates,
            "forwardSourcesOnly": True,
            "realizedOnly": True,
        },
        "summary": {
            "forwardRows": len(forward),
            "evaluatedRows": len(evaluated),
            "independentDecisions": len(independent),
            "duplicateRowsRemoved": len(evaluated) - len(independent),
            "mixedFingerprintDecisionUnits": mixed_units,
            "fingerprintedIndependentDecisions": fingerprinted,
            "legacyIndependentDecisions": len(independent) - fingerprinted,
        },
        "cohorts": cohorts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-decisions", type=int, default=200)
    parser.add_argument("--min-signal-dates", type=int, default=60)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()

    report = build(
        min_decisions=max(1, args.min_decisions),
        min_signal_dates=max(1, args.min_signal_dates),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
