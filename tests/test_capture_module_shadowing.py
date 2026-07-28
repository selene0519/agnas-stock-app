"""캡처 스크립트가 루트 app.py에 가려지지 않는지 회귀 테스트.

레포 루트에는 스트림릿 앱 `app.py`(단일 모듈)가 있고, 백엔드에는 `app/`
**패키지**가 있다. 둘 다 sys.path에 있으면 `import app`이 루트 쪽으로 잡혀
`from app.engine import ...`이 "'app' is not a package"로 죽는다.

2026-07-28 CI 실측: 예측 캡처 스텝이 매 실행 이 에러로 종료됐는데, 워크플로가
`set +e`라 스텝은 success로 찍혔다. 원장의 최신 createdAt이 2026-07-23에
멈춰 있는 걸 헬스체크(prediction_capture=STALE)가 잡아내서야 발견됐다.
CLAUDE.md #1의 generate_kr_recommendations sys.path 사고와 같은 계열이다.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_recommendation_predictions.py"


def test_script_puts_backend_ahead_of_repo_root() -> None:
    """루트보다 백엔드가 sys.path 앞에 와야 `app` 패키지가 이긴다."""
    spec = importlib.util.spec_from_file_location("cap_paths", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    backend = str(module.BACKEND)
    root = str(module.ROOT)
    assert backend in sys.path and root in sys.path
    assert sys.path.index(backend) < sys.path.index(root), "백엔드가 루트보다 뒤에 있다"


def test_capture_imports_backend_package_even_when_root_app_preloaded(tmp_path) -> None:
    """루트 app.py가 먼저 임포트돼 sys.modules를 오염시켜도 캡처가 살아야 한다.

    CI가 정확히 이 상태였다(cwd=mone-web-app/backend, PYTHONPATH=.).
    """
    probe = tmp_path / "probe.py"
    probe.write_text(textwrap.dedent(f"""
        import sys
        from pathlib import Path
        root = Path(r"{ROOT}")
        sys.path.insert(0, str(root))
        import app as root_app                      # 루트 app.py 선점
        assert not hasattr(root_app, "__path__")    # 패키지가 아님을 확인

        import importlib.util
        spec = importlib.util.spec_from_file_location("cap", r"{SCRIPT}")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)                  # 스크립트의 가드가 정리해야 함

        from app.engine import mone_v65_api_stabilizer as stab
        assert "mone-web-app" in stab.__file__, stab.__file__
        print("OK")
    """).strip(), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=str(ROOT / "mone-web-app" / "backend"),
        capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "PYTHONPATH": ".", "PYTHONUTF8": "1"},
    )
    assert "OK" in result.stdout, (
        "루트 app.py 선점 상태에서 캡처가 백엔드 패키지를 임포트하지 못한다.\n"
        f"stdout={result.stdout[-800:]}\nstderr={result.stderr[-1500:]}"
    )
