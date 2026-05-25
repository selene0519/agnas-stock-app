from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / 'logs'
LOG_DIR.mkdir(exist_ok=True)

try:
    from core.v92_stable_update_engine import run_v92_update
    result = run_v92_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    (LOG_DIR / 'v92_daily_update_last.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    if str(result.get('status')) not in {'OK', 'WARN'}:
        sys.exit(2)
except Exception as exc:
    err = {'status': 'ERROR', 'version': 'v92', 'error': f'{type(exc).__name__}: {exc}'}
    print(json.dumps(err, ensure_ascii=False, indent=2, default=str), flush=True)
    (LOG_DIR / 'v92_daily_update_last.json').write_text(json.dumps(err, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    sys.exit(1)
