"""국면 판정의 거래량 확인이 살아 있는지 지킨다.

2026-07-30 검증(호라이즌별 각 26,000여 건, 15년 전략 재현):
    정의                국면 간 격차 (short / swing / mid)
    trend60단독         0.671 / 0.839 / 1.796 pp
    trend60+거래량      0.494 / **1.033** / **2.021** pp
거래량 확인은 **보유가 길수록** 값이 있다(2/3 개선, mid에서 최대).
short의 손실(0.671->0.494)은 알려진 대가로 남긴다.

발상: 나쁜 국면이 SIDE(횡보)이고, 횡보는 **거래량 고갈**과 함께 온다 —
추세가 없어 좁은 손절(ATR 1.2~2.0배)이 잡음에 털린다.

⚠️ 결측 내성이 핵심이다. 처음 구현은 `all(v60)`로 검사해서 60봉 중 **한 개**만
   거래량 0이어도 None을 돌려주고 거래량 확인이 **조용히 꺼졌다.** 실제로
   KOSPI 2026-06-29의 0 한 개 때문에 최신 판정에서 비활성됐다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_dried_up_volume_forces_side() -> None:
    """거래량이 마르면 추세가 좋아도 강세로 부르지 않는다."""
    import regime_kr as R
    assert R._classify(1.0, 1.0, trend60=+10.0, vol_ratio=0.70) == "SIDE"
    assert R._classify(1.0, 1.0, trend60=+10.0, vol_ratio=1.00) == "BULL"


def test_volume_check_survives_a_single_missing_bar() -> None:
    """한 봉의 결측이 기능을 통째로 끄면 안 된다 — 실제로 그랬다."""
    import regime_kr as R
    vols = [1000.0] * 60
    vols[30] = 0.0                      # 한 봉 결측
    vr = R._vol_ratio(vols, 59)
    assert vr is not None, "결측 한 개로 거래량 확인이 꺼졌다"
    assert 0.9 < vr < 1.1


def test_volume_check_gives_up_only_when_mostly_missing() -> None:
    """절반 이상 결측이면 그때는 포기해야 한다 — 없는 정보를 만들지 않는다."""
    import regime_kr as R
    vols = [0.0] * 60
    vols[:5] = [1000.0] * 5
    assert R._vol_ratio(vols, 59) is None


def test_thresholds_match_the_validated_values() -> None:
    """임계를 임의로 바꾸면 15년 검증의 근거가 사라진다."""
    import regime_kr as R
    assert R.TREND60_BULL == 3.0
    assert R.TREND60_BEAR == -3.0
    assert R.VOL_DRYUP_RATIO == 0.85


def test_latest_regime_reports_what_it_used() -> None:
    """어떤 정의로 판정했는지 밖에서 알 수 있어야 한다."""
    import regime_kr as R
    _reg, _lab, det = R.latest_regime(str(ROOT))
    assert det.get("definition") == "trend60+거래량"
    assert "trend60" in det and "volRatio" in det
