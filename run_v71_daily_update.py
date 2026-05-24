from __future__ import annotations
import json

if __name__ == '__main__':
    from core.v71_mone_guard_quant_ui_engine import run_v71_update
    res = run_v71_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
