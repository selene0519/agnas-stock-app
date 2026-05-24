from __future__ import annotations
import json

if __name__ == '__main__':
    from core.v72_visible_guard_quant_engine import run_v72_update
    res = run_v72_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
