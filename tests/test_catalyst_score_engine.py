import json
from datetime import datetime, timezone

import pandas as pd

from core.api_data_quality_engine import save_api_data_quality_summary
from core.catalyst_score_engine import (
    apply_catalyst_scores,
    calculate_catalyst_score,
    deduplicate_news_items,
    save_catalyst_runtime_reports,
    save_catalyst_score_summary,
    save_disclosure_score_summary,
    save_news_dedup_summary,
)


def test_api_failure_does_not_raise_and_adds_warning():
    result = calculate_catalyst_score(
        {"symbol": "ABC", "volume_ratio": 1.0},
        {"api_errors": ["finnhub timeout"], "news": None, "disclosures": None},
    )

    assert 0 <= result["catalyst_score"] <= 100
    assert any("API 실패" in warning for warning in result["catalyst_warnings"])


def test_catalyst_score_is_clipped_0_100():
    result = calculate_catalyst_score(
        {
            "symbol": "ABC",
            "revenue_growth": 999,
            "operating_income_growth": 999,
            "net_income_growth": 999,
            "operating_margin": 999,
            "roe": 999,
            "volume_ratio": 99,
        },
        {
            "news": [{"title": "huge contract growth approval", "published_at": "2026-05-18", "importance": 999}],
            "disclosures": [{"title": "major contract order"}],
        },
    )

    assert 0 <= result["catalyst_score"] <= 100


def test_negative_disclosure_penalizes_disclosure_score():
    good = calculate_catalyst_score({}, {"disclosures": [{"title": "major contract order"}]})
    bad = calculate_catalyst_score({}, {"disclosures": [{"title": "lawsuit investigation risk"}]})

    assert bad["disclosure_score"] < good["disclosure_score"]
    assert any("악재 공시" in warning for warning in bad["catalyst_warnings"])


def test_news_deduplication_removes_duplicate_titles():
    news = [
        {"title": "AI contract signed", "published_at": "2026-05-18"},
        {"title": "AI contract signed", "published_at": "2026-05-18"},
        {"title": "Different update", "published_at": "2026-05-18"},
    ]

    assert len(deduplicate_news_items(news)) == 2
    result = calculate_catalyst_score({}, {"news": news})

    assert any("뉴스 중복 제거 후 2건" in item for item in result["decision_change_log"])


def test_old_news_has_low_freshness_score():
    result = calculate_catalyst_score(
        {},
        {
            "news": [{"title": "old contract news", "published_at": "2020-01-01"}],
        },
    )

    assert result["news_freshness_score"] <= 30


def test_apply_catalyst_scores_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", "custom_col": "keep", "volume_ratio": 2.0}])

    out = apply_catalyst_scores(df, {"ABC": {"news": [{"title": "growth contract", "published_at": "2026-05-18"}]}})

    assert "custom_col" in out.columns
    assert out.loc[0, "custom_col"] == "keep"
    assert "catalyst_score" in out.columns


def test_api_data_quality_summary_is_created_without_secret_values(tmp_path):
    target = tmp_path / "reports" / "api_data_quality_summary.json"
    env = {
        "KIS_APP_KEY": "secret-key",
        "KIS_APP_SECRET": "secret-secret",
        "DART_API_KEY": "secret-dart",
        "FINNHUB_API_KEY": "secret-finnhub",
        "SEC_USER_AGENT": "secret-agent",
    }

    summary = save_api_data_quality_summary(target, env=env)
    raw = target.read_text(encoding="utf-8")

    assert target.exists()
    assert summary["kis_available"] is True
    assert summary["dart_available"] is True
    assert "KIS_ACCESS_TOKEN" not in summary["missing_env_keys"]
    assert summary["kis_key_loaded"] is True
    assert summary["kis_secret_loaded"] is True
    assert "secret-key" not in raw
    assert "secret-dart" not in raw


def test_catalyst_score_summary_is_created(tmp_path):
    target = tmp_path / "reports" / "catalyst_score_summary.json"
    df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "catalyst_score": 60,
                "news_importance_score": 55,
                "disclosure_score": 50,
                "earnings_score": 65,
                "supply_score": 70,
            }
        ]
    )

    summary = save_catalyst_score_summary(target, candidate_df=df)

    assert target.exists()
    assert summary["row_count"] == 1
    assert summary["avg_catalyst_score"] == 60


def test_news_dedup_summary_is_created(tmp_path):
    target = tmp_path / "reports" / "news_dedup_summary.json"
    context = {
        "AAA": {
            "news": [
                {"title": "same news", "published_at": "2026-05-18"},
                {"title": "same news", "published_at": "2026-05-18"},
            ]
        }
    }

    summary = save_news_dedup_summary(target, context)

    assert target.exists()
    assert summary["collected_news_count"] == 2
    assert summary["deduped_news_count"] == 1
    assert summary["duplicate_removed_count"] == 1


def test_disclosure_score_summary_is_created(tmp_path):
    target = tmp_path / "reports" / "disclosure_score_summary.json"
    context = {
        "AAA": {
            "disclosures": [
                {"title": "major contract order"},
                {"title": "lawsuit investigation risk"},
            ]
        }
    }

    summary = save_disclosure_score_summary(target, context)

    assert target.exists()
    assert summary["disclosure_count"] == 2
    assert summary["negative_disclosure_count"] == 1
    assert summary["positive_disclosure_count"] == 1


def test_runtime_reports_are_created_when_api_failed(tmp_path, monkeypatch):
    import core.api_data_quality_engine as api_engine
    import core.catalyst_score_engine as catalyst_engine

    monkeypatch.setattr(api_engine, "API_DATA_QUALITY_SUMMARY_JSON", tmp_path / "reports" / "api_data_quality_summary.json")
    monkeypatch.setattr(catalyst_engine, "CATALYST_SCORE_SUMMARY_JSON", tmp_path / "reports" / "catalyst_score_summary.json")
    monkeypatch.setattr(catalyst_engine, "NEWS_DEDUP_SUMMARY_JSON", tmp_path / "reports" / "news_dedup_summary.json")
    monkeypatch.setattr(catalyst_engine, "DISCLOSURE_SCORE_SUMMARY_JSON", tmp_path / "reports" / "disclosure_score_summary.json")

    save_catalyst_runtime_reports(
        candidate_df=pd.DataFrame([{"symbol": "ABC", "catalyst_score": 0}]),
        api_contexts={"ABC": {"api_errors": ["network down"]}},
    )

    for name in [
        "api_data_quality_summary.json",
        "catalyst_score_summary.json",
        "news_dedup_summary.json",
        "disclosure_score_summary.json",
    ]:
        assert (tmp_path / "reports" / name).exists()
    api_summary = json.loads((tmp_path / "reports" / "api_data_quality_summary.json").read_text(encoding="utf-8"))
    assert api_summary["api_status"] in {"WARNING", "ERROR"}
    assert api_summary["error_count"] >= 1


def test_kis_token_failure_is_recorded_without_raising(tmp_path, monkeypatch):
    import core.kis_token_manager as kis_token_manager

    target = tmp_path / "reports" / "api_data_quality_summary.json"
    env = {
        "KIS_APP_KEY": "secret-key",
        "KIS_APP_SECRET": "secret-secret",
        "DART_API_KEY": "secret-dart",
        "FINNHUB_API_KEY": "secret-finnhub",
        "SEC_USER_AGENT": "secret-agent",
    }

    def fake_get_kis_access_token(*args, **kwargs):
        return {
            "status": "failed",
            "valid": False,
            "auto_issued": False,
            "is_mock": True,
            "failure_reason": "KIS token HTTP error: 500",
        }

    monkeypatch.setattr(kis_token_manager, "get_kis_access_token", fake_get_kis_access_token)
    summary = save_api_data_quality_summary(target, env=env, attempt_kis_token=True)

    assert target.exists()
    assert summary["kis_token_status"] == "failed"
    assert summary["kis_access_token_valid"] is False
    assert summary["fallback_used"] is True
    assert summary["api_status"] == "WARNING"
    assert summary["api_failure_reasons"]


def test_kis_access_token_value_is_not_written_to_summary(tmp_path, monkeypatch):
    import core.kis_token_manager as kis_token_manager

    target = tmp_path / "reports" / "api_data_quality_summary.json"
    env = {
        "KIS_APP_KEY": "secret-key",
        "KIS_APP_SECRET": "secret-secret",
        "DART_API_KEY": "secret-dart",
        "FINNHUB_API_KEY": "secret-finnhub",
        "SEC_USER_AGENT": "secret-agent",
    }

    def fake_get_kis_access_token(*args, **kwargs):
        return {
            "status": "issued",
            "access_token": "SUPER-SECRET-TOKEN",
            "valid": True,
            "auto_issued": True,
            "is_mock": False,
            "failure_reason": "",
        }

    monkeypatch.setattr(kis_token_manager, "get_kis_access_token", fake_get_kis_access_token)
    summary = save_api_data_quality_summary(target, env=env, attempt_kis_token=True)
    raw = target.read_text(encoding="utf-8")

    assert summary["kis_access_token_auto_issued"] is True
    assert summary["kis_access_token_valid"] is True
    assert "SUPER-SECRET-TOKEN" not in raw


def test_kis_real_mode_warning_reason_is_recorded(tmp_path, monkeypatch):
    import core.kis_token_manager as kis_token_manager

    target = tmp_path / "reports" / "api_data_quality_summary.json"
    env = {
        "KIS_APP_KEY": "secret-key",
        "KIS_APP_SECRET": "secret-secret",
        "DART_API_KEY": "secret-dart",
        "FINNHUB_API_KEY": "secret-finnhub",
        "SEC_USER_AGENT": "secret-agent",
    }

    def fake_get_kis_access_token(*args, **kwargs):
        return {
            "status": "cached",
            "access_token": "SUPER-SECRET-TOKEN",
            "valid": True,
            "auto_issued": False,
            "is_mock": False,
            "failure_reason": "",
        }

    monkeypatch.setattr(kis_token_manager, "get_kis_access_token", fake_get_kis_access_token)
    summary = save_api_data_quality_summary(target, env=env, attempt_kis_token=True)
    raw = target.read_text(encoding="utf-8")

    assert summary["warning_count"] == 1
    assert "KIS 실전 서버 모드: 주문 기능 없음, 데이터 조회만 사용" in summary["api_warning_reasons"]
    assert "SUPER-SECRET-TOKEN" not in raw


def test_kis_token_failure_adds_catalyst_warning():
    result = calculate_catalyst_score(
        {"symbol": "ABC"},
        {"kis_token_status": "failed", "kis_token_failed": True},
    )

    assert "KIS 토큰 발급 실패: fallback 점수 사용" in result["catalyst_warnings"]


def test_decision_change_log_has_component_specific_reasons():
    result = calculate_catalyst_score(
        {"symbol": "ABC", "volume_ratio": 0.5},
        {
            "news": [{"title": "old lawsuit risk", "published_at": "2020-01-01"}],
            "disclosures": [{"source": "DART", "title": "lawsuit investigation risk"}],
        },
    )

    logs = " / ".join(result["decision_change_log"])
    assert "DART 부정 공시 확인: 감점" in logs
    assert "뉴스 신선도 낮음: 소폭 감점" in logs
    assert "수급 점수 약함: 소폭 감점" in logs


def test_missing_news_and_disclosure_are_neutral_not_bad_disclosure():
    result = calculate_catalyst_score({"symbol": "ABC", "score": 50}, {"news": [], "disclosures": []})
    logs = " / ".join(result["decision_change_log"])

    assert "최근 뉴스 없음: 중립 유지" in logs
    assert "공시 특이사항 없음: 중립 유지" in logs
    assert "부정 공시 확인: 감점" not in logs
    assert result["news_data_status"] == "no_recent_issue"
    assert result["disclosure_data_status"] == "no_recent_issue"


def test_positive_signal_raises_catalyst_score():
    neutral = calculate_catalyst_score({"symbol": "ABC", "score": 50}, {"news": [], "disclosures": []})
    positive = calculate_catalyst_score(
        {"symbol": "ABC", "score": 90, "turnover": 3_000_000_000, "sector": "반도체/AI"},
        {"news": [{"title": "major growth contract approval", "published_at": "2026-05-18"}]},
    )

    assert positive["catalyst_score"] > neutral["catalyst_score"]
    assert any("가산" in item for item in positive["decision_change_log"])


def test_negative_signal_lowers_catalyst_score():
    neutral = calculate_catalyst_score({"symbol": "ABC", "score": 50}, {"news": [], "disclosures": []})
    negative = calculate_catalyst_score(
        {"symbol": "ABC", "score": 20, "volume_ratio": 0.2},
        {
            "news": [{"title": "lawsuit investigation risk", "published_at": "2026-05-18"}],
            "disclosures": [{"title": "offering downgrade investigation risk"}],
        },
    )

    assert negative["catalyst_score"] < neutral["catalyst_score"]
    assert any("감점" in item for item in negative["decision_change_log"])


def test_decision_change_log_varies_by_row_features():
    strong = calculate_catalyst_score({"symbol": "AAA", "score": 95, "turnover": 5_000_000_000}, {"news": []})
    weak = calculate_catalyst_score({"symbol": "BBB", "score": 15, "turnover": 10_000_000}, {"news": []})

    assert strong["decision_change_log"] != weak["decision_change_log"]
