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
import sys
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


# ── PR 워크플로 설치 목록이 테스트의 실제 임포트를 덮는가 ─────────────────
# 2026-07-29 실측: PR 게이트 첫 실행이 `ERROR tests/test_alpha_display_and_pr_checks.py`
# (exit 2)로 죽었다. 원인은 `import yaml`인데 워크플로 설치 목록에 PyYAML이 없었던 것.
# **로컬엔 이미 깔려 있어서 통과했다** — 이 레포가 반복해서 당한 "로컬에서 되는 것과
# CI에서 되는 것은 다르다"를 그대로 밟았다.
#
# 설치 목록은 손으로 관리하는 중복이라 또 빠진다. 그래서 핀 하나를 더하는 대신
# **tests/가 실제로 임포트하는 서드파티 모듈이 전부 설치되는지**를 검사한다.

PR_WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"

# 표준 라이브러리는 **하드코딩하지 않는다** — 손으로 적은 표는 낡는다
# (실제로 첫 시도에서 `inspect`를 빠뜨렸다. 이 파일이 막으려는 실수와 같은 종류다).
# sys.stdlib_module_names가 인터프리터의 권위 있는 목록이다.
_STDLIB = set(sys.stdlib_module_names) | {"__future__"}
# 레포 내부 모듈 — 설치 대상이 아니다.
_REPO_LOCAL = {"app", "core", "scripts", "tests", "conftest", "daily_system_check"}
# import 이름 != 배포 패키지명인 것들.
_IMPORT_TO_PACKAGE = {
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "fitz": "pymupdf",
    "FinanceDataReader": "finance-datareader",
}


def _test_third_party_imports() -> set[str]:
    """tests/ 전체에서 최상위 임포트 모듈명을 모은다(AST로 — 주석/문자열 제외)."""
    import ast as _ast

    mods: set[str] = set()
    for path in sorted((ROOT / "tests").glob("*.py")):
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    mods.add(alias.name.split(".")[0])
            elif isinstance(node, _ast.ImportFrom):
                if node.level == 0 and node.module:
                    mods.add(node.module.split(".")[0])
    return {m for m in mods if m not in _STDLIB and m not in _REPO_LOCAL}


def test_pr_workflow_installs_everything_tests_import() -> None:
    install_block = PR_WORKFLOW.read_text(encoding="utf-8").lower()
    missing = []
    for mod in sorted(_test_third_party_imports()):
        pkg = _IMPORT_TO_PACKAGE.get(mod, mod).lower()
        if pkg not in install_block:
            missing.append(f"{mod} (설치명 {pkg})")
    assert not missing, (
        "tests/가 임포트하는데 PR 워크플로가 설치하지 않는 패키지: "
        + ", ".join(missing)
        + " — 로컬엔 이미 깔려 있어 통과하고 CI에서만 수집 에러로 죽는다"
    )
