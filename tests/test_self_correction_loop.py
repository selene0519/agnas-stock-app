"""자가보정 루프가 실제로 닫혀 있는지 지킨다.

2026-07-29 실측으로 드러난 세 가지 구멍:

1. **실패 원인이 비어 있었다.** postmortem_ledger 93행의 failureReasonTags가
   **전부 "none"**. 태그가 이벤트 필드(뉴스/공시/실적/매크로/섹터)에만
   의존했는데 그 데이터가 비어 있었다. "왜 틀렸는지"가 없으면 보정이 배울
   근거가 없다.

2. **보정이 시장을 안 나눴다.** 귀속은 byMarket인데 적용되는 adjustments는
   mode/horizon 키만 있어서, 국장에서 배운 계수가 미장 필터에 그대로 갔다.
   시장별 회귀를 내보니 rsi 계수가 KR 0.093 vs US 0.237로 **2.5배** 다르고,
   시장별 R2(0.127/0.119)가 풀링 R2(0.062)의 **2배**였다.

3. **보정 효과가 0이었다.** adjustment_performance_report 1547건에서
   원본 적중 49.7% -> 보정 후 49.7% (차이 0.00%p). 동전던지기다.
   1번과 2번이 고쳐지지 않으면 표본이 늘어도 3번은 그대로다.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTMORTEM = ROOT / "mone-web-app" / "backend" / "app" / "services" / "postmortem.py"
ATTRIBUTION = ROOT / "scripts" / "factor_attribution.py"
ADJUSTER = ROOT / "scripts" / "factor_filter_adjuster.py"
GENERATORS = [ROOT / "scripts" / "generate_kr_recommendations.py",
              ROOT / "scripts" / "generate_us_recommendations.py"]


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_failure_tags_do_not_depend_only_on_event_fields() -> None:
    """이벤트 데이터가 비면 태그가 전부 none이 된다 — 실제로 그랬다."""
    s = _src(POSTMORTEM)
    block = s[s.index("def _build_failure_reason_tags"):]
    block = block[:block.index("\ndef ")]
    # 가격·변동성 기반 태그가 있어야 이벤트가 없어도 원인이 남는다.
    for tag in ("high_volatility_entry", "overbought_entry", "deep_drawdown_entry"):
        assert tag in block, f"{tag} 태그가 없다"


def test_failure_tags_separate_market_from_stock_specific() -> None:
    """손실의 몫이 시장인지 종목인지 구분 못 하면 엉뚱한 곳을 보정한다.

    2026-07-29 측정: D+1 손실의 **89%가 시장 몫**이었다.
    """
    s = _src(POSTMORTEM)
    assert "market_decline" in s and "stock_specific_loss" in s


def test_attribution_emits_per_market_regression() -> None:
    s = _src(ATTRIBUTION)
    assert "regressionByMarket" in s
    # 표본이 적으면 계수를 만들지 않아야 한다.
    assert "INSUFFICIENT_DATA" in s


def test_adjuster_emits_per_market_adjustments() -> None:
    s = _src(ADJUSTER)
    assert '"byMarket"' in s
    assert "regressionByMarket" in s


def test_generators_prefer_their_own_market_adjustments() -> None:
    """풀링 조정만 읽으면 국장 계수가 미장에 그대로 간다."""
    for p in GENERATORS:
        s = _src(p)
        assert 'byMarket' in s, f"{p.name}이 시장별 조정을 안 읽는다"
        assert 'mine["adjustments"]' in s, f"{p.name}이 자기 시장 값을 안 쓴다"


def test_pooled_fallback_is_kept() -> None:
    """시장별 표본이 모자랄 때 아무것도 못 쓰게 되면 안 된다."""
    for p in GENERATORS:
        s = _src(p)
        assert 'doc.get("adjustments", {})' in s, f"{p.name}에 풀링 폴백이 없다"
