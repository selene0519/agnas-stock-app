from __future__ import annotations
import json
from core.v82_clean_general_ui_engine import run_v82_update

if __name__ == "__main__":
    result = run_v82_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
