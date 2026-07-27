"""_apply_light_correction의 승률 감점이 비율인지 회귀 테스트.

예전엔 퍼센트포인트를 그대로 뺐다(`probability - 15`). 그 15는 낙관적인
백테스트 승률(44~55%) 스케일에 맞춰진 값이라, 승률 소스를 라이브 실측
(KR 10% 안팎)으로 바꾸자 10.5 - 15 = 음수 → 0.0으로 뭉개져 화면에 "승률 0%"가
떴다. 같은 함수가 점수는 이미 `* 0.85`로 비율 감점하고 있었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
loaded = sys.modules.get("app")
if loaded is not None and not hasattr(loaded, "__path__"):
    sys.modules.pop("app", None)

from app.engine import mone_v65_api_stabilizer as stabilizer  # noqa: E402

SUMMARY = {"active": True, "penaltyPct": 15.0}


def test_low_live_win_rate_is_not_crushed_to_zero() -> None:
    """라이브 실측 승률(10.5%)이 0으로 뭉개지면 안 된다 — 원래 버그."""
    out = stabilizer._apply_light_correction({"probability": 10.5}, SUMMARY)
    assert out["probability"] > 0.0, "실측 승률이 0으로 뭉개졌다"
    assert abs(out["probability"] - 8.9) < 0.05


def test_penalty_is_proportional_not_absolute() -> None:
    out = stabilizer._apply_light_correction({"probability": 50.0}, SUMMARY)
    # 비율 감점: 50 * 0.85 = 42.5 (예전 절대 감점이면 35.0)
    assert abs(out["probability"] - 42.5) < 0.05


def test_scores_and_probability_use_the_same_penalty_semantics() -> None:
    """점수는 *0.85, 승률은 -15 였던 불일치가 사라졌는지 확인."""
    item = {"probability": 40.0, "finalScore": 40.0}
    out = stabilizer._apply_light_correction(item, SUMMARY)
    assert abs(out["probability"] - out["finalScore"]) < 0.05


def test_inactive_summary_leaves_item_untouched() -> None:
    item = {"probability": 10.5, "finalScore": 80.0}
    out = stabilizer._apply_light_correction(item, {"active": False})
    assert out["probability"] == 10.5
    assert out["finalScore"] == 80.0


def test_zero_probability_stays_zero() -> None:
    out = stabilizer._apply_light_correction({"probability": 0.0}, SUMMARY)
    assert out["probability"] == 0.0
