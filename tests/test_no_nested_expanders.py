"""Streamlit expander 중첩 금지 — 핵심 UI 함수 정적 검사."""
from __future__ import annotations

import ast
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
TARGET_FUNCTIONS = {
    "render_unified_update_results_panel",
    "_render_phase11_intraday_sections",
    "render_swing_candidate_board",
}


class _NestedExpanderVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[int] = []
        self.nested: list[tuple[int, int]] = []

    def visit_With(self, node: ast.With) -> None:
        is_expander = False
        if node.items:
            ctx = node.items[0].context_expr
            if (
                isinstance(ctx, ast.Call)
                and isinstance(ctx.func, ast.Attribute)
                and ctx.func.attr == "expander"
            ):
                is_expander = True
        if is_expander:
            if self.stack:
                self.nested.append((node.lineno, self.stack[-1]))
            self.stack.append(node.lineno)
        self.generic_visit(node)
        if is_expander:
            self.stack.pop()


def _function_ranges(tree: ast.Module) -> dict[str, tuple[int, int]]:
    ranges: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            end = node.end_lineno or node.lineno
            ranges[node.name] = (node.lineno, end)
    return ranges


def test_no_nested_expanders_in_key_ui_functions() -> None:
    src = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    ranges = _function_ranges(tree)

    visitor = _NestedExpanderVisitor()
    visitor.visit(tree)

    violations: list[str] = []
    for fn_name, (start, end) in ranges.items():
        for child_ln, parent_ln in visitor.nested:
            if start <= child_ln <= end and start <= parent_ln <= end:
                violations.append(f"{fn_name}: line {child_ln} nested in expander at {parent_ln}")

    assert not violations, "nested st.expander found:\n" + "\n".join(violations)
