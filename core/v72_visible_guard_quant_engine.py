from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v71_mone_guard_quant_ui_engine import run_v71_update
except Exception:  # pragma: no cover
    run_v71_update = None

try:
    from core.v69_finance_api_engine import REPORT_DIR, _now, _read_csv, _write_csv, _write_json
except Exception:  # fallback for old bundles
    REPORT_DIR = Path('reports')
    def _now() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    def _read_csv(path: str | Path) -> pd.DataFrame:
        p = Path(path)
        if p.exists() and p.stat().st_size:
            try:
                return pd.read_csv(p)
            except Exception:
                return pd.DataFrame()
        return pd.DataFrame()
    def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False, encoding='utf-8-sig')
    def _write_json(data: dict[str, Any], path: str | Path) -> None:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _copy_report(src_name: str, dst_name: str) -> bool:
    src = REPORT_DIR / src_name
    dst = REPORT_DIR / dst_name
    if src.exists() and src.stat().st_size:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return True
    return False


def _report_rows(name: str) -> int:
    df = _read_csv(REPORT_DIR / name)
    return 0 if df.empty else len(df)


def _build_v72_manifest(base_result: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for slug, label in [('kr', '국장'), ('us', '미장')]:
        items = [
            ('오늘 실행 5카드', f'v72_today_summary_{slug}.csv'),
            ('시장 가드', f'v72_market_guard_{slug}.csv'),
            ('섹터 강도', f'v72_sector_strength_{slug}.csv'),
            ('보유·매도 카드', f'v72_position_cards_{slug}.csv'),
            ('시그널 패널', f'v72_signal_panel_{slug}.csv'),
            ('뉴스 카드', f'v70_news_cards_{slug}.csv'),
            ('기업분석 카드', f'v70_company_cards_{slug}.csv'),
            ('시장·거시 카드', f'v70_macro_cards_{slug}.csv'),
        ]
        for title, filename in items:
            p = REPORT_DIR / filename
            rows.append({
                '시장': label,
                '항목': title,
                '파일': filename,
                '행수': _report_rows(filename),
                '파일상태': '있음' if p.exists() and p.stat().st_size else '없음',
                '마지막수정': datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S') if p.exists() else '-',
            })
    df = pd.DataFrame(rows)
    _write_csv(df, REPORT_DIR / 'v72_visible_data_status.csv')
    manifest = {
        'status': 'OK',
        'version': 'v72',
        'updated_at': _now(),
        'visible_change': 'version banner + Donhyun market guard + QuantAI card UI + 5-card first screen',
        'base_result': base_result,
        'data_status_rows': len(df),
    }
    _write_json(manifest, REPORT_DIR / 'v72_status.json')
    return manifest


def run_v72_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    base: dict[str, Any]
    if run_v71_update is not None:
        try:
            base = run_v71_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status': 'WARN', 'error': f'{type(exc).__name__}: {exc}', 'version': 'v71_failed'}
    else:
        base = {'status': 'WARN', 'error': 'v71 engine import failed', 'version': 'v71_missing'}

    for slug in ['kr', 'us']:
        _copy_report(f'v71_today_summary_{slug}.csv', f'v72_today_summary_{slug}.csv')
        _copy_report(f'v71_market_guard_{slug}.csv', f'v72_market_guard_{slug}.csv')
        _copy_report(f'v71_sector_strength_{slug}.csv', f'v72_sector_strength_{slug}.csv')
        _copy_report(f'v71_position_cards_{slug}.csv', f'v72_position_cards_{slug}.csv')
        _copy_report(f'v71_signal_panel_{slug}.csv', f'v72_signal_panel_{slug}.csv')

    return _build_v72_manifest(base)
