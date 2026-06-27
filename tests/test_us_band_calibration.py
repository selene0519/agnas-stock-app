from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

# scripts.generate_us_recommendations 임포트는 scripts.generate_kr_recommendations를
# 거쳐 core/ 전체(레거시 Streamlit 의존성)를 끌어오고, 그 과정에서 sys.path 순서가
# 바뀌어 같이 돌아가는 다른 테스트 파일의 `app.engine` import가 깨질 수 있다(실제로
# 한 번 재현됐다). 그래서 서브프로세스에서 검증해 메인 pytest 프로세스를 절대 안 건드린다.
_PROBE = r"""
import sys, json
sys.path.insert(0, {root!r})
import scripts.generate_us_recommendations as gen

def ind(rsi, vr):
    return {{
        "ma5": 105, "ma20": 100, "ma60": 90,
        "rsi14": rsi, "volumeRatio20": vr,
        "distanceToMa20": 0.0, "atr14": 1.0, "bullRatio5": 0.5,
        "gapUpPct": 0.0,
    }}

out = {{}}
out["cons_rsi34_pass"] = gen.passes_us_quality_filters(ind(34, 0.6), "Tech", "conservative", "swing", {{}}, 99)[0]
out["cons_rsi31"] = gen.passes_us_quality_filters(ind(31, 0.6), "Tech", "conservative", "swing", {{}}, 99)
out["bal_vr04_pass"] = gen.passes_us_quality_filters(ind(50, 0.4), "Tech", "balanced", "swing", {{}}, 99)[0]
out["bal_vr03"] = gen.passes_us_quality_filters(ind(50, 0.3), "Tech", "balanced", "swing", {{}}, 99)
out["override_pass"] = gen.passes_us_quality_filters(
    ind(29, 0.6), "Tech", "conservative", "swing", {{}}, 99, rsi_band=(20, 40))[0]
out["sector_cap"] = gen.passes_us_quality_filters(
    ind(50, 0.6), "Tech", "conservative", "swing", {{"Tech": 2}}, 2)
print(json.dumps(out))
"""


def _probe() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(root=str(ROOT_DIR))],
        capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_conservative_rsi_band_widened_to_33_76() -> None:
    """2026-06-28 백테스트(scripts/backtest_band_calibration.py) 근거로 38~72 -> 33~76."""
    out = _probe()
    assert out["cons_rsi34_pass"] is True  # 옛 밴드라면 38 미달로 탈락했어야 함
    assert out["cons_rsi31"] == [False, "B_rsi"]  # 새 밴드 33 밖이면 여전히 탈락


def test_balanced_min_vr_loosened_to_0_35() -> None:
    """0.5 -> 0.35. 옛 기준이면 탈락했을 0.4 거래량비율이 이제 통과해야 한다."""
    out = _probe()
    assert out["bal_vr04_pass"] is True
    assert out["bal_vr03"] == [False, "C_volume"]


def test_explicit_rsi_band_override_bypasses_mode_default() -> None:
    """백테스트 스크립트가 쓰는 override 경로 — mode 기본값을 무시하고 그대로 적용돼야 한다."""
    out = _probe()
    assert out["override_pass"] is True


def test_sector_cap_still_enforced_after_band_loosening() -> None:
    """밴드를 넓혔다고 섹터 다양성 캡(필터 H)까지 같이 느슨해지면 안 된다."""
    out = _probe()
    assert out["sector_cap"] == [False, "H_sector_diversity"]
