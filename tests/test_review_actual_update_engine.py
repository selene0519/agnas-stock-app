from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from core.review_actual_update_engine import (
    ACTUAL_REQUIRED_COLUMNS,
    coerce_ohlc_frame,
    ensure_actual_columns,
    enrich_review_columns,
    market_actual_ready,
    run_review_actual_update,
    select_actual_row,
    update_predictions_with_actuals,
)


def test_ensure_actual_columns_adds_status_columns():
    out = ensure_actual_columns(pd.DataFrame([{"ticker": "AAPL", "target_date": "2026-05-14"}]))

    for col in ACTUAL_REQUIRED_COLUMNS:
        assert col in out.columns


def test_existing_actual_ohlc_is_not_overwritten():
    calls = []

    def fetcher(ticker, market, target_date):
        calls.append((ticker, market, target_date))
        return {
            "actual_open": 100,
            "actual_high": 110,
            "actual_low": 90,
            "actual_close": 105,
            "actual_volume": 999,
        }

    df = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "market": "US",
                "target_date": "2026-05-14",
                "actual_open": 1,
                "actual_high": 2,
                "actual_low": 0.5,
                "actual_close": 1.5,
                "actual_volume": 10,
            }
        ]
    )

    out, stats = update_predictions_with_actuals(df, today=date(2026, 5, 18), fetcher=fetcher)

    assert calls == []
    assert stats.skipped_existing == 1
    assert out.loc[0, "actual_open"] == 1
    assert out.loc[0, "actual_update_status"] == "already_present"


def test_missing_actual_ohlc_is_filled_and_review_can_recalculate():
    def fetcher(ticker, market, target_date):
        return {
            "actual_date": "2026-05-14",
            "actual_open": 101,
            "actual_high": 112,
            "actual_low": 98,
            "actual_close": 108,
            "actual_volume": 12345,
            "actual_source": "test",
        }

    df = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "market": "US",
                "target_date": "2026-05-14",
                "preferred_entry": 100,
                "stop_loss": 95,
                "take_profit1": 110,
            }
        ]
    )

    out, stats = update_predictions_with_actuals(
        df,
        today=date(2026, 5, 18),
        fetcher=fetcher,
        now=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert stats.updated_rows == 1
    assert stats.filled_cells == 4
    assert out.loc[0, "actual_open"] == 101
    assert out.loc[0, "actual_high"] >= out.loc[0, "actual_open"]
    assert out.loc[0, "actual_low"] <= out.loc[0, "actual_open"]
    assert len({out.loc[0, c] for c in ["actual_open", "actual_high", "actual_low", "actual_close"]}) > 1
    assert out.loc[0, "actual_volume"] == 12345
    assert out.loc[0, "actual_update_status"] == "updated"
    assert str(out.loc[0, "actual_updated_at"]).startswith("2026-05-18T21:00:00")


def test_flat_existing_ohlc_is_refreshed_from_distinct_daily_values():
    def fetcher(ticker, market, target_date):
        return {
            "actual_date": "2026-05-14",
            "actual_open": 101,
            "actual_high": 112,
            "actual_low": 98,
            "actual_close": 108,
            "actual_volume": 12345,
            "actual_source": "test_daily",
        }

    df = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "market": "US",
                "target_date": "2026-05-14",
                "actual_open": 100,
                "actual_high": 100,
                "actual_low": 100,
                "actual_close": 100,
                "actual_volume": 0,
                "actual_source": "KIS Open API",
            }
        ]
    )

    out, stats = update_predictions_with_actuals(df, today=date(2026, 5, 18), fetcher=fetcher)

    assert stats.flat_suspect_rows == 1
    assert stats.updated_rows == 1
    assert out.loc[0, "actual_open"] == 101
    assert out.loc[0, "actual_high"] == 112
    assert out.loc[0, "actual_low"] == 98
    assert out.loc[0, "actual_close"] == 108
    assert out.loc[0, "actual_source"] == "test_daily"
    assert out.loc[0, "actual_update_status"] == "refreshed_flat_ohlc"


def test_flat_existing_ohlc_is_cleared_when_refresh_fails():
    df = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "market": "US",
                "target_date": "2026-05-14",
                "actual_open": 100,
                "actual_high": 100,
                "actual_low": 100,
                "actual_close": 100,
                "actual_volume": 0,
                "actual_source": "KIS Open API",
            }
        ]
    )

    out, stats = update_predictions_with_actuals(
        df,
        today=date(2026, 5, 18),
        fetcher=lambda ticker, market, target_date: None,
    )

    assert stats.flat_suspect_rows == 1
    assert stats.cleared_flat_rows == 1
    assert out.loc[0, "actual_update_status"] == "fetch_failed"
    assert pd.isna(out.loc[0, "actual_open"])
    assert pd.isna(out.loc[0, "actual_high"])
    assert pd.isna(out.loc[0, "actual_low"])
    assert pd.isna(out.loc[0, "actual_close"])


def test_coerce_ohlc_frame_reads_open_high_low_close_separately_and_preserves_date():
    raw = pd.DataFrame(
        {
            "Date": [
                pd.Timestamp("2026-05-14 00:00:00", tz="Asia/Seoul"),
                pd.Timestamp("2026-05-15 00:00:00", tz="Asia/Seoul"),
            ],
            "Open": [101, 201],
            "High": [112, 212],
            "Low": [98, 198],
            "Close": [108, 208],
            "Volume": [12345, 45678],
        }
    )

    frame = coerce_ohlc_frame(raw)
    row = select_actual_row(frame, date(2026, 5, 14))

    assert row is not None
    assert str(row["Date"]) == "2026-05-14"
    assert row["Open"] == 101
    assert row["High"] == 112
    assert row["Low"] == 98
    assert row["Close"] == 108


def test_review_metrics_use_distinct_ohlc_for_profit_and_drawdown():
    df = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "market": "US",
                "target_date": "2026-05-14",
                "preferred_entry": 100,
                "stop_loss": 95,
                "take_profit1": 110,
                "actual_open": 101,
                "actual_high": 112,
                "actual_low": 98,
                "actual_close": 108,
            }
        ]
    )

    out = enrich_review_columns(df)

    assert out.loc[0, "max_profit_pct"] == 12.0
    assert out.loc[0, "max_drawdown_pct"] == -2.0


def test_future_target_date_is_left_pending():
    def fetcher(ticker, market, target_date):
        raise AssertionError("future rows should not fetch")

    df = pd.DataFrame([{"ticker": "AAPL", "market": "US", "target_date": "2099-01-01"}])
    out, stats = update_predictions_with_actuals(df, today=date(2026, 5, 18), fetcher=fetcher)

    assert stats.future_rows == 1
    assert out.loc[0, "actual_update_status"] == "pending_future"


def test_us_target_date_is_pending_before_us_close_even_if_kst_date_matches():
    def fetcher(ticker, market, target_date):
        raise AssertionError("US target day should not fetch before the US session closes")

    df = pd.DataFrame([{"ticker": "AAPL", "market": "미국주식", "target_date": "2026-05-18"}])
    out, stats = update_predictions_with_actuals(
        df,
        today=date(2026, 5, 18),
        fetcher=fetcher,
        now=datetime(2026, 5, 18, 17, 51, tzinfo=timezone.utc).astimezone(),
    )

    assert stats.pending_not_ready_rows == 1
    assert out.loc[0, "actual_update_status"] == "pending_session_not_closed"


def test_market_actual_ready_uses_market_close_not_local_date_only():
    assert market_actual_ready("미국주식", date(2026, 5, 18), datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc)) is False
    assert market_actual_ready("미국주식", date(2026, 5, 18), datetime(2026, 5, 18, 22, 0, tzinfo=timezone.utc)) is True
    assert market_actual_ready("한국주식", date(2026, 5, 18), datetime(2026, 5, 18, 6, 0, tzinfo=timezone.utc)) is False
    assert market_actual_ready("한국주식", date(2026, 5, 18), datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc)) is True


def test_run_review_actual_update_writes_required_columns_and_review(monkeypatch, tmp_path):
    path = tmp_path / "predictions.csv"
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "market": "US",
                "target_date": "2026-05-14",
                "preferred_entry": 100,
                "stop_loss": 95,
                "take_profit1": 110,
            }
        ]
    ).to_csv(path, index=False)

    def fake_fetch(ticker, market, target_date):
        return {
            "actual_date": "2026-05-14",
            "actual_open": 101,
            "actual_high": 112,
            "actual_low": 98,
            "actual_close": 108,
            "actual_volume": 12345,
            "actual_source": "test",
        }

    monkeypatch.setattr("core.review_actual_update_engine.fetch_actual_ohlc", fake_fetch)
    out, stats = run_review_actual_update(path)
    saved = pd.read_csv(path)

    assert stats.updated_rows == 1
    for col in ACTUAL_REQUIRED_COLUMNS:
        assert col in saved.columns
    assert out.loc[0, "prediction_result"] in {"success", "fail", "neutral", "not_enough_data"}
    assert "failure_reason" in saved.columns
