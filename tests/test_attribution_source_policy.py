"""귀속분석이 SOURCE_CALIBRATION_WEIGHTS 정책을 지키는지 회귀 테스트.

정책은 진작 명시돼 있었다 — `HISTORICAL_REPLAY: 0.0`,
주석까지 "hypothesis-generation evidence only. It cannot auto-adjust live
recommendation parameters." 그런데 `attribution_feedback`/`attribution_analysis`만
그 정책을 안 보고 전부 풀링했다.

2026-07-28 실측이 대가를 보여준다:
    HISTORICAL_REPLAY    n=1298  승률 39.8%  평균 -0.40%
    FORWARD_PAPER_TRADE  n= 569  승률 19.9%  평균 -5.58%
    풀링(기존 근거)              승률 33.7%

즉 화면과 자가보정이 근거로 삼던 32%대는 **70%가 과거 리플레이**였고, 그
낙관값이 라이브 점수 배율을 움직이고 있었다. 같은 원장을 forward만으로 보면
19.9%/-5.58%다. `strategy_win_rates.json`(KR 9.1%/US 20.4%)과의 3배 모순도
여기서 왔다.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
loaded = sys.modules.get("app")
if loaded is not None and not hasattr(loaded, "__path__"):
    sys.modules.pop("app", None)

from app.services import virtual_trade_journal as vtj  # noqa: E402


def test_replay_is_not_calibration_admissible() -> None:
    assert vtj._is_calibration_admissible({"source_type": "FORWARD_PAPER_TRADE"}) is True
    assert vtj._is_calibration_admissible({"source_type": "MANUAL_REVIEWED"}) is True
    assert vtj._is_calibration_admissible({"source_type": "HISTORICAL_REPLAY"}) is False


def test_unknown_source_is_refused_by_default() -> None:
    """소스를 모르면 보정 근거로 쓰지 않는다(가중치 기본값 0)."""
    assert vtj._is_calibration_admissible({}) is False
    assert vtj._is_calibration_admissible({"source_type": "SOMETHING_NEW"}) is False


def test_source_breakdown_reports_excluded_rows_instead_of_hiding_them() -> None:
    rows = [
        {"source_type": "HISTORICAL_REPLAY", "net_pnl_pct": "5.0"},
        {"source_type": "HISTORICAL_REPLAY", "net_pnl_pct": "3.0"},
        {"source_type": "FORWARD_PAPER_TRADE", "net_pnl_pct": "-4.0"},
    ]
    out = {b["sourceType"]: b for b in vtj._source_breakdown(rows)}

    assert out["HISTORICAL_REPLAY"]["n"] == 2
    assert out["HISTORICAL_REPLAY"]["admissible"] is False
    assert out["HISTORICAL_REPLAY"]["winRate"] == 1.0
    assert out["FORWARD_PAPER_TRADE"]["admissible"] is True
    assert out["FORWARD_PAPER_TRADE"]["winRate"] == 0.0


def _row(source_type: str, pnl: float, i: int) -> dict:
    return {
        "journal_id": f"j{i}", "source_type": source_type, "status": "EVALUATED",
        "market": "kr", "mode": "balanced", "horizon": "swing",
        "symbol": f"{i:06d}", "name": f"종목{i}",
        "net_pnl_pct": str(pnl), "outcome": "TARGET_HIT" if pnl > 0 else "STOP_HIT",
        "journal_session": "PREMARKET_PLAN", "as_of_date": "2026-07-20",
    }


def test_replay_cannot_inflate_the_headline_win_rate(monkeypatch) -> None:
    """리플레이가 이겨도 baseWinRate는 forward 실측만 반영해야 한다."""
    # 리플레이 20건 전승 + forward 12건 전패. 풀링하면 62.5%, forward만이면 0%.
    rows = [_row("HISTORICAL_REPLAY", 5.0, i) for i in range(20)]
    rows += [_row("FORWARD_PAPER_TRADE", -4.0, 100 + i) for i in range(12)]
    monkeypatch.setattr(vtj, "_read_journal_rows", lambda *a, **k: rows)
    monkeypatch.setattr(vtj, "_merge_evaluations", lambda r: r)

    result = vtj.attribution_feedback(market="all")

    assert result["status"] == "OK"
    assert result["sampleCount"] == 12, "forward 12건만 근거여야 한다"
    assert result["excludedBySourcePolicyCount"] == 20
    assert result["baseWinRate"] == 0.0, "리플레이 전승이 승률을 끌어올리면 안 된다"
    assert result["calibrationBasis"].startswith("forward_only")

    by = {b["sourceType"]: b for b in result["sourceBreakdown"]}
    assert by["HISTORICAL_REPLAY"]["winRate"] == 1.0   # 제외됐지만 보이긴 해야 한다
    assert by["FORWARD_PAPER_TRADE"]["winRate"] == 0.0


def test_replay_only_journal_yields_no_adjustments(monkeypatch) -> None:
    """리플레이밖에 없으면 보정 근거가 없다 — 배율을 만들어내면 안 된다."""
    rows = [_row("HISTORICAL_REPLAY", 5.0, i) for i in range(30)]
    monkeypatch.setattr(vtj, "_read_journal_rows", lambda *a, **k: rows)
    monkeypatch.setattr(vtj, "_merge_evaluations", lambda r: r)

    result = vtj.attribution_feedback(market="all")

    assert result["status"] == "LOW_SAMPLE"
    assert result["excludedBySourcePolicyCount"] == 30
    assert result["adjustments"] == []
