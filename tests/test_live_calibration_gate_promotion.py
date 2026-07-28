"""라이브 실측 게이트 자동 승격 회귀 테스트.

목표: **표본이 쌓이는 것만으로** 게이트가 저절로 정직해져야 한다.
사람이 스위치를 올리러 들어올 필요가 없어야 한다.

설계 메모:
- 라이브 유효표본(effN)이 기준 이상인 셀만 라이브 소스로 승격한다.
  얇은 셀까지 승격하면 노이즈로 차단이 튄다.
- 승격되면 절대 기준 45%를 쓰지 않는다. 그 45%는 낙관적인 백테스트
  분포(44~55%)에 맞춰진 값이라 라이브 실측(전체 17%대)에 대면 게이트가
  아니라 영구 정지 스위치가 된다. 대신 **그 종목의 RR로 계산한 손익분기
  승률 + 마진**을 요구한다 — 종목마다 자동으로 맞춰지고 임의의 상수가 없다.
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

from app.engine import mone_v65_api_stabilizer as stab  # noqa: E402

POLICY = stab.PUBLIC_QUANT_POLICY


def test_breakeven_win_rate_matches_risk_reward() -> None:
    assert stab._breakeven_win_rate_pct(3.0) == 25.0        # 1/(1+3)
    assert stab._breakeven_win_rate_pct(1.0) == 50.0
    assert abs(stab._breakeven_win_rate_pct(1.5) - 40.0) < 1e-9
    assert stab._breakeven_win_rate_pct(0) is None
    assert stab._breakeven_win_rate_pct(None) is None


def test_thin_live_sample_keeps_backtest_source() -> None:
    """표본이 얇으면 승격하지 않는다 — 기존 동작 유지."""
    thin = float(POLICY["minLiveCalibrationEffN"]) - 1.0
    assert thin > 0
    # effN이 기준 미만이면 라이브 승률이 아무리 낮아도 라이브 게이트를 안 건다.
    assert thin < float(POLICY["minLiveCalibrationEffN"])


def test_promotion_threshold_is_configurable_and_positive() -> None:
    assert float(POLICY["minLiveCalibrationEffN"]) > 0
    assert float(POLICY["liveWinRateMarginPct"]) >= 0


def test_required_rate_adapts_to_risk_reward() -> None:
    """RR이 좋을수록 요구 승률이 낮아져야 한다(손익분기 성질)."""
    margin = float(POLICY["liveWinRateMarginPct"])
    req_rr3 = stab._breakeven_win_rate_pct(3.0) + margin
    req_rr1 = stab._breakeven_win_rate_pct(1.0) + margin
    assert req_rr3 < req_rr1, "RR이 높은데 요구 승률이 더 높다"
    assert abs(req_rr3 - (25.0 + margin)) < 1e-9


def _item(**over):
    """게이트를 통과할 수 있는 정상 후보. 필요한 항목만 덮어쓴다."""
    base = {
        "symbol": "005930", "market": "kr", "name": "삼성전자",
        "entry": 10000.0, "stop": 9000.0, "target": 13000.0,   # RR 3.0
        "rrActual": 3.0,
        "expectedValue": 5.0,
        "dataStatus": "NORMAL",
        "calibrationCount": 50,
        "calibratedWinRate": 55.0,   # 백테스트 소스는 통과 수준
    }
    base.update(over)
    return base


def _verdict(item):
    return stab._public_quant_verdict(item, {"status": "PERFORMANCE_OK"}, {}, 0.0)


def _has_live_block(v) -> bool:
    return any("live win rate below breakeven" in str(r) for r in (v.get("reasons") or []))


def test_thin_live_sample_does_not_promote(monkeypatch) -> None:
    """effN이 기준 미만이면 라이브 승률이 낮아도 라이브 게이트를 걸지 않는다."""
    thin = float(POLICY["minLiveCalibrationEffN"]) - 1.0
    item = _item(liveCalibratedWinRate=5.0, liveCalibrationEffN=thin)
    v = _verdict(item)

    assert item["calibrationGateSource"] == "BACKTEST"
    assert not _has_live_block(v)


def test_enough_live_sample_promotes_and_blocks_below_breakeven() -> None:
    """표본이 쌓이면 자동 승격되고, 손익분기 미달이면 차단한다."""
    enough = float(POLICY["minLiveCalibrationEffN"]) + 5.0
    item = _item(liveCalibratedWinRate=17.0, liveCalibrationEffN=enough)  # 현 실측 수준
    v = _verdict(item)

    assert item["calibrationGateSource"] == "LIVE_SETTLED"
    # RR 3.0 → 손익분기 25% + 마진. 17%는 미달이므로 차단돼야 한다.
    assert item["calibrationGateRequiredPct"] == 25.0 + float(POLICY["liveWinRateMarginPct"])
    assert _has_live_block(v)


def test_live_rate_above_breakeven_passes() -> None:
    enough = float(POLICY["minLiveCalibrationEffN"]) + 5.0
    required = 25.0 + float(POLICY["liveWinRateMarginPct"])
    item = _item(liveCalibratedWinRate=required + 3.0, liveCalibrationEffN=enough)
    v = _verdict(item)

    assert item["calibrationGateSource"] == "LIVE_SETTLED"
    assert not _has_live_block(v)


def test_promoted_gate_ignores_optimistic_backtest_rate() -> None:
    """승격되면 백테스트 55%가 라이브 미달을 덮지 못한다."""
    enough = float(POLICY["minLiveCalibrationEffN"]) + 5.0
    item = _item(calibratedWinRate=55.0, liveCalibratedWinRate=10.0, liveCalibrationEffN=enough)
    v = _verdict(item)

    assert item["calibrationGateSource"] == "LIVE_SETTLED"
    assert _has_live_block(v), "백테스트 낙관값이 라이브 차단을 덮었다"


def test_healthcheck_threshold_matches_backend_policy() -> None:
    """헬스체크는 stdlib만 쓰려고 상수를 복제한다 — 두 값이 갈라지면 안 된다.

    갈라지면 "승격됐다"고 보고하는데 실제로는 안 됐거나(또는 반대) 하는
    상태가 되고, 그건 자동화를 못 믿게 만든다.
    """
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "hc_thresh", root / "scripts" / "data_freshness_healthcheck.py")
    hc = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(hc)

    assert float(hc.LIVE_GATE_MIN_EFFN) == float(POLICY["minLiveCalibrationEffN"]), (
        "헬스체크와 백엔드의 승격 기준(effN)이 다르다"
    )
