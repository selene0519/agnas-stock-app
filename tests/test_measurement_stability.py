"""측정 안정성 감시의 회귀 테스트.

"앱이 흔들리면 안 된다"를 감시 가능한 불변식으로 바꾼 것이
`scripts/check_measurement_stability.py`다. 이 파일은 그 감시가
**조용히 통과하지 못하게** 지킨다.

2026-07-29 실측으로 드러난 것:
  * 멱등성은 확보됐다 — 재정산 두 번째 실행에서 판정 0행/값 0행.
  * **두 원장은 같은 예측에 다른 답을 준다.** 공통 60건 중 0.5%p 이내
    일치가 **5건(8.3%)**, 평균 3.0%p 차이. 오늘 고친 STOP_FIRST
    버그(1.14%p)보다 크다.
  * 원인은 버그가 아니라 **설계가 갈린 것**이다:
        비용 국장  A 0.09%   vs  B 0.41%
        창   mid   A 28일    vs  B 60일
        진입창     A 없음    vs  B 3/5/10일
    코드로 한쪽에 맞추면 그 순간 과거 수치의 의미가 바뀌므로,
    자동 수정 대상이 아니라 **사람이 결정할 항목**으로 드러내야 한다.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_measurement_stability.py"
HEALTH = ROOT / "scripts" / "data_freshness_healthcheck.py"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_checker_covers_idempotency_and_cross_ledger() -> None:
    s = _src(CHECKER)
    assert "def check_idempotency" in s
    assert "def check_cross_ledger" in s
    assert "def rule_divergence" in s


def test_checker_fails_loudly_instead_of_returning_zero() -> None:
    """불변식이 깨졌는데 종료코드 0이면 CI가 못 잡는다."""
    s = _src(CHECKER)
    assert "return 0 if ok else 1" in s


def test_no_shared_trades_is_not_reported_as_pass() -> None:
    """비교할 게 없는 것과 비교해서 통과한 것은 다르다."""
    s = _src(CHECKER)
    assert "통과가 아니라 미판정" in s


def test_rule_divergence_is_surfaced_not_auto_fixed() -> None:
    """비용·창을 코드로 한쪽에 맞추면 과거 수치의 의미가 조용히 바뀐다."""
    s = _src(CHECKER)
    assert "decisionNeeded" in s
    assert "사람이 정해야" in s


def test_healthcheck_watches_measurement_stability() -> None:
    """매일 도는 감시에 붙어 있지 않으면 한 번 보고 끝난 리포트가 된다."""
    s = _src(HEALTH)
    assert "measurement_stability" in s
    # 멱등성이 깨지는 건 critical이어야 한다 — 값이 실행할 때마다 달라진다는 뜻이다.
    idx = s.index("measurement_stability")
    block = s[idx:idx + 1400]
    assert "정산이 멱등하지 않다" in block
