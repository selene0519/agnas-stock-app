import pandas as pd

from core.performance_penalty_engine import (
    apply_performance_penalty_to_candidates,
    build_failure_profile,
    calculate_performance_penalty,
)


OVERHEAT_HIGH = "\ub192\uc74c"
OVERHEAT_VERY_HIGH = "\ub9e4\uc6b0 \ub192\uc74c"
RR_WEAK = "\ubd80\uc871"
NEWS_PREPRICED = "\ub274\uc2a4 \uc120\ubc18\uc601"
CHASE_OVERHEAT = "\uacfc\uc5f4 \ucd94\uaca9"
MARKET_HIGH = "\ub192\uc74c"


def _review_rows(count=5, **overrides):
    rows = []
    for i in range(count):
        row = {
            "target_date": f"2026-05-{10 + i:02d}",
            "prediction_result": "fail",
            "decision_success": False,
            "failure_reason": overrides.get("failure_reason", ""),
            "overheat_level": overrides.get("overheat_level", ""),
            "rr_level": overrides.get("rr_level", ""),
            "news_grade": overrides.get("news_grade", ""),
            "market_risk_level": overrides.get("market_risk_level", ""),
            "chase_risk": overrides.get("chase_risk", False),
            "sell_the_news_risk": overrides.get("sell_the_news_risk", False),
            "risk_final_decision": overrides.get("risk_final_decision", ""),
            "setup_grade": overrides.get("setup_grade", ""),
        }
        rows.append(row)
    return rows


def test_not_enough_data_is_excluded_from_reviewed_count():
    df = pd.DataFrame(
        [
            {"prediction_result": "success"},
            {"prediction_result": "fail"},
            {"prediction_result": "neutral"},
            {"prediction_result": "not_enough_data"},
        ]
    )

    profile = build_failure_profile(df)

    assert profile["total_reviewed"] == 3


def test_failure_reason_counts_are_calculated_from_fail_rows():
    df = pd.DataFrame(
        [
            {"prediction_result": "fail", "failure_reason": CHASE_OVERHEAT},
            {"prediction_result": "fail", "failure_reason": CHASE_OVERHEAT},
            {"prediction_result": "success", "failure_reason": CHASE_OVERHEAT},
        ]
    )

    profile = build_failure_profile(df)

    assert profile["failure_reason_counts"][CHASE_OVERHEAT] == 2


def test_high_overheat_fail_rate_applies_penalty_to_matching_candidate():
    review_df = pd.DataFrame(_review_rows(5, overheat_level=OVERHEAT_HIGH))
    profile = build_failure_profile(review_df)

    result = calculate_performance_penalty({"overheat_level": OVERHEAT_HIGH}, profile)

    assert result["performance_penalty_score"] < 0
    assert result["recent_fail_pattern_hit"] is True


def test_weak_rr_fail_rate_applies_penalty_to_matching_candidate():
    review_df = pd.DataFrame(_review_rows(5, rr_level=RR_WEAK))
    profile = build_failure_profile(review_df)

    result = calculate_performance_penalty({"rr_level": RR_WEAK}, profile)

    assert result["performance_penalty_score"] < 0
    assert result["recent_fail_pattern_hit"] is True


def test_less_than_five_reviewed_condition_rows_do_not_apply_strong_penalty():
    review_df = pd.DataFrame(_review_rows(4, overheat_level=OVERHEAT_HIGH))
    profile = build_failure_profile(review_df)

    result = calculate_performance_penalty({"overheat_level": OVERHEAT_HIGH}, profile)

    assert result["performance_penalty_score"] == 0
    assert result["recent_fail_pattern_hit"] is False


def test_penalty_is_capped_at_minus_40():
    review_df = pd.DataFrame(
        _review_rows(
            5,
            overheat_level=OVERHEAT_VERY_HIGH,
            rr_level=RR_WEAK,
            news_grade="C",
            market_risk_level=MARKET_HIGH,
            chase_risk=True,
            sell_the_news_risk=True,
            failure_reason=CHASE_OVERHEAT,
        )
    )
    profile = build_failure_profile(review_df)

    result = calculate_performance_penalty(
        {
            "overheat_level": OVERHEAT_VERY_HIGH,
            "rr_level": RR_WEAK,
            "news_grade": "C",
            "market_risk_level": MARKET_HIGH,
            "chase_risk": True,
            "sell_the_news_risk": True,
            "failure_reason": CHASE_OVERHEAT,
        },
        profile,
    )

    assert result["performance_penalty_score"] == -40


def test_adjusted_score_after_review_stays_between_0_and_100():
    review_df = pd.DataFrame(_review_rows(5, overheat_level=OVERHEAT_VERY_HIGH))
    candidate_df = pd.DataFrame(
        [
            {"grade": "A", "score": 5, "overheat_level": OVERHEAT_VERY_HIGH},
            {"grade": "B", "score": 120, "overheat_level": ""},
        ]
    )

    out = apply_performance_penalty_to_candidates(candidate_df, review_df)

    assert out["adjusted_score_after_review"].between(0, 100).all()


def test_a_grade_is_downgraded_when_penalty_is_minus_15_or_lower():
    review_df = pd.DataFrame(_review_rows(5, overheat_level=OVERHEAT_VERY_HIGH))
    candidate_df = pd.DataFrame(
        [
            {"grade": "A", "grade_label": "A", "score": 90, "overheat_level": OVERHEAT_VERY_HIGH},
        ]
    )

    out = apply_performance_penalty_to_candidates(candidate_df, review_df)

    assert out.loc[0, "performance_penalty_score"] <= -15
    assert out.loc[0, "grade"] != "A"
