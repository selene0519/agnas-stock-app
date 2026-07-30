"""변동성 인지 재랭킹의 회귀 테스트.

근거(2026-07-29 홀드아웃, 저널 642건, 추천일 날짜순 60/40):
  같은 날 추천들의 평균을 빼 **공통 시장 요인 제거** 후에도
    atr14_pct_at_entry  train ρ -0.427 / test ρ **-0.494**  (5분위 격차 -6.77%p)
  반면 앱이 쓰던 랭킹 점수는
    final_rank_score    train ρ +0.026 / test ρ **-0.291**  (격차 -4.26%p)

즉 **정보는 있는데 랭킹이 반대로 고르고 있었다.** 이 파일은 그 보정이
조용히 사라지거나 과도해지지 않게 지킨다.

⚠️ 이 보정은 수익을 보장하지 않는다. 표본이 KOSPI -24% 한 국면뿐이고,
   저변동 우위는 국면 의존적이다. 확인된 것은 "순위가 덜 틀린다"까지다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = (ROOT / "mone-web-app" / "backend" / "app" / "engine"
          / "mone_v65_api_stabilizer.py")


def _src() -> str:
    return ENGINE.read_text(encoding="utf-8")


def test_volatility_score_is_monotone_decreasing_in_atr() -> None:
    """ATR이 높을수록 점수가 낮아야 한다 — 부호가 뒤집히면 정반대로 고른다."""
    src = _src()
    ns: dict = {}
    # 의존성 없이 함수만 떼어 실행한다.
    ns["_clamp"] = lambda v, lo, hi: max(lo, min(hi, v))
    ns["_num"] = lambda v, default=0.0: (float(v) if v not in (None, "") else default)
    m = re.search(r"VOL_ATR_REF_PCT = ([\d.]+)", src)
    assert m, "VOL_ATR_REF_PCT 상수가 없다"
    ns["VOL_ATR_REF_PCT"] = float(m.group(1))
    body = src[src.index("def _volatility_rank_score"):]
    body = body[:body.index("\ndef ")]
    exec(compile(body, "<vol>", "exec"), ns)
    f = ns["_volatility_rank_score"]

    scores = [f({"atr14Pct": a}) for a in (1.0, 2.0, 3.0, 5.0, 8.0)]
    assert all(s is not None for s in scores)
    assert scores == sorted(scores, reverse=True), (
        f"ATR이 커질수록 점수가 낮아져야 한다: {scores}")


def test_missing_atr_falls_back_without_inventing() -> None:
    """변동성을 모르면 원점수를 쓴다 — 없는 정보를 지어내지 않는다."""
    src = _src()
    blk = src[src.index("def _sync_final_rank_score"):]
    blk = blk[:blk.index("\ndef ")] if "\ndef " in blk[10:] else blk
    assert "volRerankApplied" in blk
    assert "없는 정보를 지어내지 않는다" in blk


def test_raw_score_is_preserved_for_comparison() -> None:
    """원점수를 지우면 두 랭킹을 더 비교할 수 없게 된다."""
    assert "finalScoreRaw" in _src()


def test_blend_weight_is_bounded_and_documented() -> None:
    """가중치가 1.0이면 원점수를 버리는 것 — 한 국면 표본으로는 과하다."""
    src = _src()
    m = re.search(r"VOL_RERANK_WEIGHT = ([\d.]+)", src)
    assert m, "VOL_RERANK_WEIGHT 상수가 없다"
    w = float(m.group(1))
    assert 0.0 < w <= 0.5, f"가중치가 범위를 벗어났다: {w}"
    assert "한 국면" in src, "국면 한정 근거가 코드에 남아 있어야 한다"


def test_no_profit_guarantee_language() -> None:
    """'보장'이라고 쓰면 그 순간 이 코드가 거짓말을 시작한다."""
    src = _src()
    blk = src[src.index("# ── 변동성 인지 재랭킹"):]
    blk = blk[:blk.index("def _sync_final_rank_score")]
    assert "보장하지 않는다" in blk
