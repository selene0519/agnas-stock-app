"""UI navigation — operational vs inspection screen areas."""

from __future__ import annotations



import ast

import subprocess

import sys

from functools import lru_cache

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

APP_PY = ROOT / "app.py"


@lru_cache(maxsize=1)
def _app_source() -> str:
    return APP_PY.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _app_tree() -> ast.Module:
    return ast.parse(_app_source())





def _nav_groups_from_source(name: str) -> dict[str, list[tuple[str, str]]]:

    tree = _app_tree()

    for node in tree.body:

        targets: list[ast.expr] = []

        value = None

        if isinstance(node, ast.Assign):

            targets = list(node.targets)

            value = node.value

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):

            targets = [node.target]

            value = node.value

        if not targets or value is None:

            continue

        for target in targets:

            if isinstance(target, ast.Name) and target.id == name:

                return ast.literal_eval(value)

    raise AssertionError(f"{name} not found in app.py")





def _page_ids_in_group(nav: dict[str, list[tuple[str, str]]], group: str) -> set[str]:

    return {pid for _, pid in nav[group]}





def test_app_py_compiles():

    proc = subprocess.run(

        [sys.executable, "-m", "py_compile", str(APP_PY)],

        capture_output=True,

        text=True,

        cwd=str(ROOT),

        timeout=120,

    )

    assert proc.returncode == 0, proc.stderr or proc.stdout





def test_operational_nav_has_six_top_groups():

    nav = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    assert len(nav) == 6

    assert "오늘의 실행 플랜" in nav

    assert "매수 후보" in nav

    assert "보유·매도" in nav

    assert "관심·차트" in nav

    assert "예측·확률" in nav

    assert "장중 요약" in nav





def test_operational_buy_group_subpages():

    nav = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    buy = _page_ids_in_group(nav, "매수 후보")

    assert "page_buy_dashboard" in buy

    assert "page_buy_decision" in buy

    assert "page_strong_watch" in buy

    assert "page_stock_quality" not in buy

    assert "매수 가격 기준" not in [label for label, _ in nav["매수 후보"]]

    assert "page_ranking" not in buy

    assert "page_portfolio_risk" not in buy

    assert "page_ops_prob_status" not in buy

    assert "page_ops_prob_guidance" not in buy





def test_operational_holdings_unified_single_page():

    nav = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    hold = _page_ids_in_group(nav, "보유·매도")

    assert hold == {"page_ops_holdings_unified"}
    assert len(nav["보유·매도"]) == 1
    assert "page_holdings_check" not in hold
    assert "page_sell_decision" not in hold





def test_operational_intraday_unified_single_page():

    nav = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    intra = _page_ids_in_group(nav, "장중 요약")

    assert intra == {"page_ops_intraday_summary"}
    assert len(nav["장중 요약"]) == 1
    assert "page_intraday_diagnosis" not in intra





def test_inspection_nav_has_five_top_groups():

    nav = _nav_groups_from_source("INSPECTION_NAV_GROUPS")

    assert len(nav) == 5

    assert "예측 검증·복기" in nav

    assert "데이터 진단" in nav

    assert "원본 데이터" in nav

    assert "시스템 점검" in nav

    assert "설정·관리" in nav





def test_page_probability_only_in_operational_prediction_group():

    op = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    insp = _nav_groups_from_source("INSPECTION_NAV_GROUPS")

    op_prob = _page_ids_in_group(op, "예측·확률")

    all_insp = {pid for entries in insp.values() for _, pid in entries}

    assert op_prob == {"page_probability"}

    assert "page_probability" not in all_insp





def test_page_admin_ui_inventory_only_in_inspection_system_group():

    op = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    insp = _nav_groups_from_source("INSPECTION_NAV_GROUPS")

    all_op = {pid for entries in op.values() for _, pid in entries}

    sys_insp = _page_ids_in_group(insp, "시스템 점검")

    assert "page_admin_ui_inventory" in sys_insp

    assert "page_admin_ui_inventory" not in all_op





def test_no_app_view_mode_general_admin_selectbox():

    text = _app_source()

    assert 'key="app_view_mode"' not in text

    assert "APP_SCREEN_AREA_KEY" in text

    assert 'key=APP_SCREEN_AREA_KEY' in text or "key=APP_SCREEN_AREA_KEY," in text





def test_sidebar_nav_groups_for_mode_uses_screen_area():

    text = _app_source()

    assert "def _sidebar_nav_groups_for_mode" in text

    assert "OPERATIONAL_NAV_GROUPS" in text

    assert "INSPECTION_NAV_GROUPS_WITH_LEGACY" in text

    assert "_is_inspection_screen_area()" in text

    assert "return SIDEBAR_NAV_GROUPS" not in text





def test_grafted_market_filter_kr_us_only():

    text = _app_source()

    assert "GRAFT_SIDEBAR_MARKET_KEY" in text

    assert 'options = ["국장", "미장"]' in text

    assert '["전체", "국장", "미장"]' not in text

    assert '["전체", "한국주식", "미국주식"]' not in text





def test_holdings_return_helpers_preserved():

    text = _app_source()

    assert "def _holding_return_display_from_row" in text

    assert "def render_holdings_action_summary" in text





def test_execution_plan_home_helpers_exist():

    text = _app_source()

    assert "def render_general_execution_plan_home" in text

    assert "def render_action_summary_cards_counts_only" in text

    assert "def _execution_plan_today_table" in text

    assert "def _render_execution_plan_status_header" in text

    assert "EXECUTION_PLAN_ACTION_PRIORITY" in text





def test_execution_plan_home_is_default_operational_page():

    op = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    first_group = list(op.keys())[0]

    assert first_group == "오늘의 실행 플랜"

    assert op[first_group][0][1] == "page_ops_execution_plan"





def test_no_page_portfolio_risk_in_operational_nav():

    op = _nav_groups_from_source("OPERATIONAL_NAV_GROUPS")

    all_op = {pid for entries in op.values() for _, pid in entries}

    assert "page_portfolio_risk" not in all_op

    assert "page_portfolio" not in all_op


def test_operational_hidden_columns_and_unified_pages_exist():

    text = _app_source()

    assert "OPERATIONAL_HIDDEN_COLUMNS" in text

    assert "def render_operational_holdings_unified_page" in text

    assert "def render_operational_intraday_summary_page" in text

    assert "def _column_hidden_in_operational" in text

    assert 'if len(sub_labels) > 1:' in text


