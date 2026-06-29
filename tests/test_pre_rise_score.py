from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

_PROBE = r"""
import sys, json
sys.path.insert(0, {root!r})
from scripts.generate_kr_recommendations import already_moved_penalty, pre_rise_score, recommendation_bucket

def ind(**kw):
    base = {{
        "rsi14": 50.0, "recentMomentum5": 0.0, "recentMomentum20": 0.0,
        "distanceToMa20": 0.0, "distanceToMa60": 0.0, "gapUpPct": 0.0,
        "volumeRatio20": 1.0, "volumeUpDownRatio": 1.0, "risingLows": False,
        "atrContracting": False, "distanceToBoxTop": 10.0, "recent5RangePct": 10.0,
    }}
    base.update(kw)
    return base

out = {{}}

# 1) 이미 급등한 종목 — 큰 감산
penalty, reasons = already_moved_penalty(ind(recentMomentum5=25.0, distanceToMa20=18.0, gapUpPct=9.0, rsi14=80.0))
out["surged_penalty"] = penalty
out["surged_reasons_count"] = len(reasons)

# 2) 조용한 종목 — 감산 없음
penalty2, reasons2 = already_moved_penalty(ind())
out["quiet_penalty"] = penalty2

# 3) 매집형 패턴
acc = pre_rise_score(ind(recentMomentum20=2.0, recent5RangePct=3.0, volumeRatio20=1.6,
                          volumeUpDownRatio=1.4, risingLows=True))
out["accumulation_score"] = acc["accumulationScore"]

# 4) 수렴형 패턴
conv = pre_rise_score(ind(atrContracting=True, distanceToMa20=1.0, distanceToMa60=2.0,
                           distanceToBoxTop=2.0))
out["convergence_score"] = conv["convergenceScore"]

# 5) 급등주는 alreadyMovedPenalty가 크고 totalScore가 깎인다
surged = pre_rise_score(ind(recentMomentum5=25.0, distanceToMa20=18.0, gapUpPct=9.0, rsi14=80.0))
out["surged_total"] = surged["totalScore"]
out["surged_already_moved"] = surged["alreadyMovedPenalty"]

# 6) 버킷 분류 — 급등주는 추격금지
bucket, _ = recommendation_bucket(ind(recentMomentum5=25.0, distanceToMa20=18.0, gapUpPct=9.0, rsi14=80.0), surged)
out["surged_bucket"] = bucket

# 7) 버킷 분류 — 수렴+박스권 근접은 돌파대기
conv_ind = ind(atrContracting=True, distanceToMa20=1.0, distanceToMa60=2.0, distanceToBoxTop=2.0)
conv_score = pre_rise_score(conv_ind)
bucket2, _ = recommendation_bucket(conv_ind, conv_score)
out["convergence_bucket"] = bucket2

# 8) 수급 점수 — 기관+외국인 동반 매수
supply_full = pre_rise_score(ind(), supply_row={{"inst5d": 5.0, "foreign5d": 3.0}})
out["supply_both"] = supply_full["supplyScore"]
supply_none = pre_rise_score(ind(), supply_row=None)
out["supply_none"] = supply_none["supplyScore"]

print(json.dumps(out))
"""


def _probe() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(root=str(ROOT_DIR))],
        capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_surged_stock_gets_large_already_moved_penalty():
    out = _probe()
    assert out["surged_penalty"] >= 30.0
    assert out["surged_reasons_count"] == 4


def test_quiet_stock_gets_no_penalty():
    out = _probe()
    assert out["quiet_penalty"] == 0.0


def test_accumulation_pattern_scores_high_on_accumulation_only():
    out = _probe()
    assert out["accumulation_score"] >= 10.0


def test_convergence_pattern_scores_high_on_convergence_only():
    out = _probe()
    assert out["convergence_score"] >= 9.0


def test_surged_stock_total_score_is_dragged_down_by_penalty():
    out = _probe()
    assert out["surged_already_moved"] <= -30.0
    assert out["surged_total"] < 0


def test_surged_stock_bucketed_as_chase_forbidden():
    out = _probe()
    assert out["surged_bucket"] == "추격금지"


def test_convergence_near_box_top_bucketed_as_breakout_wait():
    out = _probe()
    assert out["convergence_bucket"] == "돌파대기"


def test_supply_score_rewards_combined_institutional_and_foreign_buying():
    out = _probe()
    assert out["supply_both"] == 7.0
    assert out["supply_none"] == 0.0
