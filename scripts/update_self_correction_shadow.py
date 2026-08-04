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
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


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
RESIDUAL_ALPHA_REPORT = ROOT / "reports" / "shadow_residual_alpha.json"
RESIDUAL_ALPHA_POLICY_VERSION = "shadow-residual-alpha-v1.1.2"

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
INITIAL_RECORDING_GRACE_DAYS = float(vtj.CALIBRATION_SHADOW_POLICY["initialRecordingGraceCalendarDays"])
MAX_PREDICTION_SILENCE_DAYS = float(vtj.CALIBRATION_SHADOW_POLICY["maxPredictionSilenceCalendarDays"])
BASE_MIN_RR = dict(vtj.CALIBRATION_SHADOW_POLICY["baseMinRiskReward"])
BASE_MAX_DISTANCE_TO_ENTRY_PCT = float(vtj.CALIBRATION_SHADOW_POLICY["baseMaxDistanceToEntryPct"])
MIN_PAYOFF_RATIO = float(vtj.CALIBRATION_SHADOW_POLICY["minPayoffRatio"])
MAX_PAYOFF_RELATIVE_DEGRADATION = float(
    vtj.CALIBRATION_SHADOW_POLICY["maxPayoffRelativeDegradationVsChampion"]
)

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
    "evaluation_policy_version", "evaluation_policy_fingerprint",
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


def _forward_seal_window(signal_date: str, market: str) -> tuple[datetime, datetime] | None:
    """Return canonical close and a conservative next-session open in UTC."""
    try:
        signal_day = date.fromisoformat(_text(signal_date)[:10])
    except ValueError:
        return None
    if signal_day.weekday() >= 5:
        return None
    normalized = _text(market).lower()
    if normalized == "kr":
        market_tz = ZoneInfo("Asia/Seoul")
        close_clock = time(15, 30)
        open_clock = time(9, 0)
    elif normalized == "us":
        market_tz = ZoneInfo("America/New_York")
        close_clock = time(16, 0)
        open_clock = time(9, 30)
    else:
        return None
    next_day = signal_day + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    signal_close = datetime.combine(signal_day, close_clock, tzinfo=market_tz).astimezone(timezone.utc)
    next_open = datetime.combine(next_day, open_clock, tzinfo=market_tz).astimezone(timezone.utc)
    return signal_close, next_open


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


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
    record_market: str = "all",
) -> dict[str, Any]:
    now = recorded_at or datetime.now(timezone.utc).isoformat()
    now_dt = _parse_time(now) or datetime.now(timezone.utc)
    existing = _read_csv(prediction_path)
    by_id = {_text(row.get("prediction_id")): row for row in existing if _text(row.get("prediction_id"))}
    appended = conflicts = skipped_contract = skipped_forward = 0
    skipped_before_close = skipped_after_open = 0
    diagnostics: list[dict[str, Any]] = []
    for candidate in candidates:
        if record_market in {"kr", "us"} and _text(candidate.get("market")).lower() != record_market:
            continue
        after = candidate.get("after") if isinstance(candidate.get("after"), dict) else {}
        fingerprint = _text(candidate.get("candidateFingerprint"))
        diagnostic = {
            "candidateFingerprint": fingerprint,
            "runAt": now,
            "market": candidate.get("market"),
            "mode": candidate.get("mode"),
            "horizon": candidate.get("horizon"),
            "matchedRecommendations": 0,
            "sealedOrConfirmed": 0,
            "appended": 0,
            "alreadySealed": 0,
            "skippedInputContract": 0,
            "skippedForwardSeal": 0,
            "skippedBeforeSignalClose": 0,
            "skippedAfterNextSessionOpen": 0,
            "conflicts": 0,
        }
        for raw_row in recommendations:
            market = _text(raw_row.get("market")).lower()
            mode = _text(raw_row.get("mode")).lower()
            horizon = _text(raw_row.get("horizon")).lower()
            if (market, mode, horizon) != (
                _text(candidate.get("market")), _text(candidate.get("mode")), _text(candidate.get("horizon")),
            ):
                continue
            diagnostic["matchedRecommendations"] += 1
            if _text(raw_row.get("correctionInputContractVersion")) != INPUT_CONTRACT_VERSION:
                skipped_contract += 1
                diagnostic["skippedInputContract"] += 1
                continue
            generated_at = _text(raw_row.get("generatedAt") or raw_row.get("generated_at"))
            generated_dt = _parse_time(generated_at)
            recording_delay_hours = (
                (now_dt - generated_dt).total_seconds() / 3600.0 if generated_dt is not None else None
            )
            signal_date = _text(raw_row.get("asOfDate") or raw_row.get("as_of_date"))[:10] or generated_at[:10]
            symbol = _text(raw_row.get("symbol")).upper()
            latest_bar = _latest_ohlcv_date(ohlcv_dir, market, symbol)
            seal_window = _forward_seal_window(signal_date, market)
            if (
                not signal_date or not symbol or latest_bar != signal_date
                or recording_delay_hours is None or recording_delay_hours < 0
                or recording_delay_hours > MAX_RECORDING_DELAY_HOURS
                or seal_window is None
            ):
                skipped_forward += 1
                diagnostic["skippedForwardSeal"] += 1
                continue
            signal_close, next_session_open = seal_window
            if generated_dt < signal_close or now_dt < signal_close:
                skipped_forward += 1
                skipped_before_close += 1
                diagnostic["skippedForwardSeal"] += 1
                diagnostic["skippedBeforeSignalClose"] += 1
                continue
            if generated_dt >= next_session_open or now_dt >= next_session_open:
                skipped_forward += 1
                skipped_after_open += 1
                diagnostic["skippedForwardSeal"] += 1
                diagnostic["skippedAfterNextSessionOpen"] += 1
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
                diagnostic["skippedInputContract"] += 1
                continue
            correction = apply_correction_params(
                {key: float(value) for key, value in components.items() if _num(value) is not None},
                raw_entry, raw_target, raw_stop, market, after,
                strength=1.0, enforce_evidence_gate=True,
            )
            if not correction.get("correctionApplied"):
                skipped_contract += 1
                diagnostic["skippedInputContract"] += 1
                continue
            champion_entry = _num(raw_row.get("entry") or raw_row.get("entryPrice"))
            champion_stop = _num(raw_row.get("stop") or raw_row.get("stopPrice"))
            champion_target = _num(raw_row.get("target") or raw_row.get("targetPrice"))
            champion_score = _num(raw_row.get("finalRankScore") or raw_row.get("finalScore"))
            if None in {champion_entry, champion_stop, champion_target, champion_score}:
                skipped_contract += 1
                diagnostic["skippedInputContract"] += 1
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
                diagnostic["appended"] += 1
                diagnostic["sealedOrConfirmed"] += 1
            elif _text(previous.get("record_hash")) == _prediction_hash(previous) and _prediction_hash(previous) == _prediction_hash(row):
                diagnostic["alreadySealed"] += 1
                diagnostic["sealedOrConfirmed"] += 1
            elif _text(previous.get("record_hash")) != _prediction_hash(previous) or _prediction_hash(previous) != _prediction_hash(row):
                conflicts += 1
                diagnostic["conflicts"] += 1
        diagnostics.append(diagnostic)
    if appended:
        _write_csv(prediction_path, existing, PREDICTION_FIELDS)
    return {
        "appended": appended, "conflicts": conflicts, "total": len(existing),
        "recordMarket": record_market,
        "skippedInputContract": skipped_contract, "skippedForwardSeal": skipped_forward,
        "skippedBeforeSignalClose": skipped_before_close,
        "skippedAfterNextSessionOpen": skipped_after_open,
        "runAt": now,
        "candidateDiagnostics": diagnostics,
    }


def _days_since(now: datetime, value: Any) -> float | None:
    timestamp = _parse_time(value)
    if timestamp is None:
        return None
    return max(0.0, (now - timestamp).total_seconds() / 86400.0)


def candidate_recording_health(
    candidate: dict[str, Any],
    registry_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    settlement_rows: list[dict[str, Any]],
    last_recording_run: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Diagnose a stalled Forward experiment without creating/backfilling evidence."""
    now_dt = now or datetime.now(timezone.utc)
    fingerprint = _text(candidate.get("candidateFingerprint"))
    registry = next((
        row for row in registry_rows
        if _text(row.get("candidate_fingerprint")) == fingerprint
    ), None)
    predictions = [
        row for row in prediction_rows
        if _text(row.get("candidate_fingerprint")) == fingerprint
    ]
    settlements = [
        row for row in settlement_rows
        if _text(row.get("candidate_fingerprint")) == fingerprint
    ]
    diagnostics = (
        last_recording_run.get("candidateDiagnostics")
        if isinstance(last_recording_run, dict) and isinstance(last_recording_run.get("candidateDiagnostics"), list)
        else []
    )
    diagnostic = next((
        row for row in diagnostics
        if isinstance(row, dict) and _text(row.get("candidateFingerprint")) == fingerprint
    ), {})
    registered_at = _text((registry or {}).get("registered_at"))
    last_prediction = max(
        (_text(row.get("recorded_at")) for row in predictions if _text(row.get("recorded_at"))),
        default="",
    )
    last_settlement = max(
        (_text(row.get("settled_at")) for row in settlements if _text(row.get("settled_at"))),
        default="",
    )
    age_days = _days_since(now_dt, registered_at)
    silence_days = _days_since(now_dt, last_prediction or registered_at)
    attempt_reason = "NO_RECORDING_RUN"
    matched = int(diagnostic.get("matchedRecommendations") or 0)
    if diagnostic:
        if int(diagnostic.get("conflicts") or 0) > 0:
            attempt_reason = "PREDICTION_IMMUTABLE_CONFLICT"
        elif int(diagnostic.get("sealedOrConfirmed") or 0) > 0:
            attempt_reason = "SEAL_CONFIRMED"
        elif matched <= 0:
            attempt_reason = "NO_SCOPE_RECOMMENDATIONS"
        elif int(diagnostic.get("skippedInputContract") or 0) >= matched:
            attempt_reason = "INPUT_CONTRACT_REJECTED"
        elif int(diagnostic.get("skippedAfterNextSessionOpen") or 0) > 0:
            attempt_reason = "NEXT_SESSION_ALREADY_OPEN"
        elif int(diagnostic.get("skippedBeforeSignalClose") or 0) > 0:
            attempt_reason = "SIGNAL_SESSION_NOT_CLOSED"
        elif int(diagnostic.get("skippedForwardSeal") or 0) > 0:
            attempt_reason = "FORWARD_SEAL_REJECTED"
        else:
            attempt_reason = "NO_SEALABLE_RECOMMENDATION"

    if registry is None:
        status, blocker = "ERROR", "CANDIDATE_NOT_REGISTERED"
    elif not registered_at:
        status, blocker = "ERROR", "CANDIDATE_REGISTRATION_TIME_MISSING"
    elif int(diagnostic.get("conflicts") or 0) > 0:
        status, blocker = "ERROR", "PREDICTION_IMMUTABLE_CONFLICT"
    elif predictions:
        if silence_days is not None and silence_days > MAX_PREDICTION_SILENCE_DAYS:
            status, blocker = "STALLED", "PREDICTION_SILENCE_EXCEEDED"
        else:
            status, blocker = "COLLECTING", ""
    elif age_days is not None and age_days > INITIAL_RECORDING_GRACE_DAYS:
        status, blocker = "STALLED", f"{attempt_reason}_AFTER_GRACE"
    else:
        status, blocker = "WARMUP", ""
    return {
        "status": status,
        "healthy": status in {"WARMUP", "COLLECTING"},
        "requiresAttention": status in {"STALLED", "ERROR"},
        "blockingReason": blocker or None,
        "lastAttemptReason": attempt_reason,
        "candidateFingerprint": fingerprint,
        "registeredAt": registered_at or None,
        "candidateAgeCalendarDays": round(age_days, 3) if age_days is not None else None,
        "predictionSilenceCalendarDays": round(silence_days, 3) if silence_days is not None else None,
        "initialGraceCalendarDays": INITIAL_RECORDING_GRACE_DAYS,
        "maxPredictionSilenceCalendarDays": MAX_PREDICTION_SILENCE_DAYS,
        "sealedPredictions": len(predictions),
        "settledPredictions": len(settlements),
        "lastPredictionRecordedAt": last_prediction or None,
        "lastSettlementAt": last_settlement or None,
        "lastRecordingRunAt": diagnostic.get("runAt") or (
            (last_recording_run or {}).get("runAt") if isinstance(last_recording_run, dict) else None
        ),
        "lastRunDiagnostics": diagnostic or None,
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
            "evaluation_policy_version": vtj.EVALUATION_POLICY["version"],
            "evaluation_policy_fingerprint": vtj._evaluation_policy_fingerprint(),
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


def _arm_stats(
    returns_pct: list[float],
    trades: int,
    trade_contributions_pct: list[float] | None = None,
) -> dict[str, Any]:
    payoff_sample = trade_contributions_pct if trade_contributions_pct is not None else returns_pct
    gains = sum(value for value in payoff_sample if value > 0)
    losses = abs(sum(value for value in payoff_sample if value < 0))
    winning_returns = [value for value in payoff_sample if value > 0]
    losing_returns = [value for value in payoff_sample if value < 0]
    average_win = sum(winning_returns) / len(winning_returns) if winning_returns else None
    average_loss = abs(sum(losing_returns) / len(losing_returns)) if losing_returns else None
    payoff_ratio = average_win / average_loss if average_win is not None and average_loss else None
    expectancy = sum(returns_pct) / len(returns_pct) if returns_pct else None
    nav = 1.0
    for value in returns_pct:
        nav *= 1.0 + value / 100.0
    return {
        "completeSignalDates": len(returns_pct),
        "selectedEvaluatedTrades": trades,
        "avgDailyReturnPct": round(expectancy, 6) if expectancy is not None else None,
        "afterCostExpectancyPct": round(expectancy, 6) if expectancy is not None else None,
        "avgWinPct": round(average_win, 6) if average_win is not None else None,
        "avgLossPct": round(average_loss, 6) if average_loss is not None else None,
        "payoffRatio": round(payoff_ratio, 6) if payoff_ratio is not None else None,
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
    champion_trade_contributions: list[float] = []
    challenger_trade_contributions: list[float] = []
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
        champion_contributions = [
            POSITION_WEIGHT * float(
                _num(settlement_by_prediction[_text(row.get("prediction_id"))].get("champion_net_pnl_pct")) or 0.0
            )
            for row in champion
        ]
        challenger_contributions = [
            POSITION_WEIGHT * float(
                _num(settlement_by_prediction[_text(row.get("prediction_id"))].get("challenger_net_pnl_pct")) or 0.0
            )
            for row in challenger
        ]
        champion_return = sum(champion_contributions)
        challenger_return = sum(challenger_contributions)
        champion_trade_contributions.extend(champion_contributions)
        challenger_trade_contributions.extend(challenger_contributions)
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
    champion_stats = _arm_stats(champion_returns, champion_trades, champion_trade_contributions)
    challenger_stats = _arm_stats(challenger_returns, challenger_trades, challenger_trade_contributions)
    champion_stats["afterCostExpectancyBootstrapCi95"] = _bootstrap_ci(champion_returns)
    challenger_stats["afterCostExpectancyBootstrapCi95"] = _bootstrap_ci(challenger_returns)
    return {
        "completedSignalDates": len(daily),
        "incompleteSignalDates": incomplete,
        "champion": champion_stats,
        "challenger": challenger_stats,
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
        seal_window = _forward_seal_window(_text(row.get("signal_date"))[:10], _text(row.get("market")))
        signal_close, next_session_open = seal_window if seal_window else (None, None)
        if (
            delay is None or delay < 0 or delay > MAX_RECORDING_DELAY_HOURS
            or _text(row.get("signal_date"))[:10] != _text(row.get("ohlcv_last_date"))[:10]
            or signal_close is None or next_session_open is None
            or generated is None or recorded is None
            or generated < signal_close or recorded < signal_close
            or generated >= next_session_open or recorded >= next_session_open
        ):
            recording_time_violations += 1
    relationship_violations = sum(
        1 for row in settlement_rows
        if _text(row.get("prediction_id")) not in prediction_by_id
        or _text(row.get("candidate_fingerprint"))
        != _text((prediction_by_id.get(_text(row.get("prediction_id"))) or {}).get("candidate_fingerprint"))
    )
    settlement_policy_violations = sum(
        1 for row in settlement_rows
        if _text(row.get("evaluation_policy_version")) != _text(vtj.EVALUATION_POLICY["version"])
        or _text(row.get("evaluation_policy_fingerprint")) != vtj._evaluation_policy_fingerprint()
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
        "settlementEvaluationPolicyViolations": settlement_policy_violations,
        "forwardSealViolations": sum(1 for row in prediction_rows if _text(row.get("forward_seal_status")) != "SEALED_FORWARD"),
        "inputContractViolations": sum(1 for row in prediction_rows if _text(row.get("input_contract_version")) != INPUT_CONTRACT_VERSION),
    }


def _residual_alpha_gate(report: dict[str, Any]) -> dict[str, Any]:
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    policy = report.get("policy") if isinstance(report.get("policy"), dict) else {}
    selected_ci = validation.get("selectedBlockBootstrapCi95")
    selected_ci = selected_ci if isinstance(selected_ci, list) and len(selected_ci) >= 2 else None
    version_matches = _text(policy.get("version")) == RESIDUAL_ALPHA_POLICY_VERSION
    lower_positive = bool(selected_ci) and (_num(selected_ci[0]) or 0.0) > 0
    blockers = list(validation.get("blockingReasons") or [])
    if validation.get("evidenceStatus") != "PASS":
        blockers.append("RESIDUAL_ALPHA_MODEL_NOT_PROVEN")
    if not version_matches:
        blockers.append("RESIDUAL_ALPHA_MODEL_VERSION_MISMATCH")
    if not lower_positive:
        blockers.append("RESIDUAL_ALPHA_LOWER_CI_NOT_POSITIVE")
    return {
        "passed": not blockers,
        "evidenceStatus": validation.get("evidenceStatus") or "MISSING",
        "policyVersion": policy.get("version"),
        "requiredPolicyVersion": RESIDUAL_ALPHA_POLICY_VERSION,
        "modelFingerprint": policy.get("fingerprint"),
        "selectedBlockBootstrapCi95": selected_ci,
        "blockingReasons": list(dict.fromkeys(_text(reason) for reason in blockers if _text(reason))),
    }


def _promotion(
    candidate: dict[str, Any],
    comparison: dict[str, Any],
    integrity: dict[str, Any],
    residual_alpha_gate: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    challenger = comparison["challenger"]
    champion = comparison["champion"]
    uplift_ci = comparison["pairedUplift"].get("bootstrapCi95")
    expectancy_ci = challenger.get("afterCostExpectancyBootstrapCi95")
    residual_gate = residual_alpha_gate or {"passed": False, "blockingReasons": ["RESIDUAL_ALPHA_GATE_MISSING"]}
    blockers: list[str] = []
    integrity_clean = not any(int(value or 0) > 0 for value in integrity.values())
    if not integrity_clean:
        blockers.append("SHADOW_INTEGRITY_VIOLATION")
    if comparison.get("completedSignalDates", 0) < MIN_SIGNAL_DATES:
        blockers.append("LOW_PROMOTION_SIGNAL_DATES")
    if challenger.get("selectedEvaluatedTrades", 0) < MIN_CHALLENGER_TRADES:
        blockers.append("LOW_PROMOTION_TRADES")
    if challenger.get("avgDailyReturnPct") is None or challenger["avgDailyReturnPct"] <= 0:
        blockers.append("NON_POSITIVE_PROMOTION_RETURN")
    if not expectancy_ci or float(expectancy_ci[0]) <= 0:
        blockers.append("PROMOTION_AFTER_COST_EXPECTANCY_NOT_PROVEN")
    if challenger.get("profitFactor") is None or challenger["profitFactor"] <= 1.0:
        blockers.append("PROMOTION_PROFIT_FACTOR_NOT_ABOVE_ONE")
    challenger_payoff = _num(challenger.get("payoffRatio"))
    champion_payoff = _num(champion.get("payoffRatio"))
    if challenger_payoff is None or challenger_payoff < MIN_PAYOFF_RATIO:
        blockers.append("PROMOTION_PAYOFF_RATIO_TOO_LOW")
    if (
        challenger_payoff is not None
        and champion_payoff is not None
        and challenger_payoff < champion_payoff * (1.0 - MAX_PAYOFF_RELATIVE_DEGRADATION)
    ):
        blockers.append("PROMOTION_PAYOFF_RATIO_DEGRADED")
    if not uplift_ci or float(uplift_ci[0]) <= 0:
        blockers.append("PROMOTION_UPLIFT_NOT_PROVEN")
    if challenger.get("maxDrawdownPct") is None or champion.get("maxDrawdownPct") is None:
        blockers.append("DRAWDOWN_COMPARISON_NOT_READY")
    elif challenger["maxDrawdownPct"] > champion["maxDrawdownPct"]:
        blockers.append("PROMOTION_DRAWDOWN_WORSE")
    if not residual_gate.get("passed"):
        blockers.append("PROMOTION_RESIDUAL_ALPHA_NOT_PROVEN")
    evidence_mature = (
        comparison.get("completedSignalDates", 0) >= MIN_SIGNAL_DATES
        and challenger.get("selectedEvaluatedTrades", 0) >= MIN_CHALLENGER_TRADES
    )
    promotion_eligible = not blockers
    if promotion_eligible:
        decision_name = vtj.CALIBRATION_PROMOTION_DECISION
        suggested_action = "AUTO_APPLY_PROMOTED_CORRECTION"
    elif evidence_mature and not integrity_clean:
        decision_name = "INVALIDATE_EXPERIMENT"
        suggested_action = "REJECT_AND_INVESTIGATE_INTEGRITY"
    elif evidence_mature:
        decision_name = "REJECT_CHALLENGER"
        suggested_action = "REJECT_PRECOMMITTED_CANDIDATE"
    else:
        decision_name = "KEEP_CHALLENGER_SHADOW"
        suggested_action = "CONTINUE_FORWARD_COLLECTION"
    decision = {
        "promotionEligible": promotion_eligible,
        "decision": decision_name,
        "blockingReasons": blockers,
        "evidenceMature": evidence_mature,
        "terminalFailure": evidence_mature and not promotion_eligible,
        "suggestedAction": suggested_action,
        "autoPromotionAllowed": bool(vtj.CALIBRATION_SHADOW_POLICY["autoPromotionAllowed"]),
        "humanApprovalRequired": bool(vtj.CALIBRATION_SHADOW_POLICY["humanApprovalRequired"]),
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
        "evaluationPolicyVersion": vtj.EVALUATION_POLICY["version"],
        "evaluationPolicyFingerprint": vtj._evaluation_policy_fingerprint(),
        "promotionEligible": True,
        "decision": vtj.CALIBRATION_PROMOTION_DECISION,
        "autoPromotionAllowed": True,
        "humanApprovalRequired": False,
        "completedSignalDates": comparison.get("completedSignalDates"),
        "evaluatedChallengerTrades": challenger.get("selectedEvaluatedTrades"),
        "avgAfterCostReturnPct": challenger.get("avgDailyReturnPct"),
        "afterCostExpectancyBootstrapCi95": expectancy_ci,
        "profitFactor": challenger.get("profitFactor"),
        "payoffRatio": challenger.get("payoffRatio"),
        "pairedUpliftCi95": uplift_ci,
        "championMaxDrawdownPct": champion.get("maxDrawdownPct"),
        "challengerMaxDrawdownPct": challenger.get("maxDrawdownPct"),
        "residualAlphaModelFingerprint": residual_gate.get("modelFingerprint"),
        "residualAlphaPolicyVersion": residual_gate.get("policyVersion"),
        "residualAlphaSelectedCi95": residual_gate.get("selectedBlockBootstrapCi95"),
    }
    certificate["recordHash"] = vtj._promotion_certificate_hash(certificate)
    return decision, certificate


def build(
    registry_path: Path = REGISTRY,
    prediction_path: Path = PREDICTIONS,
    settlement_path: Path = SETTLEMENTS,
    output_path: Path = OUT,
    promotion_path: Path = PROMOTION,
    residual_path: Path = RESIDUAL_ALPHA_REPORT,
    *,
    record: bool = True,
    settle: bool = True,
    record_market: str = "all",
) -> dict[str, Any]:
    try:
        previous_payload = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(previous_payload, dict):
            previous_payload = {}
    except Exception:
        previous_payload = {}
    candidate_status = vtj.calibration_shadow_candidates()
    candidates = candidate_status.get("items") if isinstance(candidate_status.get("items"), list) else []
    readiness = candidate_status.get("readiness") if isinstance(candidate_status.get("readiness"), dict) else {}
    registry_status = register_candidates(candidates, registry_path) if record else {"appended": 0, "conflicts": 0, "total": len(_read_csv(registry_path))}
    prediction_status = (
        record_predictions(
            candidates,
            _read_recommendations(),
            prediction_path,
            record_market=record_market,
        )
        if record and record_market != "none"
        else {"appended": 0, "conflicts": 0, "total": len(_read_csv(prediction_path)), "recordMarket": record_market}
    )
    previous_recording_run = (
        previous_payload.get("lastRecordingRun")
        if isinstance(previous_payload.get("lastRecordingRun"), dict)
        else None
    )
    if record and record_market != "none":
        previous_diagnostics = (
            previous_recording_run.get("candidateDiagnostics")
            if isinstance(previous_recording_run, dict)
            and isinstance(previous_recording_run.get("candidateDiagnostics"), list)
            else []
        )
        merged_diagnostics = {
            _text(row.get("candidateFingerprint")): row
            for row in previous_diagnostics
            if isinstance(row, dict) and _text(row.get("candidateFingerprint"))
        }
        merged_diagnostics.update({
            _text(row.get("candidateFingerprint")): row
            for row in prediction_status.get("candidateDiagnostics") or []
            if isinstance(row, dict) and _text(row.get("candidateFingerprint"))
        })
        last_recording_run = {**prediction_status, "candidateDiagnostics": list(merged_diagnostics.values())}
    else:
        last_recording_run = previous_recording_run
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
    residual_gate = _residual_alpha_gate(_read_json(residual_path))
    results: list[dict[str, Any]] = []
    certificates: list[dict[str, Any]] = []
    for candidate in candidates:
        fingerprint = _text(candidate.get("candidateFingerprint"))
        comparison = compare_candidate(fingerprint, active_predictions, active_settlements)
        decision, certificate = _promotion(candidate, comparison, integrity, residual_gate)
        recording_health = candidate_recording_health(
            candidate,
            active_registry,
            active_predictions,
            active_settlements,
            last_recording_run,
        )
        if certificate is not None:
            certificates.append(certificate)
        results.append({
            "approvalId": candidate.get("approvalId"),
            "candidateFingerprint": fingerprint,
            "market": candidate.get("market"),
            "mode": candidate.get("mode"),
            "horizon": candidate.get("horizon"),
            "reason": candidate.get("reason"),
            "recordingHealth": recording_health,
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
        "residualAlphaGate": residual_gate,
        "summary": {
            "activeCandidates": len(candidates),
            "registeredCandidates": len(active_registry),
            "sealedPredictions": len(active_predictions),
            "settledPredictions": len(active_settlements),
            "promotionEligible": len(certificates),
            "readyForReview": int(readiness.get("readyForReview") or 0),
            "eligibleSuggestions": int(readiness.get("eligibleSuggestions") or 0),
            "recordingHealthy": all(
                bool((row.get("recordingHealth") or {}).get("healthy")) for row in results
            ) if results else True,
            "stalledCandidates": sum(
                1 for row in results
                if (row.get("recordingHealth") or {}).get("status") in {"STALLED", "ERROR"}
            ),
            "terminalFailureCandidates": sum(
                1 for row in results if bool((row.get("promotion") or {}).get("terminalFailure"))
            ),
            "abstain": not certificates,
        },
        "integrity": integrity,
        "registryRun": registry_status,
        "predictionRun": prediction_status,
        "lastRecordingRun": last_recording_run,
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


def operational_exit_code(payload: dict[str, Any]) -> int:
    integrity = payload.get("integrity") if isinstance(payload.get("integrity"), dict) else {}
    if any(int(value or 0) > 0 for value in integrity.values()):
        return 2
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    if any(
        _text((row.get("recordingHealth") or {}).get("status")).upper() == "ERROR"
        for row in candidates if isinstance(row, dict)
    ):
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--no-settle", action="store_true")
    parser.add_argument("--record-market", choices=("all", "kr", "us", "none"), default="all")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--promotion-output", type=Path, default=PROMOTION)
    parser.add_argument("--residual-report", type=Path, default=RESIDUAL_ALPHA_REPORT)
    args = parser.parse_args()
    payload = build(
        output_path=args.output,
        promotion_path=args.promotion_output,
        residual_path=args.residual_report,
        record=not args.no_record,
        settle=not args.no_settle,
        record_market=args.record_market,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    exit_code = operational_exit_code(payload)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if exit_code:
        print("::error::Self-correction Shadow evidence integrity or candidate registration failed.")
    elif int(summary.get("stalledCandidates") or 0) > 0:
        print("::warning::Self-correction Forward evidence collection is stalled; inspect recordingHealth.")
    if int(summary.get("terminalFailureCandidates") or 0) > 0:
        print("::warning::A mature self-correction challenger failed its precommitted promotion gate.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
