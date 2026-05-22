import json

import pandas as pd

from core.portfolio_risk_manager import (
    PORTFOLIO_RISK_COLUMNS,
    apply_portfolio_risk_to_candidates,
    backfill_portfolio_risk_candidate_files,
    calculate_portfolio_risk,
    load_holdings_for_market,
    save_portfolio_risk_summary,
)


def test_detects_sector_concentration():
    candidates = pd.DataFrame(
        [
            {"symbol": "A", "sector": "반도체", "position_size_pct": 15, "strategy_adjusted_grade": "A", "strategy_trade_allowed": True},
            {"symbol": "B", "sector": "반도체", "position_size_pct": 15, "strategy_adjusted_grade": "B", "strategy_trade_allowed": True},
            {"symbol": "C", "sector": "반도체", "position_size_pct": 15, "strategy_adjusted_grade": "B", "strategy_trade_allowed": True},
        ]
    )

    result = calculate_portfolio_risk(pd.DataFrame(), candidates)

    assert result["sector_concentration"]["반도체"]["count"] == 3
    assert any("반도체" in warning for warning in result["portfolio_warnings"])


def test_risk_market_limits_new_exposure():
    candidates = pd.DataFrame(
        [
            {
                "symbol": "A",
                "sector": "AI",
                "position_size_pct": 20,
                "strategy_mode": "위험장",
                "strategy_adjusted_grade": "B",
                "strategy_trade_allowed": True,
            }
        ]
    )

    result = calculate_portfolio_risk(pd.DataFrame(), candidates)

    assert any("위험장" in warning for warning in result["portfolio_warnings"])
    assert any("신규 포지션" in action for action in result["portfolio_actions"])


def test_forbidden_candidate_is_not_includable():
    candidates = pd.DataFrame(
        [
            {"symbol": "A", "sector": "바이오", "position_size_pct": 20, "strategy_adjusted_grade": "C", "strategy_trade_allowed": False}
        ]
    )

    result = calculate_portfolio_risk(pd.DataFrame(), candidates)

    assert any("편입 불가" in warning for warning in result["portfolio_warnings"])
    assert result["total_exposure_pct"] == 0


def test_total_exposure_over_100_warns():
    positions = pd.DataFrame(
        [
            {"symbol": "A", "sector": "반도체", "current_weight_pct": 70},
        ]
    )
    candidates = pd.DataFrame(
        [
            {"symbol": "B", "sector": "소프트웨어", "position_size_pct": 40, "strategy_adjusted_grade": "A", "strategy_trade_allowed": True}
        ]
    )

    result = calculate_portfolio_risk(positions, candidates)

    assert result["total_exposure_pct"] == 110
    assert any("100%" in warning for warning in result["portfolio_warnings"])


def test_expected_loss_and_expected_return_are_calculated():
    candidates = pd.DataFrame(
        [
            {
                "symbol": "A",
                "sector": "AI",
                "position_size_pct": 20,
                "entry": 100,
                "stop": 90,
                "expected_return_5d": 3,
                "strategy_adjusted_grade": "A",
                "strategy_trade_allowed": True,
            }
        ]
    )

    result = calculate_portfolio_risk(pd.DataFrame(), candidates)

    assert result["max_expected_loss_pct"] == 2
    assert result["portfolio_expected_return"] == 0.6


def test_root_holdings_us_creates_summary_with_position_count(tmp_path):
    pd.DataFrame(
        [
            {"ticker": "AAPL", "avg_price": 100, "shares": 2, "memo": "core"},
            {"ticker": "MSFT", "avg_price": 200, "shares": 1, "memo": "core"},
        ]
    ).to_csv(tmp_path / "holdings_us.csv", index=False, encoding="utf-8-sig")
    (tmp_path / "data").mkdir()
    pd.DataFrame(columns=["ticker", "market", "name", "avg_price", "quantity", "current_price", "memo", "holding_type"]).to_csv(
        tmp_path / "data" / "holdings_kr.csv", index=False, encoding="utf-8-sig"
    )
    target = tmp_path / "reports" / "portfolio_risk_summary.json"

    summary = save_portfolio_risk_summary(target, base_dir=tmp_path, candidates_df=pd.DataFrame())
    saved = json.loads(target.read_text(encoding="utf-8"))

    assert target.exists()
    assert summary["position_count"] > 0
    assert saved["position_count"] > 0


def test_holdings_sector_is_mapped_from_metadata_sources(tmp_path):
    pd.DataFrame(
        [
            {"ticker": "ASTS", "avg_price": 100, "shares": 2, "memo": "no sector"},
            {"ticker": "BMNR", "avg_price": 20, "shares": 5, "memo": "no sector"},
        ]
    ).to_csv(tmp_path / "holdings_us.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "symbol": "ASTS",
                "sector_proxy": "전기차/성장주",
                "theme": "위성통신",
                "type": "speculative",
                "risk_level": "매우 높음",
            },
            {
                "symbol": "BMNR",
                "sector_proxy": "가상자산",
                "theme": "비트코인",
                "type": "speculative",
                "risk_level": "매우 높음",
            },
        ]
    ).to_csv(tmp_path / "candidate_universe_us.csv", index=False, encoding="utf-8-sig")

    summary = save_portfolio_risk_summary(tmp_path / "reports" / "portfolio_risk_summary.json", base_dir=tmp_path, candidates_df=pd.DataFrame())

    sectors = set(summary["sector_concentration"])
    assert "미분류" not in sectors
    assert sectors & {"전기차/성장주", "가상자산"}


def test_default_loss_pct_is_used_when_stop_loss_is_missing():
    positions = pd.DataFrame(
        [
            {"symbol": "A", "sector": "AI", "current_weight_pct": 50, "avg_price": 100},
        ]
    )

    result = calculate_portfolio_risk(positions, pd.DataFrame())

    assert result["max_expected_loss_pct"] == 3.5


def test_high_beta_default_loss_pct_is_used_without_stop_loss():
    positions = pd.DataFrame(
        [
            {"symbol": "CRCL", "sector": "가상자산", "theme": "코인", "type": "speculative", "current_weight_pct": 20, "avg_price": 100},
        ]
    )

    result = calculate_portfolio_risk(positions, pd.DataFrame())

    assert result["max_expected_loss_pct"] == 2


def test_data_holdings_kr_fallback_is_read(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "005930",
                "market": "한국주식",
                "name": "삼성전자",
                "avg_price": 70000,
                "quantity": 2,
                "current_price": 72000,
                "memo": "",
                "holding_type": "core",
            }
        ]
    ).to_csv(data_dir / "holdings_kr.csv", index=False, encoding="utf-8-sig")

    holdings = load_holdings_for_market("한국주식", tmp_path)

    assert len(holdings) == 1
    assert float(holdings.loc[0, "position_value"]) == 144000


def test_no_holdings_summary_is_created(tmp_path):
    target = tmp_path / "reports" / "portfolio_risk_summary.json"

    summary = save_portfolio_risk_summary(target, base_dir=tmp_path, candidates_df=pd.DataFrame())

    assert target.exists()
    assert summary["portfolio_risk_level"] == "포트폴리오 없음"
    assert summary["position_count"] == 0
    assert summary["portfolio_warnings"] == ["등록된 보유 포트폴리오 없음"]


def test_candidate_backfill_adds_portfolio_columns_and_preserves_c_safety(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    us_a = reports / "swing_candidates_us_A_top3.csv"
    us_b = reports / "swing_candidates_us_B_watch.csv"
    us_c = reports / "swing_candidates_us_C_excluded.csv"
    kr_c = reports / "swing_candidates_kr_C_excluded.csv"
    for path in [us_a, us_b]:
        pd.DataFrame(columns=["symbol", "grade"]).to_csv(path, index=False, encoding="utf-8-sig")
    c_df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "grade": "C",
                "strategy_adjusted_grade": "C",
                "strategy_trade_allowed": False,
                "position_size_pct": 0,
            }
        ]
    )
    c_df.to_csv(us_c, index=False, encoding="utf-8-sig")
    c_df.to_csv(kr_c, index=False, encoding="utf-8-sig")

    backfill_portfolio_risk_candidate_files([us_a, us_b, us_c, kr_c], tmp_path / "reports" / "portfolio_risk_summary.json", base_dir=tmp_path)

    for path in [us_a, us_b, us_c, kr_c]:
        df = pd.read_csv(path, dtype=str).fillna("")
        for col in PORTFOLIO_RISK_COLUMNS:
            assert col in df.columns
    for path in [us_c, kr_c]:
        df = pd.read_csv(path, dtype=str).fillna("")
        assert df["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum() == 0
        assert not df["portfolio_warnings"].astype(str).str.strip().isin(["", "nan", "None"]).any()


def test_apply_portfolio_risk_to_candidates_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", "custom": "keep"}])
    summary = {
        "portfolio_risk_level": "보통",
        "total_exposure_pct": 50,
        "sector_concentration": {},
        "portfolio_expected_return": 1,
        "max_expected_loss_pct": 2,
        "portfolio_actions": ["유지"],
        "portfolio_warnings": ["경고 없음"],
    }

    out = apply_portfolio_risk_to_candidates(df, summary)

    assert out.loc[0, "custom"] == "keep"
    assert "portfolio_risk_level" in out.columns
