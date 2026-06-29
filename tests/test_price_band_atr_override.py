from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

# generate_kr_recommendations 임포트는 core/ 전체(레거시 Streamlit 의존성)를 끌어오고,
# 그 과정에서 sys.path 순서가 바뀌어 같이 돌아가는 다른 테스트 파일의 app.engine import를
# 깨뜨릴 수 있다(이 세션에서 여러 번 재현됨). 서브프로세스로 완전히 격리한다.
_PROBE = r"""
import sys, json
sys.path.insert(0, {root!r})
import scripts.generate_kr_recommendations as gen

def ind(atr14):
    return {{"atr14": atr14}}

with_default = gen._price_band(60.0, 10000.0, "conservative", "swing", ind(200.0))
explicit_current = gen._price_band(
    60.0, 10000.0, "conservative", "swing", ind(200.0),
    atr_mult_override={{"short": (1.2, 2.8), "swing": (1.5, 4.5), "mid": (2.0, 5.5)}},
)
wider = gen._price_band(
    60.0, 10000.0, "conservative", "swing", ind(200.0),
    atr_mult_override={{"short": (1.2, 2.8), "swing": (3.0, 6.0), "mid": (2.0, 5.5)}},
)
print(json.dumps({{
    "default": list(with_default[:3]),
    "explicit_current": list(explicit_current[:3]),
    "wider": list(wider[:3]),
}}))
"""


def _probe() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(root=str(ROOT_DIR))],
        capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_price_band_default_unchanged_without_override():
    """atr_mult_override 없이 호출하면 기존과 100% 동일한 결과를 내야 한다(운영 동작 보존)."""
    out = _probe()
    assert out["default"] == out["explicit_current"]


def test_price_band_override_changes_stop_and_target():
    """override를 주면 실제로 다른 손절/목표가가 나와야 한다 — scripts/backtest_price_band_design.py가
    이 경로로 대안 ATR 배수를 검증한다."""
    out = _probe()
    default_entry, default_stop, _ = out["default"]
    entry, stop, _ = out["wider"]
    # swing 손절배수를 1.5->3.0으로 넓혔으니 손절가가 entry에서 더 멀어져야 한다
    assert (entry - stop) > (default_entry - default_stop)
