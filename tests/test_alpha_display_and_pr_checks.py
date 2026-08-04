"""알파 표시 배선 + PR 체크 워크플로 회귀 테스트.

■ 알파 표시
  화면이 원시 수익률만 보여주면 사용자는 "-14%"를 앱 실패로 읽는다. 그런데
  같은 구간에 KOSPI가 -24% 빠졌다면 선택은 오히려 시장을 이긴 것이다.
  그래서 원시 / 시장 몫 / 알파를 **함께** 내보내야 한다.

  동시에 과대 해석도 막아야 한다 — 이벤트가 며칠에 몰리면 유의성을 주장할 수
  없고, 알파가 (+)여도 계좌는 줄 수 있다. 이 경고가 카드에서 빠지면 그 카드는
  낙관을 파는 물건이 된다. 테스트가 그걸 지킨다.

■ PR 체크
  2026-07-29 실측: 피처 브랜치 대상 GitHub Actions 실행이 **0건**이었다.
  모든 워크플로가 schedule/workflow_dispatch뿐이라 PR에는 Vercel 배포만
  붙었고, 그건 프론트가 빌드되는지만 본다. 즉 테스트를 깨는 PR도 초록이었다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"
FRONTEND = ROOT / "mone-web-app" / "frontend"
PR_WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"


# ── 알파 표시 ──────────────────────────────────────────────────────────
def test_alpha_endpoint_exists_and_passes_through_caveats() -> None:
    src = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/api/edge/alpha")' in src
    # 한계를 빼고 수치만 내보내면 화면이 그걸 확정적 사실로 그린다.
    assert '"clustering"' in src
    assert '"caveats"' in src


def test_alpha_endpoint_does_not_invent_data_when_report_missing() -> None:
    """리포트가 없으면 0이나 빈 표가 아니라 DATA_PENDING을 돌려줘야 한다."""
    src = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    start = src.index('@app.get("/api/edge/alpha")')
    body = src[start:start + 2500]
    assert "DATA_PENDING" in body


def test_alpha_panel_shows_raw_market_and_alpha_together() -> None:
    """세 값이 같이 있어야 사용자가 -14%를 오독하지 않는다."""
    panel = (FRONTEND / "components" / "AlphaPanel.tsx").read_text(encoding="utf-8")
    for field in ("meanRawReturnPct", "marketComponentPct", "meanCarPct"):
        assert field in panel, f"{field}가 카드에 없다"


def test_alpha_panel_warns_that_positive_alpha_is_not_profit() -> None:
    """알파 (+)를 '수익'으로 읽게 두면 이 카드는 낙관을 파는 물건이 된다."""
    panel = (FRONTEND / "components" / "AlphaPanel.tsx").read_text(encoding="utf-8")
    assert "시장보다 덜 빠졌다" in panel
    assert "수익이 났다는" in panel


def test_alpha_panel_surfaces_clustering_warning() -> None:
    """이벤트 군집이면 '통계적 유의성 주장 불가'가 화면에 떠야 한다."""
    panel = (FRONTEND / "components" / "AlphaPanel.tsx").read_text(encoding="utf-8")
    assert "isClustered" in panel
    assert "통계적 유의성은 주장할 수 없습니다" in panel


def test_alpha_panel_is_mounted_before_raw_numbers() -> None:
    """원시 수익률 표보다 위에 있어야 읽는 순서가 맞다."""
    page = (FRONTEND / "components" / "pages" / "VirtualJournalPage.tsx").read_text(encoding="utf-8")
    assert "<AlphaPanel />" in page
    assert page.index("<AlphaPanel />") < page.index("BookOpenCheck size={17}")


# ── PR 체크 워크플로 ───────────────────────────────────────────────────
def _pr_workflow() -> dict:
    return yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))


def test_pr_workflow_runs_on_pull_request() -> None:
    wf = _pr_workflow()
    triggers = wf.get(True) if True in wf else wf.get("on")
    assert "pull_request" in triggers, "PR에서 안 돌면 존재 이유가 없다"


def test_pr_workflow_runs_pytest_without_swallowing_failures() -> None:
    """`set +e`로 실패를 삼키면 이 워크플로도 거짓말을 시작한다.

    이 레포는 워크플로 34곳의 `set +e` 때문에 캡처가 매 실행 죽는데도
    success로 찍힌 전례가 있다. PR 게이트만큼은 그러면 안 된다.
    """
    raw = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "pytest tests" in raw
    # 주석에는 "왜 set +e를 안 쓰는가"가 적혀 있으므로 **실행되는 줄만** 본다.
    # (앞서 정규식이 자기 docstring을 잡은 것과 같은 실수를 피한다.)
    offenders = [ln.strip() for ln in raw.splitlines()
                 if "set +e" in ln and not ln.strip().startswith("#")]
    assert not offenders, (
        "PR 체크에서 실패를 삼키면 게이트가 무의미하다: " + "; ".join(offenders))


def test_pr_workflow_checks_frontend_types_and_build() -> None:
    raw = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "tsc --noEmit" in raw
    assert "next build" in raw


def test_pr_workflow_pins_pandas_upper_bound() -> None:
    """무핀이면 최신 메이저를 끌어와 코드를 안 건드린 날 PR이 깨진다."""
    raw = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "pandas>=2.2,<3" in raw
    assert "numpy>=1.26,<3" in raw
