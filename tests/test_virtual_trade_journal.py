from __future__ import annotations

import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engine import correction_store  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def _write_valid_calibration_promotion_certificate(approval: dict, suggestion: dict) -> dict:
    market = str(approval["market"])
    mode = str(approval["mode"])
    horizon = str(approval["horizon"])
    source_type = str(approval["source_type"])
    raw_samples = int(float(approval["sample_count"]))
    source_weight = vtj._source_weight(source_type)
    effective_samples = max(30, int(round(raw_samples * source_weight)))
    delta = vtj._approved_delta(str(approval["reason"]), float(approval["share"]), source_weight)
    before = correction_store.load_correction(market, mode, horizon)
    after = vtj._clamp_nested_adjustments(vtj._merge_nested_adjustments(before, delta))
    after.update({
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sampleCount": max(int(before.get("sampleCount") or 0), effective_samples),
        "rawJournalSampleCount": raw_samples,
        "effectiveJournalSampleCount": effective_samples,
        "confidence": min(
            vtj._source_confidence_cap(source_type),
            max(float(before.get("confidence") or 0.0), vtj._confidence_from_effective_samples(effective_samples)),
        ),
        "journalCalibrationApplied": True,
        "journalCalibrationSource": approval["approval_id"],
        "journalCalibrationSourceType": source_type,
    })
    top = list(before.get("topFailureReasons") or [])
    reason = str(approval["reason"])
    if reason and reason not in top:
        top.insert(0, reason)
    after["topFailureReasons"] = top[:8]
    candidate_fingerprint = vtj._correction_candidate_fingerprint(
        approval,
        str(approval["evidence_fingerprint"]),
        before,
        after,
        delta,
    )
    certificate = {
        "version": vtj.CALIBRATION_PROMOTION_VERSION,
        "approvalId": approval["approval_id"],
        "approvalRecordHash": approval["record_hash"],
        "evidenceFingerprint": approval["evidence_fingerprint"],
        "calibrationPolicyFingerprint": vtj._calibration_policy_fingerprint(),
        "candidateFingerprint": candidate_fingerprint,
        "shadowPolicyVersion": vtj.CALIBRATION_SHADOW_POLICY["version"],
        "shadowPolicyFingerprint": vtj._calibration_shadow_policy_fingerprint(),
        "evaluationPolicyVersion": vtj.EVALUATION_POLICY["version"],
        "evaluationPolicyFingerprint": vtj._evaluation_policy_fingerprint(),
        "promotionEligible": True,
        "decision": "READY_FOR_HUMAN_REVIEW",
        "completedSignalDates": vtj.CALIBRATION_PROMOTION_MIN_SIGNAL_DATES,
        "evaluatedChallengerTrades": vtj.CALIBRATION_PROMOTION_MIN_TRADES,
        "avgAfterCostReturnPct": 0.1,
        "pairedUpliftCi95": [0.01, 0.2],
        "championMaxDrawdownPct": 8.0,
        "challengerMaxDrawdownPct": 6.0,
    }
    certificate["recordHash"] = vtj._promotion_certificate_hash(certificate)
    vtj.CALIBRATION_PROMOTION_JSON.parent.mkdir(parents=True, exist_ok=True)
    vtj.CALIBRATION_PROMOTION_JSON.write_text(
        json.dumps({"certificates": [certificate]}),
        encoding="utf-8",
    )
    return certificate


def test_negative_expectancy_attribution_never_boosts_a_strategy() -> None:
    multiplier = vtj._attribution_multiplier(
        win_rate=0.27,
        avg_pnl=-3.52,
        base_win_rate=0.35,
        base_avg_pnl=-1.92,
    )

    assert multiplier < 0.95


def test_positive_expectancy_attribution_can_reward_a_strategy() -> None:
    multiplier = vtj._attribution_multiplier(
        win_rate=0.62,
        avg_pnl=2.4,
        base_win_rate=0.45,
        base_avg_pnl=0.8,
    )

    assert multiplier > 1.0


def test_ops_dashboard_uses_persisted_learning_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "self_learning_status.json"
    snapshot_path.write_text(
        json.dumps({
            "status": "OK",
            "generatedAt": "2026-07-28T10:00:00",
            "latest": {
                "status": "SHADOW_ONLY",
                "market": "all",
                "generatedAt": "2026-07-28T09:00:00",
                "policyFingerprint": vtj._calibration_policy_fingerprint(),
                "quality": {"score": 88},
                "eligibleCount": 2,
                "applied": 0,
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(vtj, "SELF_LEARNING_STATUS_JSON", snapshot_path)
    monkeypatch.setattr(vtj, "JOURNAL_CSV", tmp_path / "journal.csv")
    monkeypatch.setattr(vtj, "EVALUATION_CSV", tmp_path / "evaluations.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPROVALS_CSV", tmp_path / "approvals.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPLICATIONS_CSV", tmp_path / "applications.csv")
    monkeypatch.setattr(vtj, "self_learning_status", lambda *_args, **_kwargs: pytest.fail("ops dashboard must not recalculate learning"))

    dashboard = vtj.ops_dashboard("all")

    assert dashboard["selfLearning"]["status"] == "SHADOW_ONLY"
    assert dashboard["selfLearning"]["quality"] == {"score": 88}
    assert dashboard["performanceGate"]["status"] == "DEFERRED"


def test_ops_dashboard_rejects_stale_self_learning_policy_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "self_learning_status.json"
    snapshot_path.write_text(
        json.dumps({
            "status": "OK",
            "generatedAt": "2026-07-28T10:00:00",
            "latest": {
                "status": "OK",
                "market": "all",
                "generatedAt": "2026-07-28T09:00:00",
                "policyFingerprint": "obsolete-policy",
                "quality": {"score": 100},
                "eligibleCount": 4,
                "applied": 4,
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(vtj, "SELF_LEARNING_STATUS_JSON", snapshot_path)
    monkeypatch.setattr(vtj, "JOURNAL_CSV", tmp_path / "journal.csv")
    monkeypatch.setattr(vtj, "EVALUATION_CSV", tmp_path / "evaluations.csv")

    persisted = vtj._persisted_self_learning_status("all")

    assert persisted["status"] == "STALE"
    assert persisted["reason"] == "POLICY_MISMATCH"
    assert persisted["quality"] is None
    assert persisted["persistedPolicyFingerprint"] == "obsolete-policy"


def _valid_recommendation(symbol: str = "TEST") -> dict:
    return {
        "market": "kr",
        "mode": "balanced",
        "horizon": "swing",
        "symbol": symbol,
        "name": symbol,
        "decisionBucket": vtj.TODAY_ENTRY,
        "entry": 100,
        "stop": 95,
        "target": 112,
        "currentPrice": 100,
        "finalRankScore": 80,
        "expectedValue": 3,
        "riskRewardRatio": 2.4,
        "probability": 65,
        "riskScore": 70,
        "eventRiskScore": 30,
        "dataStatus": "NORMAL",
        "tradeBlockStatus": "",
        "priceSource": "pytest",
        "marketRegime": "RISK_ON",
        "generatedAt": "2026-06-18T08:20:00",
        "appliedCorrectionVersion": 42,
        "modelVersion": "ranker-test-v1",
        "codeVersion": "deadbeef",
    }


def test_snapshot_records_immutable_strategy_and_decision_identity() -> None:
    item = _valid_recommendation("IDENTITY")

    first = vtj._snapshot_from_item(item, "FORWARD_PAPER_TRADE", "2026-06-18")
    second = vtj._snapshot_from_item({**item, "finalRankScore": 91}, "FORWARD_PAPER_TRADE", "2026-06-18")

    assert first["decision_unit_id"] == second["decision_unit_id"]
    assert first["strategy_fingerprint"] == second["strategy_fingerprint"]
    assert first["strategy_identity_status"] == "FULL"
    assert first["correction_version_at_signal"] == "42"
    assert first["data_cutoff_at_signal"] == "2026-06-18"


def test_decision_unit_dedup_keeps_highest_score_and_marks_legacy_rows() -> None:
    rows = [
        {"as_of_date": "2026-06-18", "market": "kr", "symbol": "005930", "final_rank_score": 70},
        {"as_of_date": "2026-06-18", "market": "kr", "symbol": "005930", "final_rank_score": 82},
        {"as_of_date": "2026-06-19", "market": "kr", "symbol": "005930", "final_rank_score": 65},
    ]

    out = vtj._dedupe_decision_units(rows)

    assert len(out) == 2
    assert out[0]["final_rank_score"] == 82
    assert all(row["strategy_fingerprint"] == "LEGACY_UNFINGERPRINTED" for row in out)


def test_strategy_diagnostics_do_not_drop_the_same_symbol_from_other_sleeves() -> None:
    rows = [
        {"as_of_date": "2026-06-18", "market": "kr", "symbol": "005930", "mode": "balanced", "horizon": "swing"},
        {"as_of_date": "2026-06-18", "market": "kr", "symbol": "005930", "mode": "aggressive", "horizon": "swing"},
    ]

    assert len(vtj._dedupe_decision_units(rows)) == 1
    assert len(vtj._dedupe_decision_units(rows, within_strategy=True)) == 2


@pytest.fixture()
def isolated_vtj(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(vtj, "JOURNAL_CSV", tmp_path / "journal.csv")
    monkeypatch.setattr(vtj, "EVALUATION_CSV", tmp_path / "evaluations.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPROVALS_CSV", tmp_path / "approvals.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPLICATIONS_CSV", tmp_path / "applications.csv")
    monkeypatch.setattr(vtj, "AUTO_CAPTURE_STATUS_JSON", tmp_path / "status.json")
    monkeypatch.setattr(vtj, "SELF_LEARNING_STATUS_JSON", tmp_path / "self_learning_status.json")
    monkeypatch.setattr(vtj, "HISTORY_OPERATION_CSV", tmp_path / "history.csv")
    monkeypatch.setattr(vtj, "HISTORY_EVALUATION_CSV", tmp_path / "history_eval.csv")
    monkeypatch.setattr(vtj, "VIRTUAL_VALIDATION_RESULTS_CSV", tmp_path / "virtual_validation_results.csv")
    monkeypatch.setattr(vtj, "HISTORICAL_CALIBRATION_REPORT_JSON", tmp_path / "historical_strategy_calibration.json")
    monkeypatch.setattr(vtj, "_FEEDBACK_JSON", tmp_path / "attribution_feedback.json")
    vtj._ensure()
    return tmp_path


def test_stop_wins_when_target_and_stop_touch_same_daily_candle() -> None:
    holding = pd.DataFrame([{"date": "2026-01-02", "open": 100, "high": 112, "low": 94, "close": 104}])

    out = vtj._find_exit(holding, entry=100, stop=95, target=110, eval_window=5)

    assert out["exit_kind"] == "STOP"
    assert out["exit_price"] == 95
    assert out["exit_date"] == "2026-01-02"
    assert out["targetTouched"] is True
    assert out["stopTouched"] is True
    assert out["targetBeforeStop"] is False


def test_limit_touch_does_not_credit_ambiguous_target_on_fill_bar() -> None:
    holding = pd.DataFrame([
        {"date": "2026-01-02", "open": 105, "high": 112, "low": 99, "close": 104},
        {"date": "2026-01-03", "open": 104, "high": 106, "low": 100, "close": 105},
    ])

    out = vtj._find_exit(
        holding,
        entry=100,
        stop=95,
        target=110,
        eval_window=2,
        allow_first_bar_target=False,
    )

    assert out["exit_kind"] == "TIME"
    assert out["targetTouched"] is False


def test_stop_gap_uses_open_instead_of_optimistic_stop_price() -> None:
    holding = pd.DataFrame([
        {"date": "2026-01-02", "open": 90, "high": 94, "low": 88, "close": 91},
    ])

    out = vtj._find_exit(holding, entry=100, stop=95, target=110, eval_window=5)

    assert out["exit_kind"] == "STOP"
    assert out["exit_price"] == 90


def test_evaluate_one_applies_limit_fill_bar_target_embargo(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"date": "2026-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"date": "2026-01-02", "open": 105, "high": 112, "low": 99, "close": 104, "volume": 1000},
    ]
    rows.extend([
        {"date": f"2026-01-0{day}", "open": 104, "high": 108, "low": 99, "close": 105, "volume": 1000}
        for day in range(3, 7)
    ])
    ohlcv = pd.DataFrame(rows)
    ohlcv["_date_ts"] = pd.to_datetime(ohlcv["date"], errors="coerce").dt.normalize()
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (ohlcv.copy(), "pytest", "actual_ohlcv"))

    out = vtj._evaluate_one({
        "journal_id": "ambiguous-fill-target",
        "market": "kr",
        "symbol": "TEST",
        "horizon": "short",
        "as_of_date": "2026-01-01",
        "entry_type": "LIMIT_TOUCH",
        "entry_price": 100,
        "stop_price": 95,
        "target_price": 110,
    })

    assert out["outcome"] != "TARGET_HIT"
    assert out["targetTouched"] is False
    assert out["exit_date"] == "2026-01-06"
    assert out["evaluation_policy_version"] == vtj.EVALUATION_POLICY["version"]
    assert out["evaluation_policy_fingerprint"] == vtj._evaluation_policy_fingerprint()


def test_evaluate_one_records_touch_order_and_excursions(monkeypatch: pytest.MonkeyPatch) -> None:
    ohlcv = pd.DataFrame(
        [
            {"date": "2026-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"date": "2026-01-02", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"date": "2026-01-03", "open": 103, "high": 112, "low": 101, "close": 111, "volume": 1000},
            {"date": "2026-01-04", "open": 111, "high": 113, "low": 109, "close": 112, "volume": 1000},
        ]
    )
    ohlcv["_date_ts"] = pd.to_datetime(ohlcv["date"], errors="coerce").dt.normalize()
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (ohlcv.copy(), "pytest", "actual_ohlcv"))

    out = vtj._evaluate_one(
        {
            "journal_id": "touch-target",
            "market": "kr",
            "symbol": "TEST",
            "horizon": "swing",
            "as_of_date": "2026-01-01",
            "entry_type": "LIMIT_TOUCH",
            "entry_price": 100,
            "stop_price": 95,
            "target_price": 110,
            "data_status": "NORMAL",
            "data_confidence": "HIGH",
            "market_regime_at_signal": "RISK_ON",
        }
    )

    assert out["entryTouched"] is True
    assert out["targetTouched"] is True
    assert out["stopTouched"] is False
    assert out["targetBeforeStop"] is True
    assert out["entryTouchDate"] == "2026-01-02"
    assert out["targetTouchDate"] == "2026-01-03"
    assert out["maxFavorableExcursion"] == out["mfe_pct"]
    assert out["maxAdverseExcursion"] == out["mae_pct"]
    assert out["holdingDays"] == out["bars_held"]
    assert out["failureReason"] == "TARGET_BEFORE_STOP"


def test_evaluate_one_does_not_fill_when_entry_is_not_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    ohlcv = pd.DataFrame(
        [{"date": f"2026-01-{day:02d}", "open": 95, "high": 99, "low": 92, "close": 96, "volume": 1000} for day in range(1, 9)]
    )
    ohlcv["_date_ts"] = pd.to_datetime(ohlcv["date"], errors="coerce").dt.normalize()
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (ohlcv.copy(), "pytest", "actual_ohlcv"))

    out = vtj._evaluate_one(
        {
            "journal_id": "touch-miss",
            "market": "kr",
            "symbol": "TEST",
            "horizon": "swing",
            "as_of_date": "2026-01-01",
            "entry_type": "LIMIT_TOUCH",
            "entry_price": 100,
            "stop_price": 95,
            "target_price": 110,
        }
    )

    assert out["status"] == "CANCELLED"
    assert out["entryTouched"] is False
    assert out["targetTouched"] is False
    assert out["stopTouched"] is False
    assert out["failureReason"] == "ENTRY_NOT_TOUCHED"


def _journal_eval_row(**overrides) -> dict:
    row = {
        "journal_id": "diag",
        "market": "kr",
        "symbol": "TEST",
        "horizon": "short",
        "as_of_date": "2026-01-01",
        "entry_type": "LIMIT_TOUCH",
        "entry_price": 100,
        "stop_price": 95,
        "target_price": 110,
        "data_status": "NORMAL",
        "data_confidence": "HIGH",
        "market_regime_at_signal": "RISK_ON",
    }
    row.update(overrides)
    return row


def _ohlcv(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["_date_ts"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def test_evaluate_one_marks_no_future_bars_as_pending_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    ohlcv = _ohlcv([{"date": "2026-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}])
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (ohlcv.copy(), "pytest", "actual_ohlcv"))

    out = vtj._evaluate_one(_journal_eval_row())

    assert out["status"] == "DATA_PENDING"
    assert out["failureReason"] == "NO_FUTURE_BARS_YET"
    assert out["diagnosticReason"] == "NO_FUTURE_BARS_YET"


def test_evaluate_one_marks_open_entry_window_as_pending_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    ohlcv = _ohlcv(
        [
            {"date": "2026-01-01", "open": 95, "high": 96, "low": 94, "close": 95, "volume": 1000},
            {"date": "2026-01-02", "open": 95, "high": 99, "low": 94, "close": 96, "volume": 1000},
            {"date": "2026-01-03", "open": 96, "high": 99, "low": 94, "close": 96, "volume": 1000},
        ]
    )
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (ohlcv.copy(), "pytest", "actual_ohlcv"))

    out = vtj._evaluate_one(_journal_eval_row())

    assert out["status"] == "PENDING"
    assert out["entryTouched"] is False
    assert out["failureReason"] == "PENDING_EVALUATION"


def test_evaluate_one_marks_open_holding_period_without_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    ohlcv = _ohlcv(
        [
            {"date": "2026-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"date": "2026-01-02", "open": 100, "high": 103, "low": 98, "close": 101, "volume": 1000},
            {"date": "2026-01-03", "open": 101, "high": 104, "low": 99, "close": 102, "volume": 1000},
            {"date": "2026-01-04", "open": 102, "high": 105, "low": 100, "close": 103, "volume": 1000},
        ]
    )
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (ohlcv.copy(), "pytest", "actual_ohlcv"))

    out = vtj._evaluate_one(_journal_eval_row())

    assert out["status"] == "PENDING"
    assert out["entryTouched"] is True
    assert out["targetTouched"] is False
    assert out["stopTouched"] is False
    assert out["failureReason"] == "INSUFFICIENT_HOLDING_PERIOD"
    assert out["diagnosticReason"] == "ENTRY_TOUCHED_BUT_NO_EXIT"


def test_evaluate_one_marks_missing_price_levels_without_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    ohlcv = _ohlcv([{"date": "2026-01-02", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}])
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (ohlcv.copy(), "pytest", "actual_ohlcv"))

    assert vtj._evaluate_one(_journal_eval_row(entry_price=""))["failureReason"] == "MISSING_ENTRY_PRICE"
    assert vtj._evaluate_one(_journal_eval_row(target_price=""))["failureReason"] == "MISSING_TARGET_OR_STOP"
    assert vtj._evaluate_one(_journal_eval_row(stop_price=105))["failureReason"] == "PRICE_INVALID"


def test_classify_failure_reason_refines_legacy_unknown_rows() -> None:
    assert vtj.classify_failure_reason({"status": "PENDING", "outcome": "PENDING", "failureReason": "UNKNOWN", "review_text": "Entry window still open.", "entryTouched": False}) == "PENDING_EVALUATION"
    assert vtj.classify_failure_reason({"status": "PENDING", "outcome": "PENDING", "failureReason": "UNKNOWN", "review_text": "Evaluation window still open.", "entryTouched": True}) == "INSUFFICIENT_HOLDING_PERIOD"
    assert vtj.classify_failure_reason({"status": "EVALUATED", "outcome": "UNKNOWN", "failureReason": "UNKNOWN", "entryTouched": True, "targetTouched": False, "stopTouched": False}) == "ENTRY_TOUCHED_BUT_NO_EXIT"


def test_time_exit_taxonomy_keeps_near_target_near_stop_mid_and_flat() -> None:
    assert vtj._outcome("TIME", target_progress=0.85, stop_progress=0.2, net=2.0) == "TIME_EXIT_NEAR_TARGET"
    assert vtj._outcome("TIME", target_progress=0.2, stop_progress=0.85, net=-2.0) == "TIME_EXIT_NEAR_STOP"
    assert vtj._outcome("TIME", target_progress=0.85, stop_progress=0.85, net=1.0) == "TIME_EXIT_MID"
    assert vtj._outcome("TIME", target_progress=0.2, stop_progress=0.2, net=0.1) == "TIME_EXIT_FLAT"


def test_historical_replay_generation_receives_only_cutoff_bars(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of_date = "2026-03-31"
    full = pd.DataFrame(
        [
            {"date": f"2026-01-{day:02d}", "open": 100 + day, "high": 101 + day, "low": 99 + day, "close": 100 + day}
            for day in range(1, 29)
        ]
        + [
            {"date": f"2026-02-{day:02d}", "open": 128 + day, "high": 129 + day, "low": 127 + day, "close": 128 + day}
            for day in range(1, 29)
        ]
        + [
            {"date": f"2026-03-{day:02d}", "open": 156 + day, "high": 157 + day, "low": 155 + day, "close": 156 + day}
            for day in range(1, 32)
        ]
        + [
            {"date": "2026-04-01", "open": 220, "high": 230, "low": 210, "close": 225},
        ]
    )
    full["_date_ts"] = pd.to_datetime(full["date"], errors="coerce").dt.normalize()

    monkeypatch.setattr(vtj, "_ohlcv_symbols_for_market", lambda market: ["TEST"])
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (full.copy(), str(isolated_vtj / "test.csv"), "actual_ohlcv"))

    def fake_item(symbol, market, mode, horizon, cutoff_date, cutoff, source):
        assert str(cutoff["_date_ts"].max().date()) == as_of_date
        assert "2026-04-01" not in set(cutoff["date"].astype(str))
        return {
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "symbol": symbol,
            "name": symbol,
            "decisionBucket": vtj.TODAY_ENTRY,
            "entry": 188,
            "stop": 178,
            "target": 208,
            "currentPrice": 188,
            "finalRankScore": 80,
            "expectedValue": 3,
            "riskRewardRatio": 2,
            "probability": 65,
            "riskScore": 70,
            "eventRiskScore": 30,
            "dataStatus": "NORMAL",
            "tradeBlockStatus": "",
            "priceSource": "test_cutoff",
            "marketRegime": "RISK_ON",
            "generatedAt": f"{cutoff_date}T23:59:00",
        }

    monkeypatch.setattr(vtj, "_historical_item_from_cutoff", fake_item)

    out = vtj.historical_replay("kr", "balanced", "swing", as_of_date=as_of_date, limit=1, evaluate_after=False)

    assert out["status"] == "OK"
    assert out["added"] == 1
    assert out["syntheticCutoffReplay"] is True
    assert out["replayMethod"] == vtj.HISTORICAL_REPLAY_METHOD


def test_premarket_and_after_close_sessions_are_separate_journal_rows(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: [_valid_recommendation()])

    pre = vtj.capture("kr", "balanced", "swing", journal_session="PREMARKET_PLAN", as_of_date="2026-06-18")
    close = vtj.capture("kr", "balanced", "swing", journal_session="AFTER_CLOSE_TRADE", as_of_date="2026-06-18")
    listed = vtj.list_trades("kr", "balanced", "swing", "FORWARD_PAPER_TRADE", "all", limit=10)

    assert pre["added"] == 1
    assert close["added"] == 1
    assert listed["count"] == 2
    assert {item["journal_session"] for item in listed["items"]} == {"PREMARKET_PLAN", "AFTER_CLOSE_TRADE"}
    pre_row = next(item for item in listed["items"] if item["journal_session"] == "PREMARKET_PLAN")
    assert "장전 계획" in pre_row["session_note"]
    assert "추격하지 않는다" in pre_row["session_note"]


def test_premarket_plan_rows_are_never_trade_evaluated(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: [_valid_recommendation()])
    vtj.capture("kr", "balanced", "swing", journal_session="PREMARKET_PLAN", as_of_date="2026-06-18")

    evaluated = vtj.evaluate(journal_session="PREMARKET_PLAN", force=True)

    assert evaluated["evaluated"] == 0
    assert vtj._read_rows(vtj.EVALUATION_CSV, vtj.EVALUATION_COLS) == []


def test_us_juneteenth_auto_capture_is_marked_market_closed(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_kst_now", lambda: datetime(2026, 6, 20, 8, 0, tzinfo=vtj.ZoneInfo("Asia/Seoul")))
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: pytest.fail("holiday capture must not load recommendations"))

    out = vtj.run_auto_capture("us", journal_session="AFTER_CLOSE_TRADE", force=True)

    assert out["runs"][0]["tradeDate"] == "2026-06-19"
    assert out["runs"][0]["status"] == "SKIPPED_MARKET_CLOSED"
    assert out["runs"][0]["runKey"] in out["completedKeys"]


def test_us_premarket_auto_capture_uses_same_day_us_trade_date(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_kst_now", lambda: datetime(2026, 6, 19, 21, 30, tzinfo=vtj.ZoneInfo("Asia/Seoul")))
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: pytest.fail("holiday capture must not load recommendations"))

    out = vtj.run_auto_capture("us", journal_session="PREMARKET_PLAN", force=True)

    assert out["runs"][0]["tradeDate"] == "2026-06-19"
    assert out["runs"][0]["journalSession"] == "PREMARKET_PLAN"
    assert out["runs"][0]["status"] == "SKIPPED_MARKET_CLOSED"


def test_market_analog_search_uses_only_cutoff_benchmark_history(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = []
    for idx in range(150):
        close = 100 + idx * 0.2 + (idx % 12 - 6) * 0.4
        rows.append(
            {
                "date": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=idx)).date().isoformat(),
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 1000 + (idx % 7) * 10,
            }
        )
    bench = pd.DataFrame(rows)
    bench["_date_ts"] = pd.to_datetime(bench["date"], errors="coerce").dt.normalize()
    cutoff = bench.iloc[130]["date"]
    monkeypatch.setattr(vtj, "_load_benchmark_ohlcv", lambda market: (bench.copy(), "TESTIDX"))

    out = vtj._find_market_analogs("kr", as_of_date=cutoff, limit=3, horizon="swing")

    assert out["status"] == "OK"
    assert out["asOfDate"] == cutoff
    assert out["benchmarkSymbol"] == "TESTIDX"
    assert len(out["items"]) == 3
    assert all(item["date"] < cutoff for item in out["items"])
    assert all("ret_20d_pct" in item["marketVector"] for item in out["items"])
    assert all("returnPct" in item["marketOutcome"] for item in out["items"])
    assert out["history"]["startDate"] == bench.iloc[0]["date"]
    assert out["history"]["independentSpacingBars"] == 20
    assert out["marketOutcomeSummary"]["researchOnly"] is True


def test_market_analog_search_prefers_independent_same_regime_samples(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = []
    for idx in range(241):
        close = 100 + idx * 0.1
        rows.append(
            {
                "date": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx)).date().isoformat(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            }
        )
    bench = pd.DataFrame(rows)
    bench["_date_ts"] = pd.to_datetime(bench["date"], errors="coerce").dt.normalize()
    monkeypatch.setattr(vtj, "_load_benchmark_ohlcv", lambda market: (bench.copy(), "TESTIDX"))

    def vector(_df: pd.DataFrame, idx: int) -> dict[str, float | str]:
        regime = "SIDE" if idx % 2 == 0 else "BEAR"
        return {**{feature: 1.0 for feature in vtj.ANALOG_FEATURES}, "regime": regime}

    monkeypatch.setattr(vtj, "_market_vector_at", vector)

    out = vtj._find_market_analogs("kr", limit=4, horizon="swing")

    assert out["status"] == "OK"
    assert out["regimeFilter"] == "SAME_REGIME"
    assert len(out["items"]) == 4
    assert all(item["marketVector"]["regime"] == "SIDE" for item in out["items"])
    dates = [pd.Timestamp(item["date"]) for item in out["items"]]
    assert all(abs((later - earlier).days) >= 20 for pos, earlier in enumerate(dates) for later in dates[pos + 1:])


def test_market_analog_replay_summarizes_future_outcomes_after_snapshot(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analog_date = "2026-01-10"

    monkeypatch.setattr(
        vtj,
        "_find_market_analogs",
        lambda *args, **kwargs: {
            "status": "OK",
            "market": "kr",
            "asOfDate": "2026-06-01",
            "benchmarkSymbol": "TESTIDX",
            "currentVector": {"ret_20d_pct": 3.2, "regime": "RISK_ON"},
            "items": [{"date": analog_date, "similarity": 0.91, "distance": 0.3, "marketVector": {"ret_20d_pct": 2.9}}],
        },
    )

    def fake_replay(**kwargs):
        row = vtj._snapshot_from_item(_valid_recommendation("SIM"), "HISTORICAL_REPLAY", analog_date, vtj.DEFAULT_JOURNAL_SESSION)
        vtj._write_rows(vtj.JOURNAL_CSV, [row], vtj.JOURNAL_COLS)
        vtj._write_rows(
            vtj.EVALUATION_CSV,
            [
                {
                    "journal_id": row["journal_id"],
                    "status": "EVALUATED",
                    "outcome": "TIME_EXIT_NEAR_TARGET",
                    "filled": True,
                    "net_pnl_pct": 2.4,
                    "mfe_pct": 5.0,
                    "mae_pct": -1.0,
                    "failure_reason": "TARGET_TOO_FAR",
                    "evaluated_at": "2026-01-31T00:00:00",
                }
            ],
            vtj.EVALUATION_COLS,
        )
        return {"status": "OK", "selected": 1, "added": 1, "duplicates": 0, "replayMethod": vtj.HISTORICAL_REPLAY_METHOD}

    monkeypatch.setattr(vtj, "historical_replay", fake_replay)

    out = vtj.market_analog_replay("kr", "balanced", "swing", analog_limit=1, replay_limit=1)

    assert out["status"] == "OK"
    assert out["items"][0]["outcomeSummary"]["evaluated"] == 1
    assert out["items"][0]["outcomeSummary"]["avgNetPnlPct"] == 2.4
    assert out["items"][0]["outcomeSummary"]["failureCounts"]["TARGET_TOO_FAR"] == 1
    assert "승률" in out["items"][0]["lesson"]


def test_calibration_review_records_decision_but_never_auto_applies(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(30):
        jid = f"jid-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T00:00:00",
                "captured_at": "2026-01-01T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"T{idx:03d}",
                "name": f"T{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -3,
                "mfe_pct": 2,
                "mae_pct": -5,
                "failure_reason": "STOP_TOO_TIGHT" if idx < 6 else "FALSE_SIGNAL",
                "evaluated_at": f"2026-01-02T00:00:{idx:02d}",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    suggestions = vtj.calibration_suggestions("kr", "balanced", "swing", "FORWARD_PAPER_TRADE")["items"]
    target = next(item for item in suggestions if item.get("reason") == "STOP_TOO_TIGHT")
    reviewed = vtj.review_calibration_suggestion(target["suggestionId"], decision="APPROVED", reviewed_by="pytest")

    assert reviewed["status"] == "OK"
    assert reviewed["applied"] is False
    assert reviewed["approval"]["decision"] == "APPROVED"


def test_approved_calibration_can_be_manually_applied_to_self_correction_params(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    journal_rows = []
    eval_rows = []
    for idx in range(60):
        jid = f"apply-jid-{idx}"
        signal_date = (datetime(2026, 1, 1) + timedelta(days=idx)).date().isoformat()
        evaluated_date = (datetime(2026, 1, 2) + timedelta(days=idx)).date().isoformat()
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": signal_date,
                "generated_at": f"{signal_date}T00:00:00",
                "captured_at": f"{signal_date}T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"A{idx:03d}",
                "name": f"A{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -3,
                "mfe_pct": 2,
                "mae_pct": -5,
                "failure_reason": "STOP_TOO_TIGHT" if idx % 5 == 0 else "FALSE_SIGNAL",
                "evaluated_at": f"{evaluated_date}T00:00:00",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    suggestions = vtj.calibration_suggestions("kr", "balanced", "swing", "FORWARD_PAPER_TRADE")["items"]
    target = next(item for item in suggestions if item.get("reason") == "STOP_TOO_TIGHT")
    reviewed = vtj.review_calibration_suggestion(target["suggestionId"], decision="APPROVED", reviewed_by="pytest")
    before_promotion = correction_store.load_params()
    blocked = vtj.apply_approved_calibrations(applied_by="pytest")
    assert blocked["applied"] == 0
    assert blocked["skipped"][0]["reason"] == "MISSING_PROMOTION_CERTIFICATE"
    assert correction_store.load_params() == before_promotion

    certificate = _write_valid_calibration_promotion_certificate(reviewed["approval"], target)
    applied = vtj.apply_approved_calibrations(applied_by="pytest")
    correction = correction_store.load_correction("kr", "balanced", "swing")
    refreshed = vtj.calibration_suggestions("kr", "balanced", "swing", "FORWARD_PAPER_TRADE")["items"]
    refreshed_target = next(item for item in refreshed if item.get("reason") == "STOP_TOO_TIGHT")

    assert applied["status"] == "OK"
    assert applied["applied"] == 1
    assert correction["journalCalibrationApplied"] is True
    assert correction["journalCalibrationPromoted"] is True
    assert correction["candidateFingerprint"] == certificate["candidateFingerprint"]
    assert correction["promotionCertificateHash"] == certificate["recordHash"]
    assert correction["promotionCertificate"] == certificate
    assert correction_store.validate_params_integrity(correction_store.load_params()) is True
    assert correction["priceAdjustments"]["stopAtrMultiplier"] > 0
    assert refreshed_target["applicationStatus"] == "APPLIED"
    application_rows = vtj._read_rows(vtj.CALIBRATION_APPLICATIONS_CSV, vtj.CALIBRATION_APPLICATION_COLS)
    assert len(application_rows) == 1
    assert application_rows[0]["policy_version"] == vtj.AUTO_CALIBRATION_POLICY["version"]
    assert application_rows[0]["distinct_signal_dates"] == "60"
    assert application_rows[0]["candidate_fingerprint"] == certificate["candidateFingerprint"]
    assert application_rows[0]["promotion_certificate_hash"] == certificate["recordHash"]
    assert application_rows[0]["record_hash"] == vtj._sealed_row_hash(application_rows[0], vtj.CALIBRATION_APPLICATION_COLS)
    integrity = vtj._calibration_ledger_integrity()
    assert integrity["approvals"]["validSealedRows"] == 1
    assert integrity["applications"]["validSealedRows"] == 1
    assert integrity["promotionCertificates"]["validCurrentPolicyRows"] == 1
    assert integrity["integrityViolations"] == 0


def test_entry_efficiency_stats_tracks_fill_rate_slippage_and_days(isolated_vtj: Path) -> None:
    journal_rows = [
        {
            "journal_id": "jid-fill-1",
            "source_type": "FORWARD_PAPER_TRADE",
            "journal_session": "AFTER_CLOSE_TRADE",
            "as_of_date": "2026-01-01",
            "generated_at": "2026-01-01T09:00:00",
            "captured_at": "2026-01-01T09:00:00",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "A001",
            "name": "A001",
            "decision_bucket": vtj.TODAY_ENTRY,
            "entry_price": 100,
            "raw_recommendation_json": "{}",
        },
        {
            "journal_id": "jid-fill-2",
            "source_type": "FORWARD_PAPER_TRADE",
            "journal_session": "AFTER_CLOSE_TRADE",
            "as_of_date": "2026-01-01",
            "generated_at": "2026-01-01T09:00:00",
            "captured_at": "2026-01-01T09:00:00",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "A002",
            "name": "A002",
            "decision_bucket": vtj.TODAY_ENTRY,
            "entry_price": 200,
            "raw_recommendation_json": "{}",
        },
        {
            "journal_id": "jid-miss",
            "source_type": "FORWARD_PAPER_TRADE",
            "journal_session": "AFTER_CLOSE_TRADE",
            "as_of_date": "2026-01-01",
            "generated_at": "2026-01-01T09:00:00",
            "captured_at": "2026-01-01T09:00:00",
            "market": "kr",
            "mode": "balanced",
            "horizon": "short",
            "symbol": "A003",
            "name": "A003",
            "decision_bucket": vtj.TODAY_ENTRY,
            "entry_price": 300,
            "raw_recommendation_json": "{}",
        },
    ]
    eval_rows = [
        {"journal_id": "jid-fill-1", "status": "EVALUATED", "filled": True, "fill_date": "2026-01-02", "fill_price": 101},
        {"journal_id": "jid-fill-2", "status": "EVALUATED", "filled": True, "fill_date": "2026-01-03", "fill_price": 198},
        {"journal_id": "jid-miss", "status": "CANCELLED", "filled": False},
    ]
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.entry_efficiency_stats("kr", "all")

    assert out["status"] == "OK"
    assert out["total"] == 3
    assert out["filled"] == 2
    assert out["fillRate"] == 0.6667
    assert out["avgSlippagePct"] == 0.0
    assert out["avgFillDays"] == 1.5
    swing = next(row for row in out["byHorizon"] if row["horizon"] == "swing")
    assert swing["fillRate"] == 1.0


def test_attribution_feedback_suggests_boost_and_reduce_without_auto_apply(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(12):
        is_winner = idx < 6
        jid = f"jid-feedback-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T09:00:00",
                "captured_at": "2026-01-01T09:00:00",
                "market": "kr",
                "mode": "balanced" if is_winner else "aggressive",
                "horizon": "swing" if is_winner else "short",
                "symbol": f"A{idx:03d}",
                "name": f"A{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_price": 100,
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "TARGET_HIT" if is_winner else "STOP_HIT",
                "filled": True,
                "fill_date": "2026-01-02",
                "fill_price": 100,
                "net_pnl_pct": 4 if is_winner else -2,
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.attribution_feedback("kr")

    assert out["status"] == "OK"
    assert out["sampleCount"] == 12
    assert out["excludedInconsistentOutcomeCount"] == 0
    assert out["autoApplied"] is False
    assert out["manualApprovalRequired"] is True
    assert out["calibrationSummary"]["applyEndpoint"] == "/api/journal/calibration/apply-approved"
    by_key = {(row["mode"], row["horizon"]): row for row in out["adjustments"]}
    assert by_key[("balanced", "swing")]["direction"] == "BOOST"
    assert by_key[("aggressive", "short")]["direction"] == "REDUCE"
    assert (isolated_vtj / "attribution_feedback.json").exists()


def test_attribution_analysis_includes_ols_regression_when_sample_is_ready(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(18):
        high_ev = idx % 2 == 0
        jid = f"jid-regression-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T09:00:00",
                "captured_at": "2026-01-01T09:00:00",
                "market": "kr",
                "mode": "balanced" if high_ev else "aggressive",
                "horizon": "swing",
                "symbol": f"R{idx:03d}",
                "name": f"R{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "expected_value": 4 if high_ev else -1,
                "risk_reward_ratio": 2.4 if high_ev else 1.1,
                "probability": 65 if high_ev else 45,
                "risk_score": 70 if high_ev else 35,
                "event_risk_score": 20,
                "market_regime_at_signal": "RISK_ON" if high_ev else "RISK_OFF",
                "sector": "TECH" if high_ev else "BANK",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "TARGET_HIT" if high_ev else "STOP_HIT",
                "filled": True,
                "net_pnl_pct": 3.0 if high_ev else -2.0,
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.attribution_analysis("kr", "all", "all")

    assert out["status"] == "OK"
    assert out["regression"]["status"] == "OK"
    assert out["regression"]["sampleCount"] == 18
    assert out["regression"]["coefficients"]


def test_auto_self_calibrate_runs_shadow_only_while_auto_apply_is_frozen(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    journal_rows = []
    eval_rows = []
    for idx in range(50):
        jid = f"auto-jid-{idx}"
        signal_date = (datetime(2026, 1, 1) + timedelta(days=idx)).date().isoformat()
        evaluated_date = (datetime(2026, 1, 2) + timedelta(days=idx)).date().isoformat()
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": signal_date,
                "generated_at": f"{signal_date}T00:00:00",
                "captured_at": f"{signal_date}T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"AUTO{idx:03d}",
                "name": f"AUTO{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -2.5,
                "failure_reason": "ENTRY_TIMING" if idx < 16 or idx >= 45 else "FALSE_SIGNAL",
                "evaluated_at": f"{evaluated_date}T00:00:00",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    result = vtj.auto_self_calibrate("kr", apply=True, max_applications=1)
    correction = correction_store.load_correction("kr", "balanced", "swing")
    status = vtj.self_learning_status("kr")

    assert result["status"] == "SHADOW_ONLY"
    assert result["eligibleCount"] >= 1
    assert result["wouldApplyCount"] == 1
    assert result["approvedCount"] == 0
    assert result["applied"] == 0
    assert correction.get("journalCalibrationApplied") is not True
    assert result["applyResult"]["reason"] == "AUTO_APPLY_FROZEN"
    assert status["autoApprovalCount"] == 0
    assert status["quality"]["score"] > 0
    assert status["lastSelfLearningRun"]["applied"] == 0


def test_auto_self_calibrate_blocks_when_holdout_drift_is_detected(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(80):
        jid = f"drift-jid-{idx}"
        signal_date = (datetime(2026, 1, 1) + timedelta(days=idx)).date().isoformat()
        evaluated_date = (datetime(2026, 1, 2) + timedelta(days=idx)).date().isoformat()
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": signal_date,
                "generated_at": f"{signal_date}T00:00:00",
                "captured_at": f"{signal_date}T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"DRIFT{idx:03d}",
                "name": f"DRIFT{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -2.0,
                "failure_reason": "ENTRY_TIMING" if idx < 30 else "FALSE_SIGNAL",
                "evaluated_at": f"{evaluated_date}T00:00:00",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    result = vtj.auto_self_calibrate("kr", apply=True, max_applications=2)

    assert result["status"] == "SHADOW_ONLY"
    assert result["applied"] == 0
    assert any(row["reason"] == "HOLDOUT_DRIFT" for row in result["blocked"])


def test_clustered_same_day_samples_never_pass_strict_holdout(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "as_of_date": "2026-01-01",
            "failure_reason": "ENTRY_TIMING" if idx < 20 else "FALSE_SIGNAL",
            "net_pnl_pct": -1.0,
        }
        for idx in range(60)
    ]
    monkeypatch.setattr(vtj, "_rows_for_suggestion_scope", lambda item: rows)
    item = {
        "status": "SUGGESTED",
        "approvalStatus": "PENDING_REVIEW",
        "applicationStatus": "NOT_APPLIED",
        "sourceType": "FORWARD_PAPER_TRADE",
        "sampleCount": 60,
        "share": 1 / 3,
        "reason": "ENTRY_TIMING",
        "threshold": 0.25,
    }

    validation = vtj._holdout_validation(item)
    verdict = vtj._auto_calibration_verdict(item)

    assert validation["status"] == "LOW_HOLDOUT"
    assert validation["passed"] is False
    assert validation["distinctSignalDates"] == 1
    assert verdict["eligible"] is False
    assert verdict["reason"] == "LOW_HOLDOUT"


def test_human_reviewed_shadow_incubation_uses_forward_test_as_primary_holdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    low_historical_holdout = {
        "status": "LOW_HOLDOUT",
        "passed": False,
        "distinctSignalDates": 10,
        "requiredDistinctSignalDates": 30,
        "reason": "NOT_ENOUGH_INDEPENDENT_DATES_FOR_STRICT_HOLDOUT",
    }
    monkeypatch.setattr(vtj, "_holdout_validation", lambda _item: low_historical_holdout)
    item = {
        "status": "SUGGESTED",
        "approvalStatus": "PENDING_REVIEW",
        "applicationStatus": "NOT_APPLIED",
        "sourceType": "FORWARD_PAPER_TRADE",
        "sampleCount": 50,
        "distinctSignalDates": 10,
        "share": 0.30,
        "reason": "STOP_TOO_TIGHT",
        "threshold": 0.15,
    }

    auto = vtj._auto_calibration_verdict(item)
    shadow = vtj._shadow_calibration_verdict(item)

    assert auto["eligible"] is False
    assert auto["reason"] == "LOW_HOLDOUT"
    assert shadow["eligible"] is True
    assert shadow["reason"] == "SHADOW_INCUBATION_ELIGIBLE"
    assert shadow["historicalHoldoutPassed"] is False
    assert shadow["requiresForwardPromotion"] is True


def test_shadow_incubation_rejects_non_forward_and_clustered_training_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_holdout_validation", lambda _item: {"status": "LOW_HOLDOUT", "passed": False})
    base = {
        "status": "SUGGESTED",
        "approvalStatus": "PENDING_REVIEW",
        "applicationStatus": "NOT_APPLIED",
        "sampleCount": 60,
        "distinctSignalDates": 10,
        "share": 0.30,
        "reason": "STOP_TOO_TIGHT",
    }

    replay = vtj._shadow_calibration_verdict({**base, "sourceType": "HISTORICAL_REPLAY"})
    clustered = vtj._shadow_calibration_verdict({
        **base,
        "sourceType": "FORWARD_PAPER_TRADE",
        "distinctSignalDates": 1,
    })

    assert replay["eligible"] is False
    assert replay["reason"] == "SHADOW_SOURCE_NOT_FORWARD"
    assert clustered["eligible"] is False
    assert clustered["reason"] == "SHADOW_TRAINING_DATE_GATE"


def test_shadow_readiness_ranks_eligible_candidate_without_granting_live_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_holdout_validation", lambda _item: {"status": "LOW_HOLDOUT", "passed": False})
    suggestions = [
        {
            "suggestionId": "ready-a",
            "sourceSummaryId": "scope-a",
            "status": "SUGGESTED",
            "approvalStatus": "PENDING_REVIEW",
            "applicationStatus": "NOT_APPLIED",
            "market": "us",
            "mode": "conservative",
            "horizon": "swing",
            "sourceType": "FORWARD_PAPER_TRADE",
            "journalSession": "AFTER_CLOSE_TRADE",
            "sampleCount": 53,
            "distinctSignalDates": 11,
            "share": 0.25,
            "reason": "STOP_TOO_TIGHT",
        },
        {
            "suggestionId": "waiting-b",
            "sourceSummaryId": "scope-b",
            "status": "SUGGESTED",
            "approvalStatus": "PENDING_REVIEW",
            "applicationStatus": "NOT_APPLIED",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "sourceType": "FORWARD_PAPER_TRADE",
            "journalSession": "AFTER_CLOSE_TRADE",
            "sampleCount": 49,
            "distinctSignalDates": 20,
            "share": 0.40,
            "reason": "STOP_TOO_TIGHT",
        },
    ]

    readiness = vtj.calibration_shadow_readiness(suggestions)

    assert readiness["readyForReview"] == 1
    assert readiness["eligibleSuggestions"] == 1
    assert readiness["items"][0]["suggestionId"] == "ready-a"
    assert readiness["items"][0]["requiresHumanReview"] is True
    assert readiness["items"][0]["requiresForwardPromotion"] is True
    assert readiness["items"][1]["remainingRawSamples"] == 1


def test_sealed_manual_approval_can_arm_low_holdout_shadow_but_not_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation = {
        "status": "LOW_HOLDOUT",
        "passed": False,
        "distinctSignalDates": 19,
        "requiredDistinctSignalDates": 30,
    }
    monkeypatch.setattr(vtj, "_holdout_validation", lambda _item: validation)
    item = {
        "suggestionId": "shadow-suggestion",
        "sourceSummaryId": "shadow-scope",
        "market": "us",
        "mode": "aggressive",
        "horizon": "short",
        "sourceType": "FORWARD_PAPER_TRADE",
        "journalSession": "AFTER_CLOSE_TRADE",
        "status": "SUGGESTED",
        "reason": "STOP_TOO_TIGHT",
        "sampleCount": 58,
        "distinctSignalDates": 19,
        "count": 13,
        "share": 0.2241,
        "threshold": 0.15,
    }
    evidence = vtj._calibration_evidence(item)
    approval = {
        "approval_id": "shadow-approval",
        "suggestion_id": item["suggestionId"],
        "decision": "APPROVED",
        "reviewed_by": "pytest-human",
        "reviewed_at": "2026-07-31T00:00:00",
        "source_summary_id": item["sourceSummaryId"],
        "market": item["market"],
        "mode": item["mode"],
        "horizon": item["horizon"],
        "source_type": item["sourceType"],
        "journal_session": item["journalSession"],
        "reason": item["reason"],
        "suggestion_status": item["status"],
        "sample_count": item["sampleCount"],
        "distinct_signal_dates": item["distinctSignalDates"],
        "count": item["count"],
        "share": item["share"],
        "threshold": item["threshold"],
        "message": "forward-only experiment",
        "before_params_json": "{}",
        "after_params_json": "{}",
        "reviewer_note": "human reviewed; no live authority",
        "policy_version": vtj.AUTO_CALIBRATION_POLICY["version"],
        "policy_fingerprint": vtj._calibration_policy_fingerprint(),
        "evidence_fingerprint": evidence["fingerprint"],
    }
    approval["record_hash"] = vtj._sealed_row_hash(approval, vtj.CALIBRATION_APPROVAL_COLS)

    armed = vtj._approval_application_verdict(approval, {item["suggestionId"]: item})
    persistent_shadow = vtj._approval_shadow_verdict(approval)
    promotion = vtj._calibration_promotion_verdict(
        approval,
        evidence["fingerprint"],
        "not-yet-promoted",
    )

    assert armed["eligible"] is True
    assert armed["reason"] == "SEALED_CURRENT_EVIDENCE_PASS"
    assert armed["validation"]["status"] == "LOW_HOLDOUT"
    assert persistent_shadow["eligible"] is True
    assert persistent_shadow["approvedEvidenceFingerprint"] == evidence["fingerprint"]
    assert promotion["passed"] is False
    assert promotion["reason"] == "MISSING_PROMOTION_CERTIFICATE"


def test_latest_scope_decision_revokes_older_shadow_approval() -> None:
    shared = {
        "source_summary_id": "scope-a",
        "reason": "STOP_TOO_TIGHT",
    }
    approved = {
        **shared,
        "approval_id": "approval-old",
        "decision": "APPROVED",
        "reviewed_at": "2026-07-01T00:00:00",
    }
    rejected = {
        **shared,
        "approval_id": "rejection-new",
        "decision": "REJECTED",
        "reviewed_at": "2026-07-02T00:00:00",
    }

    latest = vtj._latest_approval_by_scope([rejected, approved])

    assert len(latest) == 1
    assert latest["scope-a|STOP_TOO_TIGHT"]["approval_id"] == "rejection-new"
    assert latest["scope-a|STOP_TOO_TIGHT"]["decision"] == "REJECTED"


def test_attached_approval_state_prefers_latest_scope_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_approval_index", lambda: {
        "same-suggestion": {
            "approval_id": "old-approval",
            "decision": "APPROVED",
            "reviewed_at": "2026-07-01T00:00:00",
        },
    })
    monkeypatch.setattr(vtj, "_approval_scope_index", lambda: {
        "scope-a|STOP_TOO_TIGHT": {
            "approval_id": "new-rejection",
            "decision": "REJECTED",
            "reviewed_at": "2026-07-02T00:00:00",
        },
    })
    monkeypatch.setattr(vtj, "_application_by_approval", lambda: {})
    monkeypatch.setattr(vtj, "_source_summary_id", lambda _item: "scope-a")
    monkeypatch.setattr(vtj, "_suggestion_id", lambda _item: "same-suggestion")

    attached = vtj._attach_approval_state([{"reason": "STOP_TOO_TIGHT"}])

    assert attached[0]["approvalStatus"] == "REJECTED"
    assert attached[0]["approvalId"] == "new-rejection"


def test_sealed_approval_rejects_tamper_and_regression_but_allows_newer_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = []
    for idx in range(60):
        signal_date = (datetime(2026, 1, 1) + timedelta(days=idx)).date().isoformat()
        rows.append({
            "as_of_date": signal_date,
            "failure_reason": "STOP_TOO_TIGHT" if idx % 5 == 0 else "FALSE_SIGNAL",
            "net_pnl_pct": -1.0,
        })
    monkeypatch.setattr(vtj, "_rows_for_suggestion_scope", lambda item: rows)
    item = {
        "suggestionId": "suggestion-a",
        "sourceSummaryId": "summary-a",
        "market": "kr",
        "mode": "balanced",
        "horizon": "swing",
        "sourceType": "FORWARD_PAPER_TRADE",
        "journalSession": "AFTER_CLOSE_TRADE",
        "status": "SUGGESTED",
        "reason": "STOP_TOO_TIGHT",
        "sampleCount": 60,
        "distinctSignalDates": 60,
        "count": 12,
        "share": 0.2,
        "threshold": 0.15,
    }
    evidence = vtj._calibration_evidence(item)
    approval = {
        "approval_id": "approval-a",
        "suggestion_id": "suggestion-a",
        "decision": "APPROVED",
        "reviewed_by": "pytest",
        "reviewed_at": "2026-04-01T00:00:00",
        "source_summary_id": "summary-a",
        "market": "kr",
        "mode": "balanced",
        "horizon": "swing",
        "source_type": "FORWARD_PAPER_TRADE",
        "journal_session": "AFTER_CLOSE_TRADE",
        "reason": "STOP_TOO_TIGHT",
        "suggestion_status": "SUGGESTED",
        "sample_count": 60,
        "distinct_signal_dates": 60,
        "count": 12,
        "share": 0.2,
        "threshold": 0.15,
        "message": "test",
        "before_params_json": "{}",
        "after_params_json": "{}",
        "reviewer_note": "test",
        "policy_version": vtj.AUTO_CALIBRATION_POLICY["version"],
        "policy_fingerprint": vtj._calibration_policy_fingerprint(),
        "evidence_fingerprint": evidence["fingerprint"],
    }
    approval["record_hash"] = vtj._sealed_row_hash(approval, vtj.CALIBRATION_APPROVAL_COLS)

    valid = vtj._approval_application_verdict(approval, {"suggestion-a": item})
    tampered = {**approval, "share": 0.4}
    regressed_item = {**item, "sampleCount": 59, "distinctSignalDates": 59}
    regressed = vtj._approval_application_verdict(approval, {"suggestion-a": regressed_item})
    newer_item = {**item, "suggestionId": "suggestion-new"}
    newer = vtj._approval_application_verdict(approval, {"suggestion-new": newer_item})

    assert valid["eligible"] is True
    assert vtj._approval_application_verdict(tampered, {"suggestion-a": item})["reason"] == "APPROVAL_RECORD_HASH_MISMATCH"
    assert regressed["eligible"] is False
    assert regressed["reason"] == "CURRENT_EVIDENCE_REGRESSED"
    assert newer["eligible"] is True
    assert newer["currentSuggestionId"] == "suggestion-new"
    assert newer["approvedEvidenceFingerprint"] == evidence["fingerprint"]
    assert newer["currentEvidenceFingerprint"] != evidence["fingerprint"]
    missing_promotion = vtj._calibration_promotion_verdict(
        approval,
        evidence["fingerprint"],
        "candidate-a",
    )
    assert missing_promotion["passed"] is False
    assert missing_promotion["reason"] == "MISSING_PROMOTION_CERTIFICATE"

    weak_certificate = {
        "version": vtj.CALIBRATION_PROMOTION_VERSION,
        "approvalId": "approval-a",
        "approvalRecordHash": approval["record_hash"],
        "evidenceFingerprint": evidence["fingerprint"],
        "calibrationPolicyFingerprint": vtj._calibration_policy_fingerprint(),
        "candidateFingerprint": "candidate-a",
        "shadowPolicyVersion": vtj.CALIBRATION_SHADOW_POLICY["version"],
        "shadowPolicyFingerprint": vtj._calibration_shadow_policy_fingerprint(),
        "evaluationPolicyVersion": vtj.EVALUATION_POLICY["version"],
        "evaluationPolicyFingerprint": vtj._evaluation_policy_fingerprint(),
        "promotionEligible": True,
        "decision": "READY_FOR_HUMAN_REVIEW",
        "completedSignalDates": 10,
        "evaluatedChallengerTrades": 20,
        "avgAfterCostReturnPct": 0.1,
        "pairedUpliftCi95": [0.01, 0.2],
        "championMaxDrawdownPct": 8.0,
        "challengerMaxDrawdownPct": 6.0,
    }
    weak_certificate["recordHash"] = vtj._promotion_certificate_hash(weak_certificate)
    vtj.CALIBRATION_PROMOTION_JSON.parent.mkdir(parents=True, exist_ok=True)
    vtj.CALIBRATION_PROMOTION_JSON.write_text(json.dumps({"certificates": [weak_certificate]}), encoding="utf-8")
    weak = vtj._calibration_promotion_verdict(approval, evidence["fingerprint"], "candidate-a")
    assert weak["passed"] is False
    assert "LOW_PROMOTION_SIGNAL_DATES" in weak["blockingReasons"]


def test_ci_commit_workflow_preserves_calibration_promotion_evidence() -> None:
    script = (BACKEND_DIR.parents[1] / "scripts" / "ci_commit_app_data.sh").read_text(encoding="utf-8")

    assert "reports/self_correction_promotion.json" in script


def test_self_learning_rollback_restores_previous_correction_version(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    correction_store.save_params({
        "version": 0,
        "generatedAt": "2026-01-01T00:00:00",
        "markets": {"kr_balanced_swing": {"confidence": 0.1}},
    })
    correction_store.save_params({
        "version": 1,
        "generatedAt": "2026-01-02T00:00:00",
        "markets": {"kr_balanced_swing": {"confidence": 0.9}},
    })

    out = vtj.rollback_self_learning(requested_by="pytest")
    restored = correction_store.load_params()

    assert out["status"] == "OK"
    assert out["fromVersion"] == 1
    assert out["toVersion"] == 0
    assert restored["rollbackFromVersion"] == 1
    assert restored["markets"]["kr_balanced_swing"]["confidence"] == 0.1


def test_self_learning_rollback_rejects_tampered_backup(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    correction_store.save_params({"version": 0, "markets": {"kr_balanced_swing": {"confidence": 0.1}}})
    correction_store.save_params({"version": 1, "markets": {"kr_balanced_swing": {"confidence": 0.9}}})
    before = correction_store.load_params()
    backup_path = isolated_vtj / "self_correction_params_v0.json"
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    backup["markets"]["kr_balanced_swing"]["confidence"] = 9.9
    backup_path.write_text(json.dumps(backup), encoding="utf-8")

    out = vtj.rollback_self_learning(version=0, requested_by="pytest")

    assert out["status"] == "ERROR"
    assert out["error"] == "ROLLBACK_INTEGRITY_FAILED"
    assert "PARAMS_INTEGRITY_INVALID" in out["blockingReasons"]
    assert correction_store.load_params() == before


def test_self_learning_rollback_rejects_backup_version_mismatch(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    correction_store.save_params({"version": 0, "markets": {}})
    correction_store.save_params({"version": 1, "markets": {}})
    before = correction_store.load_params()
    backup_path = isolated_vtj / "self_correction_params_v0.json"
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    backup["version"] = 99
    backup_path.write_text(json.dumps(correction_store.seal_params(backup)), encoding="utf-8")

    out = vtj.rollback_self_learning(version=0, requested_by="pytest")

    assert out["status"] == "ERROR"
    assert out["error"] == "ROLLBACK_INTEGRITY_FAILED"
    assert "ROLLBACK_VERSION_MISMATCH" in out["blockingReasons"]
    assert correction_store.load_params() == before


def test_self_learning_rollback_can_replace_tampered_current_from_valid_backup(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    correction_store.save_params({"version": 0, "markets": {"kr_balanced_swing": {"confidence": 0.1}}})
    correction_store.save_params({"version": 1, "markets": {"kr_balanced_swing": {"confidence": 0.9}}})
    current_path = correction_store._params_path()
    current = correction_store.load_params()
    current["markets"]["kr_balanced_swing"]["confidence"] = 9.9
    current_path.write_text(json.dumps(current), encoding="utf-8")

    out = vtj.rollback_self_learning(version=0, requested_by="pytest")
    restored = correction_store.load_params()

    assert out["status"] == "OK"
    assert restored["markets"]["kr_balanced_swing"]["confidence"] == 0.1
    assert correction_store.validate_params_integrity(restored) is True


def test_historical_replay_backfill_steps_cutoff_dates_without_future_peek(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_replay(**kwargs):
        calls.append(kwargs)
        return {
            "status": "OK",
            "selected": 2,
            "added": 1,
            "duplicates": 1,
            "rejected": {},
            "replayMethod": vtj.HISTORICAL_REPLAY_METHOD,
        }

    monkeypatch.setattr(vtj, "historical_replay", fake_replay)

    out = vtj.historical_replay_backfill(
        market="kr",
        mode="balanced",
        horizon="swing",
        start_date="2025-01-01",
        end_date="2025-02-15",
        step_days=20,
        limit=5,
        max_runs=2,
    )

    assert out["status"] == "OK"
    assert out["runs"] == 2
    assert out["added"] == 2
    assert [call["as_of_date"] for call in calls] == ["2025-01-01", "2025-01-21"]
    assert all(call["evaluate_after"] is True for call in calls)
    assert "ohlcv_date_lte_as_of_date" in out["futureDataPolicy"]


def test_calibration_performance_gate_flags_degraded_applied_correction(isolated_vtj: Path) -> None:
    app_row = {
        "application_id": "app-1",
        "approval_id": "approval-1",
        "suggestion_id": "suggestion-1",
        "applied_by": "pytest",
        "applied_at": "2026-02-01T00:00:00",
        "market": "kr",
        "mode": "balanced",
        "horizon": "swing",
        "source_type": "FORWARD_PAPER_TRADE",
        "journal_session": "AFTER_CLOSE_TRADE",
        "source_weight": 1.0,
        "raw_sample_count": 60,
        "effective_sample_count": 60,
        "reason": "ENTRY_TIMING",
        "before_params_json": "{}",
        "after_params_json": "{}",
        "correction_version": 3,
        "status": "APPLIED",
    }
    vtj._write_rows(vtj.CALIBRATION_APPLICATIONS_CSV, [app_row], vtj.CALIBRATION_APPLICATION_COLS)

    journal_rows = []
    eval_rows = []
    for idx in range(60):
        before = idx < 30
        start = datetime(2026, 1, 1) if before else datetime(2026, 2, 1)
        date = (start + timedelta(days=idx if before else idx - 30)).date().isoformat()
        jid = f"gate-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "correction_version_at_signal": 2 if before else 3,
                "as_of_date": date,
                "generated_at": f"{date}T09:00:00",
                "captured_at": f"{date}T09:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"GATE{idx:03d}",
                "name": f"GATE{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": json.dumps({"correctionApplied": not before}),
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "TARGET_HIT" if before else "STOP_HIT",
                "filled": True,
                "net_pnl_pct": 2.0 if before else -1.5,
                "evaluated_at": f"{date}T18:00:00",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.calibration_performance_gate("kr")

    assert out["status"] == "DEGRADED_BLOCKED"
    assert out["candidateCount"] == 0
    assert out["items"][0]["before"]["samples"] == 30
    assert out["items"][0]["after"]["samples"] == 30
    assert out["items"][0]["degraded"] is True
    assert out["items"][0]["rollbackReady"] is False
    assert "APPLICATION_RECORD_HASH_MISMATCH" in out["items"][0]["lineage"]["blockingReasons"]


def _performance_gate_promoted_correction(candidate_fingerprint: str = "candidate-live") -> dict:
    certificate = {
        "approvalId": "approval-live",
        "approvalRecordHash": "approval-hash-live",
        "evidenceFingerprint": "evidence-live",
        "candidateFingerprint": candidate_fingerprint,
        "calibrationPolicyFingerprint": vtj._calibration_policy_fingerprint(),
        "shadowPolicyFingerprint": vtj._calibration_shadow_policy_fingerprint(),
        "evaluationPolicyFingerprint": vtj._evaluation_policy_fingerprint(),
        "promotionEligible": True,
        "decision": "READY_FOR_HUMAN_REVIEW",
    }
    certificate["recordHash"] = correction_store.promotion_certificate_hash(certificate)
    return {
        "confidence": 0.8,
        "sampleCount": 120,
        "journalCalibrationPromoted": True,
        "candidateFingerprint": candidate_fingerprint,
        "calibrationPolicyVersion": vtj.AUTO_CALIBRATION_POLICY["version"],
        "calibrationPolicyFingerprint": vtj._calibration_policy_fingerprint(),
        "promotionCertificateHash": certificate["recordHash"],
        "promotionCertificate": certificate,
    }


def _performance_gate_application(correction: dict, version: int = 3) -> dict:
    row = {
        "application_id": "application-live",
        "approval_id": "approval-live",
        "applied_at": "2026-02-01T00:00:00",
        "market": "kr",
        "mode": "balanced",
        "horizon": "swing",
        "status": "APPLIED",
        "correction_version": version,
        "policy_version": vtj.AUTO_CALIBRATION_POLICY["version"],
        "policy_fingerprint": vtj._calibration_policy_fingerprint(),
        "candidate_fingerprint": correction["candidateFingerprint"],
        "promotion_certificate_hash": correction["promotionCertificateHash"],
    }
    row["record_hash"] = vtj._sealed_row_hash(row, vtj.CALIBRATION_APPLICATION_COLS)
    return row


def _performance_gate_rows(*, clustered: bool = False) -> list[dict]:
    rows: list[dict] = []
    before_start = datetime(2026, 1, 1)
    after_start = datetime(2026, 2, 1)
    for index in range(30):
        before_date = before_start if clustered else before_start + timedelta(days=index)
        after_date = after_start if clustered else after_start + timedelta(days=index)
        rows.extend([
            {
                "status": "EVALUATED",
                "generated_at": before_date.isoformat(),
                "source_type": "FORWARD_PAPER_TRADE",
                "correction_version_at_signal": 2,
                "raw_recommendation_json": json.dumps({"correctionApplied": False}),
                "net_pnl_pct": 2.0,
                "outcome": "TARGET_HIT",
            },
            {
                "status": "EVALUATED",
                "generated_at": after_date.isoformat(),
                "source_type": "FORWARD_PAPER_TRADE",
                "correction_version_at_signal": 3,
                "raw_recommendation_json": json.dumps({"correctionApplied": True}),
                "net_pnl_pct": -1.5,
                "outcome": "STOP_HIT",
            },
        ])
    return sorted(rows, key=vtj._row_event_date)


@pytest.mark.parametrize(
    ("corrupt_backup", "expected_status"),
    [(False, "ROLLED_BACK"), (True, "QUARANTINED")],
)
def test_performance_gate_rolls_back_or_quarantines_only_exact_active_lineage(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt_backup: bool,
    expected_status: str,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    correction_store.save_params({
        "version": 2,
        "markets": {"kr_balanced_swing": {"confidence": 0.1}},
    })
    promoted = _performance_gate_promoted_correction()
    correction_store.save_params({
        "version": 3,
        "markets": {"kr_balanced_swing": promoted},
    })
    application = _performance_gate_application(promoted)
    vtj._write_rows(vtj.CALIBRATION_APPLICATIONS_CSV, [application], vtj.CALIBRATION_APPLICATION_COLS)
    monkeypatch.setattr(vtj, "_performance_scope_rows", lambda *_args, **_kwargs: _performance_gate_rows())
    if corrupt_backup:
        backup_path = isolated_vtj / "self_correction_params_v2.json"
        backup = json.loads(backup_path.read_text(encoding="utf-8"))
        backup["version"] = 999
        backup_path.write_text(json.dumps(backup), encoding="utf-8")

    out = vtj.calibration_performance_gate("kr", auto_rollback=True)
    current = correction_store.load_params()

    assert out["status"] == expected_status
    assert out["capitalBlocked"] is True
    assert out["candidateCount"] == 1
    if corrupt_backup:
        assert out["rollbackResult"]["error"] == "ROLLBACK_INTEGRITY_FAILED"
        assert current["markets"]["kr_balanced_swing"]["journalCalibrationPromoted"] is False
        assert current["markets"]["kr_balanced_swing"]["journalCalibrationQuarantined"] is True
    else:
        assert out["rollbackResult"]["status"] == "OK"
        assert current["version"] == 2
        assert current["markets"]["kr_balanced_swing"]["confidence"] == 0.1


def test_performance_gate_does_not_treat_clustered_trades_as_independent_dates(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _performance_gate_application(_performance_gate_promoted_correction())
    vtj._write_rows(vtj.CALIBRATION_APPLICATIONS_CSV, [application], vtj.CALIBRATION_APPLICATION_COLS)
    monkeypatch.setattr(
        vtj,
        "_performance_scope_rows",
        lambda *_args, **_kwargs: _performance_gate_rows(clustered=True),
    )

    out = vtj.calibration_performance_gate("kr", auto_rollback=True)

    assert out["status"] == "LOW_SAMPLE"
    assert out["candidateCount"] == 0
    assert out["capitalBlocked"] is False
    assert out["items"][0]["after"]["distinctSignalDates"] == 1


def test_ops_dashboard_reports_journal_and_file_health(isolated_vtj: Path) -> None:
    row = {
        **vtj._snapshot_from_item(_valid_recommendation("OPS"), "FORWARD_PAPER_TRADE", "2026-06-18", "AFTER_CLOSE_TRADE"),
        "journal_id": "ops-1",
    }
    vtj._write_rows(vtj.JOURNAL_CSV, [row], vtj.JOURNAL_COLS)

    out = vtj.ops_dashboard("kr")

    assert out["status"] == "OK"
    assert out["journal"]["totalRows"] == 1
    assert out["journal"]["sourceCounts"]["FORWARD_PAPER_TRADE"] == 1
    assert any(str(item["path"]).endswith("journal.csv") and item["exists"] for item in out["files"])


def test_historical_strategy_calibration_keeps_historical_research_out_of_forward_gate(isolated_vtj: Path) -> None:
    history_rows = []
    eval_rows = []
    for i in range(30):
        created = f"2026-01-{(i % 20) + 1:02d} 09:00:00"
        symbol = f"T{i:03d}"
        history_rows.append({
            "created_at": created,
            "market": "us",
            "symbol": symbol,
            "mode": "balanced",
            "hold_days": "5",
            "data_status": "NORMAL",
        })
        eval_rows.append({
            "evaluated_at": "2026-02-01 09:00:00",
            "created_at": created,
            "market": "us",
            "symbol": symbol,
            "name": symbol,
            "mode": "balanced",
            "outcome_result": "stop_hit",
            "realized_return_pct": "-4.5",
        })
    pd.DataFrame(history_rows).to_csv(vtj.HISTORY_OPERATION_CSV, index=False)
    pd.DataFrame(eval_rows).to_csv(vtj.HISTORY_EVALUATION_CSV, index=False)
    pd.DataFrame([
        {
            "market": "us",
            "symbol": f"F{i:03d}",
            "mode": "balanced",
            "horizon": "swing",
            "result": "STOP",
            "returnPct": "-2.0",
            "dataStatus": "NORMAL",
        }
        for i in range(30)
    ]).to_csv(vtj.VIRTUAL_VALIDATION_RESULTS_CSV, index=False)

    out = vtj.historical_strategy_calibration(
        market="us",
        min_samples=30,
        include_chart=False,
        include_pattern=False,
    )

    assert out["status"] == "OK"
    assert out["counts"]["historicalOperationRows"] == 30
    assert out["counts"]["virtualValidationRows"] == 30
    assert out["counts"]["forwardEligibleRows"] == 30
    row = out["strategyRows"][0]
    assert row["market"] == "us"
    assert row["mode"] == "balanced"
    assert row["horizon"] == "swing"
    assert row["sampleCount"] == 30
    assert row["winRate"] == 0
    assert out["historicalResearchRows"][0]["sampleCount"] == 30
    suggestion = out["suggestions"][0]
    assert suggestion["status"] == "SUGGESTED"
    assert suggestion["action"] == "WIDEN_STOP_OR_TIGHTEN_ENTRY"


def test_performance_dashboard_excludes_replay_and_missing_return_rows_from_live_metrics(monkeypatch, isolated_vtj: Path) -> None:
    rows = [
        {
            "market": "us", "mode": "balanced", "horizon": "swing", "source_type": "FORWARD_PAPER_TRADE",
            "status": "EVALUATED", "outcome": "STOP", "net_pnl_pct": "-2.0", "as_of_date": "2026-01-02",
        },
        {
            "market": "us", "mode": "balanced", "horizon": "swing", "source_type": "HISTORICAL_REPLAY",
            "status": "EVALUATED", "outcome": "TARGET_HIT", "net_pnl_pct": "10.0", "as_of_date": "2025-01-02",
        },
        {
            "market": "us", "mode": "balanced", "horizon": "swing", "source_type": "FORWARD_PAPER_TRADE",
            "status": "EVALUATED", "outcome": "STOP", "net_pnl_pct": "", "as_of_date": "2026-01-03",
        },
    ]
    monkeypatch.setattr(vtj, "_read_journal_rows", lambda: rows)
    monkeypatch.setattr(vtj, "_merge_evaluations", lambda source: source)

    out = vtj.performance_by_strategy(market="us")

    assert out["summary"]["count"] == 1
    assert out["summary"]["avgPnlPct"] == -2.0
    assert out["researchOnly"]["count"] == 2
    assert out["performanceDataPolicy"]["requiresRealizedReturn"] is True


def test_historical_replay_cannot_auto_apply_live_calibration() -> None:
    verdict = vtj._auto_calibration_verdict({
        "status": "SUGGESTED",
        "approvalStatus": "PENDING_REVIEW",
        "applicationStatus": "",
        "sourceType": "HISTORICAL_REPLAY",
        "sampleCount": 5000,
        "share": 0.1,
        "reason": "STOP_TOO_TIGHT",
    })

    assert verdict["eligible"] is False
    assert verdict["reason"] == "RAW_SAMPLE_GATE"
