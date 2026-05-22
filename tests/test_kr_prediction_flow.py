"""국장 예측 기준·하이닉스 매칭·OHLC 검증 스모크 테스트 (미국주식 로직 비호출)."""

from __future__ import annotations

import numpy as np

import app as m


def test_validate_kr_basis_ok() -> None:
    ok, issue = m.validate_kr_prediction_basis_fields(
        "2026-05-15",
        "2026-05-14",
        100_000.0,
        105_000.0,
        99_000.0,
        103_000.0,
        1_000_000.0,
        104_000.0,
    )
    assert ok == "OK"
    assert issue == ""


def test_validate_kr_basis_bad_high() -> None:
    ok, issue = m.validate_kr_prediction_basis_fields(
        "2026-05-15",
        "2026-05-14",
        100_000.0,
        100_500.0,
        99_000.0,
        101_000.0,
        1_000_000.0,
        np.nan,
    )
    assert ok == "NG"
    assert "high" in issue


def test_hynix_cell_matches_code() -> None:
    assert m._kr_cell_matches_symbol("000660", "000660")
    assert m._kr_cell_matches_symbol("SK하이닉스", "000660")
    assert m._kr_cell_matches_symbol("하이닉스", "000660")


def test_kr_prediction_log_candidates_empty() -> None:
    df = m._kr_prediction_log_candidates("999999", "2099-01-01")
    assert df.empty


def test_assess_freshness_missing() -> None:
    st, msg = m.assess_kr_prediction_freshness(None, "2026-05-15", "")
    assert st == "MISSING_TODAY_PREDICTION"
