#!/usr/bin/env python3
"""Forward-only Champion–Challenger evidence for sealed self-correction candidates."""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.engine.self_correction_v2 import apply_correction_params  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


OHLCV = ROOT / "data" / "market" / "ohlcv"
REGISTRY = ROOT / "data" / "self_correction_candidate_registry.csv"
PREDICTIONS = ROOT / "data" / "self_correction_shadow_predictions.csv"
SETTLEMENTS = ROOT / "data" / "self_correction_shadow_settlements.csv"
OUT = ROOT / "reports" / "self_correction_shadow.json"
PROMOTION = ROOT / "reports" / "self_correction_promotion.json"

POLICY_VERSION = str(vtj.CALIBRATION_SHADOW_POLICY["version"])
INPUT_CONTRACT_VERSION = str(vtj.CALIBRATION_SHADOW_POLICY["inputContractVersion"])
MAX_POSITIONS = int(vtj.CALIBRATION_SHADOW_POLICY["maxPositions"])
POSITION_WEIGHT = float(vtj.CALIBRATION_SHADOW_POLICY["positionWeight"])
MIN_SCORE = float(vtj.CALIBRATION_SHADOW_POLICY["minScore"])
MIN_SIGNAL_DATES = vtj.CALIBRATION_PROMOTION_MIN_SIGNAL_DATES
MIN_CHALLENGER_TRADES = vtj.CALIBRATION_PROMOTION_MIN_TRADES
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260731
MAX_RECORDING_DELAY_HOURS = float(vtj.CALIBRATION_SHADOW_POLICY["maxRecordingDelayHours"])
BASE_MIN_RR = dict(vtj.CALIBRATION_SHADOW_POLICY["baseMinRiskReward"])
BASE_MAX_DISTANCE_TO_ENTRY_PCT = float(vtj.CALIBRATION_SHADOW_POLICY["baseMaxDistanceToEntryPct"])

REGISTRY_FIELDS = [
    "candidate_fingerprint", "approval_id", "approval_record_hash",
    "calibration_policy_version", "calibration_policy_fingerprint",
    "approved_evidence_fingerprint", "registered_at", "market", "mode", "horizon",
    "source_type", "reason", "before_params_json", "after_params_json", "delta_json",
    "record_hash",
]
PREDICTION_FIELDS = [
    "prediction_id", "candidate_fingerprint", "approval_id", "approval_record_hash",
    "calibration_policy_fingerprint", "shadow_policy_version", "shadow_policy_fingerprint",
    "recorded_at", "signal_date", "generated_at", "market", "mode", "horizon", "symbol", "name",
    "recommendation_source", "input_contract_version", "forward_seal_status", "ohlcv_last_date",
    "champion_eligible", "challenger_eligible", "champion_score", "challenger_score",
    "champion_entry", "champion_stop", "champion_target",
    "challenger_entry", "challenger_stop", "challenger_target",
    "champion_rr", "challenger_rr", "expected_value", "data_status",
    "score_components_json", "score_weights_json", "record_hash",
]
SETTLEMENT_FIELDS = [
    "settlement_id", "prediction_id", "candidate_fingerprint", "settled_at", "signal_date",
    "market", "mode", "horizon", "symbol", "champion_status", "challenger_status",
    "champion_outcome", "challenger_outcome", "champion_net_pnl_pct", "challenger_net_pnl_pct",
    "champion_exit_date", "challenger_exit_date", "record_hash",
]


def _policy() -> dict[str, Any]:
    return dict(vtj.CALIBRATION_SHADOW_POLICY)


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _policy_fingerprint() -> str:
    return vtj._calibration_shadow_policy_fingerprint()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        raw = (
            _text(value).replace(",", "").replace("%", "").replace("$", "")
            .replace("₩", "").replace("원", "")
        )
        return float(raw) if raw and raw.lower() not in {"nan", "none", "null", "-"} else None
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "t", "yes", "y"}


def _parse_time(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


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


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_recommendations() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_path in sorted(glob.glob(str(ROOT / "reports" / "mone_v36_final_recommendations_*.csv"))):
        path = Path(raw_path)
        for row in _read_csv(path):
            row["recommendationSource"] = path.name
            rows.append(row)
    return rows


def _canonical(field: str, value: Any) -> str:
    numeric = {
        "champion_score", "challenger_score", "champion_entry", "champion_stop", "champion_target",
        "challenger_entry", "challenger_stop", "challenger_target", "champion_rr", "challenger_rr",
        "expected_value", "champion_net_pnl_pct", "challenger_net_pnl_pct",
    }
    if field not in numeric:
        return _text(value)
    number = _num(value)
    return "" if number is None else format(0.0 if abs(number) < 1e-15 else number, ".12g")


def _row_hash(row: dict[str, Any], fields: list[str], excluded: set[str]) -> str:
    return _json_hash({field: _canonical(field, row.get(field)) for field in fields if field not in excluded})


def _registry_hash(row: dict[str, Any]) -> str:
    return _row_hash(row, REGISTRY_FIELDS, {"registered_at", "record_hash"})


def _prediction_hash(row: dict[str, Any]) -> str:
    return _row_hash(row, PREDICTION_FIELDS, {"recorded_at", "record_hash"})


def _settlement_hash(row: dict[str, Any]) -> str:
    return _row_hash(row, SETTLEMENT_FIELDS, {"settled_at", "record_hash"})


def _latest_ohlcv_date(ohlcv_dir: Path, market: str, symbol: str) -> str:
    rows = _read_csv(ohlcv_dir / f"{market}_{symbol}_daily.csv")
    return max((_text(row.get("date"))[:10] for row in rows if _text(row.get("date"))), default="")


def register_candidates(
    candidates: list[dict[str, Any]],
    registry_path: Path = REGISTRY,
    registered_at: str | None = None,
) -> dict[str, Any]:
    now = registered_at or datetime.now(timezone.utc).isoformat()
    rows = _read_csv(registry_path)
    by_id = {_text(row.get("candidate_fingerprint")): row for row in rows if _text(row.get("candidate_fingerprint"))}
    appended = conflicts = 0
    for candidate in candidates:
        fingerprint = _text(candidate.get("candidateFingerprint"))
        if not fingerprint:
            continue
        row = {
            "candidate_fingerprint": fingerprint,
            "approval_id": candidate.get("approvalId"),
            "approval_record_hash": candidate.get("approvalRecordHash"),
            "calibration_policy_version": candidate.get("calibrationPolicyVersion"),
            "calibration_policy_fingerprint": candidate.get("calibrationPolicyFingerprint"),
            "approved_evidence_fingerprint": candidate.get("approvedEvidenceFingerprint"),
            "registered_at": now,
            "market": candidate.get("market"),
            "mode": candidate.get("mode"),
            "horizon": candidate.get("horizon"),
            "source_type": candidate.get("sourceType"),
            "reason": candidate.get("reason"),
            "before_params_json": json.dumps(candidate.get("before") or {}, ensure_ascii=True, sort_keys=True),
            "after_params_json": json.dumps(candidate.get("after") or {}, ensure_ascii=True, sort_keys=True),
            "delta_json": json.dumps(candidate.get("delta") or {}, ensure_ascii=True, sort_keys=True),
        }
        row["record_hash"] = _registry_hash(row)
        previous = by_id.get(fingerprint)
        if previous is None:
            rows.append(row)
            by_id[fingerprint] = row
            appended += 1
        elif _registry_hash(previous) != _registry_hash(row) or _text(previous.get("record_hash")) != _registry_hash(previous):
            conflicts += 1
    if appended:
        _write_csv(registry_path, rows, REGISTRY_FIELDS)
    return {"appended": appended, "conflicts": conflicts, "total": len(rows)}


def _load_json_field(row: dict[str, Any], field: str) -> dict[str, Any]:
    try:
        value = json.loads(_text(row.get(field)))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _weighted_score(raw_score: float, raw: dict[str, Any], adjusted: dict[str, Any], weights: dict[str, Any]) -> float:
    delta = sum(
        (float(_num(adjusted.get(key)) or 0.0) - float(_num(raw.get(key)) or 0.0))
        * float(_num(weight) or 0.0)
        for key, weight in weights.items()
        if key != "newsRiskPenalty" and key in raw and key in adjusted
    )
    return round(max(0.0, min(100.0, raw_score + delta)), 6)


def _eligible(
    row: dict[str, Any],
    score: float,
    rr: float | None,
    min_rr: float,
    entry: float | None,
    max_distance_to_entry_pct: float,
) -> bool:
    current = _num(row.get("currentPrice") or row.get("current_price"))
    distance = abs(entry - current) / current * 100.0 if entry is not None and current and current > 0 else None
    return (
        _text(row.get("dataStatus") or row.get("data_status")).upper() in {"NORMAL", "OK"}
        and (_num(row.get("expectedValue") or row.get("expected_value")) or 0.0) > 0
        and rr is not None and rr >= min_rr
        and score >= MIN_SCORE
        and distance is not None and distance <= max_distance_to_entry_pct
    )


def record_predictions(
    candidates: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    prediction_path: Path = PREDICTIONS,
    ohlcv_dir: Path = OHLCV,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    now = recorded_at or datetime.now(timezone.utc).isoformat()
    now_dt = _parse_time(now) or datetime.now(timezone.utc)
    existing = _read_csv(prediction_path)
    by_id = {_text(row.get("prediction_id")): row for row in existing if _text(row.get("prediction_id"))}
    appended = conflicts = skipped_contract = skipped_forward = 0
    for candidate in candidates:
        after = candidate.get("after") if isinstance(candidate.get("after"), dict) else {}
        fingerprint = _text(candidate.get("candidateFingerprint"))
        for raw_row in recommendations:
            market = _text(raw_row.get("market")).lower()
            mode = _text(raw_row.get("mode")).lower()
            horizon = _text(raw_row.get("horizon")).lower()
            if (market, mode, horizon) != (
                _text(candidate.get("market")), _text(candidate.get("mode")), _text(candidate.get("horizon")),
            ):
                continue
            if _text(raw_row.get("correctionInputContractVersion")) != INPUT_CONTRACT_VERSION:
                skipped_contract += 1
                continue
            generated_at = _text(raw_row.get("generatedAt") or raw_row.get("generated_at"))
            generated_dt = _parse_time(generated_at)
            recording_delay_hours = (
                (now_dt - generated_dt).total_seconds() / 3600.0 if generated_dt is not None else None
            )
            signal_date = _text(raw_row.get("asOfDate") or raw_row.get("as_of_date"))[:10] or generated_at[:10]
            symbol = _text(raw_row.get("symbol")).upper()
            latest_bar = _latest_ohlcv_date(ohlcv_dir, market, symbol)
            if (
                not signal_date or not symbol or latest_bar != signal_date
                or recording_delay_hours is None or recording_delay_hours < 0
                or recording_delay_hours > MAX_RECORDING_DELAY_HOURS
            ):
                skipped_forward += 1
                continue
            raw_entry = _num(raw_row.get("rawEntry"))
            raw_stop = _num(raw_row.get("rawStop"))
            raw_target = _num(raw_row.get("rawTarget"))
            raw_score = _num(raw_row.get("rawModelScore"))
            components = _load_json_field(raw_row, "scoreComponentsJson")
            weights = _load_json_field(raw_row, "scoreWeightsJson")
            if (
                raw_entry is None or raw_stop is None or raw_target is None or raw_score is None
                or not raw_target > raw_entry > raw_stop or not components or not weights
            ):
                skipped_contract += 1
                continue
            correction = apply_correction_params(
                {key: float(value) for key, value in components.items() if _num(value) is not None},
                raw_entry, raw_target, raw_stop, market, after,
                strength=1.0, enforce_evidence_gate=True,
            )
            if not correction.get("correctionApplied"):
                skipped_contract += 1
                continue
            champion_entry = _num(raw_row.get("entry") or raw_row.get("entryPrice"))
            champion_stop = _num(raw_row.get("stop") or raw_row.get("stopPrice"))
            champion_target = _num(raw_row.get("target") or raw_row.get("targetPrice"))
            champion_score = _num(raw_row.get("finalRankScore") or raw_row.get("finalScore"))
            if None in {champion_entry, champion_stop, champion_target, champion_score}:
                skipped_contract += 1
                continue
            challenger_score = _weighted_score(raw_score, components, correction["adjustedScores"], weights)
            champion_rr = (
                (champion_target - champion_entry) / (champion_entry - champion_stop)
                if champion_entry > champion_stop else None
            )
            challenger_rr = _num(correction.get("adjustedRrActual"))
            rr_adjustment = float(_num((after.get("filterAdjustments") or {}).get("minRiskRewardRatio")) or 0.0)
            distance_adjustment = float(_num((after.get("filterAdjustments") or {}).get("maxDistanceToEntryPct")) or 0.0)
            base_min_rr = BASE_MIN_RR.get(horizon, 1.8)
            prediction_id = hashlib.sha256(
                f"{fingerprint}|{signal_date}|{market}|{mode}|{horizon}|{symbol}".encode("utf-8")
            ).hexdigest()[:24]
            row = {
                "prediction_id": prediction_id,
                "candidate_fingerprint": fingerprint,
                "approval_id": candidate.get("approvalId"),
                "approval_record_hash": candidate.get("approvalRecordHash"),
                "calibration_policy_fingerprint": candidate.get("calibrationPolicyFingerprint"),
                "shadow_policy_version": POLICY_VERSION,
                "shadow_policy_fingerprint": _policy_fingerprint(),
                "recorded_at": now,
                "signal_date": signal_date,
                "generated_at": generated_at,
                "market": market,
                "mode": mode,
                "horizon": horizon,
                "symbol": symbol,
                "name": raw_row.get("name"),
                "recommendation_source": raw_row.get("recommendationSource"),
                "input_contract_version": INPUT_CONTRACT_VERSION,
                "forward_seal_status": "SEALED_FORWARD",
                "ohlcv_last_date": latest_bar,
                "champion_eligible": _eligible(
                    raw_row, float(champion_score), champion_rr, base_min_rr,
                    champion_entry, BASE_MAX_DISTANCE_TO_ENTRY_PCT,
                ),
                "challenger_eligible": _eligible(
                    raw_row, challenger_score, challenger_rr, base_min_rr + rr_adjustment,
                    _num(correction.get("adjustedEntry")),
                    BASE_MAX_DISTANCE_TO_ENTRY_PCT + distance_adjustment,
                ),
                "champion_score": champion_score,
                "challenger_score": challenger_score,
                "champion_entry": champion_entry,
                "champion_stop": champion_stop,
                "champion_target": champion_target,
                "challenger_entry": correction.get("adjustedEntry"),
                "challenger_stop": correction.get("adjustedStop"),
                "challenger_target": correction.get("adjustedTarget"),
                "champion_rr": champion_rr,
                "challenger_rr": challenger_rr,
                "expected_value": _num(raw_row.get("expectedValue") or raw_row.get("expected_value")),
                "data_status": raw_row.get("dataStatus") or raw_row.get("data_status"),
                "score_components_json": json.dumps(components, ensure_ascii=True, sort_keys=True),
                "score_weights_json": json.dumps(weights, ensure_ascii=True, sort_keys=True),
            }
            row["record_hash"] = _prediction_hash(row)
            previous = by_id.get(prediction_id)
            if previous is None:
                existing.append(row)
                by_id[prediction_id] = row
                appended += 1
            elif _text(previous.get("record_hash")) != _prediction_hash(previous) or _prediction_hash(previous) != _prediction_hash(row):
                conflicts += 1
    if appended:
        _write_csv(prediction_path, existing, PREDICTION_FIELDS)
    return {
        "appended": appended, "conflicts": conflicts, "total": len(existing),
        "skippedInputContract": skipped_contract, "skippedForwardSeal": skipped_forward,
    }


def _arm_evaluation(prediction: dict[str, Any], arm: str) -> dict[str, Any]:
    return vtj._evaluate_one({
        "journal_id": f"{prediction.get('prediction_id')}:{arm}",
        "market": prediction.get("market"),
        "mode": prediction.get("mode"),
        "horizon": prediction.get("horizon"),
        "symbol": prediction.get("symbol"),
        "as_of_date": prediction.get("signal_date"),
        "entry_price": prediction.get(f"{arm}_entry"),
        "stop_price": prediction.get(f"{arm}_stop"),
        "target_price": prediction.get(f"{arm}_target"),
        "entry_type": "LIMIT_TOUCH",
        "data_confidence": "HIGH",
    })


def _resolved(evaluation: dict[str, Any]) -> tuple[bool, float | None]:
    status = _text(evaluation.get("status")).upper()
    outcome = _text(evaluation.get("outcome")).upper()
    if status == "EVALUATED" and _num(evaluation.get("net_pnl_pct")) is not None:
        return True, _num(evaluation.get("net_pnl_pct"))
    if status == "CANCELLED" and outcome == "CANCELLED_NOT_FILLED":
        return True, 0.0
    return False, None


def settle_predictions(
    prediction_path: Path = PREDICTIONS,
    settlement_path: Path = SETTLEMENTS,
    settled_at: str | None = None,
) -> dict[str, Any]:
    now = settled_at or datetime.now(timezone.utc).isoformat()
    predictions = _read_csv(prediction_path)
    settlements = _read_csv(settlement_path)
    settled_ids = {_text(row.get("prediction_id")) for row in settlements}
    appended = pending = invalid_predictions = 0
    for prediction in predictions:
        prediction_id = _text(prediction.get("prediction_id"))
        if not prediction_id or prediction_id in settled_ids:
            continue
        if _text(prediction.get("record_hash")) != _prediction_hash(prediction):
            invalid_predictions += 1
            continue
        champion = _arm_evaluation(prediction, "champion")
        challenger = _arm_evaluation(prediction, "challenger")
        champion_done, champion_pnl = _resolved(champion)
        challenger_done, challenger_pnl = _resolved(challenger)
        if not champion_done or not challenger_done:
            pending += 1
            continue
        row = {
            "settlement_id": hashlib.sha256(f"{prediction_id}|paired".encode("utf-8")).hexdigest()[:24],
            "prediction_id": prediction_id,
            "candidate_fingerprint": prediction.get("candidate_fingerprint"),
            "settled_at": now,
            "signal_date": prediction.get("signal_date"),
            "market": prediction.get("market"),
            "mode": prediction.get("mode"),
            "horizon": prediction.get("horizon"),
            "symbol": prediction.get("symbol"),
            "champion_status": champion.get("status"),
            "challenger_status": challenger.get("status"),
            "champion_outcome": champion.get("outcome"),
            "challenger_outcome": challenger.get("outcome"),
            "champion_net_pnl_pct": champion_pnl,
            "challenger_net_pnl_pct": challenger_pnl,
            "champion_exit_date": champion.get("exit_date"),
            "challenger_exit_date": challenger.get("exit_date"),
        }
        row["record_hash"] = _settlement_hash(row)
        settlements.append(row)
        settled_ids.add(prediction_id)
        appended += 1
    if appended:
        _write_csv(settlement_path, settlements, SETTLEMENT_FIELDS)
    return {"appended": appended, "pending": pending, "invalidPredictions": invalid_predictions, "total": len(settlements)}


def _max_drawdown(returns_pct: list[float]) -> float:
    nav = peak = 1.0
    max_dd = 0.0
    for value in returns_pct:
        nav *= 1.0 + value / 100.0
        peak = max(peak, nav)
        max_dd = max(max_dd, (peak - nav) / peak * 100.0 if peak else 0.0)
    return round(max_dd, 6)


def _arm_stats(returns_pct: list[float], trades: int) -> dict[str, Any]:
    gains = sum(value for value in returns_pct if value > 0)
    losses = abs(sum(value for value in returns_pct if value < 0))
    nav = 1.0
    for value in returns_pct:
        nav *= 1.0 + value / 100.0
    return {
        "completeSignalDates": len(returns_pct),
        "selectedEvaluatedTrades": trades,
        "avgDailyReturnPct": round(sum(returns_pct) / len(returns_pct), 6) if returns_pct else None,
        "totalReturnPct": round((nav - 1.0) * 100.0, 6) if returns_pct else None,
        "profitFactor": round(gains / losses, 6) if losses > 0 else (999.0 if gains > 0 else None),
        "maxDrawdownPct": _max_drawdown(returns_pct) if returns_pct else None,
    }


def _bootstrap_ci(values: list[float]) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means = [sum(values[rng.randrange(len(values))] for _ in values) / len(values) for _ in range(BOOTSTRAP_SAMPLES)]
    means.sort()
    return [
        round(means[int(0.025 * (len(means) - 1))], 6),
        round(means[int(0.975 * (len(means) - 1))], 6),
    ]


def compare_candidate(
    candidate_fingerprint: str,
    predictions: list[dict[str, Any]],
    settlements: list[dict[str, Any]],
) -> dict[str, Any]:
    cohort = [row for row in predictions if _text(row.get("candidate_fingerprint")) == candidate_fingerprint]
    settlement_by_prediction = {
        _text(row.get("prediction_id")): row for row in settlements
        if _text(row.get("candidate_fingerprint")) == candidate_fingerprint
        and _text(row.get("record_hash")) == _settlement_hash(row)
    }
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cohort:
        by_date[_text(row.get("signal_date"))[:10]].append(row)
    daily: list[dict[str, Any]] = []
    incomplete = champion_trades = challenger_trades = 0
    for signal_date in sorted(date for date in by_date if date):
        rows = by_date[signal_date]
        champion = sorted(
            (row for row in rows if _bool(row.get("champion_eligible"))),
            key=lambda row: float(_num(row.get("champion_score")) or -1e9), reverse=True,
        )[:MAX_POSITIONS]
        challenger = sorted(
            (row for row in rows if _bool(row.get("challenger_eligible"))),
            key=lambda row: float(_num(row.get("challenger_score")) or -1e9), reverse=True,
        )[:MAX_POSITIONS]
        required = {_text(row.get("prediction_id")) for row in champion + challenger}
        if any(prediction_id not in settlement_by_prediction for prediction_id in required):
            incomplete += 1
            continue
        champion_return = POSITION_WEIGHT * sum(
            float(_num(settlement_by_prediction[_text(row.get("prediction_id"))].get("champion_net_pnl_pct")) or 0.0)
            for row in champion
        )
        challenger_return = POSITION_WEIGHT * sum(
            float(_num(settlement_by_prediction[_text(row.get("prediction_id"))].get("challenger_net_pnl_pct")) or 0.0)
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
        })
    champion_returns = [row["championReturnPct"] for row in daily]
    challenger_returns = [row["challengerReturnPct"] for row in daily]
    uplifts = [row["upliftPct"] for row in daily]
    return {
        "completedSignalDates": len(daily),
        "incompleteSignalDates": incomplete,
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


def _integrity(
    registry_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    settlement_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    registry_by_candidate = {
        _text(row.get("candidate_fingerprint")): row for row in registry_rows
        if _text(row.get("candidate_fingerprint"))
    }
    prediction_by_id = {
        _text(row.get("prediction_id")): row for row in prediction_rows
        if _text(row.get("prediction_id"))
    }
    registry_ids = [_text(row.get("candidate_fingerprint")) for row in registry_rows]
    prediction_ids = [_text(row.get("prediction_id")) for row in prediction_rows]
    settlement_ids = [_text(row.get("settlement_id")) for row in settlement_rows]
    lineage_violations = 0
    recording_time_violations = 0
    for row in prediction_rows:
        registry = registry_by_candidate.get(_text(row.get("candidate_fingerprint")))
        if (
            registry is None
            or _text(row.get("approval_id")) != _text(registry.get("approval_id"))
            or _text(row.get("approval_record_hash")) != _text(registry.get("approval_record_hash"))
            or _text(row.get("calibration_policy_fingerprint")) != _text(registry.get("calibration_policy_fingerprint"))
            or _text(row.get("shadow_policy_version")) != POLICY_VERSION
            or _text(row.get("shadow_policy_fingerprint")) != _policy_fingerprint()
        ):
            lineage_violations += 1
        generated = _parse_time(row.get("generated_at"))
        recorded = _parse_time(row.get("recorded_at"))
        delay = (recorded - generated).total_seconds() / 3600.0 if generated and recorded else None
        if (
            delay is None or delay < 0 or delay > MAX_RECORDING_DELAY_HOURS
            or _text(row.get("signal_date"))[:10] != _text(row.get("ohlcv_last_date"))[:10]
        ):
            recording_time_violations += 1
    relationship_violations = sum(
        1 for row in settlement_rows
        if _text(row.get("prediction_id")) not in prediction_by_id
        or _text(row.get("candidate_fingerprint"))
        != _text((prediction_by_id.get(_text(row.get("prediction_id"))) or {}).get("candidate_fingerprint"))
    )
    return {
        "registryHashViolations": sum(1 for row in registry_rows if _text(row.get("record_hash")) != _registry_hash(row)),
        "predictionHashViolations": sum(1 for row in prediction_rows if _text(row.get("record_hash")) != _prediction_hash(row)),
        "settlementHashViolations": sum(1 for row in settlement_rows if _text(row.get("record_hash")) != _settlement_hash(row)),
        "registryDuplicateIds": len(registry_ids) - len(set(registry_ids)),
        "predictionDuplicateIds": len(prediction_ids) - len(set(prediction_ids)),
        "settlementDuplicateIds": len(settlement_ids) - len(set(settlement_ids)),
        "predictionLineageViolations": lineage_violations,
        "predictionRecordingTimeViolations": recording_time_violations,
        "predictionSettlementRelationshipViolations": relationship_violations,
        "forwardSealViolations": sum(1 for row in prediction_rows if _text(row.get("forward_seal_status")) != "SEALED_FORWARD"),
        "inputContractViolations": sum(1 for row in prediction_rows if _text(row.get("input_contract_version")) != INPUT_CONTRACT_VERSION),
    }


def _promotion(candidate: dict[str, Any], comparison: dict[str, Any], integrity: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    challenger = comparison["challenger"]
    champion = comparison["champion"]
    uplift_ci = comparison["pairedUplift"].get("bootstrapCi95")
    blockers: list[str] = []
    if any(int(value or 0) > 0 for value in integrity.values()):
        blockers.append("SHADOW_INTEGRITY_VIOLATION")
    if comparison.get("completedSignalDates", 0) < MIN_SIGNAL_DATES:
        blockers.append("LOW_PROMOTION_SIGNAL_DATES")
    if challenger.get("selectedEvaluatedTrades", 0) < MIN_CHALLENGER_TRADES:
        blockers.append("LOW_PROMOTION_TRADES")
    if challenger.get("avgDailyReturnPct") is None or challenger["avgDailyReturnPct"] <= 0:
        blockers.append("NON_POSITIVE_PROMOTION_RETURN")
    if not uplift_ci or float(uplift_ci[0]) <= 0:
        blockers.append("PROMOTION_UPLIFT_NOT_PROVEN")
    if challenger.get("maxDrawdownPct") is None or champion.get("maxDrawdownPct") is None:
        blockers.append("DRAWDOWN_COMPARISON_NOT_READY")
    elif challenger["maxDrawdownPct"] > champion["maxDrawdownPct"]:
        blockers.append("PROMOTION_DRAWDOWN_WORSE")
    decision = {
        "promotionEligible": not blockers,
        "decision": "READY_FOR_HUMAN_REVIEW" if not blockers else "KEEP_CHALLENGER_SHADOW",
        "blockingReasons": blockers,
        "autoPromotionAllowed": False,
        "humanApprovalRequired": True,
    }
    if blockers:
        return decision, None
    certificate = {
        "version": vtj.CALIBRATION_PROMOTION_VERSION,
        "approvalId": candidate.get("approvalId"),
        "approvalRecordHash": candidate.get("approvalRecordHash"),
        "evidenceFingerprint": candidate.get("approvedEvidenceFingerprint"),
        "calibrationPolicyFingerprint": candidate.get("calibrationPolicyFingerprint"),
        "candidateFingerprint": candidate.get("candidateFingerprint"),
        "shadowPolicyVersion": POLICY_VERSION,
        "shadowPolicyFingerprint": _policy_fingerprint(),
        "promotionEligible": True,
        "decision": "READY_FOR_HUMAN_REVIEW",
        "completedSignalDates": comparison.get("completedSignalDates"),
        "evaluatedChallengerTrades": challenger.get("selectedEvaluatedTrades"),
        "avgAfterCostReturnPct": challenger.get("avgDailyReturnPct"),
        "pairedUpliftCi95": uplift_ci,
        "championMaxDrawdownPct": champion.get("maxDrawdownPct"),
        "challengerMaxDrawdownPct": challenger.get("maxDrawdownPct"),
    }
    certificate["recordHash"] = vtj._promotion_certificate_hash(certificate)
    return decision, certificate


def build(
    registry_path: Path = REGISTRY,
    prediction_path: Path = PREDICTIONS,
    settlement_path: Path = SETTLEMENTS,
    output_path: Path = OUT,
    promotion_path: Path = PROMOTION,
    *,
    record: bool = True,
    settle: bool = True,
) -> dict[str, Any]:
    candidate_status = vtj.calibration_shadow_candidates()
    candidates = candidate_status.get("items") if isinstance(candidate_status.get("items"), list) else []
    readiness = candidate_status.get("readiness") if isinstance(candidate_status.get("readiness"), dict) else {}
    registry_status = register_candidates(candidates, registry_path) if record else {"appended": 0, "conflicts": 0, "total": len(_read_csv(registry_path))}
    prediction_status = record_predictions(candidates, _read_recommendations(), prediction_path) if record else {"appended": 0, "conflicts": 0, "total": len(_read_csv(prediction_path))}
    settlement_status = settle_predictions(prediction_path, settlement_path) if settle else {"appended": 0, "pending": 0, "total": len(_read_csv(settlement_path))}
    registry_rows = _read_csv(registry_path)
    prediction_rows = _read_csv(prediction_path)
    settlement_rows = _read_csv(settlement_path)
    active_fingerprints = {_text(candidate.get("candidateFingerprint")) for candidate in candidates}
    active_registry = [row for row in registry_rows if _text(row.get("candidate_fingerprint")) in active_fingerprints]
    active_predictions = [row for row in prediction_rows if _text(row.get("candidate_fingerprint")) in active_fingerprints]
    active_settlements = [row for row in settlement_rows if _text(row.get("candidate_fingerprint")) in active_fingerprints]
    integrity = _integrity(active_registry, active_predictions, active_settlements)
    integrity["candidateRegistryImmutableConflicts"] = int(registry_status.get("conflicts") or 0)
    integrity["predictionImmutableConflicts"] = int(prediction_status.get("conflicts") or 0)
    results: list[dict[str, Any]] = []
    certificates: list[dict[str, Any]] = []
    for candidate in candidates:
        fingerprint = _text(candidate.get("candidateFingerprint"))
        comparison = compare_candidate(fingerprint, active_predictions, active_settlements)
        decision, certificate = _promotion(candidate, comparison, integrity)
        if certificate is not None:
            certificates.append(certificate)
        results.append({
            "approvalId": candidate.get("approvalId"),
            "candidateFingerprint": fingerprint,
            "market": candidate.get("market"),
            "mode": candidate.get("mode"),
            "horizon": candidate.get("horizon"),
            "reason": candidate.get("reason"),
            "comparison": comparison,
            "promotion": decision,
        })
    payload = {
        "status": "SHADOW_ONLY",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {**_policy(), "fingerprint": _policy_fingerprint()},
        "calibrationPolicy": {
            "version": candidate_status.get("policyVersion"),
            "fingerprint": candidate_status.get("policyFingerprint"),
        },
        "summary": {
            "activeCandidates": len(candidates),
            "registeredCandidates": len(active_registry),
            "sealedPredictions": len(active_predictions),
            "settledPredictions": len(active_settlements),
            "promotionEligible": len(certificates),
            "readyForReview": int(readiness.get("readyForReview") or 0),
            "eligibleSuggestions": int(readiness.get("eligibleSuggestions") or 0),
            "abstain": not certificates,
        },
        "integrity": integrity,
        "registryRun": registry_status,
        "predictionRun": prediction_status,
        "settlementRun": settlement_status,
        "candidateGate": candidate_status,
        "candidates": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    promotion_path.parent.mkdir(parents=True, exist_ok=True)
    promotion_path.write_text(json.dumps({
        "status": "SHADOW_ONLY",
        "generatedAt": payload["generatedAt"],
        "shadowPolicyVersion": POLICY_VERSION,
        "shadowPolicyFingerprint": _policy_fingerprint(),
        "certificates": certificates,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--no-settle", action="store_true")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--promotion-output", type=Path, default=PROMOTION)
    args = parser.parse_args()
    payload = build(
        output_path=args.output,
        promotion_path=args.promotion_output,
        record=not args.no_record,
        settle=not args.no_settle,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
