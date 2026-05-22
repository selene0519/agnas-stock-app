from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from core.unified_display_enrichment import enrich_candidate_frame  # noqa: E402


def test_unified_enrichment_normalizes_kr_code_and_fills_alias_scores():
    kr = "한국주식"
    frame = pd.DataFrame(
        [
            {
                "code": "5930",
                "market": kr,
                "active_scenario_entry_price": "70000",
                "active_scenario_stop_loss": "65000",
                "active_scenario_take_profit_1": "80000",
            }
        ]
    )
    master = {
        "005930": {
            "symbol": "005930",
            "name": "삼성전자",
            "market": kr,
            "supply_score": "71",
            "earnings_score": "63",
            "valuation_score": "55",
        }
    }

    out = enrich_candidate_frame(frame, kr, master=master, fingerprint={})

    row = out.iloc[0]
    assert row["symbol"] == "005930"
    assert row["종목코드"] == "005930"
    assert row["종목명"] == "삼성전자"
    assert row["조건부 진입가"] == "70000"
    assert row["수급점수"] == "71"
    assert row["실적점수"] == "63"
    assert row["밸류에이션점수"] == "55"
    assert row["price_data_status"] == "저장된 후보 기준"


def test_buy_decision_uses_saved_price_aliases_without_price_missing():
    kr = "한국주식"
    row = enrich_candidate_frame(
        pd.DataFrame(
            [
                {
                    "symbol": "222800",
                    "market": kr,
                    "name": "심텍",
                    "active_scenario_entry_price": "1000",
                    "active_scenario_pullback_price": "950",
                    "active_scenario_stop_loss": "900",
                    "active_scenario_take_profit_1": "1200",
                    "active_scenario_take_profit_2": "1300",
                    "active_scenario_risk_reward": "2.0",
                }
            ]
        ),
        kr,
        master={"222800": {"symbol": "222800", "name": "심텍", "market": kr}},
        fingerprint={},
    ).iloc[0]

    display = app._buy_decision_rank_row_from_series(row, kr, 1)

    assert display["종목명"] == "심텍"
    assert display["종목코드"] == "222800"
    assert display["가격상태"] == "저장된 후보 기준"
    assert display["매수가"] != "가격 기준 미산출"
    assert display["손절가"] != "가격 기준 미산출"
    assert display["목표가"] != "가격 기준 미산출"
    assert display["2차 목표가"] != "가격 기준 미산출"
    assert display["손익비"] == "2.0"


def test_sell_decision_name_fallback_uses_holding_name_or_code():
    holdings_status = pd.DataFrame(
        [
            {
                "종목명": "심텍",
                "종목코드": "222800",
                "보유판단": "보유 관망",
                "현재가": "1,000",
                "평단가": "900",
                "수익률": "+11.11%",
                "손절가": "850",
                "1차익절가": "1,200",
                "손절가여유": "+17.65%",
                "1차익절여유": "+20.00%",
            }
        ]
    )

    out = app.build_native_sell_decision_df(pd.DataFrame(), holdings_status, "한국주식")

    assert out.loc[0, "종목"] == "심텍"
