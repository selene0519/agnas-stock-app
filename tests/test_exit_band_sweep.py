"""손절/목표 밴드 스윕의 안전장치 회귀 테스트.

반사실 시뮬레이터는 **틀렸을 때 가장 그럴듯해 보인다.** 2026-07-29 실측이
정확히 그랬다 — 표는 깔끔하게 나왔고 상위 셀이 평균 +0.579%를 찍었는데,
같은 시뮬레이터로 **원래 밴드를 넣어 원장을 재현시켜 보니 평균이 +2.39%p
낙관 쪽으로 치우쳐** 있었다(0.5%p 이내 일치 60.8%).

원인은 원장에 정산 규약이 두 계열 섞여 있던 것이다:
  대문자 STOP / STOP_FIRST / TARGET / HOLDING_EVAL  (600건+)
  소문자 stop_hit / close_exit / target_hit          (26건)
이 시뮬레이터는 소문자 계열의 규칙이라 그쪽만 재현한다(stop_hit 평균 +0.37%p).

그래서 이 파일이 지키는 것은 두 가지다 — **재현 검증이 표보다 먼저 나올 것**,
그리고 **재현 실패가 눈에 보일 것**.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sweep_exit_bands.py"


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_baseline_check_runs_before_building_grid() -> None:
    """표를 먼저 만들면 재현 실패를 모른 채 수치를 인용하게 된다."""
    src = _src()
    assert "_baseline_check(trades)" in src
    assert src.index("_baseline_check(trades)") < src.index("for sp in STOP_PCTS")


def test_reproducibility_verdict_is_reported() -> None:
    src = _src()
    for key in ("reproducible", "meanDiffPp", "withinHalfPointShare",
                "byResultVocabulary"):
        assert key in src, f"{key} 보고가 빠졌다"


def test_cli_warns_loudly_when_not_reproducible() -> None:
    """재현 실패인데 표만 예쁘게 찍으면 그게 곧 낙관 누출이다."""
    src = _src()
    body = src[src.index("def main("):]
    assert "인용 금지" in body
    assert 'b.get("reproducible")' in body


def test_sweep_reuses_settlement_cost_and_rule() -> None:
    """손절가를 세 군데서 따로 계산하다 어긋난 전례가 있다 — 두 번째 산식 금지."""
    src = _src()
    assert "from settle_pending_validations import" in src
    assert "COST_PCT" in src
    # 비용을 스스로 하드코딩하면 정산 경로와 갈린다.
    hardcoded = re.findall(r"cost\s*=\s*0\.\d+", src)
    assert not hardcoded, f"비용을 따로 하드코딩했다: {hardcoded}"


def test_sweep_states_it_is_diagnostic_only() -> None:
    """이 표에서 최적 셀을 고르면 과적합이다. 그 경고가 산출물에 남아야 한다."""
    src = _src()
    assert "과적합" in src
    assert "purpose" in src and "진단" in src


def test_low_sample_cells_are_flagged() -> None:
    src = _src()
    assert "MIN_TRADES" in src and "usable" in src
