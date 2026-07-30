#!/usr/bin/env python3
"""Persist and evaluate the pre-registered shadow Champion–Challenger test.

Champion takes the top three raw candidates at a fixed 10% weight each.
Challenger takes only meta-gate TAKE decisions at the same weight. Unused
exposure remains cash. Promotion is never automatic and requires independent
signal-date evidence, positive after-cost performance, positive paired uplift,
usable residual alpha, drawdown control, and clean time integrity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
META_GATE = ROOT / "reports" / "shadow_meta_gate.json"
ALPHA_REPORT = ROOT / "reports" / "recommendation_alpha.json"
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
EVALUATIONS = ROOT / "data" / "virtual_trade_evaluations.csv"
LEDGER = ROOT / "data" / "shadow_challenger_journal.csv"
OUT = ROOT / "reports" / "champion_challenger.json"

POLICY_VERSION = "champion-challenger-v1.0.0"
POSITION_WEIGHT = 0.10
MAX_POSITIONS = 3
MIN_COMPLETE_SIGNAL_DATES = 60
MIN_EVALUATED_CHALLENGER_TRADES = 120
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260730

LEDGER_FIELDS = [
    "decision_id", "policy_version", "policy_fingerprint", "recorded_at",
    "signal_date", "generated_at", "market", "mode", "horizon", "symbol",
    "name", "score", "champion_decision", "challenger_decision", "reasons",
]


def _policy() -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "champion": "TOP_3_RAW_CANDIDATES",
        "challenger": "SHADOW_META_GATE_TAKE_ONLY",
        "positionWeight": POSITION_WEIGHT,
        "maxPositions": MAX_POSITIONS,
        "removedExposureStaysCash": True,
        "sameSignalDatePairedComparison": True,
        "minCompleteSignalDates": MIN_COMPLETE_SIGNAL_DATES,
        "minEvaluatedChallengerTrades": MIN_EVALUATED_CHALLENGER_TRADES,
        "requiresPositiveAfterCostReturn": True,
        "requiresProfitFactorAboveOne": True,
        "requiresPairedUpliftBootstrapLowerAboveZero": True,
        "requiresD20ResidualAlphaLowerCiAboveZero": True,
        "requiresChallengerDrawdownNoWorseThanChampion": True,
        "requiresTimeIntegrity": True,
        "autoPromotionAllowed": False,
        "humanApprovalRequired": True,
    }


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        raw = _text(value).replace(",", "").replace("%", "").replace("$", "")
        return float(raw) if raw and raw.lower() not in {"nan", "none", "null", "-"} else None
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


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


def _write_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _ledger_row(decision: dict[str, Any], recorded_at: str) -> dict[str, Any] | None:
    signal_date = _text(decision.get("signalDate"))[:10]
    symbol = _text(decision.get("symbol")).upper()
    if not signal_date or not symbol:
        return None
    decision_id = _text(decision.get("decisionId"))
    if not decision_id:
        raw = "|".join([
            _text(decision.get("policyFingerprint")), signal_date,
            _text(decision.get("market")).lower(), _text(decision.get("mode")).lower(),
            _text(decision.get("horizon")).lower(), symbol,
        ])
        decision_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    reasons = decision.get("reasons") if isinstance(decision.get("reasons"), list) else []
    return {
        "decision_id": decision_id,
        "policy_version": POLICY_VERSION,
        "policy_fingerprint": _fingerprint(_policy()),
        "recorded_at": recorded_at,
        "signal_date": signal_date,
        "generated_at": _text(decision.get("generatedAt")),
        "market": _text(decision.get("market")).lower(),
        "mode": _text(decision.get("mode")).lower(),
        "horizon": _text(decision.get("horizon")).lower(),
        "symbol": symbol,
        "name": _text(decision.get("name")),
        "score": _num(decision.get("score")),
        "champion_decision": "TAKE",
        "challenger_decision": _text(decision.get("decision")).upper() or "WAIT",
        "reasons": ";".join(_text(reason) for reason in reasons if _text(reason)),
    }


def record_decisions(meta: dict[str, Any], ledger_path: Path, recorded_at: str | None = None) -> dict[str, int]:
    now = recorded_at or datetime.now(timezone.utc).isoformat()
    existing = _read_csv(ledger_path)
    by_id = {_text(row.get("decision_id")): row for row in existing if _text(row.get("decision_id"))}
    appended = 0
    conflicts = 0
    skipped = 0
    immutable_fields = [field for field in LEDGER_FIELDS if field != "recorded_at"]
    for decision in meta.get("decisions") if isinstance(meta.get("decisions"), list) else []:
        row = _ledger_row(decision, now)
        if row is None:
            skipped += 1
            continue
        previous = by_id.get(row["decision_id"])
        if previous is not None:
            if any(_text(previous.get(field)) != _text(row.get(field)) for field in immutable_fields):
                conflicts += 1
            continue
        existing.append(row)
        by_id[row["decision_id"]] = row
        appended += 1
    existing.sort(key=lambda row: (_text(row.get("signal_date")), _text(row.get("decision_id"))))
    if appended or (not ledger_path.exists() and existing):
        _write_ledger(ledger_path, existing)
    return {"appended": appended, "conflicts": conflicts, "skipped": skipped, "total": len(existing)}


def _decision_key(row: dict[str, Any]) -> str:
    return "|".join([
        _text(row.get("signal_date") or row.get("as_of_date"))[:10],
        _text(row.get("market")).lower(), _text(row.get("mode")).lower(),
        _text(row.get("horizon")).lower(), _text(row.get("symbol")).upper(),
    ])


def _latest_outcomes(journal_path: Path, evaluations_path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    evaluations: dict[str, dict[str, str]] = {}
    for row in _read_csv(evaluations_path):
        journal_id = _text(row.get("journal_id"))
        if _text(row.get("status")).upper() != "EVALUATED" or _num(row.get("net_pnl_pct")) is None:
            continue
        if journal_id and (journal_id not in evaluations or _text(row.get("evaluated_at")) >= _text(evaluations[journal_id].get("evaluated_at"))):
            evaluations[journal_id] = row

    outcomes: dict[str, dict[str, Any]] = {}
    violations: list[dict[str, Any]] = []
    for journal in _read_csv(journal_path):
        evaluation = evaluations.get(_text(journal.get("journal_id")))
        if evaluation is None:
            continue
        merged = {**journal, **evaluation}
        key = _decision_key(merged)
        signal_date = _text(journal.get("as_of_date"))[:10]
        fill_date = _text(evaluation.get("fill_date"))[:10]
        exit_date = _text(evaluation.get("exit_date"))[:10]
        evaluated_date = _text(evaluation.get("evaluated_at"))[:10]
        invalid = (
            (fill_date and fill_date < signal_date)
            or (exit_date and fill_date and exit_date < fill_date)
            or (evaluated_date and evaluated_date < signal_date)
        )
        if invalid:
            violations.append({"decisionKey": key, "signalDate": signal_date, "fillDate": fill_date, "exitDate": exit_date, "evaluatedDate": evaluated_date})
            continue
        candidate = {**merged, "net_pnl_pct": float(_num(evaluation.get("net_pnl_pct")) or 0.0)}
        previous = outcomes.get(key)
        if previous is None or _text(candidate.get("evaluated_at")) >= _text(previous.get("evaluated_at")):
            outcomes[key] = candidate
    return outcomes, violations


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (_num(row.get("score")) if _num(row.get("score")) is not None else float("-inf"), _text(row.get("symbol"))), reverse=True)


def _max_drawdown(returns_pct: list[float]) -> float:
    nav = peak = 1.0
    max_dd = 0.0
    for value in returns_pct:
        nav *= 1.0 + value / 100.0
        peak = max(peak, nav)
        max_dd = max(max_dd, (peak - nav) / peak if peak > 0 else 0.0)
    return max_dd * 100.0


def _arm_stats(returns_pct: list[float], selected_trades: int) -> dict[str, Any]:
    nav = 1.0
    for value in returns_pct:
        nav *= 1.0 + value / 100.0
    gains = sum(value for value in returns_pct if value > 0)
    losses = abs(sum(value for value in returns_pct if value < 0))
    return {
        "completeSignalDates": len(returns_pct),
        "selectedEvaluatedTrades": selected_trades,
        "avgDailyReturnPct": round(sum(returns_pct) / len(returns_pct), 6) if returns_pct else None,
        "totalReturnPct": round((nav - 1.0) * 100.0, 6) if returns_pct else None,
        "profitFactor": round(gains / losses, 6) if losses > 0 else (None if gains <= 0 else 999.0),
        "maxDrawdownPct": round(_max_drawdown(returns_pct), 6) if returns_pct else None,
    }


def _bootstrap_ci(values: list[float]) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        means.append(sum(values[rng.randrange(len(values))] for _ in values) / len(values))
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(0.975 * (len(means) - 1))]
    return [round(low, 6), round(high, 6)]


def compare(ledger_rows: list[dict[str, Any]], outcomes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ledger_rows:
        grouped[_text(row.get("signal_date"))[:10]].append(row)

    daily: list[dict[str, Any]] = []
    incomplete_dates = 0
    champion_trades = challenger_trades = 0
    for signal_date in sorted(date for date in grouped if date):
        rows = _rank(grouped[signal_date])
        champion = rows[:MAX_POSITIONS]
        challenger = [row for row in rows if _text(row.get("challenger_decision")).upper() == "TAKE"][:MAX_POSITIONS]
        required = {row["decision_id"]: row for row in champion + challenger}
        resolved: dict[str, dict[str, Any]] = {}
        for decision_id, row in required.items():
            outcome = outcomes.get(_decision_key(row))
            if outcome is not None:
                resolved[decision_id] = outcome
        if len(resolved) != len(required):
            incomplete_dates += 1
            continue
        champion_return = POSITION_WEIGHT * sum(float(resolved[row["decision_id"]]["net_pnl_pct"]) for row in champion)
        challenger_return = POSITION_WEIGHT * sum(float(resolved[row["decision_id"]]["net_pnl_pct"]) for row in challenger)
        champion_trades += len(champion)
        challenger_trades += len(challenger)
        daily.append({
            "signalDate": signal_date,
            "championReturnPct": round(champion_return, 6),
            "challengerReturnPct": round(challenger_return, 6),
            "upliftPct": round(challenger_return - champion_return, 6),
            "championTrades": len(champion),
            "challengerTrades": len(challenger),
        })

    champion_returns = [row["championReturnPct"] for row in daily]
    challenger_returns = [row["challengerReturnPct"] for row in daily]
    uplifts = [row["upliftPct"] for row in daily]
    return {
        "completedSignalDates": len(daily),
        "incompleteSignalDates": incomplete_dates,
        "champion": _arm_stats(champion_returns, champion_trades),
        "challenger": _arm_stats(challenger_returns, challenger_trades),
        "pairedUplift": {
            "meanPct": round(sum(uplifts) / len(uplifts), 6) if uplifts else None,
            "bootstrapCi95": _bootstrap_ci(uplifts),
            "bootstrapUnit": "SIGNAL_DATE",
            "bootstrapSamples": BOOTSTRAP_SAMPLES,
        },
        "daily": daily,
    }


def _alpha_gate(alpha: dict[str, Any]) -> dict[str, Any]:
    windows = alpha.get("windows") if isinstance(alpha.get("windows"), dict) else {}
    d20 = windows.get("D+20") if isinstance(windows.get("D+20"), dict) else {}
    ci = d20.get("bootstrapCi95") if isinstance(d20.get("bootstrapCi95"), list) else None
    usable = bool(d20.get("significanceUsable")) and bool(ci) and _num(ci[0]) is not None and float(ci[0]) > 0
    return {
        "passed": usable,
        "blockMeanCarPct": d20.get("blockMeanCarPct"),
        "bootstrapCi95": ci,
        "independentMarketDateBlocks": d20.get("independentMarketDateBlocks"),
        "significanceUsable": bool(d20.get("significanceUsable")),
    }


def promotion_decision(comparison: dict[str, Any], alpha_gate: dict[str, Any], integrity: dict[str, Any]) -> dict[str, Any]:
    challenger = comparison["challenger"]
    champion = comparison["champion"]
    uplift_ci = comparison["pairedUplift"].get("bootstrapCi95")
    blockers: list[str] = []
    if integrity.get("immutableConflicts", 0) > 0:
        blockers.append("IMMUTABLE_DECISION_CONFLICT")
    if integrity.get("timeIntegrityViolations", 0) > 0:
        blockers.append("TIME_INTEGRITY_VIOLATION")
    if integrity.get("fingerprintCoverage", 0.0) < 1.0:
        blockers.append("INCOMPLETE_POLICY_FINGERPRINT_COVERAGE")
    if comparison.get("completedSignalDates", 0) < MIN_COMPLETE_SIGNAL_DATES:
        blockers.append("LOW_COMPLETE_SIGNAL_DATES")
    if challenger.get("selectedEvaluatedTrades", 0) < MIN_EVALUATED_CHALLENGER_TRADES:
        blockers.append("LOW_EVALUATED_CHALLENGER_TRADES")
    if challenger.get("avgDailyReturnPct") is None or challenger["avgDailyReturnPct"] <= 0:
        blockers.append("NON_POSITIVE_CHALLENGER_RETURN")
    if challenger.get("profitFactor") is None or challenger["profitFactor"] <= 1.0:
        blockers.append("CHALLENGER_PROFIT_FACTOR_NOT_ABOVE_ONE")
    if not uplift_ci or float(uplift_ci[0]) <= 0:
        blockers.append("PAIRED_UPLIFT_NOT_PROVEN")
    if challenger.get("maxDrawdownPct") is None or champion.get("maxDrawdownPct") is None:
        blockers.append("DRAWDOWN_COMPARISON_NOT_READY")
    elif challenger["maxDrawdownPct"] > champion["maxDrawdownPct"]:
        blockers.append("CHALLENGER_DRAWDOWN_WORSE")
    if not alpha_gate.get("passed"):
        blockers.append("RESIDUAL_ALPHA_NOT_PROVEN")
    return {
        "promotionEligible": not blockers,
        "decision": "READY_FOR_HUMAN_REVIEW" if not blockers else "KEEP_CHALLENGER_SHADOW",
        "blockingReasons": blockers,
        "autoPromotionAllowed": False,
        "humanApprovalRequired": True,
    }


def build(
    meta_path: Path = META_GATE,
    alpha_path: Path = ALPHA_REPORT,
    journal_path: Path = JOURNAL,
    evaluations_path: Path = EVALUATIONS,
    ledger_path: Path = LEDGER,
    *,
    record: bool = True,
) -> dict[str, Any]:
    meta = _read_json(meta_path)
    record_status = record_decisions(meta, ledger_path) if record else {"appended": 0, "conflicts": 0, "skipped": 0, "total": len(_read_csv(ledger_path))}
    ledger_rows = _read_csv(ledger_path)
    outcomes, violations = _latest_outcomes(journal_path, evaluations_path)
    comparison = compare(ledger_rows, outcomes)
    alpha_gate = _alpha_gate(_read_json(alpha_path))
    fingerprinted = sum(1 for row in ledger_rows if _text(row.get("policy_fingerprint")))
    integrity = {
        "immutableConflicts": record_status["conflicts"],
        "timeIntegrityViolations": len(violations),
        "fingerprintCoverage": round(fingerprinted / len(ledger_rows), 6) if ledger_rows else 0.0,
        "violations": violations[:20],
    }
    promotion = promotion_decision(comparison, alpha_gate, integrity)
    return {
        "status": "SHADOW_ONLY",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {**_policy(), "fingerprint": _fingerprint(_policy())},
        "recording": record_status,
        "integrity": integrity,
        "alphaGate": alpha_gate,
        "comparison": comparison,
        "promotion": promotion,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", type=Path, default=META_GATE)
    parser.add_argument("--alpha", type=Path, default=ALPHA_REPORT)
    parser.add_argument("--journal", type=Path, default=JOURNAL)
    parser.add_argument("--evaluations", type=Path, default=EVALUATIONS)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args()
    report = build(args.meta, args.alpha, args.journal, args.evaluations, args.ledger, record=not args.no_record)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"recording": report["recording"], "promotion": report["promotion"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
