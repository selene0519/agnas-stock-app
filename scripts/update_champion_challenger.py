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
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
META_GATE = ROOT / "reports" / "shadow_meta_gate.json"
ALPHA_REPORT = ROOT / "reports" / "recommendation_alpha.json"
RESIDUAL_ALPHA_REPORT = ROOT / "reports" / "shadow_residual_alpha.json"
RISK_BUDGET_REPORT = ROOT / "reports" / "shadow_risk_budget.json"
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
EVALUATIONS = ROOT / "data" / "virtual_trade_evaluations.csv"
LEDGER = ROOT / "data" / "shadow_challenger_journal.csv"
OUT = ROOT / "reports" / "champion_challenger.json"

POLICY_VERSION = "champion-challenger-v1.3.3"
RESIDUAL_ALPHA_POLICY_VERSION = "shadow-residual-alpha-v1.1.2"
RISK_BUDGET_POLICY_VERSION = "shadow-risk-budget-v1.1.0"
EXPECTED_RISK_POLICY = {
    "baseWeight": 0.10,
    "maxPositionWeight": 0.10,
    "maxGrossExposure": 0.30,
    "maxSectorExposure": 0.15,
    "maxPortfolioBeta": 0.30,
    "accountRiskPerTrade": 0.005,
    "removedExposureStaysCash": True,
    "redistributionAllowed": False,
}
POSITION_WEIGHT = 0.10
MAX_POSITIONS = 3
MIN_COMPLETE_SIGNAL_DATES = 60
MIN_EVALUATED_CHALLENGER_TRADES = 120
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260730

LEDGER_FIELDS = [
    "decision_id", "meta_decision_id", "policy_version", "policy_fingerprint", "recorded_at",
    "candidate_key", "meta_policy_fingerprint", "residual_alpha_model_fingerprint",
    "residual_alpha_model_instance_fingerprint",
    "risk_policy_version", "risk_policy_fingerprint", "risk_allocation_fingerprint",
    "challenger_weight",
    "predicted_residual_alpha_pct", "residual_alpha_lower90_pct",
    "signal_date", "generated_at", "market", "mode", "horizon", "symbol",
    "name", "score", "champion_decision", "challenger_decision", "reasons",
    "record_hash",
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
        "requiresValidatedResidualAlphaPredictionModel": True,
        "residualAlphaPolicyVersion": RESIDUAL_ALPHA_POLICY_VERSION,
        "challengerUsesRecordedRiskBudgetWeights": True,
        "riskBudgetPolicyVersion": RISK_BUDGET_POLICY_VERSION,
        "requiresValidRiskAllocationLineage": True,
        "requiresChallengerDrawdownNoWorseThanChampion": True,
        "requiresTimeIntegrity": True,
        "autoPromotionAllowed": False,
        "humanApprovalRequired": True,
    }


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _full_fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _allocation_evidence(risk: dict[str, Any]) -> dict[str, Any]:
    policy = risk.get("policy") if isinstance(risk.get("policy"), dict) else {}
    positions = risk.get("positions") if isinstance(risk.get("positions"), list) else []
    rejected = risk.get("rejected") if isinstance(risk.get("rejected"), list) else []
    position_rows = [
        {
            "decisionId": _text(row.get("decisionId")),
            "candidateKey": _text(row.get("candidateKey")),
            "symbol": _text(row.get("symbol")),
            "market": _text(row.get("market")),
            "sector": _text(row.get("sector")),
            "weight": round(float(_num(row.get("weight")) or 0.0), 8),
            "stopDistancePct": round(float(_num(row.get("stopDistancePct")) or 0.0), 8),
            "lossAtStopPctOfEquity": round(float(_num(row.get("lossAtStopPctOfEquity")) or 0.0), 8),
            "beta": round(float(_num(row.get("beta")) or 0.0), 8),
            "betaSource": _text(row.get("betaSource")),
            "clamps": sorted(_text(value) for value in (row.get("clamps") or [])),
        }
        for row in positions if isinstance(row, dict)
    ]
    rejected_rows = [
        {
            "decisionId": _text(row.get("decisionId")),
            "candidateKey": _text(row.get("candidateKey")),
            "symbol": _text(row.get("symbol")),
            "reason": _text(row.get("reason")),
            "clamps": sorted(_text(value) for value in (row.get("clamps") or [])),
        }
        for row in rejected if isinstance(row, dict)
    ]
    return {
        "policyFingerprint": _text(policy.get("fingerprint")),
        "metaPolicyFingerprint": _text(policy.get("metaPolicyFingerprint")),
        "positions": sorted(position_rows, key=lambda row: (row["decisionId"], row["symbol"])),
        "rejected": sorted(rejected_rows, key=lambda row: (row["decisionId"], row["symbol"], row["reason"])),
    }


def _risk_context(meta: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
    meta_policy = meta.get("policy") if isinstance(meta.get("policy"), dict) else {}
    risk_policy = risk.get("policy") if isinstance(risk.get("policy"), dict) else {}
    lineage = risk.get("lineage") if isinstance(risk.get("lineage"), dict) else {}
    meta_fingerprint = _text(meta_policy.get("fingerprint"))
    policy_fingerprint = _text(risk_policy.get("fingerprint"))
    expected_policy = {
        "version": RISK_BUDGET_POLICY_VERSION,
        "metaPolicyFingerprint": meta_fingerprint or "MISSING",
        **EXPECTED_RISK_POLICY,
    }
    declared_allocation = _text(lineage.get("allocationFingerprint"))
    computed_allocation = _full_fingerprint(_allocation_evidence(risk))
    blockers: list[str] = []
    if risk_policy.get("version") != RISK_BUDGET_POLICY_VERSION:
        blockers.append("RISK_BUDGET_VERSION_MISMATCH")
    if not policy_fingerprint:
        blockers.append("MISSING_RISK_POLICY_FINGERPRINT")
    elif {key: value for key, value in risk_policy.items() if key != "fingerprint"} != expected_policy:
        blockers.append("RISK_POLICY_DEFINITION_MISMATCH")
    elif policy_fingerprint != _fingerprint(expected_policy):
        blockers.append("RISK_POLICY_FINGERPRINT_MISMATCH")
    if _text(risk_policy.get("metaPolicyFingerprint")) != meta_fingerprint:
        blockers.append("RISK_META_POLICY_MISMATCH")
    if lineage.get("valid") is not True:
        blockers.extend(lineage.get("blockingReasons") or ["RISK_LINEAGE_NOT_VALID"])
    if not declared_allocation or declared_allocation != computed_allocation:
        blockers.append("RISK_ALLOCATION_FINGERPRINT_MISMATCH")

    positions = risk.get("positions") if isinstance(risk.get("positions"), list) else []
    rejected = risk.get("rejected") if isinstance(risk.get("rejected"), list) else []
    take = meta.get("take") if isinstance(meta.get("take"), list) else []
    take_by_id = {
        _text(row.get("decisionId")): _text(row.get("candidateKey"))
        for row in take if isinstance(row, dict) and _text(row.get("decisionId"))
    }
    outcome_rows = [row for row in positions + rejected if isinstance(row, dict)]
    outcome_ids = [_text(row.get("decisionId")) for row in outcome_rows]
    if set(outcome_ids) != set(take_by_id) or len(outcome_ids) != len(set(outcome_ids)):
        blockers.append("RISK_ALLOCATION_DECISION_SET_MISMATCH")
    if any(
        take_by_id.get(_text(row.get("decisionId"))) != _text(row.get("candidateKey"))
        for row in outcome_rows
    ):
        blockers.append("RISK_ALLOCATION_CANDIDATE_MISMATCH")
    weights: dict[str, float] = {}
    computed_beta = 0.0
    computed_sectors: dict[str, float] = defaultdict(float)
    for row in positions:
        if not isinstance(row, dict):
            continue
        decision_id = _text(row.get("decisionId"))
        weight = _num(row.get("weight"))
        if not decision_id or weight is None or weight <= 0 or weight > POSITION_WEIGHT + 1e-12:
            blockers.append("INVALID_RISK_POSITION")
            continue
        if decision_id in weights:
            blockers.append("DUPLICATE_RISK_POSITION")
            continue
        weights[decision_id] = float(weight)
        beta = _num(row.get("beta"))
        stop_distance_pct = _num(row.get("stopDistancePct"))
        loss_at_stop_pct = _num(row.get("lossAtStopPctOfEquity"))
        sector = _text(row.get("sector"))
        if (
            weight > EXPECTED_RISK_POLICY["maxPositionWeight"] + 1e-12
            or beta is None or beta <= 0
            or stop_distance_pct is None or stop_distance_pct <= 0
            or loss_at_stop_pct is None
            or loss_at_stop_pct > EXPECTED_RISK_POLICY["accountRiskPerTrade"] * 100.0 + 1e-6
            or not sector
        ):
            blockers.append("RISK_POSITION_LIMIT_VIOLATION")
            continue
        computed_beta += float(weight) * float(beta)
        computed_sectors[sector] += float(weight)

    gross = sum(weights.values())
    reported_sectors = risk.get("sectorWeights") if isinstance(risk.get("sectorWeights"), dict) else {}
    aggregates_match = (
        math.isclose(float(_num(risk.get("grossExposure")) or 0.0), gross, abs_tol=1e-6)
        and math.isclose(float(_num(risk.get("cashWeight")) or 0.0), 1.0 - gross, abs_tol=1e-6)
        and math.isclose(float(_num(risk.get("portfolioBeta")) or 0.0), computed_beta, abs_tol=1e-5)
        and set(reported_sectors) == set(computed_sectors)
        and all(
            math.isclose(float(_num(reported_sectors.get(sector)) or 0.0), weight, abs_tol=1e-6)
            for sector, weight in computed_sectors.items()
        )
    )
    if not aggregates_match:
        blockers.append("RISK_ALLOCATION_AGGREGATE_MISMATCH")
    if gross > EXPECTED_RISK_POLICY["maxGrossExposure"] + 1e-12:
        blockers.append("RISK_GROSS_LIMIT_VIOLATION")
    if computed_beta > EXPECTED_RISK_POLICY["maxPortfolioBeta"] + 1e-6:
        blockers.append("RISK_BETA_LIMIT_VIOLATION")
    if any(weight > EXPECTED_RISK_POLICY["maxSectorExposure"] + 1e-12 for weight in computed_sectors.values()):
        blockers.append("RISK_SECTOR_LIMIT_VIOLATION")
    return {
        "valid": not blockers,
        "blockingReasons": list(dict.fromkeys(_text(reason) for reason in blockers if _text(reason))),
        "policyVersion": risk_policy.get("version"),
        "policyFingerprint": policy_fingerprint,
        "allocationFingerprint": declared_allocation,
        "weights": weights if not blockers else {},
    }


def _write_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _canonical_record_value(field: str, value: Any) -> str:
    numeric_fields = {
        "challenger_weight", "predicted_residual_alpha_pct",
        "residual_alpha_lower90_pct", "score",
    }
    if field not in numeric_fields:
        return _text(value)
    raw = str(value).strip() if value is not None else ""
    if not raw or raw.lower() in {"nan", "none", "null", "-"}:
        return ""
    try:
        number = float(raw.replace(",", "").replace("%", "").replace("$", ""))
    except (TypeError, ValueError):
        return ""
    return format(0.0 if abs(number) < 1e-15 else number, ".12g")


def _record_hash(row: dict[str, Any]) -> str:
    payload = {
        field: _canonical_record_value(field, row.get(field))
        for field in LEDGER_FIELDS
        if field not in {"recorded_at", "record_hash"}
    }
    return _full_fingerprint(payload)


def _ledger_row(
    decision: dict[str, Any],
    recorded_at: str,
    risk_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    signal_date = _text(decision.get("signalDate"))[:10]
    symbol = _text(decision.get("symbol")).upper()
    if not signal_date or not symbol:
        return None
    meta_decision_id = _text(decision.get("decisionId"))
    if not meta_decision_id:
        raw = "|".join([
            _text(decision.get("policyFingerprint")), signal_date,
            _text(decision.get("market")).lower(), _text(decision.get("mode")).lower(),
            _text(decision.get("horizon")).lower(), symbol,
        ])
        meta_decision_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    decision_id = hashlib.sha256(
        f"{_fingerprint(_policy())}|{meta_decision_id}".encode("utf-8")
    ).hexdigest()[:24]
    reasons = decision.get("reasons") if isinstance(decision.get("reasons"), list) else []
    risk_context = risk_context or {}
    risk_weights = risk_context.get("weights") if isinstance(risk_context.get("weights"), dict) else {}
    row = {
        "decision_id": decision_id,
        "meta_decision_id": meta_decision_id,
        "policy_version": POLICY_VERSION,
        "policy_fingerprint": _fingerprint(_policy()),
        "recorded_at": recorded_at,
        "candidate_key": _text(decision.get("candidateKey")),
        "meta_policy_fingerprint": _text(decision.get("policyFingerprint")),
        "residual_alpha_model_fingerprint": _text(decision.get("residualAlphaModelFingerprint")),
        "residual_alpha_model_instance_fingerprint": _text(decision.get("residualAlphaModelInstanceFingerprint")),
        "risk_policy_version": _text(risk_context.get("policyVersion")),
        "risk_policy_fingerprint": _text(risk_context.get("policyFingerprint")),
        "risk_allocation_fingerprint": _text(risk_context.get("allocationFingerprint")),
        "challenger_weight": float(_num(risk_weights.get(meta_decision_id)) or 0.0),
        "predicted_residual_alpha_pct": _num(decision.get("predictedResidualAlphaPct")),
        "residual_alpha_lower90_pct": _num(decision.get("residualAlphaLower90Pct")),
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
    row["record_hash"] = _record_hash(row)
    return row


def record_decisions(
    meta: dict[str, Any],
    ledger_path: Path,
    recorded_at: str | None = None,
    *,
    risk_context: dict[str, Any] | None = None,
) -> dict[str, int]:
    now = recorded_at or datetime.now(timezone.utc).isoformat()
    existing = _read_csv(ledger_path)
    by_id = {_text(row.get("decision_id")): row for row in existing if _text(row.get("decision_id"))}
    appended = 0
    conflicts = 0
    skipped = 0
    immutable_fields = [field for field in LEDGER_FIELDS if field != "recorded_at"]
    decisions = meta.get("decisions") if isinstance(meta.get("decisions"), list) else []
    if risk_context is not None and not risk_context.get("valid"):
        return {"appended": 0, "conflicts": 0, "skipped": len(decisions), "total": len(existing)}
    for decision in decisions:
        row = _ledger_row(decision, now, risk_context)
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
        challenger = [
            row for row in rows
            if _text(row.get("challenger_decision")).upper() == "TAKE"
            and float(_num(row.get("challenger_weight")) or 0.0) > 0
        ][:MAX_POSITIONS]
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
        challenger_return = sum(
            float(_num(row.get("challenger_weight")) or 0.0)
            * float(resolved[row["decision_id"]]["net_pnl_pct"])
            for row in challenger
        )
        champion_trades += len(champion)
        challenger_trades += len(challenger)
        daily.append({
            "signalDate": signal_date,
            "championReturnPct": round(champion_return, 6),
            "challengerReturnPct": round(challenger_return, 6),
            "upliftPct": round(challenger_return - champion_return, 6),
            "championTrades": len(champion),
            "challengerTrades": len(challenger),
            "challengerGrossExposurePct": round(
                100.0 * sum(float(_num(row.get("challenger_weight")) or 0.0) for row in challenger),
                6,
            ),
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


def _residual_model_gate(report: dict[str, Any]) -> dict[str, Any]:
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    policy = report.get("policy") if isinstance(report.get("policy"), dict) else {}
    version_matches = policy.get("version") == RESIDUAL_ALPHA_POLICY_VERSION
    return {
        "passed": validation.get("evidenceStatus") == "PASS" and version_matches,
        "evidenceStatus": validation.get("evidenceStatus") or "MISSING",
        "modelFingerprint": policy.get("fingerprint"),
        "policyVersion": policy.get("version"),
        "requiredPolicyVersion": RESIDUAL_ALPHA_POLICY_VERSION,
        "oosPredictions": validation.get("oosPredictions"),
        "oosSignalDates": validation.get("oosSignalDates"),
        "selectedBlockBootstrapCi95": validation.get("selectedBlockBootstrapCi95"),
        "blockingReasons": (
            validation.get("blockingReasons") or ["MISSING_RESIDUAL_ALPHA_MODEL_REPORT"]
        ) + ([] if version_matches else ["RESIDUAL_ALPHA_MODEL_VERSION_MISMATCH"]),
    }


def _active_policy_rows(
    rows: list[dict[str, Any]],
    meta: dict[str, Any],
    champion_fingerprint: str | None = None,
    risk_policy_fingerprint: str | None = None,
) -> list[dict[str, Any]]:
    meta_policy = meta.get("policy") if isinstance(meta.get("policy"), dict) else {}
    active_meta_fingerprint = _text(meta_policy.get("fingerprint"))
    active_champion_fingerprint = champion_fingerprint or _fingerprint(_policy())
    return [
        row for row in rows
        if _text(row.get("policy_fingerprint")) == active_champion_fingerprint
        and _text(row.get("meta_policy_fingerprint")) == active_meta_fingerprint
        and (
            risk_policy_fingerprint is None
            or _text(row.get("risk_policy_fingerprint")) == risk_policy_fingerprint
        )
    ]


def promotion_decision(
    comparison: dict[str, Any],
    alpha_gate: dict[str, Any],
    residual_model_gate: dict[str, Any],
    integrity: dict[str, Any],
    risk_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    challenger = comparison["challenger"]
    champion = comparison["champion"]
    uplift_ci = comparison["pairedUplift"].get("bootstrapCi95")
    blockers: list[str] = []
    if risk_gate is not None and not risk_gate.get("passed"):
        blockers.append("RISK_ALLOCATION_NOT_PROVEN")
    if integrity.get("immutableConflicts", 0) > 0:
        blockers.append("IMMUTABLE_DECISION_CONFLICT")
    if integrity.get("recordHashViolations", 0) > 0:
        blockers.append("CHAMPION_LEDGER_RECORD_HASH_VIOLATION")
    if integrity.get("timeIntegrityViolations", 0) > 0:
        blockers.append("TIME_INTEGRITY_VIOLATION")
    if integrity.get("fingerprintCoverage", 0.0) < 1.0:
        blockers.append("INCOMPLETE_POLICY_FINGERPRINT_COVERAGE")
    if integrity.get("riskLineageCoverage", 0.0) < 1.0:
        blockers.append("INCOMPLETE_RISK_LINEAGE_COVERAGE")
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
    if not residual_model_gate.get("passed"):
        blockers.append("RESIDUAL_ALPHA_MODEL_NOT_PROVEN")
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
    residual_path: Path = RESIDUAL_ALPHA_REPORT,
    risk_path: Path = RISK_BUDGET_REPORT,
    record: bool = True,
) -> dict[str, Any]:
    meta = _read_json(meta_path)
    risk_context = _risk_context(meta, _read_json(risk_path))
    record_status = record_decisions(meta, ledger_path, risk_context=risk_context) if record else {"appended": 0, "conflicts": 0, "skipped": 0, "total": len(_read_csv(ledger_path))}
    all_ledger_rows = _read_csv(ledger_path)
    active_fingerprint = _fingerprint(_policy())
    meta_policy = meta.get("policy") if isinstance(meta.get("policy"), dict) else {}
    active_meta_fingerprint = _text(meta_policy.get("fingerprint"))
    cohort_rows = _active_policy_rows(
        all_ledger_rows,
        meta,
        active_fingerprint,
        _text(risk_context.get("policyFingerprint")),
    ) if risk_context.get("valid") else []
    invalid_record_hashes = [
        _text(row.get("decision_id"))
        for row in cohort_rows
        if not _text(row.get("record_hash")) or _text(row.get("record_hash")) != _record_hash(row)
    ]
    ledger_rows = [
        row for row in cohort_rows
        if _text(row.get("record_hash")) and _text(row.get("record_hash")) == _record_hash(row)
    ]
    outcomes, violations = _latest_outcomes(journal_path, evaluations_path)
    comparison = compare(ledger_rows, outcomes)
    alpha_gate = _alpha_gate(_read_json(alpha_path))
    residual_model_gate = _residual_model_gate(_read_json(residual_path))
    fingerprinted = sum(1 for row in ledger_rows if _text(row.get("policy_fingerprint")))
    risk_lineage_rows = sum(
        1 for row in ledger_rows
        if _text(row.get("risk_policy_version")) == RISK_BUDGET_POLICY_VERSION
        and _text(row.get("risk_policy_fingerprint"))
        and _text(row.get("risk_allocation_fingerprint"))
        and _num(row.get("challenger_weight")) is not None
    )
    integrity = {
        "immutableConflicts": record_status["conflicts"],
        "timeIntegrityViolations": len(violations),
        "recordHashViolations": len(invalid_record_hashes),
        "invalidRecordIds": invalid_record_hashes[:20],
        "fingerprintCoverage": round(fingerprinted / len(ledger_rows), 6) if ledger_rows else 0.0,
        "riskLineageCoverage": round(risk_lineage_rows / len(ledger_rows), 6) if ledger_rows else 0.0,
        "violations": violations[:20],
    }
    risk_gate = {
        "passed": bool(risk_context.get("valid")),
        "policyVersion": risk_context.get("policyVersion"),
        "requiredPolicyVersion": RISK_BUDGET_POLICY_VERSION,
        "policyFingerprint": risk_context.get("policyFingerprint"),
        "allocationFingerprint": risk_context.get("allocationFingerprint"),
        "blockingReasons": risk_context.get("blockingReasons") or [],
    }
    promotion = promotion_decision(comparison, alpha_gate, residual_model_gate, integrity, risk_gate)
    return {
        "status": "SHADOW_ONLY",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {**_policy(), "fingerprint": _fingerprint(_policy())},
        "recording": record_status,
        "policyCohort": {
            "activeFingerprint": active_fingerprint,
            "activeMetaPolicyFingerprint": active_meta_fingerprint,
            "activeRiskPolicyFingerprint": risk_context.get("policyFingerprint"),
            "activeRows": len(cohort_rows),
            "validActiveRows": len(ledger_rows),
            "excludedPriorPolicyRows": len(all_ledger_rows) - len(cohort_rows),
        },
        "integrity": integrity,
        "alphaGate": alpha_gate,
        "residualAlphaModelGate": residual_model_gate,
        "riskAllocationGate": risk_gate,
        "comparison": comparison,
        "promotion": promotion,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", type=Path, default=META_GATE)
    parser.add_argument("--alpha", type=Path, default=ALPHA_REPORT)
    parser.add_argument("--residual-alpha", type=Path, default=RESIDUAL_ALPHA_REPORT)
    parser.add_argument("--risk-budget", type=Path, default=RISK_BUDGET_REPORT)
    parser.add_argument("--journal", type=Path, default=JOURNAL)
    parser.add_argument("--evaluations", type=Path, default=EVALUATIONS)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args()
    report = build(
        args.meta,
        args.alpha,
        args.journal,
        args.evaluations,
        args.ledger,
        residual_path=args.residual_alpha,
        risk_path=args.risk_budget,
        record=not args.no_record,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"recording": report["recording"], "promotion": report["promotion"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
