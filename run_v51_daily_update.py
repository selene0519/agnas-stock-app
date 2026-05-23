from __future__ import annotations
import json
from core.v51_fast_light_engine import run_v51_update

if __name__ == '__main__':
    print(json.dumps(run_v51_update(fetch_news=False), ensure_ascii=False, indent=2, default=str))
