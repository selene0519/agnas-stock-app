from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engine import data_quality as dq  # noqa: E402


def test_market_quality_uses_another_nonempty_strategy_cell(tmp_path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    balanced = reports / "mone_v36_final_recommendations_kr_balanced_swing.csv"
    aggressive = reports / "mone_v36_final_recommendations_kr_aggressive_mid.csv"
    balanced.write_text("symbol\n", encoding="utf-8")
    aggressive.write_text("symbol\n005930\n", encoding="utf-8")

    monkeypatch.setattr(dq, "_repo_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        dq,
        "_deep_csv_inspect",
        lambda path, market: {
            "deepStatus": "NORMAL",
            "emptyResult": path == balanced,
            "rowCount": 0 if path == balanced else 1,
            "validSymbolCount": 0 if path == balanced else 1,
            "latestDataDate": "2026-08-14",
        },
    )
    monkeypatch.setattr(
        dq.session,
        "evaluate_file_status",
        lambda path, market, required_today=True: {"status": "NORMAL", "mtimeDate": "2026-08-14"},
    )
    monkeypatch.setattr(dq.session, "get_price_session", lambda market: {"priceSession": "after_close"})

    result = dq._recommendation_csv_inspect("kr")

    assert result["status"] == "NORMAL"
    assert result["emptyResult"] is False
    assert result["rowCount"] == 1
    assert result["path"] == str(aggressive)
