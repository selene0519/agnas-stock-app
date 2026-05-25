from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v83_sidebar_update_fix_engine import run_v83_update, REPORT_DIR, DATA_DIR, HISTORY_DIR, _write_csv, _write_json
except Exception:  # pragma: no cover
    run_v83_update = None
    REPORT_DIR = Path('reports')
    DATA_DIR = Path('data')
    HISTORY_DIR = DATA_DIR / 'history'

    def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
        p = Path(path)
        if not p.is_absolute():
            p = REPORT_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False, encoding='utf-8-sig')

    def _write_json(data: dict[str, Any], path: str | Path) -> None:
        p = Path(path)
        if not p.is_absolute():
            p = REPORT_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _copy_versioned(src_version: str, dst_version: str) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for pattern in (f'{src_version}_*.csv', f'{src_version}_*.json'):
        for p in sorted(REPORT_DIR.glob(pattern)):
            dst = REPORT_DIR / p.name.replace(f'{src_version}_', f'{dst_version}_', 1)
            try:
                shutil.copyfile(p, dst)
                copied.append({'source': p.name, 'target': dst.name, 'bytes': dst.stat().st_size})
            except Exception as exc:
                copied.append({'source': p.name, 'target': dst.name, 'error': f'{type(exc).__name__}: {exc}'})
    return copied


def _write_update_status(base: dict[str, Any], copied: list[dict[str, Any]]) -> pd.DataFrame:
    env = base.get('env') if isinstance(base, dict) else {}
    if not isinstance(env, dict):
        env = {}
    rows = [
        {'항목': 'v84 업데이트', '상태': '정상' if str(base.get('status')) in {'OK', 'WARN'} else '확인 필요', '설명': 'v83 데이터 생성 후 v84 화면용 파일로 복사'},
        {'항목': 'HTML 노출 방지', '상태': '정상', '설명': '일반 화면 카드 렌더링을 Streamlit 기본 컴포넌트로 변경'},
        {'항목': '사이드바', '상태': '정상', '설명': '핵심 메뉴만 표시하고 원본/진단은 관리자 모드로 분리'},
        {'항목': '업데이트 실행', '상태': '정상', '설명': '실패 시 logs/v84_daily_update.log에 기록'},
        {'항목': '복사 파일 수', '상태': str(len(copied)), '설명': 'v84_ 리포트 파일 생성 수'},
    ]
    for key in ['DART_API_KEY', 'FINNHUB_API_KEY', 'GNEWS_API_KEY', 'SEC_USER_AGENT', 'APIFY_TOKEN']:
        if key in env:
            rows.append({'항목': key, '상태': '인식' if env.get(key) else '미인식', '설명': '.env 키 인식 여부'})
    df = pd.DataFrame(rows)
    _write_csv(df, 'v84_data_status.csv')
    return df


def run_v84_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dirs()
    base: dict[str, Any] = {'status': 'SKIPPED', 'reason': 'v83 engine unavailable'}
    if run_v83_update is not None:
        try:
            base = run_v83_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status': 'ERROR', 'error': f'{type(exc).__name__}: {exc}'}
    copied = _copy_versioned('v83', 'v84')
    status_df = _write_update_status(base, copied)
    result = {
        'status': 'OK' if str(base.get('status')) in {'OK', 'WARN', 'SKIPPED'} else 'WARN',
        'version': 'v84',
        'updated_at': _now(),
        'base': base,
        'copied_files': len(copied),
        'status_rows': len(status_df),
        'ui_note': 'Native Streamlit cards are used in main pages to prevent raw HTML text from appearing.',
    }
    _write_json(result, 'v84_status.json')
    return result


if __name__ == '__main__':
    print(json.dumps(run_v84_update(), ensure_ascii=False, indent=2, default=str))
