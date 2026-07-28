"""의존성 상한 핀 회귀 테스트.

무핀으로 두면 CI가 매 실행 최신 메이저를 새로 풀어오므로, **아무도 코드를
안 건드린 날 갑자기 깨진다.** 이 레포에서 조용한 실패가 반복된 자리와 같은
계열이고, 원인이 코드에 없어서 추적이 제일 오래 걸리는 종류다.

2026-07-29 실측: pandas 3.0.5에서 테스트 622개 중 5개가
`TypeError: Invalid value 'True' for dtype 'str'`로 사망했다. pandas 3.0이
문자열 컬럼에 bool 대입을 막았는데 예측 원장 쪽이 그 패턴을 쓴다.
pandas 2.3.3으로 내리자 622개 전부 통과.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 메이저 업그레이드가 깨는 게 실증된 패키지. 상한이 반드시 있어야 한다.
UPPER_BOUND_REQUIRED = ("pandas", "numpy")

WORKFLOWS = ROOT / ".github" / "workflows"


def _requirement_lines() -> list[str]:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_requirements_pin_upper_bounds_for_breaking_packages() -> None:
    lines = _requirement_lines()
    for pkg in UPPER_BOUND_REQUIRED:
        matched = [ln for ln in lines if re.match(rf"^{pkg}\b", ln, re.IGNORECASE)]
        assert matched, f"requirements.txt에 {pkg} 항목이 없다"
        spec = matched[0]
        assert "<" in spec, (
            f"{pkg}에 상한이 없다: {spec!r} — 무핀이면 CI가 최신 메이저를 풀어와 "
            f"코드를 안 건드린 날 깨진다(pandas 3.0 사례)."
        )


def test_workflows_do_not_install_breaking_packages_unpinned() -> None:
    """워크플로의 폴백 설치 경로도 requirements.txt와 같은 상한을 써야 한다.

    requirements.txt만 고치면, 그 파일이 없을 때 도는 `pip install pandas numpy`
    폴백 분기가 여전히 최신 메이저를 끌어온다.
    """
    offenders: list[str] = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            if "pip install" not in line:
                continue
            for pkg in UPPER_BOUND_REQUIRED:
                # 따옴표 없이 맨 이름으로 설치하면 무핀이다.
                if re.search(rf"(?<![\"'\w-]){pkg}(?![\w.<>=-])", line):
                    offenders.append(f"{wf.name}:{i}: {line.strip()}")
                    break
    assert not offenders, (
        "무핀 설치가 남아 있다 (상한 없는 pandas/numpy):\n  " + "\n  ".join(offenders)
    )
