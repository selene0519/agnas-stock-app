"""사용자 화면 제목 정리(sanitize_user_title) 테스트."""
from __future__ import annotations

import app


def test_sanitize_removes_emoji_and_circled_numbers():
    assert app.sanitize_user_title("💼 포트폴리오 / 보유종목") == "포트폴리오 / 보유종목"
    assert app.sanitize_user_title("📋 오늘 요약") == "오늘 요약"
    assert app.sanitize_user_title("⑥ 미장 보유종목·수동 매수 단위") == "미장 보유종목·수동 매수 단위"
    assert app.sanitize_user_title("②-2 실전 주문계획") == "실전 주문계획"
    assert app.sanitize_user_title("③-2 시장 뉴스 요약") == "시장 뉴스 요약"


def test_sanitize_removes_version_tag():
    assert app.sanitize_user_title("✅ v9.2.1 국장 운용 체크") == "국장 운용 체크"


def test_nav_page_intro_for_holdings_pnl():
    assert "page_holdings_pnl" in app.NAV_PAGE_INTROS
    assert "평균단가" in app.NAV_PAGE_INTROS["page_holdings_pnl"]


def test_graft_router_source_no_duplicate_category_caption():
    import inspect

    src = inspect.getsource(app.render_grafted_feature_router)
    assert "대분류:" not in src
    assert "render_grafted_nav_header" in src
