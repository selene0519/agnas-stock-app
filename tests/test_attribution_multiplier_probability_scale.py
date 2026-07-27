"""귀속 배율 적용 시 probability 스케일 회귀 테스트.

`probability`는 이 코드베이스 전체에서 0~100 퍼센트인데, 귀속 배율 적용
루프만 상한을 1.0(=0~1 분수 가정)으로 걸어두고 있었다. 그래서 배율이
1.0이 아닌 순간 8.9% 같은 값이 1.0으로 잘려 "승률 1%"가 화면에 떴다.
승률 소스가 낙관적 백테스트(44~55%)였을 땐 늘 상한에 걸려 항상 1.0이라
아무도 이상함을 못 느꼈다.
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


def _apply(item: dict, attr_mult: float) -> dict:
    """서빙 루프의 귀속 배율 적용부와 동일한 연산."""
    for key in ("finalRankScore", "probability"):
        val = item.get(key)
        if val is not None:
            item[key] = round(stabilizer._clamp(float(val) * attr_mult, 0.0, 100.0), 1)
    return item


def test_probability_percentage_survives_multiplier() -> None:
    out = _apply({"probability": 8.9}, 0.9)
    assert out["probability"] > 1.0, "퍼센트 승률이 1.0으로 잘렸다"
    assert abs(out["probability"] - 8.0) < 0.05


def test_probability_and_score_share_the_same_scale() -> None:
    out = _apply({"probability": 40.0, "finalRankScore": 40.0}, 0.8)
    assert abs(out["probability"] - out["finalRankScore"]) < 0.05
    assert abs(out["probability"] - 32.0) < 0.05


def test_multiplier_above_one_still_clamps_at_100() -> None:
    out = _apply({"probability": 80.0}, 1.5)
    assert out["probability"] == 100.0


def test_multiplier_never_produces_negative() -> None:
    out = _apply({"probability": 10.0}, 0.0)
    assert out["probability"] == 0.0
