from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.services import data_loader, signal_ledger  # noqa: E402


def _snapshot() -> dict:
    return {
        "symbol": "TEST",
        "market": "us",
        "currentPrice": 100.0,
        "entryPrice": 99.0,
        "newsEventTag": "negative_news",
        "macroEventTag": "volatility_risk",
        "marketRegime": "SIDEWAYS",
    }


def test_empirical_forecast_keeps_raw_analog_probability_without_floor(monkeypatch) -> None:
    def fake_similar(*_args, **_kwargs):
        return {
            "source": "full OHLCV test data",
            "summary": {
                "d1": {"count": 20, "winRate": 42.0, "avgReturn": -0.5},
                "d5": {"count": 20, "winRate": 47.5, "avgReturn": 0.7},
                "d10": {"count": 20, "winRate": 61.0, "avgReturn": 1.4},
            },
        }

    monkeypatch.setattr(data_loader, "similar_pattern_history", fake_similar)
    signal_ledger._EMPIRICAL_FORECAST_CACHE.clear()

    forecast = signal_ledger._attach_empirical_forecast(_snapshot())

    assert forecast["forecastStatus"] == "MEASURED"
    assert forecast["forecastProbability1d"] == 42.0
    assert forecast["forecastExpectedReturn5d"] == 0.7
    assert forecast["forecastExpectedPrice10d"] == 101.4
    assert forecast["forecastDirection1d"] == "DOWN"
    assert forecast["forecastDirection5d"] == "UP"


def test_empirical_forecast_refuses_small_analog_sample(monkeypatch) -> None:
    monkeypatch.setattr(
        data_loader,
        "similar_pattern_history",
        lambda *_args, **_kwargs: {"summary": {"d1": {"count": 19, "winRate": 90, "avgReturn": 5}}},
    )
    signal_ledger._EMPIRICAL_FORECAST_CACHE.clear()

    forecast = signal_ledger._attach_empirical_forecast(_snapshot())

    assert forecast["forecastStatus"] == "INSUFFICIENT_SAMPLE"
    assert forecast.get("forecastProbability1d") is None


def test_forward_validation_reports_hit_error_and_context_as_hypothesis() -> None:
    row = {
        **_snapshot(),
        "forecastExpectedReturn1d": 1.0,
        "forecastExpectedReturn5d": 2.0,
        "forecastExpectedReturn10d": 3.0,
        "forecastDirection1d": "UP",
        "forecastDirection5d": "UP",
        "forecastDirection10d": "UP",
    }
    result = {
        "return_1d": 1.5,
        "return_5d": -1.0,
        "return_10d": None,
        "stop_first": False,
    }

    signal_ledger._attach_forecast_validation(row, result)

    assert result["forecastDirectionHit1d"] == "HIT"
    assert result["forecastDirectionHit5d"] == "MISS"
    assert result["forecastDirectionHit10d"] == "PENDING"
    assert result["forecastError1d"] == 0.5
    assert result["forecastFailureReason"] == "DIRECTION_MISS_WITH_EVENT_RISK_CONTEXT"
    assert "Do not infer causality" in result["forecastSuggestedAdjustment"]
