from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

# scripts/generate_kr_recommendations.py 임포트는 core/ 전체를 끌어와서(레거시 Streamlit
# 의존성 포함) 다른 테스트 파일의 `app` 패키지 sys.path 해석을 깨뜨릴 수 있다(실제로 함께
# 돌리면 ModuleNotFoundError가 났다). 그래서 별도 서브프로세스에서 검증해 메인 pytest
# 프로세스의 sys.path/sys.modules를 절대 건드리지 않게 한다.
_PROBE = r"""
import sys, json, csv
sys.path.insert(0, {root!r})
import scripts.generate_kr_recommendations as gen
import tempfile, os
from pathlib import Path
tmp = tempfile.mkdtemp()
path = Path(tmp) / "rec.csv"

# 1) force 없이 빈 결과 -> 기존 파일 보존
gen._write_csv(path, [{{"symbol": "AAA"}}])
gen._write_csv(path, [])
with open(path, encoding="utf-8-sig", newline="") as f:
    preserved = list(csv.DictReader(f))

# 2) force=True -> 실제로 비워짐
gen._write_csv(path, [], force=True)
size_after_force = os.path.getsize(path)

print(json.dumps({{"preserved": preserved, "size_after_force": size_after_force}}))
"""


def _run_probe() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(root=str(ROOT_DIR))],
        capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    import json
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_write_csv_preserves_existing_file_on_incidental_empty_result() -> None:
    """기존 동작: 일시적으로 후보가 0건이면 기존 파일을 보존한다(우발적 데이터 손실 방지)."""
    out = _run_probe()
    assert out["preserved"] == [{"symbol": "AAA"}]


def test_write_csv_force_clears_file_even_if_one_exists() -> None:
    """약세장 공격형 비활성화처럼 '의도적으로' 비우는 경우엔 force=True로 실제로 비워야 한다.

    이전 버그: BEAR 레짐일 때 _write_csv(path, [])를 호출해 공격형 추천을 지우려 했지만,
    "빈 결과 → 기존 파일 보존" 가드 때문에 약세장 진입 전 마지막 추천이 그대로 남아
    사용자에게 계속 노출됐다(안전장치가 안 작동).
    """
    out = _run_probe()
    assert out["size_after_force"] <= 3  # BOM만 남고 비어 있어야 함


def test_bear_regime_aggressive_disable_call_sites_pass_force_true() -> None:
    """BEAR 레짐 공격형 비활성화 분기가 _write_csv를 force=True로 호출하는지 소스로 확인."""
    for fname in ("generate_kr_recommendations.py", "generate_us_recommendations.py"):
        src = (ROOT_DIR / "scripts" / fname).read_text(encoding="utf-8")
        idx = src.index("약세장으로 비활성화")
        block = src[max(0, idx - 400):idx]
        assert block.count("force=True") >= 2, f"{fname}: BEAR-disable 분기가 force=True 없이 _write_csv를 호출함"
