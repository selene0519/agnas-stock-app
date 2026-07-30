from __future__ import annotations

import csv
import importlib.util
from datetime import date, datetime, timedelta, timezone
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


def _forward_prediction(generated_at: str, candidate: str = "candidate-a", lower: float = 0.5) -> dict:
    return {
        "candidateKey": candidate,
        "economicEventKey": "event-a",
        "signalDate": "2026-07-30",
        "generatedAt": generated_at,
        "market": "kr",
        "mode": "balanced",
        "horizon": "short",
        "symbol": "005930",
        "status": "PREDICTED",
        "trainRows": 150,
        "trainDates": 30,
        "trainMaxLabelAvailableDate": "2026-07-29",
        "predictedResidualAlphaPct": 1.0,
        "predictionLower90Pct": lower,
        "baselinePredictionPct": 0.1,
    }


def test_forward_prediction_journal_records_timely_naive_kst_once(tmp_path) -> None:
    journal = tmp_path / "predictions.csv"
    now = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    prediction = _forward_prediction("2026-07-30 09:00:00")  # naive recommendation timestamps are KST

    first = model.record_forward_predictions([prediction], journal, now)
    second = model.record_forward_predictions([prediction], journal, now + timedelta(minutes=5))

    assert first["appendedRows"] == 1
    assert second["appendedRows"] == 0
    assert second["duplicateRows"] == 1
    rows = model._read_csv(journal)
    assert len(rows) == 1
    assert rows[0]["generated_at"] == "2026-07-30T00:00:00+00:00"


def test_forward_prediction_journal_never_backfills_stale_candidate(tmp_path) -> None:
    journal = tmp_path / "predictions.csv"
    result = model.record_forward_predictions(
        [_forward_prediction("2026-07-29 09:00:00")],
        journal,
        datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc),
    )

    assert result["lateCandidatesSkipped"] == 1
    assert result["appendedRows"] == 0
    assert not journal.exists()


def test_forward_prediction_journal_detects_immutable_conflict(tmp_path) -> None:
    journal = tmp_path / "predictions.csv"
    now = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    model.record_forward_predictions([_forward_prediction("2026-07-30 09:00:00")], journal, now)
    changed = {**_forward_prediction("2026-07-30 09:00:00"), "predictedResidualAlphaPct": 99.0}

    result = model.record_forward_predictions([changed], journal, now)

    assert result["immutableConflicts"] == 1
    assert len(model._read_csv(journal)) == 1


def test_settlement_is_append_only_and_live_oos_uses_current_fingerprint(tmp_path) -> None:
    prediction_journal = tmp_path / "predictions.csv"
    settlement_journal = tmp_path / "settlements.csv"
    now = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    model.record_forward_predictions(
        [_forward_prediction("2026-07-30 09:00:00")], prediction_journal, now
    )
    label = {
        "economicEventKey": "event-a",
        "labelAvailableDate": "2026-08-06",
        "residualAlphaPct": 2.5,
        "beta": 0.8,
        "marketModelR2": 0.4,
    }

    first = model.settle_forward_predictions([label], prediction_journal, settlement_journal, now)
    second = model.settle_forward_predictions([label], prediction_journal, settlement_journal, now + timedelta(days=1))
    rows, source = model.live_forward_oos(prediction_journal, settlement_journal)

    assert first["appendedRows"] == 1
    assert second["duplicateRows"] == 1
    assert len(rows) == 1
    assert rows[0]["realizedResidualAlphaPct"] == 2.5
    assert source["settledCurrentModelEconomicEvents"] == 1


def test_forward_journal_hash_detects_manual_prediction_mutation(tmp_path) -> None:
    prediction_journal = tmp_path / "predictions.csv"
    now = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    model.record_forward_predictions(
        [_forward_prediction("2026-07-30 09:00:00")], prediction_journal, now
    )
    rows = model._read_csv(prediction_journal)
    rows[0]["prediction_lower90_pct"] = "999"
    with prediction_journal.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=model.PREDICTION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    _, source = model.live_forward_oos(prediction_journal, tmp_path / "settlements.csv")
    sealed = model.apply_forward_seal_status(
        [_forward_prediction("2026-07-30 09:00:00")], prediction_journal
    )

    assert source["journalIntegrity"]["predictionHashViolations"] == 1
    assert sealed[0]["forwardSealStatus"] == "UNSEALED"


def test_recomputed_research_validation_cannot_promote(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(model, "_read_csv", lambda path: [])
    monkeypatch.setattr(model, "build_labeled_rows", lambda rows: ([], {}))
    monkeypatch.setattr(model, "expanding_oos", lambda rows: [{"research": True}])
    monkeypatch.setattr(model, "_recommendation_rows", lambda: [])
    monkeypatch.setattr(
        model,
        "validation_summary",
        lambda rows: {
            "evidenceStatus": "PASS" if rows else "WAIT",
            "blockingReasons": [] if rows else ["LOW_OOS_PREDICTIONS"],
            "oosPredictions": len(rows),
            "oosSignalDates": len(rows),
        },
    )

    report = model.build(
        tmp_path / "predictions.csv",
        tmp_path / "settlements.csv",
        datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc),
    )

    assert report["researchValidation"]["evidenceStatus"] == "PASS"
    assert report["researchValidation"]["promotionEligible"] is False
    assert report["validation"]["evidenceStatus"] == "WAIT"
    assert report["validation"]["source"] == "IMMUTABLE_FORWARD_PREDICTION_AND_SETTLEMENT_JOURNALS"


def test_scheduled_pipeline_builds_residual_model_before_meta_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "mone-settle-validations.yml").read_text(encoding="utf-8")
    accumulator = (ROOT / ".github" / "workflows" / "mone-auto-accumulator.yml").read_text(encoding="utf-8")
    commit_script = (ROOT / "scripts" / "ci_commit_app_data.sh").read_text(encoding="utf-8")

    assert workflow.index("scripts/build_shadow_residual_alpha.py") < workflow.index("scripts/build_shadow_meta_gate.py")
    assert "reports/shadow_residual_alpha.json" in workflow
    assert "data/shadow_residual_alpha_predictions.csv" in workflow
    assert "data/shadow_residual_alpha_settlements.csv" in workflow
    assert accumulator.index("scripts/generate_us_recommendations.py") < accumulator.index("scripts/build_shadow_residual_alpha.py")
    assert "data/shadow_residual_alpha_predictions.csv" in commit_script
    assert "data/shadow_residual_alpha_settlements.csv" in commit_script
