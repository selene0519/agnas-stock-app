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


def test_kr_supply_flow_prefers_fresh_clean_source(tmp_path, monkeypatch):
    import scripts.generate_kr_recommendations as gen

    monkeypatch.setattr(gen, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    fresh_date = datetime.now().date().isoformat()
    stale_date = (datetime.now() - timedelta(days=10)).date().isoformat()
    with (tmp_path / "data" / "kr_supply_flow.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "asOf", "signalScore", "foreign5d", "institution5d", "foreign20d", "institution20d"])
        writer.writeheader()
        writer.writerow({"symbol": "000001", "asOf": fresh_date, "signalScore": "4", "foreign5d": "100", "institution5d": "100", "foreign20d": "200", "institution20d": "200"})
        writer.writerow({"symbol": "000002", "asOf": stale_date, "signalScore": "4", "foreign5d": "100", "institution5d": "100", "foreign20d": "200", "institution20d": "200"})

    supply = gen._load_supply_data_from_kr_supply_flow()
    assert "000001" in supply
    assert supply["000001"]["signal"] == "STRONG_BUY"
    assert "000002" not in supply

    # _load_supply_data()는 신선한 kr_supply_flow.csv가 있으면 predictions.csv를 보지 않음
    assert gen._load_supply_data() == supply


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


# ── KIS 투자자별 순매수(수급) 신호 — 라이브 API 호출 자체는 로컬에서 검증 못함 ───────
# (이 환경에 KIS 인증키가 없음). 파싱/점수 계산 로직만 모킹된 응답으로 검증.

def test_investor_flow_history_maps_kis_field_names_and_sorts():
    from app.services import quotes
    # KIS는 보통 최신순으로 반환 — 일부러 역순으로 넣어 정렬 검증
    raw = [
        {"stck_bsop_date": "20260623", "frgn_ntby_qty": "2000", "orgn_ntby_qty": "1500", "prsn_ntby_qty": "-3500"},
        {"stck_bsop_date": "20260620", "frgn_ntby_qty": "1000", "orgn_ntby_qty": "-500", "prsn_ntby_qty": "-500"},
    ]
    rows = quotes._investor_flow_history(raw)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-06-20"
    assert rows[0]["foreign_net_qty"] == 1000.0
    assert rows[1]["institution_net_qty"] == 1500.0
    assert rows == sorted(rows, key=lambda r: r["date"])  # 날짜순 정렬됨


def test_investor_flow_history_empty_input():
    from app.services import quotes
    assert quotes._investor_flow_history([]) == []


def test_investor_flow_supply_score_both_buying_scores_positive():
    from app.services import quotes
    rows = [{"date": f"2026-06-{i:02d}", "foreign_net_qty": 100, "institution_net_qty": 100, "retail_net_qty": -200} for i in range(1, 21)]
    score = quotes.investor_flow_supply_score(rows)
    assert score["ok"] is True
    assert score["score"] == 4  # 5일+2, 20일+2


def test_investor_flow_supply_score_both_selling_scores_negative():
    from app.services import quotes
    rows = [{"date": f"2026-06-{i:02d}", "foreign_net_qty": -100, "institution_net_qty": -100, "retail_net_qty": 200} for i in range(1, 21)]
    score = quotes.investor_flow_supply_score(rows)
    assert score["score"] == -4


def test_investor_flow_supply_score_empty_rows():
    from app.services import quotes
    assert quotes.investor_flow_supply_score([])["ok"] is False


def test_fetch_investor_flow_kr_gracefully_disabled_without_credentials(monkeypatch):
    from app.services import quotes
    monkeypatch.setattr(quotes, "_kis_enabled", lambda: False)
    result = quotes.fetch_investor_flow_kr("005930")
    assert result["ok"] is False
    assert "error" in result
