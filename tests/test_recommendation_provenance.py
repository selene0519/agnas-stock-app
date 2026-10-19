from __future__ import annotations

import runpy
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

from app import main  # noqa: E402
from app.services import event_context, final_engine  # noqa: E402
from app.engine import quant_scanner  # noqa: E402


def test_cache_freshness_rejects_missing_old_and_future_times() -> None:
    now = datetime(2026, 10, 20, 12, tzinfo=ZoneInfo("Asia/Seoul"))
    assert final_engine.recommendation_cache_freshness({"precomputedAt": "2026-10-19 16:17:35"}, now)["status"] == "FRESH"
    assert final_engine.recommendation_cache_freshness({"precomputedAt": "2026-10-15 11:00:00"}, now)["status"] == "STALE"
    assert final_engine.recommendation_cache_freshness({"precomputedAt": "2026-10-21 11:00:00"}, now)["status"] == "FUTURE"
    assert final_engine.recommendation_cache_freshness({}, now)["status"] == "UNKNOWN"


def test_stale_cache_cannot_be_treated_as_actionable_even_if_global_data_is_normal() -> None:
    payload = {"servedFrom": "precompute", "precomputedAt": "2000-01-01 00:00:00", "items": [{"symbol": "TEST", "recommended": True}]}
    result = main._apply_recommendation_trade_safety(payload, {"dataStatus": "NORMAL"})
    assert result["cacheFreshness"]["status"] == "STALE"
    assert result["tradeSafety"]["isTradeBlocked"] is True
    assert result["items"][0]["reviewOnly"] is True


def test_slim_recommendation_preserves_evidence_but_not_heavy_chart_payload(monkeypatch) -> None:
    monkeypatch.setenv("MONE_DISABLE_PRECOMPUTE", "1")
    script = runpy.run_path(str(ROOT / "scripts/precompute_recommendations.py"))
    result = script["_slim_item"]({
        "symbol": "A", "recommended": False, "newsCount": 2, "disclosureCount": 0,
        "eventContextUsed": True, "chartSignalUsed": False, "priceSourceDate": "2026-10-19",
        "chartSignalSummary": {"status": "unavailable", "source": "ohlcv", "trendlineLearning": {"large": [1, 2]}},
        "patternStrategy": {"status": "ERROR", "isBlocked": False, "details": [1, 2]},
    })
    assert result["newsCount"] == 2 and result["disclosureCount"] == 0
    assert result["eventContextUsed"] is True and result["chartSignalUsed"] is False
    assert result["chartSignalSummary"] == {"status": "unavailable", "source": "ohlcv"}
    assert result["patternStrategy"] == {"status": "ERROR", "isBlocked": False}
    assert result["priceSourceDate"] == "2026-10-19"


def test_precompute_reports_failure_when_any_combination_fails(monkeypatch) -> None:
    monkeypatch.setenv("MONE_DISABLE_PRECOMPUTE", "1")
    script = runpy.run_path(str(ROOT / "scripts/precompute_recommendations.py"))
    monkeypatch.setattr(sys, "argv", ["precompute_recommendations.py", "--market", "kr"])

    def fail(*args, **kwargs):
        raise RuntimeError("test generation failure")

    monkeypatch.setattr(final_engine, "final_recommendations", fail)
    assert script["main"]() == 1


def test_empty_event_feeds_are_unknown_not_proof_of_no_risk(monkeypatch) -> None:
    monkeypatch.setattr(event_context, "_news_cache_entry", lambda *_: {})
    monkeypatch.setattr(event_context, "_get_news_rows", lambda *_: [])
    monkeypatch.setattr(event_context, "_get_disclosure_rows", lambda *_: [])
    result = event_context.get_event_context("AAPL", "us")
    assert result["newsEventTag"] == "unknown"
    assert result["disclosureEventTag"] == "unknown"
    assert result["eventDataSourceType"] == "unavailable"
    assert result["eventSummary"] == "이벤트 데이터 확인 불가"


def test_historical_event_context_never_reads_current_news(monkeypatch) -> None:
    def forbidden(*args):
        raise AssertionError("current cache must not be read for historical evaluation")
    monkeypatch.setattr(event_context, "_news_cache_entry", forbidden)
    result = event_context.get_event_context("AAPL", "us", as_of_date="2020-01-01")
    assert result["eventDataSourceType"] == "unavailable"
    assert result["eventLearningEligible"] is False
    assert result["newsEventTag"] == "unknown"


def test_unverified_cached_news_is_not_misrepresented_as_live_or_learning_evidence(monkeypatch) -> None:
    monkeypatch.setattr(event_context, "_news_cache_entry", lambda *_: {"tag": "NEGATIVE", "penalty": 2})
    monkeypatch.setattr(event_context, "_get_news_rows", lambda *_: [])
    monkeypatch.setattr(event_context, "_get_disclosure_rows", lambda *_: [])
    result = event_context.get_event_context("AAPL", "us")
    assert result["newsEventTag"] == "negative_news"
    assert result["eventDataSourceType"] == "cached"
    assert result["eventLearningEligible"] is False
    assert result["eventReliabilityScore"] == 0
    assert event_context.compute_event_score_adjustment(result) == 0
    assert "최신성 미검증" in result["eventSummary"]


def test_us_regime_requires_at_least_two_sufficient_indices(monkeypatch, tmp_path) -> None:
    ohlcv = tmp_path / "data" / "market" / "ohlcv"
    ohlcv.mkdir(parents=True)
    (ohlcv / "us_SPY_daily.csv").touch()
    rows = [{"date": f"2026-10-{day:02d}", "close": str(100 + day)} for day in range(1, 21)]
    monkeypatch.setattr(quant_scanner, "_read_csv", lambda _: rows)
    assert quant_scanner.load_market_regime(tmp_path, "us")["dataStatus"] == "INSUFFICIENT"
    (ohlcv / "us_QQQ_daily.csv").touch()
    result = quant_scanner.load_market_regime(tmp_path, "us")
    assert result["dataStatus"] == "NORMAL"
    assert result["indexCount"] == 2
    assert result["asOf"] == "2026-10-20"
