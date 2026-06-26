from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import portfolio_risk_budget as prb  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


# ── 유동성 기반 슬리피지 배수 ────────────────────────────────────────────

def _synthetic_ohlcv(close: float, volume: float, days: int = 25) -> pd.DataFrame:
    return pd.DataFrame({
        "_date_ts": pd.date_range("2025-01-01", periods=days),
        "close": [close] * days,
        "volume": [volume] * days,
    })


def test_liquidity_multiplier_high_volume_is_baseline():
    from app.services import virtual_trade_journal as vtj
    df = _synthetic_ohlcv(close=70_000, volume=10_000_000)  # 7000억원/일
    mult = vtj._liquidity_slippage_multiplier(df, "kr", df["_date_ts"].iloc[-1])
    assert mult == 1.0


def test_liquidity_multiplier_mid_volume_is_1_5x():
    from app.services import virtual_trade_journal as vtj
    df = _synthetic_ohlcv(close=10_000, volume=500_000)  # 50억원/일
    mult = vtj._liquidity_slippage_multiplier(df, "kr", df["_date_ts"].iloc[-1])
    assert mult == 1.5


def test_liquidity_multiplier_low_volume_is_2_5x():
    from app.services import virtual_trade_journal as vtj
    df = _synthetic_ohlcv(close=10_000, volume=50_000)  # 5억원/일
    mult = vtj._liquidity_slippage_multiplier(df, "kr", df["_date_ts"].iloc[-1])
    assert mult == 2.5


def test_liquidity_multiplier_empty_ohlcv_falls_back_to_baseline():
    from app.services import virtual_trade_journal as vtj
    mult = vtj._liquidity_slippage_multiplier(pd.DataFrame(), "kr", pd.Timestamp("2025-01-01"))
    assert mult == 1.0


def test_liquidity_multiplier_does_not_use_future_volume():
    """as_of 이후 거래량 폭증이 as_of 시점 슬리피지 산정에 섞이면 미래데이터 누출."""
    from app.services import virtual_trade_journal as vtj
    df = _synthetic_ohlcv(close=10_000, volume=50_000, days=25)  # 과거 25일: 저유동성
    future_rows = pd.DataFrame({
        "_date_ts": pd.date_range(df["_date_ts"].iloc[-1] + timedelta(days=1), periods=5),
        "close": [10_000] * 5,
        "volume": [50_000_000] * 5,  # 미래에 거래량 폭증
    })
    combined = pd.concat([df, future_rows], ignore_index=True)
    as_of = df["_date_ts"].iloc[-1]
    mult = vtj._liquidity_slippage_multiplier(combined, "kr", as_of)
    assert mult == 2.5  # 미래의 거래량 폭증이 반영되면 안 됨


# ── 상관계수 기반 포트폴리오 리스크 ──────────────────────────────────────

def test_pairwise_correlation_perfectly_correlated():
    dates = [f"2025-01-{i:02d}" for i in range(1, 26)]
    series_a = {d: 0.01 * i for i, d in enumerate(dates)}
    series_b = {d: 0.02 * i for i, d in enumerate(dates)}  # 항상 같은 방향, 비례
    corr = prb._pairwise_correlation(series_a, series_b)
    assert corr is not None
    assert corr > 0.99


def test_pairwise_correlation_uncorrelated_returns_none_or_low():
    dates = [f"2025-01-{i:02d}" for i in range(1, 26)]
    series_a = {d: (0.01 if i % 2 == 0 else -0.01) for i, d in enumerate(dates)}
    series_b = {d: (0.01 if i % 3 == 0 else -0.01) for i, d in enumerate(dates)}
    corr = prb._pairwise_correlation(series_a, series_b)
    assert corr is not None
    assert abs(corr) < 0.7


def test_pairwise_correlation_too_few_overlapping_dates_returns_none():
    series_a = {"2025-01-01": 0.01, "2025-01-02": 0.02}
    series_b = {"2025-01-01": 0.01, "2025-01-02": 0.02}
    assert prb._pairwise_correlation(series_a, series_b) is None


def test_correlation_risk_flags_cross_sector_cluster(monkeypatch):
    """섹터 라벨이 달라도 실제로 같이 움직이면 클러스터로 잡혀야 한다."""
    import random
    dates = [f"2025-01-{i:02d}" if i <= 9 else f"2025-02-{i-9:02d}" for i in range(1, 26)]
    rng_ab = random.Random(1)
    correlated_series = {d: rng_ab.uniform(-0.03, 0.03) for d in dates}
    rng_c = random.Random(99)
    independent_series = {d: rng_c.uniform(-0.03, 0.03) for d in dates}

    def fake_daily_returns(market, symbol, lookback_days):
        if symbol in ("AAA", "BBB"):
            return dict(correlated_series)
        return dict(independent_series)  # CCC: AAA/BBB와 무관한 독립 난수

    monkeypatch.setattr(prb, "_daily_returns", fake_daily_returns)
    positions = [
        {"market": "kr", "symbol": "AAA", "sector": "Semiconductor", "weightPct": 25.0},
        {"market": "kr", "symbol": "BBB", "sector": "Bio", "weightPct": 25.0},
        {"market": "kr", "symbol": "CCC", "sector": "Finance", "weightPct": 10.0},
    ]
    result = prb._correlation_risk(positions)
    assert result["status"] == "OK"
    flagged_pairs = {frozenset((p["symbolA"], p["symbolB"])) for p in result["highCorrelationPairs"]}
    assert frozenset({"AAA", "BBB"}) in flagged_pairs
    cluster_members = {frozenset(c["members"]) for c in result["concentratedClusters"]}
    assert frozenset({"AAA", "BBB"}) in cluster_members


def test_correlation_risk_no_cluster_when_below_weight_threshold(monkeypatch):
    dates = [f"2025-01-{i:02d}" for i in range(1, 26)]
    correlated_series = {d: 0.01 * ((-1) ** i) * (i % 5) for i, d in enumerate(dates)}

    monkeypatch.setattr(prb, "_daily_returns", lambda market, symbol, lookback_days: dict(correlated_series))
    positions = [
        {"market": "kr", "symbol": "AAA", "sector": "Semiconductor", "weightPct": 5.0},
        {"market": "kr", "symbol": "BBB", "sector": "Bio", "weightPct": 5.0},
    ]
    result = prb._correlation_risk(positions)
    assert result["concentratedClusters"] == []  # 합산비중 10% < 40% 임계값


# ── 수급 데이터 staleness guard ──────────────────────────────────────────

def test_stale_supply_rows_are_excluded(tmp_path, monkeypatch):
    import scripts.generate_kr_recommendations as gen

    monkeypatch.setattr(gen, "ROOT", tmp_path)
    fresh_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stale_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

    pred_path = tmp_path / "predictions.csv"
    with pred_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "market", "ticker", "created_at",
            "kis_institution_5d", "kis_foreign_5d", "kis_institution_20d", "kis_foreign_20d",
        ])
        writer.writeheader()
        writer.writerow({"market": "kr", "ticker": "000001", "created_at": fresh_date,
                          "kis_institution_5d": "100", "kis_foreign_5d": "100",
                          "kis_institution_20d": "100", "kis_foreign_20d": "100"})
        writer.writerow({"market": "kr", "ticker": "000002", "created_at": stale_date,
                          "kis_institution_5d": "100", "kis_foreign_5d": "100",
                          "kis_institution_20d": "100", "kis_foreign_20d": "100"})

    supply = gen._load_supply_data()
    assert "000001" in supply
    assert "000002" not in supply


def test_supply_data_missing_file_returns_empty(tmp_path, monkeypatch):
    import scripts.generate_kr_recommendations as gen

    monkeypatch.setattr(gen, "ROOT", tmp_path)
    assert gen._load_supply_data() == {}


# ── 종가 검증 스냅샷이 KR/US 둘 다 만들어지는지 ───────────────────────────
# settle_pending_validations.py가 찾는 mone_v36_final_trade_validation_{market}_*_{date}.csv를
# US는 한 번도 생성한 적이 없어서, US 예측은 정산 기한이 지나면 무조건 EXPIRED로 끝났다.

def test_close_validation_covers_both_markets():
    import scripts.generate_kr_close_validation as gen
    assert "us" in gen.MARKETS
    assert "kr" in gen.MARKETS


def test_close_validation_symbol_norm_is_market_aware():
    import scripts.generate_kr_close_validation as gen
    assert gen.norm_symbol("5930", "kr") == "005930"
    assert gen.norm_symbol("aapl", "us") == "AAPL"


def test_close_validation_uses_per_market_cost():
    import scripts.generate_kr_close_validation as gen
    assert gen.COST_PCT["kr"] != gen.COST_PCT["us"]
    row = {"symbol": "AAPL", "entryPrice": "100", "stopPrice": "90", "targetPrice": "120"}
    ohlcv_row = {"high": "121", "low": "99", "close": "115"}

    original_close_row = gen.close_row
    gen.close_row = lambda market, symbol: ohlcv_row
    try:
        result_us = gen.validate_one("us", row, "balanced", "swing")
    finally:
        gen.close_row = original_close_row
    assert result_us["result"] == "target_hit"
    # (120-100)/100*100 - 0.06 = 19.94
    assert result_us["returnPct"] == pytest.approx(19.94, abs=0.001)
