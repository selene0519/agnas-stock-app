from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from core.v91_operational_final_engine import run_v91_update, REPORT_DIR, DATA_DIR, HISTORY_DIR
except Exception:  # pragma: no cover
    run_v91_update = None
    REPORT_DIR = Path('reports')
    DATA_DIR = Path('data')
    HISTORY_DIR = DATA_DIR / 'history'

VERSION = 'v92'
BASE_VERSION = 'v91'
FALLBACK_SOURCE_VERSIONS = ['v91', 'v85', 'v84', 'v83', 'v82', 'v81', 'v80', 'v79', 'v78', 'v75', 'v74']

def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    Path('logs').mkdir(exist_ok=True)
    Path('backups').mkdir(exist_ok=True)

def _copy_base_reports() -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for source_version in FALLBACK_SOURCE_VERSIONS:
        for pattern in (f'{source_version}_*.csv', f'{source_version}_*.json'):
            for src in sorted(REPORT_DIR.glob(pattern)):
                dst = REPORT_DIR / src.name.replace(f'{source_version}_', f'{VERSION}_', 1)
                if dst.name in seen_targets:
                    continue
                seen_targets.add(dst.name)
                try:
                    if src.exists() and src.stat().st_size > 0:
                        shutil.copyfile(src, dst)
                        copied.append({
                            'source_version': source_version,
                            'source': src.name,
                            'target': dst.name,
                            'bytes': dst.stat().st_size,
                        })
                except Exception as exc:
                    copied.append({
                        'source_version': source_version,
                        'source': src.name,
                        'target': dst.name,
                        'error': f'{type(exc).__name__}: {exc}',
                    })
    return copied

def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}

def _write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def _rows(path: Path) -> int:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return 0
        import pandas as pd
        return len(pd.read_csv(path, encoding='utf-8-sig'))
    except Exception:
        return 0

def run_v92_update(fetch_news: bool = False, fetch_fundamentals: bool = False, fetch_macro: bool = False) -> dict[str, Any]:
    """Stable wrapper around v91.

    The previous one-click launcher repeatedly ran pip install and could appear to hang.
    v92 intentionally does not install packages. It only runs the update engine and
    copies the resulting v91 reports to v92 names so the UI can prefer v92 files while
    safely falling back to v91/v85/v84 if needed.
    """
    _ensure_dirs()
    started = _now()
    base: dict[str, Any]
    rebuild_v91 = bool(fetch_news or fetch_fundamentals or fetch_macro) or str(os.environ.get('MONE_REBUILD_V91', '')).strip() == '1'
    if rebuild_v91 and run_v91_update is None:
        base = {'status': 'WARN', 'error': 'v91 update engine is not importable; using existing reports'}
    elif rebuild_v91:
        try:
            base = run_v91_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status': 'WARN', 'error': f'{type(exc).__name__}: {exc}'}
    else:
        base = {'status': 'SKIPPED', 'reason': 'using existing report files'}
    copied = _copy_base_reports()
    status = 'OK' if copied and str(base.get('status')) in {'OK', 'WARN', 'SKIPPED'} else 'WARN'
    checks = {}
    for slug in ['kr', 'us']:
        for key in ['today_summary', 'symbol_snapshot', 'confidence_cards', 'operational_dashboard']:
            p = REPORT_DIR / f'{VERSION}_{key}_{slug}.csv'
            checks[f'{key}_{slug}'] = {'exists': p.exists(), 'bytes': p.stat().st_size if p.exists() else 0, 'rows': _rows(p)}
    result = {
        'status': status,
        'version': VERSION,
        'started_at': started,
        'updated_at': _now(),
        'base_version': BASE_VERSION,
        'base_status': base.get('status'),
        'base': base,
        'copied_files': len(copied),
        'copied_detail': copied[:20],
        'checks': checks,
        'note': 'v92 is a stable no-install update wrapper. It avoids pip install loops and keeps v91/v85/v84/v83/v82 fallback data available.',
    }
    _write_json(result, REPORT_DIR / f'{VERSION}_status.json')
    _write_json(result, Path('logs') / f'{VERSION}_update_last.json')
    try:
        manifest = _read_json(Path('backups') / 'v91_backup_manifest.json')
        manifest['v92_last_update'] = result
        _write_json(manifest, Path('backups') / 'v92_backup_manifest.json')
    except Exception:
        pass
    return result
