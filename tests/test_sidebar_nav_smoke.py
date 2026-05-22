"""Sidebar navigation and unified panel smoke tests (no Streamlit UI)."""
from __future__ import annotations

import app


def test_sidebar_nav_groups_complete():
    required_groups = [
        "오늘 요약",
        "후보 / 매수 판단",
        "보유 / 매도 / 포트폴리오",
        "장중 실시간",
        "검증 / 복기",
        "데이터 / 운영 상태",
        "설정 / 관리",
    ]
    for g in required_groups:
        assert g in app.SIDEBAR_NAV_GROUPS
        assert len(app.SIDEBAR_NAV_GROUPS[g]) >= 1


def test_nav_page_ids_unique_within_each_group():
    for group, items in app.SIDEBAR_NAV_GROUPS.items():
        ids = [pid for _, pid in items]
        assert len(ids) == len(set(ids)), f"duplicate page_id in group: {group}"


def test_watchlist_pages_in_sidebar_nav():
    buy_ids = [pid for _, pid in app.SIDEBAR_NAV_GROUPS["후보 / 매수 판단"]]
    hold_ids = [pid for _, pid in app.SIDEBAR_NAV_GROUPS["보유 / 매도 / 포트폴리오"]]
    settings_ids = [pid for _, pid in app.SIDEBAR_NAV_GROUPS["설정 / 관리"]]
    assert "page_watch_mini" not in buy_ids
    assert "page_execution_plan" not in hold_ids
    assert "page_watch_manage" in settings_ids
    assert "page_holdings" in hold_ids


def test_grafted_sidebar_helpers_exist():
    assert hasattr(app, "_render_grafted_sidebar_market_and_watch")
    assert hasattr(app, "render_sidebar_daily_watch_cards")


def test_daily_watch_symbol_picker_helpers():
    labels, label_map = app._watchlist_selection_options("한국주식")
    assert isinstance(labels, list)
    assert isinstance(label_map, dict)


def test_intraday_diagnosis_reachable_from_admin_group_only():
    """장중 상세 진단은 일반 모드 중복 노출 없이 관리자 모드로 이동한다."""
    found = 0
    for items in app.SIDEBAR_NAV_GROUPS.values():
        if any(pid == "page_intraday_diagnosis" for _, pid in items):
            found += 1
    assert found == 1


def test_load_swing_candidates_and_safety_counts():
    df = app._load_swing_candidate_reports("한국주식")
    assert "symbol" in df.columns or df.empty
    trade, entry = app._c_excluded_intraday_safety_counts()
    assert trade == 0
    assert entry == 0


def test_derive_daily_system_check_status_ok():
    coverage = app._safe_report_json(app.REPORT_DIR / "intraday_data_coverage_diagnosis.json")
    status = app._derive_daily_system_check_status(coverage)
    assert status in {"OK", "OK_WITH_NOTICE", "ERROR"}


def test_intraday_flow_snapshot_path_referenced_in_app():
    text = open(app.__file__, encoding="utf-8").read()
    assert "intraday_flow_snapshot.csv" in text
