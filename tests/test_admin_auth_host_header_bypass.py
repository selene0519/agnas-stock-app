"""관리자 인증 우회 회귀 테스트 (starlette PYSEC-2026-161 계열).

`request.url`은 `{scheme}://{host}{path}`를 이어붙였다 다시 파싱해 만들어진다.
그래서 Host 헤더에 `/`가 섞이면 경로 경계가 밀려 `request.url.path`가 실제 요청
경로와 달라진다. 라우팅은 raw scope path를 쓰므로 **엔드포인트는 정상 실행되는데
앞단의 경로 기반 인증만 건너뛴다.**

2026-07-29 실측 (레포 핀 버전 starlette 0.41.3):
    GET /api/admin/secret + `Host: example.com/abc?bar=`
      request.url.path == "/abc"  -> 관리자 prefix 불일치 -> 인증 통과
      라우팅은 /api/admin/secret -> 200 + 데이터 노출
starlette 1.3.1에서는 라이브러리가 막지만, 우리 코드가 scope를 쓰면 **버전과
무관하게** 안전하다. 이 테스트는 라이브러리가 아니라 그 습관을 지킨다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = ROOT / "mone-web-app" / "backend" / "app" / "main.py"

ADMIN_PREFIX = "/api/admin/"
POISON_HOST = "example.com/abc?bar="


async def _admin_secret(request):
    return JSONResponse({"leaked": "ADMIN ONLY DATA"})


def _build_app(path_getter):
    class AdminAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if path_getter(request).startswith(ADMIN_PREFIX):
                return JSONResponse({"ok": False, "code": "ADMIN_AUTH_REQUIRED"},
                                    status_code=401)
            return await call_next(request)

    return Starlette(routes=[Route("/api/admin/secret", _admin_secret)],
                     middleware=[Middleware(AdminAuth)])


def test_scope_path_blocks_poisoned_host_header() -> None:
    """scope 경로로 판정하면 Host를 조작해도 관리자 인증이 유지된다."""
    client = TestClient(_build_app(lambda r: str(r.scope.get("path") or "")))
    assert client.get("/api/admin/secret").status_code == 401
    poisoned = client.get("/api/admin/secret", headers={"Host": POISON_HOST})
    assert poisoned.status_code == 401, (
        f"Host 헤더 조작으로 관리자 인증이 우회됐다: {poisoned.status_code} {poisoned.text}"
    )


def test_main_py_does_not_use_request_url_for_path_decisions() -> None:
    """main.py가 `request.url.path`로 되돌아가면 즉시 잡는다.

    라이브러리를 올려서 증상이 사라져도 패턴 자체는 취약하다 — 다음 CVE(경로가
    `/`로 시작하지 않는 경우, PYSEC-2026-248)가 같은 자리를 다시 문다.
    """
    source = MAIN_PY.read_text(encoding="utf-8")
    # 주석·docstring은 취약 패턴을 **설명**하려고 그 문자열을 담고 있으므로
    # 정규식으로 훑으면 자기 문서에 걸린다. 실행되는 코드만 AST로 골라낸다.
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "path":
            continue
        inner = node.value
        if (isinstance(inner, ast.Attribute) and inner.attr == "url"
                and isinstance(inner.value, ast.Name) and inner.value.id == "request"):
            line = source.splitlines()[node.lineno - 1].strip()
            offenders.append(f"{node.lineno}: {line}")
    assert not offenders, (
        "보안/경로 판정에 request.url.path를 쓰고 있다. request.scope['path']를 쓸 것:\n  "
        + "\n  ".join(offenders)
    )


def test_vulnerable_pattern_is_actually_exploitable_on_pinned_starlette() -> None:
    """왜 이 테스트가 있는지 증명한다 — 취약 패턴이 실제로 뚫리는지.

    라이브러리가 이미 패치됐으면(starlette>=1.0.1) 우회가 안 되므로 skip한다.
    그래도 위의 소스 검사가 패턴 자체를 계속 막는다.
    """
    client = TestClient(_build_app(lambda r: r.url.path))
    assert client.get("/api/admin/secret").status_code == 401
    poisoned = client.get("/api/admin/secret", headers={"Host": POISON_HOST})
    if poisoned.status_code == 401:
        pytest.skip("설치된 starlette가 이미 Host 헤더를 검증한다(패치 버전)")
    assert poisoned.status_code == 200  # 취약 버전에서의 실제 동작 기록


def test_global_error_handler_does_not_leak_traceback_by_default() -> None:
    """500 응답에 스택트레이스가 기본 노출되면 안 된다.

    파일 경로·코드 구조가 새고, 예외 메시지엔 자격증명이 섞이기 쉽다
    (psycopg2 접속 문자열, URL에 키를 실은 외부 API 클라이언트 등).
    이 백엔드는 Render에 배포돼 인터넷에서 닿는다.
    """
    source = MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == "global_exception_handler"),
        None,
    )
    assert handler is not None, "global_exception_handler를 찾지 못했다"

    # "trace" 키를 무조건 채우면(= 조건 분기 밖에서 대입) 기본 노출이다.
    guarded = any(isinstance(n, ast.If) for n in ast.walk(handler))
    mentions_trace = "trace" in ast.dump(handler)
    assert not mentions_trace or guarded, (
        "스택트레이스를 조건 없이 응답에 싣고 있다 — 디버그 플래그로 가릴 것"
    )
