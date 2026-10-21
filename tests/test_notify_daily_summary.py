"""장전 텔레그램 브리핑의 이벤트 정보가 실행 가능한 형태인지 검증한다."""
from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "notify_daily_summary.py"
_SPEC = importlib.util.spec_from_file_location("notify_daily_summary", _SCRIPT)
assert _SPEC and _SPEC.loader
notify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notify)


def test_economic_briefing_includes_forecast_previous_and_actual(monkeypatch):
    monkeypatch.setattr(
        notify,
        "_event_rows_for_market",
        lambda market, days=1: [{
            "date": "2026-10-21T08:30:00Z",
            "country": "US",
            "event": "Consumer Price Index",
            "impact": "high",
            "actual": "3.0",
            "forecast": "3.1",
            "previous": "3.2",
            "unit": "%",
        }],
    )

    text = notify.build_economic_section("us")

    assert "Consumer Price Index" in text
    assert "실제 3.0%" in text
    assert "예상 3.1%" in text
    assert "이전 3.2%" in text
    assert "갭 추격을 금지" in text


def test_focus_earnings_marks_candidate_with_estimates(monkeypatch):
    monkeypatch.setattr(
        notify,
        "_focus_earnings_rows",
        lambda market, days=1: [{
            "date": "2026-10-21",
            "symbol": "MONE",
            "name": "MONE Inc",
            "epsEstimate": "1.25",
            "revenueEstimate": "1000000000",
            "hour": "amc",
        }],
    )

    text, symbols = notify.build_earnings_risk_section("us")

    assert "EPS 예상 1.25" in text
    assert "매출 예상 1000000000" in text
    assert "장후" in text
    assert "MONE" in symbols


def test_event_metric_keeps_a_zero_actual_value():
    assert notify._event_metric("실제", 0, "%") == "실제 0%"
