from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402
from app.services import product_scope  # noqa: E402


FORBIDDEN_LIVE_ORDER_MARKERS = (
    "/uapi/domestic-stock/v1/trading/order-cash",
    "/uapi/domestic-stock/v1/trading/order-rvsecncl",
    "/uapi/overseas-stock/v1/trading/order",
    "tttc0801u",
    "tttc0802u",
    "vttc0801u",
    "vttc0802u",
    "jttt1002u",
    "jttt1006u",
)


def test_product_scope_permanently_denies_live_broker_execution() -> None:
    scope = product_scope.product_scope()

    assert scope["executionMode"] == "ADVISORY_PAPER_ONLY"
    assert scope["humanDecisionRequired"] is True
    assert scope["liveBrokerOrdersSupported"] is False
    assert scope["liveOrderAllowed"] is False
    assert scope["brokerCredentialStorageAllowed"] is False
    assert scope["automaticCapitalScalingAllowed"] is False
    assert scope["paperLedgerMutationsAllowed"] is True
    assert product_scope.live_order_allowed() is False


def test_public_product_scope_api_exposes_the_same_immutable_boundary() -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/quant/product-scope")

    assert response.status_code == 200
    assert response.json() == product_scope.product_scope()


def test_production_sources_contain_no_known_live_broker_order_endpoint() -> None:
    sources = [ROOT / "app.py"]
    for folder in (ROOT / "core", ROOT / "scripts", BACKEND_DIR / "app"):
        sources.extend(folder.rglob("*.py"))
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore").lower() for path in sources)

    assert all(marker not in combined for marker in FORBIDDEN_LIVE_ORDER_MARKERS)


def test_quant_lab_ui_names_paper_evidence_and_user_decision_boundary() -> None:
    bottom_nav = (ROOT / "mone-web-app" / "frontend" / "components" / "BottomNav.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "mone-web-app" / "frontend" / "components" / "Sidebar.tsx").read_text(encoding="utf-8")
    advanced = (ROOT / "mone-web-app" / "frontend" / "components" / "pages" / "AdvancedPage.tsx").read_text(encoding="utf-8")
    paper = (ROOT / "mone-web-app" / "frontend" / "components" / "pages" / "PaperTradingPage.tsx").read_text(encoding="utf-8")
    status = (ROOT / "mone-web-app" / "frontend" / "components" / "QuantOperatingStatus.tsx").read_text(encoding="utf-8")

    assert "MONE 퀀트 랩" in bottom_nav + sidebar
    assert "AI 추천일지" in advanced
    assert "Paper 검증 계좌" in paper
    assert "실제 주문 없이" in paper
    assert "사용자가 결정하고 증권사에서 직접 실행" in status
    assert "실계좌 주문 연결 없음" in status
    assert "MONE 트레이딩" not in bottom_nav + sidebar + advanced
    assert "AI 매매일지" not in bottom_nav + advanced
