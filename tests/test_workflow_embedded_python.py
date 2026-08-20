from __future__ import annotations

import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PYTHON_HEREDOC_START = re.compile(r"^\s*python(?:3)?\s+-\s+<<['\"]?PY['\"]?\s*$")
PYTHON_HEREDOC_END = re.compile(r"^\s*PY\s*$")


def _embedded_python(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    scripts: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if not PYTHON_HEREDOC_START.match(lines[index]):
            index += 1
            continue
        start = index + 1
        index += 1
        body: list[str] = []
        while index < len(lines) and not PYTHON_HEREDOC_END.match(lines[index]):
            body.append(lines[index])
            index += 1
        assert index < len(lines), f"{path}:{start}: Python heredoc is missing its PY terminator"
        scripts.append((start + 1, textwrap.dedent("\n".join(body)) + "\n"))
        index += 1
    return scripts


def test_all_workflow_embedded_python_is_complete_and_compiles() -> None:
    checked = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line_number, script in _embedded_python(path):
            compile(script, f"{path}:{line_number}", "exec")
            checked += 1

    assert checked >= 10, "workflow Python coverage unexpectedly disappeared"

def test_all_active_workflows_parse_as_yaml() -> None:
    import yaml

    for path in sorted(WORKFLOWS.glob("*.yml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), f"{path}: workflow must be a mapping"
        assert isinstance(payload.get("jobs"), dict), f"{path}: workflow jobs are missing"
