#!/usr/bin/env python3
"""Build a time-purged residual-alpha prediction challenger.

The model is deliberately shadow-only.  Labels are pre-event market-model
CARs and become eligible for training only after the complete event window is
observable.  Expanding-window validation is grouped by signal date so rows
from the same market shock can never leak across train and test.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import glob
import hashlib
import inspect
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OHLCV = ROOT / "data" / "market" / "ohlcv"
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
KR_MASTER = ROOT / "data" / "stock_master_kr.csv"
REPORTS = ROOT / "reports"
OUT = REPORTS / "shadow_residual_alpha.json"
PREDICTION_JOURNAL = ROOT / "data" / "shadow_residual_alpha_predictions.csv"
SETTLEMENT_JOURNAL = ROOT / "data" / "shadow_residual_alpha_settlements.csv"
MODEL_REGISTRY = ROOT / "data" / "shadow_residual_model_registry.csv"

FORWARD_SOURCES = {"FORWARD_PAPER_TRADE", "MANUAL_REVIEWED"}
PLAN_ONLY_SESSIONS = {"PREMARKET_PLAN", "INTRADAY_CHECK"}
DEFAULT_BENCHMARKS = {"kr": "KOSPI", "us": "SPY"}
HORIZON_WINDOWS = {"short": 5, "swing": 20, "mid": 20}
ESTIMATION_START = -250
ESTIMATION_END = -11
MIN_ESTIMATION_OBS = 60
MIN_TRAIN_ROWS = 120
MIN_TRAIN_DATES = 20
MIN_OOS_PREDICTIONS = 120
MIN_OOS_DATES = 30
MIN_SELECTED_OOS = 60
RIDGE_LAMBDA = 10.0
LOWER_QUANTILE_Z = 1.645
MAX_RECORDING_DELAY_HOURS = 6.0
POLICY_VERSION = "shadow-residual-alpha-v1.1.2"

PREDICTION_FIELDS = [
    "prediction_id", "policy_version", "model_fingerprint", "recorded_at",
    "generated_at", "signal_date", "candidate_key", "economic_event_key",
    "market", "mode", "horizon", "symbol", "status", "train_rows",
    "train_dates", "train_max_label_available_date",
    "training_data_fingerprint", "model_instance_fingerprint",
    "predicted_residual_alpha_pct", "prediction_lower90_pct",
    "baseline_prediction_pct", "record_hash",
]
SETTLEMENT_FIELDS = [
    "prediction_id", "model_fingerprint", "settled_at", "signal_date",
    "economic_event_key", "label_available_date",
    "realized_residual_alpha_pct", "beta", "market_model_r2", "record_hash",
]
MODEL_REGISTRY_FIELDS = [
    "model_fingerprint", "policy_version", "implementation_fingerprint",
    "first_seen_at", "predecessor_model_fingerprint", "lifecycle_status",
    "record_hash",
]

NUMERIC_FEATURES = (
    "final_rank_score",
    "expected_value",
    "risk_reward_ratio",
    "probability",
    "risk_score",
    "event_risk_score",
    "rsi_at_entry",
    "volume_ratio_at_entry",
    "distance_to_ma20_at_entry",
    "atr14_pct_at_entry",
    "mdd20_at_entry",
    "momentum5_at_entry",
)
FEATURE_ALIASES = {
    "final_rank_score": ("finalRankScore", "finalScore"),
    "expected_value": ("expectedValue",),
    "risk_reward_ratio": ("rrActual", "riskRewardRatio"),
    "probability": ("probability",),
    "risk_score": ("riskScore",),
    "event_risk_score": ("eventRiskScore",),
    "rsi_at_entry": ("rsi14", "rsiAtEntry"),
    "volume_ratio_at_entry": ("volumeRatio20", "volumeRatioAtEntry"),
    "distance_to_ma20_at_entry": ("distanceToMa20", "distanceToMa20AtEntry"),
    "atr14_pct_at_entry": ("atr14Pct", "atr14PctAtEntry"),
    "mdd20_at_entry": ("mdd20", "mdd20AtEntry"),
    "momentum5_at_entry": ("recentMomentum5", "momentum5AtEntry"),
}
CATEGORY_FEATURES = (
    ("market", "us"),
    ("mode", "conservative"),
    ("mode", "aggressive"),
    ("horizon", "swing"),
    ("horizon", "mid"),
)


def _policy() -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "label": "POST_SIGNAL_PRE_EVENT_MARKET_MODEL_CAR_BY_HORIZON",
        "horizonWindows": HORIZON_WINDOWS,
        "estimationWindow": [ESTIMATION_START, ESTIMATION_END],
        "minEstimationObservations": MIN_ESTIMATION_OBS,
        "minTrainRows": MIN_TRAIN_ROWS,
        "minTrainDates": MIN_TRAIN_DATES,
        "minOosPredictions": MIN_OOS_PREDICTIONS,
        "minOosDates": MIN_OOS_DATES,
        "minSelectedOos": MIN_SELECTED_OOS,
        "ridgeLambda": RIDGE_LAMBDA,
        "selectionRule": "PREDICTION_LOWER_90_ABOVE_ZERO",
        "sampleUnit": "UNIQUE_SIGNAL_DATE_MARKET_SYMBOL_LABEL_WINDOW",
        "sameDateRowsStayInOneTestBlock": True,
        "eventDayReturnExcluded": True,
        "trainingLabelAvailableStrictlyBeforeSignalDate": True,
        "validationSource": "IMMUTABLE_FORWARD_PREDICTION_AND_SETTLEMENT_JOURNALS",
        "researchWalkForwardCannotPromote": True,
        "maxPredictionRecordingDelayHours": MAX_RECORDING_DELAY_HOURS,
        "modelFingerprintCohortRequired": True,
        "immutablePredictionAndSettlementRows": True,
        "immutableModelRegistryRequired": True,
        "policyVersionCannotIdentifyMultipleImplementations": True,
        "implementationFingerprint": _model_implementation_fingerprint(),
        "numericFeatures": list(NUMERIC_FEATURES),
        "categoryFeatures": [f"{field}={value}" for field, value in CATEGORY_FEATURES],
    }


def _policy_fingerprint() -> str:
    raw = json.dumps(_policy(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _model_implementation_fingerprint() -> str:
    critical_functions = (
        "_event_label",
        "_feature_matrix",
        "_fit_predict",
        "expanding_oos",
        "training_data_fingerprint",
        "model_instance_fingerprint",
        "current_predictions",
    )
    sources: dict[str, str] = {}
    for name in critical_functions:
        function = globals().get(name)
        if function is None:
            raise RuntimeError(f"model implementation function missing: {name}")
        try:
            sources[name] = inspect.getsource(function)
        except (OSError, TypeError) as exc:
            raise RuntimeError(f"cannot fingerprint model implementation: {name}") from exc
    payload = {
        "functions": sources,
        "featureAliases": FEATURE_ALIASES,
        "numericFeatures": NUMERIC_FEATURES,
        "categoryFeatures": CATEGORY_FEATURES,
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        raw = _text(value).replace(",", "").replace("%", "")
        return float(raw) if raw and raw.lower() not in {"nan", "none", "null", "-"} else None
    except (TypeError, ValueError):
        return None


def _feature_num(row: dict[str, Any], feature: str) -> float | None:
    for key in (feature, *FEATURE_ALIASES.get(feature, ())):
        value = _num(row.get(key))
        if value is not None:
            return value
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


def candidate_key(row: dict[str, Any], signal_date: str | None = None) -> str:
    day = _text(signal_date or row.get("asOfDate") or row.get("as_of_date") or row.get("generatedAt"))[:10]
    raw = "|".join((
        day,
        _text(row.get("market")).lower(),
        _text(row.get("mode")).lower(),
        _text(row.get("horizon")).lower(),
        _text(row.get("symbol")).upper(),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def economic_event_key(row: dict[str, Any], signal_date: str | None = None) -> str:
    day = _text(signal_date or row.get("asOfDate") or row.get("as_of_date") or row.get("generatedAt"))[:10]
    market = _text(row.get("market")).lower()
    symbol = _text(row.get("symbolNormalized") or row.get("symbol")).upper().split(".")[0]
    if market == "kr":
        symbol = symbol.zfill(6)
    window = HORIZON_WINDOWS.get(_text(row.get("horizon")).lower())
    raw = "|".join((day, market, symbol, str(window or "")))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _parse_generated_at(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return parsed.astimezone(timezone.utc)


def _prediction_id(model_fingerprint: str, candidate_key_value: str) -> str:
    raw = f"{model_fingerprint}|{candidate_key_value}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:28]


def _same_immutable_row(left: dict[str, Any], right: dict[str, Any], ignored: set[str]) -> bool:
    keys = (set(left) | set(right)) - ignored
    return all(_text(left.get(key)) == _text(right.get(key)) for key in keys)


def _row_hash(row: dict[str, Any], ignored: set[str]) -> str:
    payload = {key: _text(value) for key, value in row.items() if key not in ignored and key != "record_hash"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _append_csv_rows(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> tuple[int, str | None]:
    if not rows:
        return 0, None
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    if exists:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        if header != fields:
            return 0, "JOURNAL_SCHEMA_MISMATCH"
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
    return len(rows), None


def register_model(
    path: Path | None = None,
    seen_at: datetime | None = None,
) -> dict[str, Any]:
    registry_path = path or MODEL_REGISTRY
    existing = _read_csv(registry_path)
    current_fingerprint = _policy_fingerprint()
    implementation_fingerprint = _model_implementation_fingerprint()
    now = (seen_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    by_fingerprint = {
        _text(row.get("model_fingerprint")): row
        for row in existing if _text(row.get("model_fingerprint"))
    }
    hash_violations = sum(
        _text(row.get("record_hash")) != _row_hash(row, {"first_seen_at"})
        for row in existing
    )
    version_reuse = sum(
        1 for row in existing
        if _text(row.get("policy_version")) == POLICY_VERSION
        and _text(row.get("model_fingerprint")) != current_fingerprint
    )
    predecessor = _text(existing[-1].get("model_fingerprint")) if existing else ""
    row = {
        "model_fingerprint": current_fingerprint,
        "policy_version": POLICY_VERSION,
        "implementation_fingerprint": implementation_fingerprint,
        "first_seen_at": now.isoformat(),
        "predecessor_model_fingerprint": predecessor,
        "lifecycle_status": "SHADOW_EVALUATION",
    }
    row["record_hash"] = _row_hash(row, {"first_seen_at"})
    previous = by_fingerprint.get(current_fingerprint)
    immutable_conflicts = 0
    duplicate = 0
    pending: list[dict[str, Any]] = []
    if previous:
        if _same_immutable_row(previous, row, {"first_seen_at", "predecessor_model_fingerprint", "record_hash"}):
            duplicate = 1
        else:
            immutable_conflicts = 1
    else:
        pending.append(row)
    appended, schema_error = _append_csv_rows(registry_path, MODEL_REGISTRY_FIELDS, pending)
    return {
        "path": str(registry_path.relative_to(ROOT)) if registry_path.is_relative_to(ROOT) else str(registry_path),
        "currentModelFingerprint": current_fingerprint,
        "currentImplementationFingerprint": implementation_fingerprint,
        "policyVersion": POLICY_VERSION,
        "existingRows": len(existing),
        "appendedRows": appended,
        "duplicateRows": duplicate,
        "versionReuseConflicts": version_reuse,
        "immutableConflicts": immutable_conflicts,
        "recordHashViolations": hash_violations,
        "schemaError": schema_error,
    }


def _dedupe_forward_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if _text(row.get("source_type")).upper() not in FORWARD_SOURCES:
            continue
        if _text(row.get("journal_session")).upper() in PLAN_ONLY_SESSIONS:
            continue
        # A stock/date can appear in several mode cells.  If the target window
        # is the same, that is one economic event, not independent evidence.
        horizon = _text(row.get("horizon")).lower()
        key = "|".join((
            _text(row.get("as_of_date")).lower(),
            _text(row.get("market")).lower(),
            _text(row.get("symbol")).lower(),
            str(HORIZON_WINDOWS.get(horizon) or horizon),
        ))
        previous = selected.get(key)
        score = _num(row.get("final_rank_score"))
        previous_score = _num(previous.get("final_rank_score")) if previous else None
        if previous is None or (score if score is not None else -math.inf) > (
            previous_score if previous_score is not None else -math.inf
        ):
            selected[key] = row
    return list(selected.values())


def _load_series(path: Path) -> tuple[list[str], np.ndarray] | None:
    pairs: dict[str, float] = {}
    for row in _read_csv(path):
        day = _text(row.get("date") or row.get("Date"))[:10]
        close = _num(row.get("close") or row.get("Close"))
        if day and close is not None and close > 0:
            pairs[day] = close
    if len(pairs) < MIN_ESTIMATION_OBS + 30:
        return None
    ordered = sorted(pairs.items())
    return [day for day, _ in ordered], np.asarray([close for _, close in ordered], dtype=float)


def _returns(closes: np.ndarray) -> np.ndarray:
    return closes[1:] / closes[:-1] - 1.0


def _fit_market_model(stock: np.ndarray, benchmark: np.ndarray) -> tuple[float, float, float]:
    design = np.column_stack([np.ones(len(stock)), benchmark])
    coefficients, *_ = np.linalg.lstsq(design, stock, rcond=None)
    prediction = design @ coefficients
    residual = float(np.sum((stock - prediction) ** 2))
    total = float(np.sum((stock - stock.mean()) ** 2))
    return float(coefficients[0]), float(coefficients[1]), 1.0 - residual / total if total > 0 else 0.0


def _kr_benchmark_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in _read_csv(KR_MASTER):
        code = _text(row.get("code") or row.get("symbol")).split(".")[0].zfill(6)
        market_type = _text(row.get("market_type") or row.get("note")).upper()
        if code.isdigit():
            mapping[code] = "KOSDAQ" if "KOSDAQ" in market_type or "코스닥" in market_type else "KOSPI"
    return mapping


def _event_label(
    row: dict[str, Any],
    stock_cache: dict[tuple[str, str], tuple[list[str], np.ndarray] | None],
    benchmark_cache: dict[tuple[str, str], tuple[list[str], np.ndarray] | None],
    kr_benchmarks: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    market = _text(row.get("market")).lower()
    horizon = _text(row.get("horizon")).lower()
    signal_date = _text(row.get("as_of_date") or row.get("captured_at"))[:10]
    raw_symbol = _text(row.get("symbol")).upper().split(".")[0]
    symbol = raw_symbol.zfill(6) if market == "kr" else raw_symbol
    window = HORIZON_WINDOWS.get(horizon)
    if market not in {"kr", "us"} or not signal_date or not symbol or window is None:
        return None, "INVALID_SIGNAL"

    benchmark_symbol = kr_benchmarks.get(symbol, DEFAULT_BENCHMARKS["kr"]) if market == "kr" else DEFAULT_BENCHMARKS["us"]
    benchmark_key = (market, benchmark_symbol)
    if benchmark_key not in benchmark_cache:
        benchmark_cache[benchmark_key] = _load_series(OHLCV / f"{market}_{benchmark_symbol}_daily.csv")
    stock_key = (market, symbol)
    if stock_key not in stock_cache:
        stock_cache[stock_key] = _load_series(OHLCV / f"{market}_{symbol}_daily.csv")
    benchmark_series = benchmark_cache[benchmark_key]
    stock_series = stock_cache[stock_key]
    if not stock_series:
        return None, "NO_STOCK_OHLCV"
    if not benchmark_series:
        return None, "NO_BENCHMARK_OHLCV"

    stock_dates, stock_closes = stock_series
    benchmark_dates, benchmark_closes = benchmark_series
    stock_returns = _returns(stock_closes)
    benchmark_returns = _returns(benchmark_closes)
    benchmark_index = {day: index for index, day in enumerate(benchmark_dates)}
    position = bisect.bisect_left(stock_dates, signal_date)
    if position <= 0 or position >= len(stock_dates):
        return None, "NO_SIGNAL_DATE"
    event_index = position - 1
    estimate_low = event_index + ESTIMATION_START
    estimate_high = event_index + ESTIMATION_END
    if estimate_low < 0 or estimate_high - estimate_low < MIN_ESTIMATION_OBS:
        return None, "SHORT_ESTIMATION"
    if event_index + window >= len(stock_returns):
        return None, "UNRESOLVED_EVENT_WINDOW"

    def benchmark_at(day: str) -> float | None:
        index = benchmark_index.get(day)
        return float(benchmark_returns[index - 1]) if index and 0 < index <= len(benchmark_returns) else None

    estimate_days = stock_dates[estimate_low + 1:estimate_high + 1]
    pairs = [
        (float(stock_returns[estimate_low + offset]), benchmark_at(day))
        for offset, day in enumerate(estimate_days)
    ]
    complete_pairs = [(stock_return, benchmark_return) for stock_return, benchmark_return in pairs if benchmark_return is not None]
    if len(complete_pairs) < MIN_ESTIMATION_OBS:
        return None, "SHORT_ESTIMATION"
    alpha, beta, r2 = _fit_market_model(
        np.asarray([stock_return for stock_return, _ in complete_pairs]),
        np.asarray([benchmark_return for _, benchmark_return in complete_pairs]),
    )

    abnormal = 0.0
    matched_days = 0
    # Recommendations are generated after the signal-day close.  Offset zero
    # is therefore already known at decision time and cannot be a predictive
    # target.  D+N contains exactly N post-signal trading returns.
    for offset in range(1, window + 1):
        index = event_index + offset
        benchmark_return = benchmark_at(stock_dates[index + 1])
        if benchmark_return is None:
            continue
        abnormal += float(stock_returns[index]) - (alpha + beta * benchmark_return)
        matched_days += 1
    if matched_days < max(2, window // 2):
        return None, "SHORT_EVENT_WINDOW"
    label_available_date = stock_dates[event_index + window + 1]
    return {
        **row,
        "signalDate": signal_date,
        "candidateKey": candidate_key(row, signal_date),
        "economicEventKey": economic_event_key(row, signal_date),
        "symbolNormalized": symbol,
        "benchmark": benchmark_symbol,
        "labelWindow": window,
        "labelAvailableDate": label_available_date,
        "residualAlphaPct": abnormal * 100.0,
        "beta": beta,
        "marketModelR2": r2,
    }, None


def build_labeled_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stock_cache: dict[tuple[str, str], tuple[list[str], np.ndarray] | None] = {}
    benchmark_cache: dict[tuple[str, str], tuple[list[str], np.ndarray] | None] = {}
    kr_benchmarks = _kr_benchmark_map()
    labeled: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)
    for row in _dedupe_forward_rows(rows):
        label, reason = _event_label(row, stock_cache, benchmark_cache, kr_benchmarks)
        if label is None:
            skipped[reason or "UNKNOWN"] += 1
        else:
            labeled.append(label)
    labeled.sort(key=lambda item: (item["signalDate"], item["candidateKey"]))
    return labeled, dict(sorted(skipped.items()))


def _feature_matrix(
    train_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, dict[str, Any]]:
    medians: list[float] = []
    means: list[float] = []
    scales: list[float] = []
    for feature in NUMERIC_FEATURES:
        values = [_feature_num(row, feature) for row in train_rows]
        finite = np.asarray([value for value in values if value is not None and math.isfinite(value)], dtype=float)
        median = float(np.median(finite)) if len(finite) else 0.0
        filled = np.asarray([value if value is not None and math.isfinite(value) else median for value in values], dtype=float)
        mean = float(filled.mean()) if len(filled) else 0.0
        scale = float(filled.std()) if len(filled) else 1.0
        medians.append(median)
        means.append(mean)
        scales.append(scale if scale > 1e-9 else 1.0)

    matrix: list[list[float]] = []
    for row in rows:
        features = [1.0]
        for index, feature in enumerate(NUMERIC_FEATURES):
            value = _feature_num(row, feature)
            missing = value is None or not math.isfinite(value)
            clean = medians[index] if missing else float(value)
            features.append((clean - means[index]) / scales[index])
            features.append(1.0 if missing else 0.0)
        for field, value in CATEGORY_FEATURES:
            features.append(1.0 if _text(row.get(field)).lower() == value else 0.0)
        matrix.append(features)
    return np.asarray(matrix, dtype=float), {
        "medians": medians,
        "means": means,
        "scales": scales,
    }


def _fit_predict(
    train_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, float]:
    x_train, _ = _feature_matrix(train_rows, train_rows)
    x_prediction, _ = _feature_matrix(train_rows, prediction_rows)
    y_raw = np.asarray([float(row["residualAlphaPct"]) for row in train_rows], dtype=float)
    lower, upper = np.percentile(y_raw, [2.5, 97.5]) if len(y_raw) >= 20 else (float(y_raw.min()), float(y_raw.max()))
    y = np.clip(y_raw, lower, upper)
    penalty = np.eye(x_train.shape[1]) * RIDGE_LAMBDA
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(x_train.T @ x_train + penalty, x_train.T @ y)
    fitted = x_train @ coefficients
    residual_sd = float(np.sqrt(np.mean((y - fitted) ** 2))) if len(y) else math.inf
    predictions = np.clip(x_prediction @ coefficients, lower, upper)
    baseline = np.full(len(prediction_rows), float(y.mean()))
    return predictions, baseline, residual_sd


def training_data_fingerprint(train_rows: list[dict[str, Any]]) -> str:
    canonical: list[dict[str, Any]] = []
    for row in train_rows:
        numeric = {
            feature: (round(value, 12) if value is not None and math.isfinite(value) else None)
            for feature in NUMERIC_FEATURES
            for value in [_feature_num(row, feature)]
        }
        canonical.append({
            "candidateKey": _text(row.get("candidateKey")),
            "economicEventKey": _text(row.get("economicEventKey")),
            "signalDate": _text(row.get("signalDate")),
            "labelAvailableDate": _text(row.get("labelAvailableDate")),
            "residualAlphaPct": round(float(row["residualAlphaPct"]), 12),
            "categories": {
                field: _text(row.get(field)).lower()
                for field in sorted({field for field, _ in CATEGORY_FEATURES})
            },
            "numericFeatures": numeric,
        })
    canonical.sort(key=lambda item: (
        item["signalDate"], item["labelAvailableDate"],
        item["candidateKey"], item["economicEventKey"],
    ))
    raw = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def model_instance_fingerprint(training_fingerprint: str) -> str:
    raw = f"{_policy_fingerprint()}|{training_fingerprint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def expanding_oos(labeled_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in labeled_rows:
        grouped[row["signalDate"]].append(row)
    predictions: list[dict[str, Any]] = []
    for signal_date in sorted(grouped):
        train = [row for row in labeled_rows if row["labelAvailableDate"] < signal_date]
        train_dates = {row["signalDate"] for row in train}
        if len(train) < MIN_TRAIN_ROWS or len(train_dates) < MIN_TRAIN_DATES:
            continue
        test = grouped[signal_date]
        values, baselines, residual_sd = _fit_predict(train, test)
        max_available = max(row["labelAvailableDate"] for row in train)
        training_fingerprint = training_data_fingerprint(train)
        instance_fingerprint = model_instance_fingerprint(training_fingerprint)
        for row, value, baseline in zip(test, values, baselines):
            predictions.append({
                "candidateKey": row["candidateKey"],
                "signalDate": signal_date,
                "labelAvailableDate": row["labelAvailableDate"],
                "trainMaxLabelAvailableDate": max_available,
                "trainRows": len(train),
                "trainDates": len(train_dates),
                "trainingDataFingerprint": training_fingerprint,
                "modelInstanceFingerprint": instance_fingerprint,
                "predictedResidualAlphaPct": float(value),
                "predictionLower90Pct": float(value - LOWER_QUANTILE_Z * residual_sd),
                "baselinePredictionPct": float(baseline),
                "realizedResidualAlphaPct": float(row["residualAlphaPct"]),
            })
    return predictions


def _rank(values: list[float]) -> np.ndarray:
    order = np.argsort(np.asarray(values, dtype=float), kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2:
        return None
    a, b = _rank(left), _rank(right)
    if float(a.std()) <= 1e-12 or float(b.std()) <= 1e-12:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _date_block_ci(rows: list[dict[str, Any]], seed: int = 20260730) -> tuple[float | None, float | None, float | None, int]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row["signalDate"]].append(float(row["realizedResidualAlphaPct"]))
    daily = np.asarray([np.mean(grouped[day]) for day in sorted(grouped)], dtype=float)
    if not len(daily):
        return None, None, None, 0
    mean = float(daily.mean())
    if len(daily) < 2:
        return mean, None, None, len(daily)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(daily), size=(5000, len(daily)))
    boot = daily[indices].mean(axis=1)
    return mean, float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)), len(daily)


def validation_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    actual = [float(row["realizedResidualAlphaPct"]) for row in predictions]
    predicted = [float(row["predictedResidualAlphaPct"]) for row in predictions]
    baseline = [float(row["baselinePredictionPct"]) for row in predictions]
    selected = [row for row in predictions if float(row["predictionLower90Pct"]) > 0]
    selected_mean, selected_low, selected_high, selected_dates = _date_block_ci(selected)
    dates = {row["signalDate"] for row in predictions}
    violations = sum(
        1 for row in predictions
        if not row["trainMaxLabelAvailableDate"] < row["signalDate"]
    )
    model_rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual)) if actual else None
    baseline_rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, baseline)) / len(actual)) if actual else None
    rank_ic = _spearman(predicted, actual)
    blockers: list[str] = []
    if len(predictions) < MIN_OOS_PREDICTIONS:
        blockers.append("LOW_OOS_PREDICTIONS")
    if len(dates) < MIN_OOS_DATES:
        blockers.append("LOW_OOS_SIGNAL_DATES")
    if len(selected) < MIN_SELECTED_OOS:
        blockers.append("LOW_SELECTED_OOS_PREDICTIONS")
    if selected_low is None or selected_low <= 0:
        blockers.append("SELECTED_ALPHA_LOWER_CI_NOT_POSITIVE")
    if model_rmse is None or baseline_rmse is None or model_rmse >= baseline_rmse:
        blockers.append("MODEL_NOT_BETTER_THAN_EXPANDING_MEAN")
    if rank_ic is None or rank_ic <= 0:
        blockers.append("NON_POSITIVE_RANK_IC")
    if violations:
        blockers.append("TEMPORAL_LEAKAGE_DETECTED")
    return {
        "evidenceStatus": "PASS" if not blockers else "WAIT",
        "blockingReasons": blockers,
        "oosPredictions": len(predictions),
        "oosSignalDates": len(dates),
        "selectedOosPredictions": len(selected),
        "selectedOosSignalDates": selected_dates,
        "selectedBlockMeanResidualAlphaPct": round(selected_mean, 6) if selected_mean is not None else None,
        "selectedBlockBootstrapCi95": [round(selected_low, 6), round(selected_high, 6)] if selected_low is not None and selected_high is not None else None,
        "modelRmse": round(model_rmse, 6) if model_rmse is not None else None,
        "expandingMeanRmse": round(baseline_rmse, 6) if baseline_rmse is not None else None,
        "rankIcSpearman": round(rank_ic, 6) if rank_ic is not None else None,
        "temporalLeakageViolations": violations,
    }


def _recommendation_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_path in sorted(glob.glob(str(REPORTS / "mone_v36_final_recommendations_*.csv"))):
        path = Path(raw_path)
        for row in _read_csv(path):
            row.setdefault("recommendationSource", path.name)
            rows.append(row)
    return rows


def current_predictions(labeled_rows: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        signal_date = _text(candidate.get("asOfDate") or candidate.get("as_of_date") or candidate.get("generatedAt"))[:10]
        train = [row for row in labeled_rows if row["labelAvailableDate"] < signal_date]
        train_dates = {row["signalDate"] for row in train}
        training_fingerprint = training_data_fingerprint(train)
        base = {
            "candidateKey": candidate_key(candidate, signal_date),
            "economicEventKey": economic_event_key(candidate, signal_date),
            "signalDate": signal_date,
            "generatedAt": _text(candidate.get("generatedAt") or candidate.get("generated_at")),
            "market": _text(candidate.get("market")).lower(),
            "mode": _text(candidate.get("mode")).lower(),
            "horizon": _text(candidate.get("horizon")).lower(),
            "symbol": _text(candidate.get("symbol")).upper(),
            "modelFingerprint": _policy_fingerprint(),
            "trainingDataFingerprint": training_fingerprint,
            "modelInstanceFingerprint": model_instance_fingerprint(training_fingerprint),
            "trainRows": len(train),
            "trainDates": len(train_dates),
        }
        if len(train) < MIN_TRAIN_ROWS or len(train_dates) < MIN_TRAIN_DATES:
            output.append({**base, "status": "INSUFFICIENT_TRAINING_HISTORY"})
            continue
        values, baselines, residual_sd = _fit_predict(train, [candidate])
        value = float(values[0])
        output.append({
            **base,
            "status": "PREDICTED",
            "trainMaxLabelAvailableDate": max(row["labelAvailableDate"] for row in train),
            "predictedResidualAlphaPct": round(value, 6),
            "predictionLower90Pct": round(value - LOWER_QUANTILE_Z * residual_sd, 6),
            "baselinePredictionPct": round(float(baselines[0]), 6),
        })
    return output


def record_forward_predictions(
    predictions: list[dict[str, Any]],
    path: Path | None = None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    journal_path = path or PREDICTION_JOURNAL
    now = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    existing = _read_csv(journal_path)
    by_id = {_text(row.get("prediction_id")): row for row in existing if _text(row.get("prediction_id"))}
    pending: list[dict[str, Any]] = []
    conflicts = 0
    duplicate = 0
    late = 0
    missing_time = 0
    future = 0
    fingerprint = _policy_fingerprint()
    for prediction in predictions:
        generated = _parse_generated_at(prediction.get("generatedAt"))
        if generated is None:
            missing_time += 1
            continue
        delay_hours = (now - generated).total_seconds() / 3600.0
        if delay_hours < 0:
            future += 1
            continue
        if delay_hours > MAX_RECORDING_DELAY_HOURS:
            late += 1
            continue
        candidate = _text(prediction.get("candidateKey"))
        prediction_id = _prediction_id(fingerprint, candidate)
        row = {
            "prediction_id": prediction_id,
            "policy_version": POLICY_VERSION,
            "model_fingerprint": fingerprint,
            "recorded_at": now.isoformat(),
            "generated_at": generated.isoformat(),
            "signal_date": prediction.get("signalDate"),
            "candidate_key": candidate,
            "economic_event_key": prediction.get("economicEventKey"),
            "market": prediction.get("market"),
            "mode": prediction.get("mode"),
            "horizon": prediction.get("horizon"),
            "symbol": prediction.get("symbol"),
            "status": prediction.get("status"),
            "train_rows": prediction.get("trainRows"),
            "train_dates": prediction.get("trainDates"),
            "train_max_label_available_date": prediction.get("trainMaxLabelAvailableDate"),
            "training_data_fingerprint": prediction.get("trainingDataFingerprint"),
            "model_instance_fingerprint": prediction.get("modelInstanceFingerprint"),
            "predicted_residual_alpha_pct": prediction.get("predictedResidualAlphaPct"),
            "prediction_lower90_pct": prediction.get("predictionLower90Pct"),
            "baseline_prediction_pct": prediction.get("baselinePredictionPct"),
        }
        row["record_hash"] = _row_hash(row, {"recorded_at"})
        previous = by_id.get(prediction_id)
        if previous:
            if _same_immutable_row(previous, row, {"recorded_at"}):
                duplicate += 1
            else:
                conflicts += 1
            continue
        by_id[prediction_id] = row
        pending.append(row)
    appended, schema_error = _append_csv_rows(journal_path, PREDICTION_FIELDS, pending)
    return {
        "path": str(journal_path.relative_to(ROOT)) if journal_path.is_relative_to(ROOT) else str(journal_path),
        "existingRows": len(existing),
        "appendedRows": appended,
        "duplicateRows": duplicate,
        "lateCandidatesSkipped": late,
        "missingGeneratedAtSkipped": missing_time,
        "futureGeneratedAtSkipped": future,
        "immutableConflicts": conflicts,
        "schemaError": schema_error,
    }


def settle_forward_predictions(
    labeled_rows: list[dict[str, Any]],
    prediction_path: Path | None = None,
    settlement_path: Path | None = None,
    settled_at: datetime | None = None,
) -> dict[str, Any]:
    predictions_path = prediction_path or PREDICTION_JOURNAL
    output_path = settlement_path or SETTLEMENT_JOURNAL
    predictions = _read_csv(predictions_path)
    existing = _read_csv(output_path)
    existing_by_id = {_text(row.get("prediction_id")): row for row in existing if _text(row.get("prediction_id"))}
    labels = {_text(row.get("economicEventKey")): row for row in labeled_rows if _text(row.get("economicEventKey"))}
    now = (settled_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    pending: list[dict[str, Any]] = []
    duplicate = 0
    conflicts = 0
    unresolved = 0
    for prediction in predictions:
        if _text(prediction.get("status")) != "PREDICTED":
            continue
        label = labels.get(_text(prediction.get("economic_event_key")))
        if label is None:
            unresolved += 1
            continue
        prediction_id = _text(prediction.get("prediction_id"))
        row = {
            "prediction_id": prediction_id,
            "model_fingerprint": prediction.get("model_fingerprint"),
            "settled_at": now.isoformat(),
            "signal_date": prediction.get("signal_date"),
            "economic_event_key": prediction.get("economic_event_key"),
            "label_available_date": label.get("labelAvailableDate"),
            "realized_residual_alpha_pct": label.get("residualAlphaPct"),
            "beta": label.get("beta"),
            "market_model_r2": label.get("marketModelR2"),
        }
        row["record_hash"] = _row_hash(row, {"settled_at"})
        previous = existing_by_id.get(prediction_id)
        if previous:
            if _same_immutable_row(previous, row, {"settled_at"}):
                duplicate += 1
            else:
                conflicts += 1
            continue
        existing_by_id[prediction_id] = row
        pending.append(row)
    appended, schema_error = _append_csv_rows(output_path, SETTLEMENT_FIELDS, pending)
    return {
        "path": str(output_path.relative_to(ROOT)) if output_path.is_relative_to(ROOT) else str(output_path),
        "predictionRows": len(predictions),
        "existingRows": len(existing),
        "appendedRows": appended,
        "duplicateRows": duplicate,
        "unresolvedPredictions": unresolved,
        "immutableConflicts": conflicts,
        "schemaError": schema_error,
    }


def live_forward_oos(
    prediction_path: Path | None = None,
    settlement_path: Path | None = None,
    model_fingerprint: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    predictions = _read_csv(prediction_path or PREDICTION_JOURNAL)
    settlements = _read_csv(settlement_path or SETTLEMENT_JOURNAL)
    fingerprint = model_fingerprint or _policy_fingerprint()
    current_predictions = [row for row in predictions if _text(row.get("model_fingerprint")) == fingerprint]
    current_settlements = [row for row in settlements if _text(row.get("model_fingerprint")) == fingerprint]
    prediction_ids = [_text(row.get("prediction_id")) for row in current_predictions]
    settlement_ids = [_text(row.get("prediction_id")) for row in current_settlements]
    prediction_hash_violations = sum(
        _text(row.get("record_hash")) != _row_hash(row, {"recorded_at"}) for row in current_predictions
    )
    settlement_hash_violations = sum(
        _text(row.get("record_hash")) != _row_hash(row, {"settled_at"}) for row in current_settlements
    )
    recording_time_violations = 0
    prediction_lineage_violations = 0
    invalid_lineage_prediction_ids: set[str] = set()
    for row in current_predictions:
        training_fingerprint = _text(row.get("training_data_fingerprint"))
        instance_fingerprint = _text(row.get("model_instance_fingerprint"))
        if (
            not training_fingerprint
            or not instance_fingerprint
            or instance_fingerprint != model_instance_fingerprint(training_fingerprint)
        ):
            prediction_lineage_violations += 1
            invalid_lineage_prediction_ids.add(_text(row.get("prediction_id")))
        generated = _parse_generated_at(row.get("generated_at"))
        recorded = _parse_generated_at(row.get("recorded_at"))
        if generated is None or recorded is None:
            recording_time_violations += 1
            continue
        delay = (recorded - generated).total_seconds() / 3600.0
        if delay < 0 or delay > MAX_RECORDING_DELAY_HOURS:
            recording_time_violations += 1
    settlements_by_id = {_text(row.get("prediction_id")): row for row in current_settlements}
    selected_by_event: dict[str, dict[str, Any]] = {}
    relationship_violations = 0
    for prediction in current_predictions:
        if _text(prediction.get("status")) != "PREDICTED":
            continue
        if _text(prediction.get("prediction_id")) in invalid_lineage_prediction_ids:
            continue
        settlement = settlements_by_id.get(_text(prediction.get("prediction_id")))
        if settlement is None:
            continue
        if (
            _text(settlement.get("economic_event_key")) != _text(prediction.get("economic_event_key"))
            or _text(settlement.get("signal_date")) != _text(prediction.get("signal_date"))
        ):
            relationship_violations += 1
            continue
        event_key = _text(prediction.get("economic_event_key"))
        row = {
            "predictionId": prediction.get("prediction_id"),
            "economicEventKey": event_key,
            "signalDate": prediction.get("signal_date"),
            "labelAvailableDate": settlement.get("label_available_date"),
            "trainMaxLabelAvailableDate": prediction.get("train_max_label_available_date"),
            "trainingDataFingerprint": prediction.get("training_data_fingerprint"),
            "modelInstanceFingerprint": prediction.get("model_instance_fingerprint"),
            "predictedResidualAlphaPct": _num(prediction.get("predicted_residual_alpha_pct")),
            "predictionLower90Pct": _num(prediction.get("prediction_lower90_pct")),
            "baselinePredictionPct": _num(prediction.get("baseline_prediction_pct")),
            "realizedResidualAlphaPct": _num(settlement.get("realized_residual_alpha_pct")),
        }
        if any(row[key] is None for key in (
            "predictedResidualAlphaPct", "predictionLower90Pct",
            "baselinePredictionPct", "realizedResidualAlphaPct",
        )):
            continue
        previous = selected_by_event.get(event_key)
        if previous is None or float(row["predictionLower90Pct"]) > float(previous["predictionLower90Pct"]):
            selected_by_event[event_key] = row
    rows = sorted(selected_by_event.values(), key=lambda row: (row["signalDate"], row["economicEventKey"]))
    integrity = {
        "duplicatePredictionIds": len(prediction_ids) - len(set(prediction_ids)),
        "duplicateSettlementIds": len(settlement_ids) - len(set(settlement_ids)),
        "predictionHashViolations": prediction_hash_violations,
        "settlementHashViolations": settlement_hash_violations,
        "recordingTimeViolations": recording_time_violations,
        "predictionLineageViolations": prediction_lineage_violations,
        "predictionSettlementRelationshipViolations": relationship_violations,
    }
    return rows, {
        "modelFingerprint": fingerprint,
        "predictionJournalRows": len(predictions),
        "settlementJournalRows": len(settlements),
        "settledCurrentModelEconomicEvents": len(rows),
        "journalIntegrity": integrity,
    }


def apply_forward_seal_status(
    predictions: list[dict[str, Any]],
    path: Path | None = None,
) -> list[dict[str, Any]]:
    fingerprint = _policy_fingerprint()
    sealed = {
        _text(row.get("prediction_id")): row
        for row in _read_csv(path or PREDICTION_JOURNAL)
        if _text(row.get("model_fingerprint")) == fingerprint
        and _text(row.get("record_hash")) == _row_hash(row, {"recorded_at"})
    }
    output: list[dict[str, Any]] = []
    for prediction in predictions:
        prediction_id = _prediction_id(fingerprint, _text(prediction.get("candidateKey")))
        row = sealed.get(prediction_id)
        expected = {
            "prediction_id": prediction_id,
            "policy_version": POLICY_VERSION,
            "model_fingerprint": fingerprint,
            "generated_at": (_parse_generated_at(prediction.get("generatedAt")) or ""),
            "signal_date": prediction.get("signalDate"),
            "candidate_key": prediction.get("candidateKey"),
            "economic_event_key": prediction.get("economicEventKey"),
            "market": prediction.get("market"),
            "mode": prediction.get("mode"),
            "horizon": prediction.get("horizon"),
            "symbol": prediction.get("symbol"),
            "status": prediction.get("status"),
            "train_rows": prediction.get("trainRows"),
            "train_dates": prediction.get("trainDates"),
            "train_max_label_available_date": prediction.get("trainMaxLabelAvailableDate"),
            "training_data_fingerprint": prediction.get("trainingDataFingerprint"),
            "model_instance_fingerprint": prediction.get("modelInstanceFingerprint"),
            "predicted_residual_alpha_pct": prediction.get("predictedResidualAlphaPct"),
            "prediction_lower90_pct": prediction.get("predictionLower90Pct"),
            "baseline_prediction_pct": prediction.get("baselinePredictionPct"),
        }
        if isinstance(expected["generated_at"], datetime):
            expected["generated_at"] = expected["generated_at"].isoformat()
        matches = bool(row) and _same_immutable_row(row, expected, {"recorded_at", "record_hash"})
        output.append({
            **prediction,
            "predictionId": prediction_id,
            "forwardSealStatus": "SEALED_FORWARD" if matches else "UNSEALED",
        })
    return output


def filter_recordable_predictions(
    predictions: list[dict[str, Any]],
    record_market: str,
) -> tuple[str, list[dict[str, Any]]]:
    market_filter = _text(record_market).lower()
    if market_filter not in {"all", "kr", "us", "none"}:
        raise ValueError(f"unsupported record market: {record_market}")
    if market_filter == "none":
        return market_filter, []
    return market_filter, [
        row for row in predictions
        if market_filter == "all" or _text(row.get("market")).lower() == market_filter
    ]


def build(
    prediction_path: Path | None = None,
    settlement_path: Path | None = None,
    now: datetime | None = None,
    record_market: str = "none",
    registry_path: Path | None = None,
) -> dict[str, Any]:
    model_registry = register_model(registry_path, now)
    raw = _read_csv(JOURNAL)
    forward = _dedupe_forward_rows(raw)
    labeled, skipped = build_labeled_rows(raw)
    research_oos = expanding_oos(labeled)
    research_validation = validation_summary(research_oos)
    predictions = current_predictions(labeled, _recommendation_rows())
    market_filter, recordable_predictions = filter_recordable_predictions(predictions, record_market)
    prediction_journal = record_forward_predictions(recordable_predictions, prediction_path, now)
    prediction_journal["recordMarket"] = market_filter
    prediction_journal["candidateRowsConsidered"] = len(recordable_predictions)
    predictions = apply_forward_seal_status(predictions, prediction_path)
    settlement_journal = settle_forward_predictions(labeled, prediction_path, settlement_path, now)
    live_oos, live_source = live_forward_oos(prediction_path, settlement_path)
    validation = validation_summary(live_oos)
    integrity_blockers: list[str] = []
    if prediction_journal["immutableConflicts"]:
        integrity_blockers.append("IMMUTABLE_PREDICTION_CONFLICT")
    if settlement_journal["immutableConflicts"]:
        integrity_blockers.append("IMMUTABLE_SETTLEMENT_CONFLICT")
    if prediction_journal["futureGeneratedAtSkipped"]:
        integrity_blockers.append("FUTURE_PREDICTION_TIMESTAMP")
    if prediction_journal["schemaError"] or settlement_journal["schemaError"]:
        integrity_blockers.append("FORWARD_JOURNAL_SCHEMA_MISMATCH")
    if model_registry["versionReuseConflicts"]:
        integrity_blockers.append("MODEL_VERSION_REUSED_FOR_DIFFERENT_MODEL")
    if model_registry["immutableConflicts"] or model_registry["recordHashViolations"]:
        integrity_blockers.append("MODEL_REGISTRY_INTEGRITY_VIOLATION")
    if model_registry["schemaError"]:
        integrity_blockers.append("MODEL_REGISTRY_SCHEMA_MISMATCH")
    journal_integrity = live_source.get("journalIntegrity") or {}
    if any(int(value or 0) > 0 for value in journal_integrity.values()):
        integrity_blockers.append("FORWARD_JOURNAL_INTEGRITY_VIOLATION")
    if integrity_blockers:
        validation["blockingReasons"] = list(dict.fromkeys(validation["blockingReasons"] + integrity_blockers))
        validation["evidenceStatus"] = "WAIT"
    validation["source"] = "IMMUTABLE_FORWARD_PREDICTION_AND_SETTLEMENT_JOURNALS"
    return {
        "status": "SHADOW_ONLY",
        "generatedAt": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "policy": {**_policy(), "fingerprint": _policy_fingerprint()},
        "data": {
            "rawJournalRows": len(raw),
            "forwardIndependentRows": len(forward),
            "labeledIndependentDecisions": len(labeled),
            "distinctSignalDates": len({row["signalDate"] for row in labeled}),
            "skipped": skipped,
        },
        "validation": validation,
        "researchValidation": {
            **research_validation,
            "source": "RECOMPUTED_EXPANDING_WALK_FORWARD_RESEARCH_ONLY",
            "promotionEligible": False,
        },
        "forwardEvidence": {
            **live_source,
            "modelRegistry": model_registry,
            "predictionJournal": prediction_journal,
            "settlementJournal": settlement_journal,
            "integrityBlockingReasons": integrity_blockers,
        },
        "summary": {
            "candidates": len(predictions),
            "predicted": sum(1 for row in predictions if row["status"] == "PREDICTED"),
            "positiveLower90": sum(1 for row in predictions if (row.get("predictionLower90Pct") or -math.inf) > 0),
            "evidenceStatus": validation["evidenceStatus"],
        },
        "predictions": predictions,
        "forwardOosAudit": live_oos,
        "researchOosAudit": research_oos,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--record-market", choices=("all", "kr", "us", "none"), default="none")
    args = parser.parse_args()
    report = build(record_market=args.record_market)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"data": report["data"], "validation": report["validation"], "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
