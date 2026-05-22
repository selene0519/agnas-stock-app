from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.intraday_realtime_engine import (
    REQUIRED_US_INTRADAY_SYMBOLS,
    load_intraday_targets,
)


def test_load_intraday_targets_includes_required_us_symbols(tmp_path, monkeypatch):
  monkeypatch.chdir(tmp_path)
  (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
  for name in (
      "swing_candidates_us_A_top3.csv",
      "swing_candidates_us_B_watch.csv",
      "swing_candidates_us_C_excluded.csv",
      "swing_candidates_kr_A_top3.csv",
      "swing_candidates_kr_B_watch.csv",
      "swing_candidates_kr_C_excluded.csv",
  ):
      (tmp_path / "reports" / name).write_text("symbol,market\n", encoding="utf-8-sig")
  (tmp_path / "watchlist_us.csv").write_text(
      "symbol,name\nTSLA,Tesla\n",
      encoding="utf-8-sig",
  )
  df = load_intraday_targets()
  us_symbols = set(df.loc[df["market"].astype(str).str.contains("미국"), "symbol"].astype(str).str.upper())
  for sym in REQUIRED_US_INTRADAY_SYMBOLS:
      assert sym in us_symbols


def test_load_intraday_targets_merges_source_tags(tmp_path, monkeypatch):
  monkeypatch.chdir(tmp_path)
  (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
  for name in (
      "swing_candidates_us_A_top3.csv",
      "swing_candidates_us_B_watch.csv",
      "swing_candidates_us_C_excluded.csv",
      "swing_candidates_kr_A_top3.csv",
      "swing_candidates_kr_B_watch.csv",
      "swing_candidates_kr_C_excluded.csv",
  ):
      (tmp_path / "reports" / name).write_text("symbol,market\n", encoding="utf-8-sig")
  (tmp_path / "holdings_us.csv").write_text(
      "ticker,shares,avg_price\nAAPL,10,100\n",
      encoding="utf-8-sig",
  )
  (tmp_path / "watchlist_us.csv").write_text(
      "symbol,name\nAAPL,Apple\n",
      encoding="utf-8-sig",
  )
  df = load_intraday_targets()
  row = df.loc[df["symbol"].astype(str).str.upper().eq("AAPL")].iloc[0]
  tags = str(row.get("source_tags", ""))
  assert "holding" in tags
  assert "watchlist" in tags


def test_flow_endpoint_not_configured_uses_none():
  from core.intraday_flow_engine import fetch_intraday_program_flow, normalize_intraday_flow_data

  raw = fetch_intraday_program_flow("005930", "한국주식")
  if raw.get("flow_failure_reason") == "endpoint_not_configured":
      norm = normalize_intraday_flow_data({**raw, "symbol": "005930", "market": "한국주식"})
      assert norm.get("program_net_buy") is None
