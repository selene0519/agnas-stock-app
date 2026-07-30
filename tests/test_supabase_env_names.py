"""Supabase 환경변수 이름이 문서와 코드에서 어긋나지 않게 고정한다.

2026-07-29 발견: `supabase_db.py:19`는
    SUPABASE_SERVICE_KEY  또는  SUPABASE_ANON_KEY
를 읽는데, **같은 파일의 docstring과 CLAUDE.md 3곳이 `SUPABASE_KEY`라고**
적어두고 있었다. 그 이름으로 등록하면 `_enabled()`가 False가 되어
**오류 한 줄 없이 동기화가 꺼진다**(모듈 스스로 "Falls back silently"라고 쓴다).

키를 등록했다고 믿는 쪽과 실제로 읽히는 쪽이 다르면, 증상은 "동기화가 안 되는데
이유를 모르겠다"로 나타난다. 설정 이름은 코드가 유일한 근거이므로 문서를
코드에 맞춰 고정한다.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPABASE_DB = ROOT / "mone-web-app" / "backend" / "app" / "services" / "supabase_db.py"
# `\b...\b`를 쓰면 안 된다 — 한글도 단어 문자라 `SUPABASE_KEY를`처럼 조사가
# 바로 붙으면 뒤쪽 경계가 성립하지 않아 **조용히 안 잡힌다.** 실제로 이 테스트가
# 그 형태를 놓치고 있었고, 백틱이 붙은 경우만 잡고 있었다.
_ENV_TOKEN = r"(?<![A-Za-z0-9_])SUPABASE_[A-Z_]+(?![A-Za-z0-9_])"

DOCS = [
    ROOT / "mone-web-app" / "frontend" / "CLAUDE.md",
    ROOT / "CLAUDE.md",
]


def _env_names_read_by_code() -> set[str]:
    """`os.getenv("...")` 인자를 AST로 모은다 (주석·문자열 오탐 방지)."""
    tree = ast.parse(SUPABASE_DB.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_getenv = (
            (isinstance(fn, ast.Attribute) and fn.attr == "getenv")
            or (isinstance(fn, ast.Name) and fn.id == "getenv")
        )
        if not is_getenv or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if arg.value.startswith("SUPABASE"):
                names.add(arg.value)
    return names


def test_code_reads_the_expected_supabase_vars() -> None:
    names = _env_names_read_by_code()
    assert "SUPABASE_URL" in names, f"SUPABASE_URL을 안 읽는다: {names}"
    assert names & {"SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY"}, (
        f"서비스/익명 키를 안 읽는다: {names}")


def test_module_docstring_does_not_name_a_var_the_code_ignores() -> None:
    """docstring이 `SUPABASE_KEY`를 요구하면 사용자가 그 이름으로 등록한다."""
    src = SUPABASE_DB.read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src)) or ""
    read = _env_names_read_by_code()
    for mentioned in re.findall(_ENV_TOKEN, doc):
        if mentioned in read:
            continue
        # 안 읽는 이름을 적어도 되지만, **읽지 않는다고 분명히 밝힌 경우만**.
        assert re.search(rf"{mentioned}[^\n]*(읽지 않는|아님|not read)", doc), (
            f"docstring이 {mentioned}를 언급하는데 코드는 안 읽는다 — "
            f"그 이름으로 등록하면 조용히 비활성이 된다. 실제로 읽는 것: {sorted(read)}")


def test_docs_do_not_instruct_the_wrong_var_name() -> None:
    """CLAUDE.md가 틀린 이름을 '등록하면 동작한다'고 안내하면 안 된다."""
    read = _env_names_read_by_code()
    offenders: list[str] = []
    for doc in DOCS:
        if not doc.exists():
            continue
        for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for mentioned in re.findall(_ENV_TOKEN, line):
                if mentioned in read:
                    continue
                # 경고 문맥이면 통과 — 틀린 이름을 **경고하려고** 적는 건 정상이다.
                # (이 검사는 "등록하라"는 안내만 잡아야 한다. 이번 세션에서만
                #  세 번째로 검사가 자기 설명문을 잡았다: AST 사건, set +e 주석,
                #  그리고 여기. 검사 대상이 그 문자열을 담고 있을 때의 고질병이다.)
                if re.search(r"아님|읽지 않는|조용히|정정|꺼진다|비활성|not read", line):
                    continue
                offenders.append(f"{doc.relative_to(ROOT)}:{i} — {mentioned}")
    assert not offenders, (
        "문서가 코드에 없는 환경변수 이름을 안내한다 (등록해도 조용히 꺼진다):\n  "
        + "\n  ".join(offenders)
        + f"\n실제로 읽는 것: {sorted(read)}")
