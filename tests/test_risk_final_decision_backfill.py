import pandas as pd

from core.risk_final_decision_backfill import (
    backfill_predictions_file,
    backfill_risk_final_decision,
    infer_risk_final_decision,
    normalize_risk_final_decision,
)


def test_existing_risk_final_decision_is_kept():
    df = pd.DataFrame([{"risk_final_decision": "손절 우선", "prediction_result": "fail"}])

    out = backfill_risk_final_decision(df)

    assert out.loc[0, "risk_final_decision"] == "손절 우선"
    assert out.loc[0, "risk_final_decision_source"] == "original"
    assert out.loc[0, "risk_final_decision_filled"] is False


def test_final_decision_is_copied_to_risk_final_decision():
    result = infer_risk_final_decision({"risk_final_decision": "", "final_decision": "비중 축소 우선"})

    assert result["risk_final_decision"] == "비중 축소 우선"
    assert result["risk_final_decision_source"] == "final_decision"


def test_not_enough_data_is_filled_conservatively():
    result = infer_risk_final_decision({"risk_final_decision": "", "prediction_result": "not_enough_data"})

    assert result["risk_final_decision"] in {"데이터 부족", "관망 우위"}
    assert result["risk_final_decision_source"] == "fallback_conservative"


def test_strategy_trade_allowed_false_never_becomes_buy():
    result = infer_risk_final_decision(
        {
            "risk_final_decision": "",
            "strategy_adjusted_grade": "A",
            "strategy_trade_allowed": False,
            "rr_pass": True,
        }
    )

    assert result["risk_final_decision"] != "매수 가능"
    assert result["risk_final_decision"] == "관망 우위"


def test_rr_pass_false_never_becomes_buy():
    result = infer_risk_final_decision(
        {
            "risk_final_decision": "",
            "strategy_adjusted_grade": "A",
            "strategy_trade_allowed": True,
            "rr_pass": False,
        }
    )

    assert result["risk_final_decision"] != "매수 가능"
    assert result["risk_final_decision"] == "관망 우위"


def test_source_and_reason_are_recorded_and_not_nan():
    out = backfill_risk_final_decision(pd.DataFrame([{"risk_final_decision": "", "prediction_result": "neutral"}]))

    assert out.loc[0, "risk_final_decision_source"]
    assert out.loc[0, "risk_final_decision_reason"]
    assert str(out.loc[0, "risk_final_decision_reason"]).lower() != "nan"


def test_existing_prediction_result_is_not_changed():
    df = pd.DataFrame([{"risk_final_decision": "", "prediction_result": "fail"}])

    out = backfill_risk_final_decision(df)

    assert out.loc[0, "prediction_result"] == "fail"


def test_backfill_predictions_file_creates_backup(tmp_path):
    path = tmp_path / "predictions.csv"
    pd.DataFrame([{"ticker": "A", "target_date": "2026-05-19", "risk_final_decision": "", "prediction_result": "neutral"}]).to_csv(
        path, index=False, encoding="utf-8-sig"
    )

    result = backfill_predictions_file(path)
    out = pd.read_csv(path, dtype=str).fillna("")

    assert result["ok"] is True
    assert result["before_missing_count"] == 1
    assert result["after_missing_count"] == 0
    assert result["risk_final_decision_filled_count"] == 1
    assert (tmp_path / "backups").exists()
    assert out.loc[0, "prediction_result"] == "neutral"
    assert out.loc[0, "risk_final_decision"] == "관망 우위"


def test_normalize_risk_final_decision_maps_known_values():
    assert normalize_risk_final_decision("신규매수 금지") == "관망 우위"
    assert normalize_risk_final_decision("손절") == "손절 우선"
    assert normalize_risk_final_decision("축소") == "비중 축소 우선"
