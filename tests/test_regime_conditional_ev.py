"""EV가 국면을 반영하되 **표시 확률은 건드리지 않는지** 지킨다.

2026-07-29 실측: 예측 목표도달률 24.9% vs 실제 13.6%. 밴드를 바꿔 괴리를
줄이려 했으나 오히려 커졌다(손절 1.5σ에서 이론 33.3% vs 실제 2.9%).
즉 **현행 밴드가 이미 최적**이고, 괴리의 원인은 밴드 기하학이 아니라
**국면 드리프트**다 — 하락장에서는 목표를 어디 두든 안 닿는다.

15년 워크포워드(82,251건)의 국면별 승률로 EV를 조정한다:
    BULL 41.8% · SIDE 41.8% · BEAR 31.3%   (풀링 40.8%)

⚠️ **처음엔 `prob`를 곱했다가 기존 정직성 테스트 4개가 잡아냈다.**
   화면에 뜨는 확률은 "실측 기반 38.0%"라는 라벨을 달고 나가므로 실측값과
   정확히 같아야 한다. 보정은 EV에만 건다.
   그리고 하한 0.05를 뒀다가 **실측 0%가 5%로 부풀려지는** 것도 같이
   잡혔다(2026-07-28 `x or default` 사건과 같은 계열).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
KR = ROOT / "scripts" / "generate_kr_recommendations.py"

_IND = {"atr14": 1000.0, "rsi14": 55, "distanceToMa20": 1.0, "volumeRatio20": 1.1,
        "recentMomentum5": 0.5, "mdd20": -5.0, "distanceToMa60": 2.0}


def _band(regime: str):
    import generate_kr_recommendations as G
    importlib.reload(G)
    G._load_market_regime = lambda: {"regime": regime}
    return G._price_band(65.0, 50000.0, "balanced", "swing", _IND)


def test_side_regime_lowers_ev_most() -> None:
    """**횡보장이 최악이다.** 2026-07-30 정정.

    15년 전략 재현(26,476건)에서 네 가지 국면 정의 **전부**에서 SIDE만 음수였고
    (BEAR +0.547 / BULL +0.521 / SIDE -0.256), 라이브 clean window(72건)도
    같았다(BEAR -3.78 / BULL -7.16 / SIDE -10.35).
    손절이 1.5 ATR로 좁아 추세 없는 구간에서 잡음에 털리기 때문이다.
    이전 구현은 BEAR를 깎고 SIDE를 BULL과 같게 뒀다 — 거꾸로였다.
    """
    _, _, _, ev_bull, _, _, _, _ = _band("BULL")
    _, _, _, ev_side, _, _, _, _ = _band("SIDE")
    _, _, _, ev_bear, _, _, _, _ = _band("BEAR")
    assert None not in (ev_bull, ev_side, ev_bear)
    assert ev_side < ev_bull, f"횡보장 EV가 강세장보다 낮아야 한다: {ev_side} vs {ev_bull}"
    assert ev_side < ev_bear, f"횡보장 EV가 하락장보다 낮아야 한다: {ev_side} vs {ev_bear}"


def test_displayed_probability_is_untouched_by_regime() -> None:
    """화면 확률은 '실측 기반'이라는 라벨을 달고 나간다 — 보정하면 거짓이 된다."""
    *_, prob_bull, _, _ = _band("BULL")
    *_, prob_bear, _, _ = _band("BEAR")
    assert abs(prob_bull - prob_bear) < 1e-9, (
        f"국면이 표시 확률을 바꿨다: {prob_bull} vs {prob_bear}")


def test_unknown_regime_does_not_adjust() -> None:
    """국면을 모르면 건드리지 않는다 — 없는 정보를 지어내지 않는다."""
    s = KR.read_text(encoding="utf-8")
    blk = s[s.index("_REGIME_WR ="):]
    blk = blk[:blk.index("except Exception")]
    assert "_rw = _REGIME_WR.get(_rg)" in blk and "if _rw:" in blk


def test_regime_table_matches_walkforward() -> None:
    """숫자를 임의로 바꾸면 근거가 사라진다."""
    s = KR.read_text(encoding="utf-8")
    for tok in ('"BULL": 0.427', '"SIDE": 0.395', '"BEAR": 0.459', "_POOLED_WR = 0.423"):
        assert tok in s, f"{tok} 가 15년 전략 재현 실측과 다르다"


def test_no_probability_floor_that_inflates_measured_zero() -> None:
    s = KR.read_text(encoding="utf-8")
    blk = s[s.index("_ev_prob = prob"):]
    blk = blk[:blk.index("ev = None")]
    assert "max(0.05" not in blk, "하한을 두면 실측 0%가 부풀려진다"
    assert "max(0.0," in blk
