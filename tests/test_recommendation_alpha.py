"""추천 알파(시장모형 이벤트 스터디) 회귀 테스트.

이 스크립트가 있는 이유: MONE의 모든 엣지 진단이 **원시 수익률**이라
선택 실력(알파)과 시장 흐름(베타)을 한 번도 분리한 적이 없었다.
2026-06~07 표본 구간에 KOSPI가 고점 대비 24% 빠졌으므로, "-5.6%/거래"의
상당 부분이 시장일 수 있다.

테스트가 지키는 것은 수치가 아니라 **정직성**이다:
  - 리플레이 표본이 섞이지 않을 것
  - 추정창이 이벤트 이전에서 끝날 것(룩어헤드 없음)
  - 이벤트가 며칠에 몰리면 스스로 "p값 쓰지 말라"고 말할 것
"""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "analyze_recommendation_alpha", ROOT / "scripts" / "analyze_recommendation_alpha.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_market_model_recovers_known_alpha_beta() -> None:
    """합성 데이터로 OLS가 실제 alpha/beta를 되찾는지."""
    mod = _load()
    rng = np.random.default_rng(7)
    market = rng.normal(0, 0.01, 400)
    stock = 0.0005 + 1.4 * market + rng.normal(0, 0.001, 400)
    alpha, beta, r2 = mod.fit_market_model(stock, market)
    assert abs(beta - 1.4) < 0.05
    assert abs(alpha - 0.0005) < 0.0005
    assert r2 > 0.9


def test_abnormal_return_is_zero_when_stock_just_tracks_market() -> None:
    """종목이 시장을 그대로 따라가면 알파는 0이어야 한다.

    이게 이 스크립트의 존재 이유다 — 시장이 빠져서 난 손실을 '선택 실패'로
    세면 고칠 대상을 잘못 고른다.
    """
    mod = _load()
    market = np.array([-0.02, -0.03, -0.01, -0.04, -0.02] * 20)
    stock = 1.0 * market            # 베타 1, 알파 0
    alpha, beta, _ = mod.fit_market_model(stock, market)
    ar = stock - (alpha + beta * market)
    assert abs(float(np.sum(ar))) < 1e-9, "시장을 그대로 탄 종목에 알파가 생기면 안 된다"


def test_ttest_flags_zero_mean_as_insignificant() -> None:
    mod = _load()
    rng = np.random.default_rng(3)
    _, p = mod._t_test(rng.normal(0, 1, 500))
    assert p > 0.05


def test_ttest_detects_real_shift() -> None:
    mod = _load()
    rng = np.random.default_rng(3)
    t, p = mod._t_test(rng.normal(0.5, 1, 500))
    assert p < 0.01 and t > 0


def test_bootstrap_ci_brackets_the_mean() -> None:
    mod = _load()
    rng = np.random.default_rng(11)
    vals = rng.normal(2.0, 1.0, 300)
    lo, hi = mod._bootstrap_ci(vals, n_boot=800)
    assert lo < float(vals.mean()) < hi


def test_replay_samples_are_excluded(tmp_path, monkeypatch) -> None:
    """HISTORICAL_REPLAY가 섞이면 2026-07-28에 고친 낙관 누출이 되살아난다."""
    mod = _load()
    journal = tmp_path / "journal.csv"
    fields = ["source_type", "market", "symbol", "as_of_date"]
    with journal.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow({"source_type": "HISTORICAL_REPLAY", "market": "kr",
                    "symbol": "005930", "as_of_date": "2026-06-20"})
    monkeypatch.setattr(mod, "JOURNAL", journal)
    res = mod.compute((1,), None)
    assert res["skipped"]["replaySource"] == 1
    assert res.get("events", 0) == 0


def test_estimation_window_ends_before_the_event() -> None:
    """추정창이 이벤트 당일까지 오면 룩어헤드가 된다."""
    mod = _load()
    assert mod.EST_END < 0, "추정창은 이벤트 이전에서 끝나야 한다"
    assert mod.EST_START < mod.EST_END


def test_clustered_events_disable_significance() -> None:
    """이벤트가 며칠에 몰리면 스스로 'p값 쓰지 말라'고 말해야 한다.

    실측에서 D+20 이벤트 150건이 6일 안에 전부 몰려 있었다(25건/일).
    모두 같은 시장 충격을 공유하므로 유효 표본은 150이 아니라 6에 가깝다.
    """
    src = (ROOT / "scripts" / "analyze_recommendation_alpha.py").read_text(encoding="utf-8")
    assert "isClustered" in src
    assert "significanceUsable" in src
    assert "독립성 가정이 깨진다" in src


def test_caveats_are_published_with_results() -> None:
    """한계를 산출물에 같이 싣지 않으면 수치만 인용된다."""
    src = (ROOT / "scripts" / "analyze_recommendation_alpha.py").read_text(encoding="utf-8")
    assert '"caveats"' in src
    # 알파가 (+)여도 계좌는 줄 수 있다는 경고가 반드시 있어야 한다.
    assert "돈을 벌었다'가 아니다" in src


@pytest.mark.skipif(not (ROOT / "data" / "virtual_trade_journal.csv").exists(),
                    reason="VTJ 저널 없음")
def test_real_repo_run_reports_clustering_state() -> None:
    """실제 데이터로 돌렸을 때 군집 상태가 반드시 산출물에 있어야 한다."""
    mod = _load()
    res = mod.compute((1,), None)
    if res.get("status") != "OK":
        pytest.skip(f"이벤트 없음: {res.get('status')}")
    assert "clustering" in res
    assert "isClustered" in res["clustering"]
    assert "eventsByMonth" in res
