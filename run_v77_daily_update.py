from __future__ import annotations

import json
from core.v77_operational_record_ui_engine import run_v77_update

if __name__ == '__main__':
    print('[INFO] Running MONE v77 daily update...')
    res = run_v77_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    print('[OK] MONE v77 daily update complete.')
