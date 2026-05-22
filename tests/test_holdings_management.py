from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def test_load_holdings_reads_data_holdings_kr_and_maps_columns(monkeypatch, tmp_path):
    path = tmp_path / "data" / "holdings_kr.csv"
    path.parent.mkdir()
    path.write_text(
        "symbol,market,name,average_price,qty,memo\n"
        "222800,한국주식,심텍,98200,55,core\n"
        "131970,한국주식,두산테스나,178200,30,core\n",
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(app, "HOLDINGS_KR_FILE", path)

    out = app.load_holdings("한국주식")

    assert list(out["ticker"]) == ["222800", "131970"]
    assert list(out["name"]) == ["심텍", "두산테스나"]
    assert list(out["shares"]) == ["55", "30"]


def test_validate_holdings_keeps_missing_avg_or_quantity_rows():
    edit = pd.DataFrame(
        [
            {"종목코드": "5930", "종목명": "삼성전자", "평균단가": "", "보유수량": ""},
            {"symbol": "222800", "name": "심텍", "avg_price": "98200", "quantity": "55"},
        ]
    )

    out, issues = app._validate_holdings_editor_rows(edit, "한국주식")

    assert list(out["ticker"]) == ["005930", "222800"]
    assert out.loc[0, "avg_price"] == ""
    assert out.loc[0, "shares"] == ""
    assert any("005930" in msg and "입력 필요" in msg for msg in issues)


def test_save_holdings_writes_data_holdings_kr_schema(monkeypatch, tmp_path):
    path = tmp_path / "data" / "holdings_kr.csv"
    monkeypatch.setattr(app, "HOLDINGS_KR_FILE", path)
    df = pd.DataFrame(
        [{"ticker": "222800", "name": "심텍", "avg_price": "98200", "shares": "55", "memo": "보유종목"}]
    )

    saved = app.save_holdings(df, "한국주식")
    out = pd.read_csv(saved, dtype=str).fillna("")

    assert saved == path
    assert list(out.columns) == ["ticker", "market", "name", "avg_price", "quantity", "current_price", "memo", "holding_type"]
    assert out.loc[0, "ticker"] == "222800"
    assert out.loc[0, "quantity"] == "55"


def test_holdings_status_displays_input_needed_for_missing_fields(monkeypatch):
    monkeypatch.setattr(
        app,
        "load_stock_data",
        lambda *args, **kwargs: pd.DataFrame([{"Close": 1000}]),
    )
    holdings = pd.DataFrame([{"ticker": "222800", "name": "심텍", "avg_price": "", "shares": "", "memo": ""}])

    status = app.build_holdings_status(holdings, pd.DataFrame(), "한국주식")

    assert status.loc[0, "종목명"] == "심텍"
    assert status.loc[0, "종목코드"] == "222800"
    assert status.loc[0, "평단가"] == "입력 필요"
    assert status.loc[0, "보유수량"] == "입력 필요"
