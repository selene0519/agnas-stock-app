"""Bootstrap / lazy-load guards — no subprocess intraday refresh on import."""
from __future__ import annotations

import ast
from pathlib import Path


APP_PY = Path(__file__).resolve().parents[1] / "app.py"


def test_app_py_parses() -> None:
    source = APP_PY.read_text(encoding="utf-8")
    ast.parse(source)


def test_bootstrap_helpers_exist() -> None:
    source = APP_PY.read_text(encoding="utf-8")
    for name in (
        "_render_app_bootstrap_loading",
        "_lazy_load_page_data",
        "clear_report_file_caches",
        "_load_stock_data_for_chart_cached",
    ):
        assert f"def {name}" in source


def test_no_subprocess_intraday_on_import_snippet() -> None:
    """Module should not invoke run_intraday_refresh via subprocess at top level."""
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr in {
                "run",
                "call",
                "Popen",
                "check_output",
            }:
                raise AssertionError("Top-level subprocess call found in app.py")
