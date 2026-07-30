from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_shadow_residual_alpha",
    ROOT / "scripts" / "build_shadow_residual_alpha.py",
)
assert SPEC and SPEC.loader
model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model)


def _row(day: int, available_offset: int, value: float, feature: float | None = None) -> dict:
    return {
        "signalDate": f"2026-01-{day:02d}",
        "labelAvailableDate": f"2026-01-{day + available_offset:02d}",
        "candidateKey": f"key-{day}-{value}",
        "residualAlphaPct": value,
        "final_rank_score": feature if feature is not None else value,
        "market": "us",
        "mode": "balanced",
        "horizon": "short",
    }


def test_candidate_key_is_stable_and_policy_independent() -> None:
    row = {"market": "us", "mode": "balanced", "horizon": "short", "symbol": "AAPL"}

    assert model.candidate_key(row, "2026-07-30") == model.candidate_key(row, "2026-07-30")
    assert model.candidate_key(row, "2026-07-30") != model.candidate_key(row, "2026-07-31")


def test_same_stock_date_and_label_window_is_one_economic_event() -> None:
    base = {
        "source_type": "FORWARD_PAPER_TRADE",
        "journal_session": "AFTER_CLOSE_TRADE",
        "as_of_date": "2026-07-30",
        "market": "kr",
        "symbol": "005930",
        "horizon": "mid",
    }
    rows = [
        {**base, "mode": "balanced", "final_rank_score": "70"},
        {**base, "mode": "aggressive", "horizon": "swing", "final_rank_score": "80"},
        {**base, "mode": "balanced", "horizon": "short", "final_rank_score": "60"},
    ]

    selected = model._dedupe_forward_rows(rows)

    assert len(selected) == 2
    assert {row["final_rank_score"] for row in selected} == {"80", "60"}


def test_predictive_label_excludes_already_known_signal_day_return() -> None:
    start = date(2025, 1, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(330)]
    signal_index = 270
    stock = np.full(len(dates), 100.0)
    stock[signal_index:] = 200.0  # jump occurs into the signal-day close
    benchmark = np.full(len(dates), 100.0)
    signal_date = dates[signal_index]
    row = {
        "source_type": "FORWARD_PAPER_TRADE",
        "journal_session": "AFTER_CLOSE_TRADE",
        "as_of_date": signal_date,
        "market": "us",
        "symbol": "TEST",
        "mode": "balanced",
        "horizon": "short",
    }

    label, reason = model._event_label(
        row,
        {("us", "TEST"): (dates, stock)},
        {("us", "SPY"): (dates, benchmark)},
        {},
    )

    assert reason is None
    assert label is not None
    assert abs(label["residualAlphaPct"]) < 1e-9
    assert label["labelAvailableDate"] == dates[signal_index + model.HORIZON_WINDOWS["short"]]


def test_expanding_oos_uses_only_labels_available_before_signal(monkeypatch) -> None:
    monkeypatch.setattr(model, "MIN_TRAIN_ROWS", 2)
    monkeypatch.setattr(model, "MIN_TRAIN_DATES", 2)
    rows = [
        _row(1, 1, 1.0),
        _row(2, 1, 2.0),
        _row(3, 1, 1000.0),  # same-day availability must not enter day-4 training
        _row(4, 1, 4.0),
    ]

    predictions = model.expanding_oos(rows)

    day4 = next(row for row in predictions if row["signalDate"] == "2026-01-04")
    assert day4["trainRows"] == 2
    assert day4["trainMaxLabelAvailableDate"] == "2026-01-03"
    assert day4["trainMaxLabelAvailableDate"] < day4["signalDate"]


def test_validation_fails_closed_on_any_temporal_violation(monkeypatch) -> None:
    monkeypatch.setattr(model, "MIN_OOS_PREDICTIONS", 1)
    monkeypatch.setattr(model, "MIN_OOS_DATES", 1)
    monkeypatch.setattr(model, "MIN_SELECTED_OOS", 1)
    predictions = [{
        "signalDate": "2026-07-01",
        "labelAvailableDate": "2026-07-10",
        "trainMaxLabelAvailableDate": "2026-07-01",
        "predictedResidualAlphaPct": 2.0,
        "predictionLower90Pct": 1.0,
        "baselinePredictionPct": 0.0,
        "realizedResidualAlphaPct": 2.0,
    }]

    result = model.validation_summary(predictions)

    assert result["evidenceStatus"] == "WAIT"
    assert "TEMPORAL_LEAKAGE_DETECTED" in result["blockingReasons"]


def test_ridge_prediction_learns_direction_without_probability_semantics() -> None:
    train = []
    for index in range(1, 41):
        feature = float(index)
        train.append(_row(1, 1, feature * 0.5, feature=feature))
    low = {**train[0], "final_rank_score": 2.0}
    high = {**train[0], "final_rank_score": 38.0}

    predictions, _, _ = model._fit_predict(train, [low, high])

    assert predictions[1] > predictions[0]


def test_camel_case_candidate_features_use_training_schema() -> None:
    row = {"finalRankScore": "88.5", "rrActual": "2.1", "rsi14": "55"}

    assert model._feature_num(row, "final_rank_score") == 88.5
    assert model._feature_num(row, "risk_reward_ratio") == 2.1
    assert model._feature_num(row, "rsi_at_entry") == 55.0


def test_current_prediction_refuses_insufficient_training(monkeypatch) -> None:
    monkeypatch.setattr(model, "MIN_TRAIN_ROWS", 3)
    monkeypatch.setattr(model, "MIN_TRAIN_DATES", 2)
    labeled = [_row(1, 1, 1.0)]
    candidate = {"asOfDate": "2026-01-10", "market": "us", "mode": "balanced", "horizon": "short", "symbol": "AAPL"}

    result = model.current_predictions(labeled, [candidate])

    assert result[0]["status"] == "INSUFFICIENT_TRAINING_HISTORY"


def test_scheduled_pipeline_builds_residual_model_before_meta_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "mone-settle-validations.yml").read_text(encoding="utf-8")

    assert workflow.index("scripts/build_shadow_residual_alpha.py") < workflow.index("scripts/build_shadow_meta_gate.py")
    assert "reports/shadow_residual_alpha.json" in workflow
