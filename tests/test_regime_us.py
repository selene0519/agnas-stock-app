"""미장 국면 판정 — **국장과 다른 표를 써야 한다.**

⚠️ 이 파일의 초판에 "미장에는 국면 판정이 아예 없었다"고 적었는데 **틀렸다.**
`generate_us_recommendations._load_us_market_regime`이 SPY/QQQ/DIA 3지수 투표로
판정하고 있었다. 없던 게 아니라 **옛 정의(MA20 이격 + 5일 모멘텀)로 판정하고
있었고**, 그건 국장에서 국면을 못 가른다고 판정돼 폐기된 것과 같은 식이다.

더 나빴던 것: `_price_band`가 국장 모듈 함수라 **미장 EV가 KOSPI 국면과 국장
승률표로 보정**되고 있었다. 15년 재현에서 두 시장의 국면 순서는 **정반대**다 —
미장은 BULL이 최악, 국장은 SIDE가 최악이다. 즉 정확히 거꾸로 갔다.

⚠️ 미장 생존편향이 국장보다 심하다 — 15년 강세장을 살아남은 158종목이고,
   그 종목들의 하락을 사는 것은 사후적으로 매우 유리하다. 그래서
   `ev_multiplier`는 **1.0을 넘기지 않는다**: 유리한 쪽으로 키우지 않고
   불리한 쪽만 깎는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_us_table_differs_from_kr() -> None:
    """미장에서 BULL이 최악, 국장에서 SIDE가 최악 — 표가 같으면 하나는 틀렸다."""
    import regime_us as U
    for h in ("short", "swing", "mid"):
        wr = U.WIN_RATES[h]
        assert wr["BULL"] < wr["SIDE"] < wr["BEAR"], (
            f"{h}: 미장은 BULL < SIDE < BEAR 순서여야 한다 — {wr}")


def test_kr_table_has_its_own_ordering() -> None:
    """국장은 SIDE가 최악이다. 두 표가 같아지면 한쪽을 복사한 것이다."""
    import regime_kr as K
    for h in ("short", "swing", "mid"):
        wr = K.WIN_RATES[h]
        assert wr["SIDE"] == min(wr.values()), f"{h}: 국장은 SIDE가 최악이어야 한다 — {wr}"


def test_two_markets_do_not_share_a_table() -> None:
    import regime_kr as K
    import regime_us as U
    assert K.WIN_RATES != U.WIN_RATES, "두 시장이 같은 승률표를 쓰고 있다"


def test_ev_multiplier_never_exceeds_one() -> None:
    """생존편향이 심한 표다 — 유리한 쪽으로 키우면 하락장에 과공격이 된다."""
    import regime_kr as K
    import regime_us as U
    for mod in (K, U):
        for h in ("short", "swing", "mid"):
            for r in ("BULL", "SIDE", "BEAR"):
                m = mod.ev_multiplier(r, h)
                assert 0.0 < m <= 1.0, f"{mod.__name__} {h}/{r} 배수가 범위 밖: {m}"


def test_unknown_regime_is_neutral() -> None:
    import regime_us as U
    assert U.ev_multiplier("", "swing") == 1.0
    assert U.ev_multiplier("XXX", "swing") == 1.0


def test_dried_up_volume_forces_side_only_for_weak_trends() -> None:
    """거래량 고갈은 **약한 추세**만 덮는다.

    이 예외가 없으면 60일 -15%가 "횡보장"이 된다 — 2026-07-29 KOSPI가 정확히
    그랬다. 화면 신뢰도 문제이기도 하고, `regime_type == "BEAR"` 게이트가
    하필 급락장에서 꺼지는 문제이기도 하다.
    """
    import regime_us as U
    assert U._classify(+5.0, 0.70) == "SIDE"      # 약한 추세 + 고갈 -> 덮는다
    assert U._classify(-5.0, 0.70) == "SIDE"
    assert U._classify(+10.0, 0.70) == "BULL"     # 강한 추세는 거래량과 무관
    assert U._classify(-15.0, 0.70) == "BEAR"
    assert U._classify(+10.0, 1.00) == "BULL"
    assert U._classify(-10.0, 1.00) == "BEAR"


def test_kr_deep_decline_is_not_called_sideways() -> None:
    """2026-07-29 KOSPI 재현: trend60 -15.36%, 거래량비 0.805."""
    import regime_kr as K
    assert K._classify(-20.14, -16.69, -15.36, 0.805) == "BEAR"


def test_volume_check_survives_single_missing_bar() -> None:
    """결측 한 개로 기능이 꺼지면 안 된다 — 국장에서 실제로 그랬다."""
    import regime_us as U
    vols = [1000.0] * 60
    vols[30] = 0.0
    assert U._vol_ratio(vols, 59) is not None


def test_price_band_uses_the_market_own_regime_table() -> None:
    """`_price_band`는 미장 생성기도 import해 쓴다 — 표가 국장에 고정되면 안 된다."""
    s = (ROOT / "scripts" / "generate_kr_recommendations.py").read_text(encoding="utf-8")
    band = s[s.index("def _price_band("):]
    band = band[:band.index("\ndef ")]
    assert "regime_source" in band, "_price_band가 시장별 국면 소스를 안 쓴다"
    assert "ev_multiplier(market" in band, "_price_band가 market을 안 넘긴다"
    # 승률표를 이 함수 안에 다시 적으면 표/판정 어긋남이 재발한다.
    assert "_REGIME_WR_BY_HORIZON" not in band, "승률표가 _price_band에 복제됐다"


def test_us_generator_does_not_double_apply_regime() -> None:
    """`_price_band`가 이미 적용한다 — 생성기에서 또 곱하면 이중 보정이다."""
    s = (ROOT / "scripts" / "generate_us_recommendations.py").read_text(encoding="utf-8")
    body = s[s.index("def generate_us_recommendations("):]
    assert "ev_multiplier" not in body, "생성기가 EV에 국면 배수를 다시 곱한다"


def test_probability_is_not_regime_adjusted() -> None:
    """표시 확률은 '실측 기반' 라벨을 달고 나간다 — 보정하면 거짓이 된다."""
    for name in ("generate_kr_recommendations.py", "generate_us_recommendations.py"):
        s = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "wr_prob = wr_prob *" not in s, f"{name}: 표시 확률을 보정하고 있다"
