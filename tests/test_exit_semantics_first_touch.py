"""청산 의미론 = **선착순**. 두 정산 경로가 같은 규칙을 쓰는지 고정한다.

2026-07-29 발견: 이 레포에 청산 의미론이 **세 가지** 있었다.

  1. `mone_v65_api_stabilizer` (원장의 대부분을 쓴다)
     창 **전체**를 훑어 target_hit/stop_hit 플래그를 모은 뒤 마지막에 판정.
     -> 2일차에 목표를 찍고 9일차에 손절을 찍으면 STOP_FIRST(손실)로 기록.
        실제로는 2일차에 익절되어 포지션이 없는데도.
  2. `settle_pending_validations._reconstruct_from_ohlcv` (폴백)
     매일 독립 평가 후 **가장 늦은 날짜로 덮어씀**.
     -> 3일차 손절이 10일차 종가청산으로 바뀜. 진입 판정도 매일 다시 해서
        한 번 들어간 뒤 진입가가 그날 범위를 벗어나면 미체결로 되돌아감.
  3. 반사실 스윕: 선착순(표준).

**실측한 편향:** STOP_FIRST로 기록된 110건 중 **46건(41.8%)이 목표 먼저**였다.
선착순으로 재판정하면 정산 663건 평균손익 -5.015% -> -3.826%(+1.189%p),
승률 15.4% -> 22.3%. 즉 기록이 체계적으로 **비관** 쪽이었다 —
이 레포가 늘 경계하던 낙관 누출과 반대 방향이라 더 늦게 발견됐다.

일봉으로는 같은 날 안에서의 순서를 알 수 없으므로, **동시 도달만** 보수적으로
손절 우선을 유지한다. 그 경우에만 STOP_FIRST 라벨을 쓴다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STABILIZER = (ROOT / "mone-web-app" / "backend" / "app" / "engine"
              / "mone_v65_api_stabilizer.py")
SETTLE = ROOT / "scripts" / "settle_pending_validations.py"


def _stabilizer_exit_block() -> str:
    src = STABILIZER.read_text(encoding="utf-8")
    start = src.index("# ── 선착순 청산")
    return src[start:start + 2600]


def test_stabilizer_exits_on_first_touch_not_window_flags() -> None:
    """플래그를 창 전체에 걸쳐 모으면 나중 손절이 앞선 익절을 덮어쓴다."""
    block = _stabilizer_exit_block()
    assert "exited" in block, "청산 후 루프를 빠져나가는 표시가 없다"
    # 예전 형태: `if touched and high >= target: target_hit = True` (누적)
    assert not re.search(r"if\s+touched\s+and\s+high\s*>=\s*target", block), (
        "창 전체 플래그 누적 방식이 되살아났다 — 나중 손절이 앞선 익절을 덮어쓴다")
    assert not re.search(r"if\s+touched\s+and\s+low\s*<=\s*stop", block)


def test_stabilizer_keeps_same_day_conservative_tiebreak() -> None:
    """일봉으로는 같은 날 순서를 모른다 -> 동시 도달은 손절 우선이 맞다."""
    block = _stabilizer_exit_block()
    assert "day_target and day_stop" in block
    # 동시 도달일 때만 STOP_FIRST가 되도록 두 플래그를 함께 세운다.
    idx = block.index("day_target and day_stop")
    tie = block[idx:idx + 400]
    assert "target_hit = True" in tie and "stop_hit = True" in tie


def _settle_ohlcv_block() -> str:
    """OHLCV 재구성 함수 본문만 잘라낸다.

    같은 파일의 `_find_result`는 **스냅샷 파일** 중 가장 늦은 것을 고르는
    별개 함수다(그건 의도된 동작이라 여기 검사 대상이 아니다). 파일 전체를
    훑으면 그 함수를 잘못 잡는다.
    """
    src = SETTLE.read_text(encoding="utf-8")
    start = src.index("# ── 선착순 청산")
    return src[start:start + 2600]


def _executable_lines(block: str) -> str:
    """주석을 걷어낸 **실행되는 줄만** 남긴다.

    옛 코드를 주석에 예시로 적어두면 검사가 그걸 잡는다. 이번 세션에만
    네 번째다(AST 사건 / set +e 주석 / Supabase 경고문 / 여기).
    검사 대상이 그 문자열을 담고 있을 때의 고질병이라 기본으로 걷어낸다.
    """
    return "\n".join(ln for ln in block.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_settlement_fallback_does_not_overwrite_with_latest_date() -> None:
    """`date > best_exec[0]`로 덮어쓰면 3일차 손절이 10일차 종가청산이 된다."""
    block = _executable_lines(_settle_ohlcv_block())
    assert not re.search(r"date\s*>\s*best_exec\[0\]", block), (
        "가장 늦은 날짜로 덮어쓰는 방식이 되살아났다")
    assert "entered" in block, "진입 상태를 한 번만 판정해야 한다"


def test_settlement_fallback_returns_on_first_touch() -> None:
    src = SETTLE.read_text(encoding="utf-8")
    start = src.index("# ── 선착순 청산")
    block = src[start:start + 2600]
    # 목표/손절에 닿으면 그 자리에서 반환해야 한다.
    assert "if target_hit or stop_hit:" in block
    assert block.index("if target_hit or stop_hit:") < block.index("last_close, last_date = close, date")


def test_both_paths_document_the_same_tiebreak() -> None:
    """두 경로가 같은 관례를 쓴다는 게 코드에 남아 있어야 한다."""
    for path in (STABILIZER, SETTLE):
        src = path.read_text(encoding="utf-8")
        assert "동시 도달" in src, f"{path.name}에 동시 도달 관례 설명이 없다"
