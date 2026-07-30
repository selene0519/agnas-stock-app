"""EV가 국면을 반영하되 **표시 확률은 건드리지 않는지** 지킨다.

2026-07-29 실측: 예측 목표도달률 24.9% vs 실제 13.6%. 밴드를 바꿔 괴리를
줄이려 했으나 오히려 커졌다(손절 1.5σ에서 이론 33.3% vs 실제 2.9%).
즉 **현행 밴드가 이미 최적**이고, 괴리의 원인은 밴드 기하학이 아니라
**국면 드리프트**다 — 하락장에서는 목표를 어디 두든 안 닿는다.

국면별 승률로 EV를 조정한다. **표는 이 파일에 복제하지 않는다** —
`regime_kr.WIN_RATES` / `regime_us.WIN_RATES`가 유일한 출처이고, 여기서는
순서와 동작만 검사한다(복제해 둔 표가 판정과 어긋나는 사고를 세 번 겪었다).

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


def _band(regime: str, market: str = "kr"):
    """국면만 바꿔 밴드를 뽑는다.

    `_price_band`는 이제 `regime_source`에 물어보므로 그쪽을 갈아끼운다.
    (예전엔 `G._load_market_regime`을 갈아끼웠는데, 그 함수는 더 이상
    EV 경로에 없다 — 그대로 뒀으면 테스트가 **아무것도 안 하면서 통과**했다.)
    """
    import generate_kr_recommendations as G
    import regime_source as RS
    importlib.reload(G)
    orig = RS.latest
    RS.latest = lambda repo, mk="kr": (regime, "", {})
    try:
        return G._price_band(65.0, 50000.0, "balanced", "swing", _IND, market=market)
    finally:
        RS.latest = orig


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
    import regime_source as RS
    assert RS.ev_multiplier("kr", "UNKNOWN", "swing") == 1.0
    # 국면이 최고인 셀도 배수가 1.0이라, 미조정과 값이 같아야 한다.
    _, _, _, ev_unknown, *_ = _band("UNKNOWN")
    _, _, _, ev_best, *_ = _band("BEAR")      # 국장 최고 국면
    assert ev_unknown == ev_best


def test_regime_table_lives_in_one_place_and_keeps_its_ordering() -> None:
    """값은 `regime_kr`에서 읽는다 — 여기 복제하면 그게 또 어긋난다."""
    import regime_kr as R
    s = KR.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in s.splitlines() if not ln.lstrip().startswith("#"))
    assert "_REGIME_WR_BY_HORIZON" not in code, "승률표가 생성기에 복제돼 있다"
    for h in ("short", "swing", "mid"):
        wr = R.WIN_RATES[h]
        assert wr["SIDE"] == min(wr.values()), f"{h}에서 SIDE가 최저가 아니다"
        assert 0.30 < R.POOLED[h] < 0.60, f"{h} 풀링 승률이 범위 밖: {R.POOLED[h]}"


def test_no_probability_floor_that_inflates_measured_zero() -> None:
    s = KR.read_text(encoding="utf-8")
    blk = s[s.index("_ev_prob = prob"):]
    blk = blk[:blk.index("ev = None")]
    assert "max(0.05" not in blk, "하한을 두면 실측 0%가 부풀려진다"
    assert "max(0.0," in blk
