"""_price_band 승률 소스 정직성 회귀 테스트.

두 가지 사고를 막는다:
  1) `winRates[key] or default` — 실측 0.0%가 falsy라서 하드코딩 기본값으로
     둔갑한다. 즉 "한 번도 못 이긴 전략"이 52.5%로 표시된다.
     (KR conservative_mid: 실측 0.0 / 표본 7건인데 화면 0.525였음)
  2) 표본이 모자라 기본값을 썼는데 그걸 측정값처럼 내보내는 것.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_kr_recommendations import _price_band  # noqa: E402


def _write_rates(tmp_path: Path, monkeypatch, *, observed, samples, min_samples=20) -> None:
    doc = {
        "minSamplesForUpdate": min_samples,
        "defaultRates": {"mid_base": 0.525, "mid_scale": 0.14},
        "byMarket": {
            "kr": {
                "observedWinRates": {"balanced_mid": observed},
                "sampleCounts": {"balanced_mid": samples},
                # winRates에는 기본값이 채워져 있는 상태를 재현한다.
                "winRates": {"balanced_mid": 0.525},
            }
        },
    }
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "strategy_win_rates.json").write_text(json.dumps(doc), encoding="utf-8")
    import scripts.generate_kr_recommendations as gen
    monkeypatch.setattr(gen, "ROOT", tmp_path)


def _call():
    return _price_band(50.0, 10000.0, "balanced", "mid", None, market="kr")


def test_zero_observed_win_rate_is_not_replaced_by_default(tmp_path, monkeypatch) -> None:
    """실측 0.0%는 기본값으로 대체되면 안 된다 — 이게 원래 버그."""
    _write_rates(tmp_path, monkeypatch, observed=0.0, samples=40)
    *_, prob, samples, measured = _call()

    assert measured is True
    assert samples == 40
    # score=50이면 스케일 항이 0이라 base가 그대로 나온다.
    # 0.525(기본값)로 부풀지 않았는지 확인.
    assert prob < 0.05, f"실측 0%가 {prob}로 부풀려졌다"


def test_low_sample_falls_back_but_is_marked_unmeasured(tmp_path, monkeypatch) -> None:
    """표본 부족이면 기본값을 쓰되 '측정됨'으로 표시하지 않는다."""
    _write_rates(tmp_path, monkeypatch, observed=0.0, samples=7)
    *_, prob, samples, measured = _call()

    assert measured is False
    assert samples == 7
    assert abs(prob - 0.525) < 1e-6


def test_sufficient_sample_uses_observed_rate(tmp_path, monkeypatch) -> None:
    _write_rates(tmp_path, monkeypatch, observed=0.38, samples=120)
    *_, prob, samples, measured = _call()

    assert measured is True
    assert samples == 120
    assert abs(prob - 0.38) < 1e-6


def test_missing_observed_rate_is_unmeasured(tmp_path, monkeypatch) -> None:
    _write_rates(tmp_path, monkeypatch, observed=None, samples=0)
    *_, prob, samples, measured = _call()

    assert measured is False
    assert samples == 0
    assert abs(prob - 0.525) < 1e-6
