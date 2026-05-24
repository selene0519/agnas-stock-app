from __future__ import annotations
import json

if __name__ == '__main__':
    from core.v68_news_finance_market_engine import run_v68_update
    res = run_v68_update(fetch_news=True, fetch_missing_fundamentals=True)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
