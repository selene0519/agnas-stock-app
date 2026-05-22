import json

from core.market_hardblock_engine import evaluate_market_hardblock
from core.market_regime_engine import build_market_regime_summary


def test_candidate_down_ratio_85_or_more_triggers_hardblock():
    result = evaluate_market_hardblock({"candidate_down_ratio": 0.86})

    assert result["market_hardblock"] is True
    assert result["hardblock_level"] in {"강함", "매우 강함"}
    assert result["new_buy_blocked"] is True


def test_hardblock_strong_or_more_blocks_new_buys():
    result = evaluate_market_hardblock({"candidate_down_ratio": 0.76})

    assert result["hardblock_level"] in {"강함", "매우 강함"}
    assert result["new_buy_blocked"] is True


def test_single_minor_signal_is_warning_not_block():
    result = evaluate_market_hardblock({"usdkrw_change_pct": 0.8})

    assert result["hardblock_level"] == "주의"
    assert result["new_buy_blocked"] is False


def test_multiple_external_shocks_can_be_very_strong():
    result = evaluate_market_hardblock(
        {
            "vix_change_pct": 10,
            "nasdaq_future_change_pct": -2,
            "sp500_future_change_pct": -1.5,
        }
    )

    assert result["hardblock_level"] == "매우 강함"
    assert result["market_hardblock"] is True


def test_market_regime_summary_keeps_existing_keys_when_written(tmp_path, monkeypatch):
    import core.market_regime_engine as engine

    target = tmp_path / "market_regime_summary.json"
    history = tmp_path / "market_regime_history.csv"
    monkeypatch.setattr(engine, "MARKET_REGIME_SUMMARY", target)
    monkeypatch.setattr(engine, "MARKET_REGIME_HISTORY", history)
    monkeypatch.setattr(
        engine,
        "load_market_inputs",
        lambda market: {
            "market": market,
            "updated_at": "2026-05-18 10:00:00",
            "nasdaq_pct": 0,
            "news_text": "",
            "candidate_down_ratio": 0.9,
            "breadth_risk_score": 90,
        },
    )
    monkeypatch.setattr(
        engine,
        "_load_candidate_breadth_context",
        lambda market: {
            "candidate_up_ratio": 0.1,
            "candidate_down_ratio": 0.9,
            "candidate_avg_change_pct": -1,
            "candidate_median_change_pct": -1,
            "candidate_volume_strength": 1.5,
            "breadth_risk_score": 90,
            "market_breadth_warning": "위험회피 후보",
            "sector_spread_score": 0,
            "sector_internal_strength": [],
        },
    )

    summary = build_market_regime_summary("미국주식", write=True)
    saved = json.loads(target.read_text(encoding="utf-8"))

    for key in ["market_regime", "market_risk_score", "risk_level", "new_buy_allowed"]:
        assert key in summary
        assert key in saved
    assert "market_hardblock" in saved
    assert "candidate_down_ratio" in saved
