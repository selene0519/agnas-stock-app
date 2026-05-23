from __future__ import annotations
import json
from core.v60_final_engine import run_v60_update

def run_once():
    # v63: use global market-filtered UI; refresh news and missing prices for light reports.
    return run_v60_update(fetch_news=True, fetch_missing_prices=True)

if __name__ == '__main__':
    print(json.dumps(run_once(), ensure_ascii=False, indent=2, default=str))
