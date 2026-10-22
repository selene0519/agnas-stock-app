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


def test_main_returns_nonzero_when_telegram_delivery_fails(monkeypatch):
    monkeypatch.setattr(notify, "_send", lambda _message: False)
    monkeypatch.setattr(notify, "build_economic_section", lambda _market: "")
    monkeypatch.setattr(notify, "build_market_news_section", lambda _market: "")
    monkeypatch.setattr(notify, "build_recommendation_section", lambda *_args: "")
    monkeypatch.setattr(notify, "build_earnings_risk_section", lambda _market: ("", set()))
    monkeypatch.setattr(notify.sys, "argv", ["notify_daily_summary.py", "--market", "kr"])

    assert notify.main() == 1


def test_main_marks_a_late_scheduled_briefing(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(notify, "_send", lambda message: sent.append(message) or True)
    monkeypatch.setattr(notify, "build_economic_section", lambda _market: "")
    monkeypatch.setattr(notify, "build_market_news_section", lambda _market: "")
    monkeypatch.setattr(notify, "build_recommendation_section", lambda *_args: "")
    monkeypatch.setattr(notify, "build_earnings_risk_section", lambda _market: ("", set()))
    monkeypatch.setattr(notify, "DELAY_NOTICE", "⚠️ 예약 지연 도착")
    monkeypatch.setattr(notify.sys, "argv", ["notify_daily_summary.py", "--market", "us"])

    assert notify.main() == 0
    assert "⚠️ 예약 지연 도착" in sent[0]


def test_send_retries_plain_text_after_telegram_html_error(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    calls: list[dict] = []

    def fake_urlopen(request, timeout):
        calls.append(__import__("json").loads(request.data))
        if len(calls) == 1:
            raise notify.urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", hdrs=None, fp=None
            )
        return Response()

    monkeypatch.setattr(notify, "BOT_TOKEN", "token")
    monkeypatch.setattr(notify, "CHAT_ID", "chat")
    monkeypatch.setattr(notify, "DRY_RUN", False)
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)

    assert notify._send("<b>brief</b> & broken <tag") is True
    assert calls[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in calls[1]
