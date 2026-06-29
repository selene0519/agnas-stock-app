from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

_PROBE = r"""
import sys, json
sys.path.insert(0, {root!r})
from scripts.generate_kr_recommendations import momentum_continuation_score

def ind(**kw):
    base = {{
        "ma5": 110.0, "ma20": 100.0, "ma60": 90.0,
        "distanceToMa20": 0.0, "recentMomentum5": 0.0, "recentMomentum20": 0.0,
        "volumeRatio20": 1.0, "distanceTo52wHigh": -20.0,
    }}
    base.update(kw)
    return base

out = {{}}

# 1) 건강한 추세 지속형: 정배열 + 20일선 위 + 모멘텀 + 거래량 + 신고가 근접
strong = momentum_continuation_score(
    ind(distanceToMa20=8.0, recentMomentum5=5.0, recentMomentum20=15.0,
        volumeRatio20=1.8, distanceTo52wHigh=-1.0)
)
out["strong_total"] = strong["totalScore"]
out["strong_trend"] = strong["trendStrengthScore"]
out["strong_near_high"] = strong["nearHighScore"]
out["strong_vol_confirm"] = strong["volumeConfirmationScore"]

# 2) 정배열 깨진 종목: 추세 점수 0
broken = momentum_continuation_score(ind(ma5=90.0, ma20=100.0, ma60=110.0))
out["broken_trend"] = broken["trendStrengthScore"]

# 3) 섹터 대장주 — 자기 모멘텀이 섹터 평균보다 강함(gap이 음수)
leader = momentum_continuation_score(ind(), sector_lead_gap=-10.0)
out["leader_sector_score"] = leader["sectorLeaderScore"]
laggard = momentum_continuation_score(ind(), sector_lead_gap=10.0)
out["laggard_sector_score"] = laggard["sectorLeaderScore"]

# 4) 수급 지속 — 기관+외국인 동반매수
supply_both = momentum_continuation_score(ind(), supply_row={{"inst5d": 5.0, "foreign5d": 3.0}})
out["supply_both"] = supply_both["supplyContinuationScore"]
supply_none = momentum_continuation_score(ind(), supply_row=None)
out["supply_none"] = supply_none["supplyContinuationScore"]

print(json.dumps(out))
"""


def _probe() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(root=str(ROOT_DIR))],
        capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_strong_trend_continuation_scores_high_overall():
    out = _probe()
    assert out["strong_total"] >= 30.0


def test_strong_trend_gets_full_trend_and_near_high_credit():
    out = _probe()
    assert out["strong_trend"] == 8.4  # 정배열 6.0 + d20*0.3 (8.0*0.3=2.4)
    assert out["strong_near_high"] == 8.0
    assert out["strong_vol_confirm"] == 7.0


def test_broken_ma_alignment_scores_zero_trend():
    out = _probe()
    assert out["broken_trend"] == 0.0


def test_sector_leader_vs_laggard_gap_sign_matters():
    """음수 gap(자기가 섹터를 앞섬) -> 가산, 양수 gap(후발) -> 0점."""
    out = _probe()
    assert out["leader_sector_score"] == 8.0
    assert out["laggard_sector_score"] == 0.0


def test_supply_continuation_rewards_combined_buying():
    out = _probe()
    assert out["supply_both"] == 8.0
    assert out["supply_none"] == 0.0
