"""누적 수익률 복리 기준 회귀 테스트 (2026-07-31).

**배경.** 관리자 화면의 "누적 수익률"이 -83.89%로 떠 있었다. 추적해 보니
`_portfolio_return_pct`가 체결 건을 **한 건씩 순차로** 자본의 10%씩 걸었다고
보고 630번 복리를 먹이고 있었다. 그런데 실제 원장은 체결 630건이 **13일**에만
몰려 있고 하루 최대 178건이었다 — 같은 날 건은 동시 포지션이지 순차 거래가
아니다. 기하 감쇠를 13번이 아니라 630번 먹여 손실을 약 2배 부풀린 것이다.

실측 대비: 직렬 -91.9% / 날짜별 등가중 -39.6% / 거래당 평균 -3.9%.

같이 고친 것:
  * `all` 분기가 수익률을 `items`(300건 절단 + 미체결 혼입)에서 뽑아
    executedTrades와 모집단이 달랐다 → 시장별과 같은 체결 집합을 쓴다.
  * `avgReturnPct` 키가 없어 화면이 None을 받았다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

main = pytest.importorskip("app.main", reason="백엔드 의존성 미설치")


def test_same_day_picks_compound_once_not_per_trade():
    """같은 날 N건은 건수와 무관하게 '하루 1회'로 복리돼야 한다."""
    for n in (1, 10, 50, 178):
        same_day = [("2026-06-02", -5.0)] * n
        # 그날 평균이 -5%이므로 몇 건이든 하루치 -5%가 전부다.
        assert main._dated_portfolio_return_pct(same_day) == pytest.approx(-5.0, abs=1e-9), n


def test_serial_model_diverges_once_daily_count_exceeds_the_slot():
    """레거시 직렬 모델이 언제부터 어긋나는지 고정한다.

    슬롯이 10%이므로 하루 10건까지는 두 방식이 사실상 같고(10 x 0.1 = 1.0),
    그 위로 갈수록 직렬 쪽이 급격히 나빠진다. 실제 원장은 하루 평균 48건 ·
    최대 178건이라 한참 위쪽 구간에 있다 — 그래서 -83.89%가 나왔다.
    """
    def serial(n):
        return main._portfolio_return_pct([-5.0] * n)

    assert serial(10) == pytest.approx(-4.89, abs=0.01)   # 교차점 부근
    assert serial(48) == pytest.approx(-21.4, abs=0.5)    # 하루 평균
    assert serial(178) == pytest.approx(-59.1, abs=0.5)   # 하루 최대
    # 날짜별 기준은 건수와 무관하게 -5% 하루치로 고정이다.
    for n in (10, 48, 178):
        assert main._dated_portfolio_return_pct([("2026-06-02", -5.0)] * n) == pytest.approx(-5.0, abs=1e-9)


def test_distinct_days_compound_per_day():
    """서로 다른 날은 날짜 수만큼 복리된다."""
    two_days = [("2026-06-02", 10.0), ("2026-06-03", 10.0)]
    assert main._dated_portfolio_return_pct(two_days) == pytest.approx(21.0, abs=1e-9)


def test_same_day_is_equal_weighted_not_summed():
    """같은 날 +10%와 -10%는 상쇄돼 0%여야 한다(합산이면 0이 아니다)."""
    mixed = [("2026-06-02", 10.0), ("2026-06-02", -10.0)]
    assert main._dated_portfolio_return_pct(mixed) == pytest.approx(0.0, abs=1e-9)


def test_undated_rows_fall_back_to_one_bucket_each():
    """날짜를 못 읽는 행은 서로 섞어 평균 내면 왜곡된다 — 각자 하루로 센다."""
    undated = [("", 10.0), ("", 10.0)]
    assert main._dated_portfolio_return_pct(undated) == pytest.approx(21.0, abs=1e-9)


def test_empty_input_is_zero():
    assert main._dated_portfolio_return_pct([]) == 0.0


def test_clustered_losses_are_not_overstated():
    """실제 원장 모양(소수 거래일에 대량 집중)에서 두 방식이 크게 갈린다."""
    clustered = [("2026-06-24", -4.0)] * 150 + [("2026-06-25", -4.0)] * 150
    dated = main._dated_portfolio_return_pct(clustered)
    serial = main._portfolio_return_pct([v for _, v in clustered])
    # 이틀치 -4% 복리 = 약 -7.84%
    assert dated == pytest.approx(-7.84, abs=0.01)
    # 직렬은 300번 복리라 훨씬 크게 잃은 것처럼 보인다.
    assert serial < -60
    assert dated > serial


def test_row_trade_date_reads_common_date_fields():
    assert main._row_trade_date({"createdAt": "2026-06-24T09:00:00"}) == "2026-06-24"
    assert main._row_trade_date({"validatedAt": "2026-07-02"}) == "2026-07-02"
    assert main._row_trade_date({"nope": "x"}) == ""
    assert main._row_trade_date("not a dict") == ""


def test_summary_exposes_basis_and_average_keys():
    """화면이 읽는 키가 실제로 채워져 나와야 한다.

    `avgReturnPct`가 없어 화면이 None을 받던 회귀를 막는다.
    """
    summary = main._virtual_summary_from_reports("kr", "all", "all")
    for key in ("avgReturnPct", "averageReturnPct", "cumulativeReturnPct",
                "serialCumulativeReturnPct", "tradingDayCount", "compoundingBasis"):
        assert key in summary, f"{key}가 응답에 없다"
    assert summary["compoundingBasis"] == "dailyEqualWeight"
    assert summary["avgReturnPct"] is not None
    # 내부 전달용 키는 기본 응답에 새어나가면 안 된다.
    assert "_datedReturns" not in summary


def test_internal_key_only_present_when_requested():
    with_internals = main._virtual_summary_from_reports("kr", "all", "all", _include_internals=True)
    assert "_datedReturns" in with_internals
    assert isinstance(with_internals["_datedReturns"], list)


def test_cumulative_is_milder_than_legacy_serial_on_real_ledger():
    """실제 원장에서 새 기준이 레거시보다 덜 비관적이어야 한다(집중도가 크므로)."""
    summary = main._virtual_summary_from_reports("kr", "all", "all")
    if not summary.get("executedTrades"):
        pytest.skip("체결 표본 없음")
    assert summary["cumulativeReturnPct"] > summary["serialCumulativeReturnPct"]
    assert summary["tradingDayCount"] >= 1
