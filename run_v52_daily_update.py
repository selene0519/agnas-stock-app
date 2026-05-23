from __future__ import annotations
import json
from core.v52_market_split_engine import run_v52_update

if __name__ == '__main__':
    print(json.dumps(run_v52_update(fetch_news=False, fetch_missing_prices=False), ensure_ascii=False, indent=2, default=str))
