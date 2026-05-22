from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    build_future_probability_scope_df,
    count_future_probability_scope_rows,
    filter_future_probability_display_scope,
)


def _future_scope_flag_yes(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().isin(["예", "true", "True", "1", "1.0", "yes", "Y"])


def _future_probability_has_values(row: pd.Series) -> bool:
    for col in ("prob_up_1d", "prob_up_3d", "prob_up_5d", "prob_up_10d", "prob_tp1_5d", "prob_stop_5d"):
        val = row.get(col, "")
        text = str(val).strip() if val is not None else ""
        if text not in {"", "-", "nan", "None", "확인 필요"}:
            return True
    return False


def test_filter_전체_returns_all_rows():
    df = pd.DataFrame(
        [
            {"symbol": "AAPL", "display_group": "보유종목", "is_holding": "예", "is_watchlist": "아니오"},
            {"symbol": "TSLA", "display_group": "관심종목", "is_holding": "아니오", "is_watchlist": "예"},
        ]
    )
    out = filter_future_probability_display_scope(df, "전체")
    assert len(out) == 2


def test_filter_관심종목_watch_only():
    df = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "display_group": "A 후보",
                "is_holding": "아니오",
                "is_watchlist": "아니오",
                "candidate_group": "A 후보",
            },
            {
                "symbol": "TSLA",
                "display_group": "관심종목",
                "is_holding": "아니오",
                "is_watchlist": "예",
                "candidate_group": "",
            },
        ]
    )
    out = filter_future_probability_display_scope(df, "관심종목")
    assert list(out["symbol"]) == ["TSLA"]


def test_build_scope_falls_back_when_candidate_df_market_filtered_empty(monkeypatch):
    """Non-empty candidate_df that fails market filter must still load per-file CSV rows."""

    def _fake_iter(_market: str | None = None):
        row = pd.Series(
            {
                "symbol": "TSLA",
                "name": "Tesla",
                "market": "미국주식",
                "prob_up_5d": 0.62,
                "grade": "C",
            }
        )
        return [(row, "swing_candidates_us_C_excluded.csv")]

    def _empty_holdings(_market: str | None = None):
        return pd.DataFrame()

    def _empty_watch(_market: str | None = None):
        return pd.DataFrame()

    monkeypatch.setattr(
        "app._iter_swing_candidate_rows_for_future_prob",
        _fake_iter,
    )
    monkeypatch.setattr("app.load_future_probability_holdings_sources", _empty_holdings)
    monkeypatch.setattr("app.load_future_probability_watchlist_sources", _empty_watch)

    misleading = pd.DataFrame(
        [{"symbol": "OLD", "market": "한국주식", "prob_up_5d": 0.5}]
    )
    scope = build_future_probability_scope_df(misleading, market="미국주식")
    assert not scope.empty
    assert "TSLA" in scope["symbol"].astype(str).tolist()
    assert len(filter_future_probability_display_scope(scope, "전체")) == len(scope)


def test_build_scope_merges_holdings_with_c_excluded(monkeypatch):
    def _fake_iter(_market: str | None = None):
        row = pd.Series(
            {
                "symbol": "NVDA",
                "name": "NVIDIA",
                "market": "미국주식",
                "prob_up_5d": 0.55,
                "grade": "C",
            }
        )
        return [(row, "swing_candidates_us_C_excluded.csv")]

    def _holdings(_market: str | None = None):
        return pd.DataFrame(
            [
                {
                    "symbol": "TSLA",
                    "name": "Tesla",
                    "market": "미국주식",
                    "is_holding": True,
                }
            ]
        )

    monkeypatch.setattr("app._iter_swing_candidate_rows_for_future_prob", _fake_iter)
    monkeypatch.setattr("app.load_future_probability_holdings_sources", _holdings)
    monkeypatch.setattr("app.load_future_probability_watchlist_sources", lambda _m: pd.DataFrame())

    scope = build_future_probability_scope_df(None, market="미국주식")
    symbols = set(scope["symbol"].astype(str))
    assert "TSLA" in symbols
    assert "NVDA" in symbols
    counts = count_future_probability_scope_rows(scope)
    assert counts["전체"] == len(scope)
    assert counts["보유종목"] >= 1
    assert counts["C 제외/관망 포함"] >= 1


def test_build_scope_float_prob_and_avg_price_no_typeerror(monkeypatch):
    """StringDtype 후보 CSV + float prob/avg_price 병합 시 TypeError가 나지 않아야 한다."""

    def _fake_iter(_market: str | None = None):
        row = pd.Series(
            {
                "symbol": "AAPL",
                "name": "Apple",
                "market": "미국주식",
                "prob_up_1d": 0.58,
                "prob_up_5d": 0.62,
                "grade": "A",
            }
        )
        return [(row, "swing_candidates_us_a_top3.csv")]

    def _holdings(_market: str | None = None):
        return pd.DataFrame(
            [
                {
                    "symbol": "TSLA",
                    "name": "Tesla",
                    "market": "미국주식",
                    "is_holding": True,
                    "avg_price": 534.7917126188248,
                    "quantity": 10.0,
                }
            ]
        )

    monkeypatch.setattr("app._iter_swing_candidate_rows_for_future_prob", _fake_iter)
    monkeypatch.setattr("app.load_future_probability_holdings_sources", _holdings)
    monkeypatch.setattr("app.load_future_probability_watchlist_sources", lambda _m: pd.DataFrame())

    stringy = pd.DataFrame(
        [
            {
                "symbol": "OLD",
                "market": "미국주식",
                "display_group": "A 후보",
                "prob_up_1d": "0.50",
            }
        ]
    ).astype("string")

    scope = build_future_probability_scope_df(stringy, market="미국주식")
    assert not scope.empty
    symbols = set(scope["symbol"].astype(str))
    assert "AAPL" in symbols
    assert "TSLA" in symbols
    tsla = scope.loc[scope["symbol"].astype(str).eq("TSLA")].iloc[0]
    assert float(pd.to_numeric(tsla["avg_price"], errors="coerce")) == pytest.approx(
        534.7917126188248
    )
    assert str(tsla["display_group"]).strip() == "보유종목"


def test_filter_counts_match_scopes():
    df = pd.DataFrame(
        [
            {
                "symbol": "TSLA",
                "display_group": "보유종목",
                "is_holding": "예",
                "is_watchlist": "아니오",
                "candidate_group": "",
                "future_probability_status": "계산 대기",
                "prob_up_5d": "",
            },
            {
                "symbol": "NVDA",
                "display_group": "C 제외/관망",
                "is_holding": "아니오",
                "is_watchlist": "아니오",
                "candidate_group": "C 제외/관망",
                "source_group_normalized": "C_excluded",
                "future_probability_status": "계산 완료",
                "prob_up_5d": 0.61,
            },
        ]
    )
    counts = count_future_probability_scope_rows(df)
    assert counts["전체"] == 2
    assert counts["보유종목"] == 1
    assert counts["C 제외/관망 포함"] == 1
    assert counts["미래확률 계산 완료만"] == 1
    assert counts["미래확률 계산 대기만"] == 1
