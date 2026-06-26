from __future__ import annotations

import csv
import os
import sys
from datetime import datetime
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app import main  # noqa: E402
from app.engine import data_quality as dq  # noqa: E402
from app.engine import mone_v65_api_stabilizer as stabilizer  # noqa: E402


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_validation_dashboard_all_aggregates_kr_us_without_counting_pending_as_wins(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    fake_main = repo / "mone-web-app" / "backend" / "app" / "main.py"
    fake_main.parent.mkdir(parents=True)
    fake_main.write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(main, "__file__", str(fake_main))

    reports = repo / "reports"
    rows = [
        {
            "predictionId": "us-win",
            "market": "us",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "AAPL",
            "isExecuted": "true",
            "result": "TARGET",
            "returnPct": "4.2",
        },
        {
            "predictionId": "us-loss",
            "market": "us",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "MSFT",
            "isExecuted": "true",
            "result": "STOP",
            "returnPct": "-3.1",
        },
        {
            "predictionId": "us-no-touch",
            "market": "us",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "NVDA",
            "isExecuted": "false",
            "result": "NOT_EXECUTED",
        },
        {
            "predictionId": "kr-win",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "005930",
            "isExecuted": "true",
            "result": "HOLDING_EVAL",
            "returnPct": "1.5",
        },
        {
            "predictionId": "kr-pending",
            "market": "kr",
            "mode": "conservative",
            "horizon": "short",
            "symbol": "000660",
            "status": "PENDING",
            "result": "PENDING",
        },
    ]
    _write_csv(reports / "virtual_validation_results.csv", rows)
    _write_csv(
        reports / "mone_v36_final_trade_validation_us_balanced_swing.csv",
        [
            {
                "predictionId": "us-win",
                "market": "us",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": "AAPL",
                "isExecuted": "true",
                "result": "TARGET",
                "returnPct": "4.2",
            }
        ],
    )

    out = main.api_validation_dashboard(market="all")

    assert out["status"] == "OK"
    assert out["market"] == "all"
    assert out["summary"]["totalCompleted"] == 3
    assert out["summary"]["totalWins"] == 2
    assert out["summary"]["totalPending"] == 1
    assert out["summary"]["totalNotExecuted"] == 1
    assert out["stats"]["balanced_swing"]["completed"] == 3
    assert out["stats"]["balanced_swing"]["winRate"] == 66.7


def test_active_stabilizer_validation_dashboard_all_uses_same_entry_touch_basis(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    reports = repo / "reports"
    rows = [
        {
            "predictionId": "us-win",
            "market": "us",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "AAPL",
            "isExecuted": "true",
            "result": "TARGET",
            "returnPct": "4.2",
        },
        {
            "predictionId": "us-loss",
            "market": "us",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "MSFT",
            "isExecuted": "true",
            "result": "STOP",
            "returnPct": "-3.1",
        },
        {
            "predictionId": "us-no-touch",
            "market": "us",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "NVDA",
            "isExecuted": "false",
            "result": "NOT_EXECUTED",
        },
        {
            "predictionId": "kr-win",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "005930",
            "isExecuted": "true",
            "result": "HOLDING_EVAL",
            "returnPct": "1.5",
        },
        {
            "predictionId": "kr-pending",
            "market": "kr",
            "mode": "conservative",
            "horizon": "short",
            "symbol": "000660",
            "status": "PENDING",
            "result": "PENDING",
        },
    ]
    _write_csv(reports / "virtual_validation_results.csv", rows)
    _write_csv(
        reports / "mone_v36_final_trade_validation_us_balanced_swing.csv",
        [
            {
                "predictionId": "us-win",
                "market": "us",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": "AAPL",
                "isExecuted": "true",
                "result": "TARGET",
                "returnPct": "4.2",
            }
        ],
    )
    monkeypatch.setattr(stabilizer, "_repo_root", lambda: repo)

    out = stabilizer._validation_dashboard_payload("all")

    assert out["status"] == "OK"
    assert out["market"] == "all"
    assert out["summary"]["totalCompleted"] == 3
    assert out["summary"]["totalWins"] == 2
    assert out["summary"]["totalPending"] == 1
    assert out["summary"]["totalNotExecuted"] == 1
    assert out["stats"]["balanced_swing"]["completed"] == 3
    assert out["stats"]["balanced_swing"]["winRate"] == 66.7


def test_stale_recommendations_are_marked_review_only_and_trade_blocked() -> None:
    payload = {"status": "OK", "count": 1, "items": [{"symbol": "AAPL", "dataStatus": "NORMAL"}]}
    quality = {"status": "OK", "dataStatus": "STALE", "summary": "US dataStatus=STALE"}

    out = main._apply_recommendation_trade_safety(payload, quality)

    assert out["tradeSafety"]["status"] == "BLOCKED"
    assert out["reviewOnly"] is True
    assert out["blockedCount"] == 1
    assert out["items"][0]["isTradeBlocked"] is True
    assert out["items"][0]["tradeBlockStatus"] == "DATA_QUALITY_BLOCK"


def test_active_stabilizer_stale_recommendations_are_trade_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        stabilizer,
        "_recommendation_data_quality",
        lambda market: {"status": "OK", "dataStatus": "STALE", "summary": "US dataStatus=STALE"},
    )
    payload = {"status": "OK", "count": 1, "items": [{"symbol": "AAPL", "dataStatus": "NORMAL"}]}

    out = stabilizer._apply_recommendation_trade_safety(payload, "us")

    assert out["tradeSafety"]["status"] == "BLOCKED"
    assert out["reviewOnly"] is True
    assert out["blockedCount"] == 1
    assert out["items"][0]["isTradeBlocked"] is True
    assert out["items"][0]["tradeBlockStatus"] == "DATA_QUALITY_BLOCK"


def test_data_quality_prefers_fresh_us_price_file_over_stale_existing_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    stale = repo / "data" / "market" / "snapshots" / "us_kis_current.json"
    fresh = repo / "reports" / "kis_current_price_us.csv"
    stale.parent.mkdir(parents=True, exist_ok=True)
    fresh.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("{}", encoding="utf-8")
    fresh.write_text("symbol,currentPrice,updatedAt\nAAPL,200,2026-06-26\n", encoding="utf-8")
    os.utime(stale, (1_718_236_800, 1_718_236_800))

    monkeypatch.setattr(dq.data, "REPO_ROOT", repo)

    files = dq._candidate_files("us")
    price_1 = next(item for item in files if item["role"] == "price_priority_1")

    assert price_1["path"] == fresh


def test_us_data_quality_uses_new_york_trading_date_not_kst_calendar_date() -> None:
    kst_morning_during_us_session = datetime(2026, 6, 27, 10, 30, tzinfo=dq.session.KST)

    assert dq._market_today_str("us", kst_morning_during_us_session) == "2026-06-26"
    assert dq._market_today_str("kr", kst_morning_during_us_session) == "2026-06-27"


def test_active_stabilizer_low_win_rate_strategy_blocks_trade_candidates(monkeypatch) -> None:
    monkeypatch.setattr(
        stabilizer,
        "_validation_dashboard_payload",
        lambda market: {
            "status": "OK",
            "stats": {
                "balanced_swing": {
                    "completed": 40,
                    "winRate": 22.5,
                    "avgReturn": -1.2,
                    "sampleStatus": "ENOUGH_SAMPLE",
                }
            },
            "summary": {"basis": "completed validations only"},
        },
    )
    payload = {"status": "OK", "count": 1, "items": [{"symbol": "AAPL"}]}

    out = stabilizer._apply_recommendation_performance_safety(payload, "us", "balanced", "swing")

    assert out["performanceSafety"]["status"] == "BLOCKED_LOW_WIN_RATE"
    assert out["reviewOnly"] is True
    assert out["blockedCount"] == 1
    assert out["items"][0]["isTradeBlocked"] is True
    assert out["items"][0]["tradeBlockStatus"] == "PERFORMANCE_GATE_BLOCK"
    assert out["items"][0]["performanceWinRate"] == 22.5


def test_active_stabilizer_validation_uses_stop_first_for_same_bar_target_and_stop() -> None:
    row = {"result": "STOP_FIRST", "targetHit": "true", "stopHit": "true", "returnPct": "-3.0"}

    assert stabilizer._is_win_row(row) is False
    assert stabilizer._is_loss_row(row) is True


def test_public_quant_policy_allows_only_validated_positive_ev_trade_candidate() -> None:
    payload = {
        "tradeSafety": {"status": "OK", "reviewOnly": False, "isTradeBlocked": False},
        "performanceSafety": {
            "status": "OK",
            "completed": 80,
            "winRate": 48.0,
            "avgReturn": 1.2,
        },
        "items": [
            {
                "symbol": "GOOD",
                "dataStatus": "NORMAL",
                "currentPrice": 100,
                "entry": 100,
                "stop": 95,
                "target": 110,
                "expectedValue": 2.0,
                "rrActual": 2.0,
                "calibratedWinRate": 52.0,
                "calibrationCount": 40,
            }
        ],
    }

    out = stabilizer._apply_public_quant_trader_policy(payload, 1_000_000)

    assert out["quantTraderPolicy"]["status"] == "OK"
    assert out["quantTraderPolicy"]["actionableCount"] == 1
    assert out["items"][0]["publicTradeStatus"] == "TRADE_CANDIDATE"
    assert out["items"][0]["positionPlan"]["suggestedWeightPct"] == 10.0
    assert out["items"][0]["positionPlan"]["maxLossPctOfPortfolio"] == 0.5


def test_public_quant_policy_blocks_negative_ev_even_when_raw_recommendation_exists() -> None:
    payload = {
        "tradeSafety": {"status": "OK", "reviewOnly": False, "isTradeBlocked": False},
        "performanceSafety": {
            "status": "OK",
            "completed": 80,
            "winRate": 48.0,
            "avgReturn": 1.2,
        },
        "items": [
            {
                "symbol": "BAD",
                "dataStatus": "NORMAL",
                "currentPrice": 100,
                "entry": 100,
                "stop": 98,
                "target": 101,
                "expectedValue": -0.2,
                "rrActual": 0.5,
                "calibratedWinRate": 52.0,
                "calibrationCount": 40,
            }
        ],
    }

    out = stabilizer._apply_public_quant_trader_policy(payload, 1_000_000)

    assert out["quantTraderPolicy"]["status"] == "NO_ACTIONABLE_TRADES"
    assert out["items"][0]["publicTradeStatus"] == "NO_TRADE"
    assert out["items"][0]["isTradeBlocked"] is True
    assert "expected value below gate" in out["items"][0]["tradeBlockReason"]
