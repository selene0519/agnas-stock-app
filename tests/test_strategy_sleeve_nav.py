"""전략별 sleeve 자본곡선 회귀 테스트.

이 스크립트의 존재 이유는 승률만으로 전략을 고르면 손익 비대칭을 놓친다는 것이다
(실측: 승률 순위와 NAV 순위의 스피어만 상관 -0.3). 그래서 테스트도 "숫자가 나온다"가
아니라 **오염된 표본이 곡선에 못 들어온다**는 쪽을 지킨다 — 2026-07-28에 낙관 누출
3건이 전부 '표본 구성'에서 나왔기 때문이다.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIELDS = ["predictionId", "createdAt", "market", "symbol", "mode", "horizon",
          "validationDueDate", "exitDate", "returnPct", "result", "source"]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "update_strategy_sleeve_nav", ROOT / "scripts" / "update_strategy_sleeve_nav.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _row(**kw) -> dict:
    base = {
        "predictionId": kw.get("predictionId", "p"), "createdAt": "2026-07-15",
        "market": "kr", "symbol": "005930", "mode": "balanced", "horizon": "swing",
        "validationDueDate": "2026-07-25", "exitDate": "2026-07-20",
        "returnPct": "1.0", "result": "TARGET_HIT", "source": "api/final/recommendations",
    }
    base.update(kw)
    return base


def _setup(tmp_path: Path, monkeypatch, rows: list[dict], clean_start="2026-07-10"):
    mod = _load_module()
    results = tmp_path / "reports" / "virtual_validation_results.csv"
    results.parent.mkdir(parents=True, exist_ok=True)
    with results.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in FIELDS} for r in rows])
    marker = tmp_path / "reports" / "clean_window_marker.json"
    marker.write_text(json.dumps({"cleanWindowStart": clean_start}), encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "RESULTS", results)
    monkeypatch.setattr(mod, "MARKER", marker)
    monkeypatch.setattr(mod, "OUT", tmp_path / "reports" / "strategy_sleeve_nav.json")
    return mod


def test_pending_rows_never_enter_the_curve(tmp_path, monkeypatch) -> None:
    """미정산 건은 실현 손익이 없다. 끼면 곡선이 미래를 아는 척하게 된다."""
    mod = _setup(tmp_path, monkeypatch, [
        _row(predictionId="a", result="PENDING", returnPct=""),
        _row(predictionId="b", result="TARGET_HIT", returnPct="5.0"),
    ])
    data = mod.build()
    assert data["sleeves"]["balanced_swing"]["trades"] == 1
    assert data["dataQuality"]["excluded"]["nonRealized"] == 1


def test_not_executed_is_excluded(tmp_path, monkeypatch) -> None:
    """진입가 미터치는 거래가 없었던 것이지 무손익 거래가 아니다."""
    mod = _setup(tmp_path, monkeypatch, [
        _row(predictionId="a", result="NOT_EXECUTED", returnPct=""),
    ])
    data = mod.build()
    assert data["sleeves"]["balanced_swing"]["trades"] == 0
    assert data["dataQuality"]["excluded"]["nonRealized"] == 1


def test_replay_source_is_excluded(tmp_path, monkeypatch) -> None:
    """HISTORICAL_REPLAY는 가중치 0 정책이다. 자본곡선에도 들어오면 안 된다.

    2026-07-28에 두 원장이 3배 어긋난 원인이 정확히 이 풀링이었다.
    """
    mod = _setup(tmp_path, monkeypatch, [
        _row(predictionId="a", source="HISTORICAL_REPLAY", returnPct="20.0"),
        _row(predictionId="b", source="api/final/recommendations", returnPct="-1.0"),
    ])
    data = mod.build()
    assert data["dataQuality"]["excluded"]["replaySource"] == 1
    assert data["sleeves"]["balanced_swing"]["trades"] == 1
    assert data["sleeves"]["balanced_swing"]["totalReturnPct"] < 0


def test_clean_window_cutoff_applies(tmp_path, monkeypatch) -> None:
    mod = _setup(tmp_path, monkeypatch, [
        _row(predictionId="a", createdAt="2026-06-15", returnPct="30.0"),
        _row(predictionId="b", createdAt="2026-07-15", returnPct="-2.0"),
    ])
    clean = mod.build(clean_only=True)
    assert clean["sleeves"]["balanced_swing"]["trades"] == 1
    assert clean["dataQuality"]["excluded"]["beforeCleanWindow"] == 1
    full = mod.build(clean_only=False)
    assert full["sleeves"]["balanced_swing"]["trades"] == 2


def test_curve_orders_by_exit_date_not_entry_date(tmp_path, monkeypatch) -> None:
    """손절로 먼저 끝난 거래가 곡선에서도 먼저 와야 한다."""
    mod = _setup(tmp_path, monkeypatch, [
        _row(predictionId="late", createdAt="2026-07-11", exitDate="2026-07-30", returnPct="4.0"),
        _row(predictionId="early", createdAt="2026-07-12", exitDate="2026-07-14", returnPct="-3.0"),
    ])
    curve = mod.build()["sleeves"]["balanced_swing"]["curve"]
    assert [p["date"] for p in curve] == ["2026-07-14", "2026-07-30"]
    assert curve[0]["returnPct"] == -3.0


def test_missing_exit_date_falls_back_and_is_disclosed(tmp_path, monkeypatch) -> None:
    """exitDate 없는 과거 행은 만기일로 근사하되 반드시 카운트되어야 한다."""
    mod = _setup(tmp_path, monkeypatch, [
        _row(predictionId="a", exitDate="", validationDueDate="2026-07-25", returnPct="1.0"),
    ])
    data = mod.build()
    assert data["dataQuality"]["estimatedTimingTrades"] == 1
    assert data["sleeves"]["balanced_swing"]["curve"][0]["date"] == "2026-07-25"


def test_payoff_ratio_separates_win_rate_from_capital_outcome(tmp_path, monkeypatch) -> None:
    """승률이 높아도 페이오프가 낮으면 자본은 준다 — 이 스크립트의 존재 이유.

    실측에서 aggressive_mid는 승률 1위(19.4%)인데 NAV는 8위(-44.5%)였다.
    """
    rows = []
    # 승률 60%지만 이익 1% / 손실 -5% → 기댓값 음수.
    for i in range(6):
        rows.append(_row(predictionId=f"w{i}", returnPct="1.0", exitDate=f"2026-07-1{i}"))
    for i in range(4):
        rows.append(_row(predictionId=f"l{i}", returnPct="-5.0", exitDate=f"2026-07-2{i}"))
    mod = _setup(tmp_path, monkeypatch, rows)
    s = mod.build()["sleeves"]["balanced_swing"]
    assert s["winRate"] == 0.6
    assert s["payoffRatio"] is not None and s["payoffRatio"] < 1.0
    assert s["totalReturnPct"] < 0
    assert s["maxDrawdownPct"] > 0


def test_empty_input_is_safe(tmp_path, monkeypatch) -> None:
    mod = _setup(tmp_path, monkeypatch, [])
    data = mod.build()
    assert data["ranking"] == []
    assert data["dataQuality"]["totalTrades"] == 0
    assert data["dataQuality"]["sampleWarning"]
