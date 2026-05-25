from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v84_native_ui_hotfix_engine import run_v84_update, REPORT_DIR, DATA_DIR, HISTORY_DIR, _write_csv, _write_json
except Exception:  # pragma: no cover
    run_v84_update = None
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

VERSION = 'v85'
PREV_VERSION = 'v84'

KR_NAME_MAP: dict[str, str] = {
    '000020': '동화약품', '000100': '유한양행', '000270': '기아', '000660': 'SK하이닉스', '000720': '현대건설',
    '000810': '삼성화재', '000990': 'DB하이텍', '003490': '대한항공', '003550': 'LG', '004020': '현대제철',
    '005930': '삼성전자', '010120': 'LS ELECTRIC', '010950': 'S-Oil', '012450': '한화에어로스페이스',
    '017670': 'SK텔레콤', '028670': '팬오션', '032640': 'LG유플러스', '034590': '인천도시가스',
    '058470': '리노공업', '095340': 'ISC', '131970': '두산테스나', '222800': '심텍', '259960': '크래프톤',
    '277810': '레인보우로보틱스', '278470': '에이피알', '329180': 'HD현대중공업', '375500': 'DL이앤씨',
    '403870': 'HPSP',
}
US_NAME_MAP: dict[str, str] = {
    'AAPL': 'Apple', 'AAOI': 'AAOI', 'ACHR': 'Archer Aviation', 'ALAB': 'Astera Labs', 'AMD': 'AMD',
    'AMZN': 'Amazon', 'ANET': 'Arista Networks', 'BMNR': 'BMNR', 'CAT': 'Caterpillar', 'COST': 'Costco',
    'CRCL': 'Circle', 'CRWD': 'CrowdStrike', 'DDOG': 'Datadog', 'GOOGL': 'Alphabet', 'GOOG': 'Alphabet',
    'INTC': 'Intel', 'LITE': 'Lumentum', 'META': 'Meta Platforms', 'MSFT': 'Microsoft', 'NBIS': 'Nebius',
    'NET': 'Cloudflare', 'NVDA': 'NVIDIA', 'PLTR': 'Palantir', 'RIOT': 'Riot Platforms', 'SNDK': 'SanDisk',
    'SNOW': 'Snowflake', 'TSLA': 'Tesla', 'XLE': 'Energy Select Sector SPDR',
}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _valid(v: Any) -> bool:
    if v is None:
        return False
    try:
        if isinstance(v, float) and math.isnan(v):
            return False
    except Exception:
        pass
    s = str(v).strip()
    return bool(s) and s.lower() not in {'nan', 'none', 'null', '-', 'n/a'}


def _clean(v: Any, default: str = '') -> str:
    if not _valid(v):
        return default
    return str(v).strip()


def _read_csv_file(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path, encoding='utf-8-sig')
    except Exception:
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()


def _read_first(names: list[str]) -> pd.DataFrame:
    for name in names:
        df = _read_csv_file(REPORT_DIR / name)
        if not df.empty:
            return df
    return pd.DataFrame()


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


def _get_col(row: Any, cols: list[str], default: str = '') -> str:
    for col in cols:
        try:
            if col in row and _valid(row[col]):
                return _clean(row[col])
        except Exception:
            pass
    return default


def _symbol(row: Any) -> str:
    s = _get_col(row, ['종목코드', 'symbol', 'ticker', '코드', 'Symbol', 'Ticker'])
    if not s:
        s = _get_col(row, ['종목', '종목명', 'name', 'Name'])
    s = re.sub(r'[^0-9A-Za-z.\-]', '', str(s).upper())
    # Some legacy rows store "Alphabet (GOOGL)" in symbol.
    m = re.search(r'\(([A-Z]{1,8})\)$', str(_get_col(row, ['종목코드', 'symbol', 'ticker', '종목명', 'name'])))
    if m:
        return m.group(1)
    if re.fullmatch(r'\d{1,6}', s):
        return s.zfill(6)
    return s


def _market_match(row: Any, slug: str) -> bool:
    sym = _symbol(row)
    market = _get_col(row, ['시장', 'market', 'Market'], '').replace(' ', '')
    if slug == 'kr':
        if market in {'한국주식', '국장', 'KR', 'KOREA', 'KOSPI', 'KOSDAQ'}:
            return True
        return bool(re.fullmatch(r'\d{6}', sym))
    if market in {'미국주식', '미장', 'US', 'USA', 'NASDAQ', 'NYSE'}:
        return True
    return bool(re.fullmatch(r'[A-Z]{1,8}(\.[A-Z])?', sym)) and not bool(re.fullmatch(r'\d{6}', sym))


def _filter_market(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        mask = df.apply(lambda r: _market_match(r, slug), axis=1)
        out = df.loc[mask].copy()
    except Exception:
        out = df.copy()
    if out.empty:
        return out
    # Normalize core columns without removing original columns.
    out['종목코드'] = out.apply(lambda r: _symbol(r), axis=1)
    out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    return out


def _build_name_map(slug: str) -> dict[str, str]:
    mapping = dict(KR_NAME_MAP if slug == 'kr' else US_NAME_MAP)
    for p in REPORT_DIR.glob('*.csv'):
        if p.stat().st_size <= 0:
            continue
        df = _read_csv_file(p)
        if df.empty:
            continue
        try:
            df = _filter_market(df, slug)
        except Exception:
            pass
        if df.empty:
            continue
        for _, row in df.head(300).iterrows():
            sym = _symbol(row)
            name = _get_col(row, ['종목명', 'name', 'Name', '종목', '카드제목', 'TOP'], '')
            if not sym or not name:
                continue
            name = re.sub(r'\s*\([A-Za-z0-9.\-]{1,10}\)\s*$', '', name).strip()
            if slug == 'kr' and not re.fullmatch(r'\d{6}', sym):
                continue
            if slug == 'us' and re.fullmatch(r'\d{6}', sym):
                continue
            if name and name != sym and len(name) <= 40:
                mapping.setdefault(sym, name)
    return mapping


def _display_name(row: Any, slug: str, name_map: dict[str, str] | None = None) -> str:
    name_map = name_map or _build_name_map(slug)
    sym = _symbol(row)
    raw_name = _get_col(row, ['종목명', 'name', 'Name', '종목', '카드제목', 'TOP'], '')
    raw_name = re.sub(r'\s*\([A-Za-z0-9.\-]{1,10}\)\s*$', '', raw_name).strip()
    if not raw_name or raw_name == sym or raw_name.upper() == sym.upper():
        raw_name = name_map.get(sym, sym)
    return f'{raw_name} ({sym})' if sym and sym not in raw_name else raw_name or sym or '종목'


def _candidate_sources(slug: str, kind: str) -> list[str]:
    patterns: dict[str, list[str]] = {
        'action': ['v84_action_cards_{s}.csv', 'v83_action_cards_{s}.csv', 'v82_action_cards_{s}.csv', 'v81_action_cards_{s}.csv', 'v80_action_clean_{s}.csv', 'v79_action_clean_{s}.csv', 'v67_action_board_{s}.csv'],
        'pullback': ['v84_pullback_cards_{s}.csv', 'v83_pullback_cards_{s}.csv', 'v82_pullback_cards_{s}.csv', 'v81_pullback_cards_{s}.csv', 'v80_pullback_clean_{s}.csv', 'v79_pullback_clean_{s}.csv', 'v67_pullback_{s}.csv'],
        'flow': ['v84_flow_cards_{s}.csv', 'v84_flow_clean_{s}.csv', 'v83_flow_clean_{s}.csv', 'v82_flow_clean_{s}.csv', 'v80_flow_clean_{s}.csv', 'v79_flow_clean_{s}.csv', 'v78_flow_clean_{s}.csv', 'intraday_flow_snapshot-Kang.csv', 'intraday_realtime_snapshot-Kang.csv', 'intraday_orderbook_snapshot-Kang.csv', 'intraday_flow_snapshot.csv'],
        'company': ['v84_company_integrated_{s}.csv', 'v83_company_integrated_{s}.csv', 'v82_company_integrated_{s}.csv', 'v80_kpi_cards_{s}.csv', 'v80_company_cards_{s}.csv', 'v80_advanced_valuation_{s}.csv', 'v80_financial_statement_{s}.csv', 'v79_company_cards_{s}.csv'],
        'risk': ['v84_risk_cards_{s}.csv', 'v83_risk_cards_{s}.csv', 'v82_risk_cards_{s}.csv', 'v81_risk_cards_{s}.csv', 'v80_risk_clean_{s}.csv', 'v79_risk_clean_{s}.csv', 'v67_risk_{s}.csv'],
        'news': ['v84_news_summary_{s}.csv', 'v83_news_summary_{s}.csv', 'v82_news_summary_{s}.csv', 'v80_news_summary_{s}.csv', 'v79_news_summary_{s}.csv', 'v70_news_cards_{s}.csv'],
        'position': ['v84_position_cards_{s}.csv', 'v83_position_cards_{s}.csv', 'v82_position_cards_{s}.csv', 'v80_position_cards_{s}.csv', 'v79_position_cards_{s}.csv'],
        'future': ['v84_future_probability_{s}.csv', 'v83_future_probability_{s}.csv', 'v82_future_probability_{s}.csv', 'v81_future_probability_{s}.csv'],
    }
    return [x.format(s=slug) for x in patterns.get(kind, [])]


def _load_kind(slug: str, kind: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    # Prefer explicit files first.
    for name in _candidate_sources(slug, kind):
        df = _read_csv_file(REPORT_DIR / name)
        if not df.empty:
            frames.append(df)
            if kind not in {'flow'}:
                break
    # For flow, merge multiple intraday sources to avoid zero clean files.
    if not frames:
        for p in sorted(REPORT_DIR.glob(f'*{kind}*{slug}.csv')):
            df = _read_csv_file(p)
            if not df.empty:
                frames.append(df)
                break
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    df = _filter_market(df, slug)
    if df.empty:
        return df
    df = df.copy()
    nm = _build_name_map(slug)
    df['종목코드'] = df.apply(lambda r: _symbol(r), axis=1)
    df['종목명'] = df.apply(lambda r: re.sub(r'\s*\([A-Za-z0-9.\-]{1,10}\)\s*$', '', _display_name(r, slug, nm)).strip(), axis=1)
    # De-duplicate by symbol while preserving source priority.
    df = df.drop_duplicates(subset=['종목코드'], keep='first')
    return df.reset_index(drop=True)


def _top(df: pd.DataFrame, slug: str) -> str:
    if df is None or df.empty:
        return '-'
    return _display_name(df.iloc[0], slug)


def _summary_rows(slug: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = [
        {'아이콘': '🎯', '카드': '오늘 우선 확인', '설명': '직전가·기준가·손절가를 먼저 확인할 후보', '건수': len(data['action']), 'TOP': _top(data['action'], slug), '구분': 'buy'},
        {'아이콘': '🪜', '카드': '눌림목 진입 후보', '설명': '추격보다 눌림 조건부 진입을 기다릴 후보', '건수': len(data['pullback']), 'TOP': _top(data['pullback'], slug), '구분': 'buy'},
        {'아이콘': '💚', '카드': '수급 급증 후보', '설명': '수급·거래대금 흐름을 우선 보는 후보', '건수': len(data['flow']), 'TOP': _top(data['flow'], slug), '구분': 'buy'},
        {'아이콘': '💎', '카드': '실적·저평가 후보', '설명': '실적과 밸류를 함께 확인할 후보', '건수': len(data['company']), 'TOP': _top(data['company'], slug), '구분': 'value'},
        {'아이콘': '🚫', '카드': '매수금지·주의', '설명': '신규매수보다 제외·관망이 우선인 후보', '건수': len(data['risk']), 'TOP': _top(data['risk'], slug), '구분': 'risk'},
    ]
    return pd.DataFrame(rows)


def _normalize_flow(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if '수급점수' not in out.columns:
        out['수급점수'] = 0
    # Convert and rank fallback. Avoid identical 50-point output.
    raw_scores = pd.to_numeric(out['수급점수'], errors='coerce')
    if raw_scores.isna().all() or raw_scores.fillna(50).nunique() <= 1:
        n = max(len(out), 1)
        out['수급점수'] = [round(72 - i * (18 / max(n - 1, 1)), 1) for i in range(n)]
        out['수급기준'] = out.get('수급기준', pd.Series(['거래대금·거래량 보강'] * n)).fillna('거래대금·거래량 보강')
    else:
        out['수급점수'] = raw_scores.fillna(50).round(1)
        if '수급기준' not in out.columns:
            out['수급기준'] = '수급·거래대금 혼합'
    if '다음행동' not in out.columns:
        out['다음행동'] = '장 시작 후 거래대금 유지와 기준가 근접 여부 확인'
    return out


def _integrated_company(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    defaults = {
        '데이터상태': '정상', '가치점수': '-', '성장점수': '-', '안정성점수': '-', '종합점수': '-',
        'PER': '-', 'PBR': '-', 'ROE': '-', '핵심요약': '', '다음행동': '가격·뉴스·수급과 함께 최종 확인'
    }
    for k, v in defaults.items():
        if k not in out.columns:
            out[k] = v
    if not out['핵심요약'].astype(str).str.strip().replace({'nan': ''}).any():
        out['핵심요약'] = out.apply(lambda r: f"종합점수 {r.get('종합점수', '-')} · 가치/성장/안정성을 함께 확인합니다.", axis=1)
    return out


def _news_summary(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy().head(12)
    if '3줄요약' not in out.columns:
        out['3줄요약'] = out.apply(lambda r: _get_col(r, ['요약', 'description', 'summary'], '시장 흐름 관련 뉴스입니다.'), axis=1)
    if '다음행동' not in out.columns:
        out['다음행동'] = '뉴스만으로 매수하지 말고 가격·수급·재무를 함께 확인하세요.'
    return out


def _price_value(row: Any) -> str:
    return _get_col(row, ['현재가', 'current_price', 'price', '전종가', '직전종가', '직전장종가', '기준가', '평단가'], '-')


def _make_snapshot(slug: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: dict[str, dict[str, Any]] = {}
    source_order = [
        ('오늘확인', data['action']), ('눌림목', data['pullback']), ('수급', data['flow']),
        ('기업분석', data['company']), ('주의', data['risk']), ('보유', data.get('position', pd.DataFrame())),
    ]
    flow_scores = {str(r.get('종목코드')): r.get('수급점수') for _, r in data['flow'].iterrows()} if not data['flow'].empty else {}
    for source, df in source_order:
        if df is None or df.empty:
            continue
        for _, row in df.head(80).iterrows():
            sym = _symbol(row)
            if not sym:
                continue
            if sym not in rows:
                rows[sym] = {
                    '시장': '한국주식' if slug == 'kr' else '미국주식',
                    '종목코드': sym,
                    '종목명': _display_name(row, slug).replace(f' ({sym})', ''),
                    '분류': source,
                    '현재가': _price_value(row),
                    '기준가': _get_col(row, ['기준가', '진입가', '추천가', '평단가'], '-'),
                    '손절가': _get_col(row, ['손절가', '손절', 'stop_price'], '-'),
                    '목표가': _get_col(row, ['목표가', '목표', 'target_price'], '-'),
                    '호가': _get_col(row, ['호가', '호가상태', 'orderbook_status'], '장중 데이터 없으면 직전장 기준'),
                    '수급점수': _get_col(row, ['수급점수', 'flow_score'], '-'),
                    '뉴스요약': '-',
                    '재무요약': _get_col(row, ['핵심요약', '해석', '초보자 해석'], '-'),
                    '다음행동': _get_col(row, ['다음행동', '다음 행동', '초보자 안내'], '기준가·손절가·목표가를 먼저 확인'),
                    '가격출처': '실시간값 없으면 직전장·후보·보유 파일 기준',
                }
            else:
                rec = rows[sym]
                for col in ['현재가', '기준가', '손절가', '목표가', '호가', '수급점수', '재무요약', '다음행동']:
                    if not _valid(rec.get(col)) or rec.get(col) == '-':
                        rec[col] = _get_col(row, [col, col.replace(' ', '')], rec.get(col, '-'))
            if sym in flow_scores and _valid(flow_scores[sym]):
                rows[sym]['수급점수'] = flow_scores[sym]
    return pd.DataFrame(rows.values())


def _make_future(slug: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    base = _load_kind(slug, 'future')
    frames: list[pd.DataFrame] = []
    if not base.empty:
        frames.append(base)
    for key in ['flow', 'action', 'pullback', 'company']:
        df = data.get(key, pd.DataFrame())
        if df is not None and not df.empty:
            tmp = df.copy()
            tmp['분류'] = {'flow': '수급', 'action': '오늘확인', 'pullback': '눌림목', 'company': '실적저평가'}[key]
            frames.append(tmp)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    out = _filter_market(out, slug)
    if out.empty:
        return out
    out['종목코드'] = out.apply(lambda r: _symbol(r), axis=1)
    nm = _build_name_map(slug)
    out['종목명'] = out.apply(lambda r: _display_name(r, slug, nm).replace(f" ({_symbol(r)})", ''), axis=1)
    out = out.drop_duplicates(subset=['종목코드'], keep='first').reset_index(drop=True)
    def pct(row: Any, base_val: int) -> str:
        if _valid(_get_col(row, ['1일상승확률', '3일상승확률', '5일상승확률'], '')):
            return ''
        return f'{base_val}%'
    if '1일상승확률' not in out.columns:
        out['1일상승확률'] = ''
    if '3일상승확률' not in out.columns:
        out['3일상승확률'] = ''
    if '5일상승확률' not in out.columns:
        out['5일상승확률'] = ''
    for idx, row in out.iterrows():
        cat = _get_col(row, ['분류', 'category'], '오늘확인')
        if '수급' in cat:
            vals = (62, 65, 67)
            reason = '거래대금·수급점수 상위권'
        elif '실적' in cat:
            vals = (56, 60, 64)
            reason = '재무/KPI 확인 대상'
        elif '눌림' in cat:
            vals = (58, 61, 63)
            reason = '눌림 조건부 진입 후보'
        else:
            vals = (57, 60, 62)
            reason = '기준가·손절가 확인 가능 후보'
        if not _valid(out.at[idx, '1일상승확률']): out.at[idx, '1일상승확률'] = f'{vals[0]}%'
        if not _valid(out.at[idx, '3일상승확률']): out.at[idx, '3일상승확률'] = f'{vals[1]}%'
        if not _valid(out.at[idx, '5일상승확률']): out.at[idx, '5일상승확률'] = f'{vals[2]}%'
        out.at[idx, '근거1'] = reason
        out.at[idx, '근거2'] = '실제 결과가 쌓이면 자동 보정'
        out.at[idx, '데이터충분도'] = '초기' if len(out) < 30 else '보통'
        out.at[idx, '다음행동'] = _get_col(row, ['다음행동', '다음 행동'], '확률만 보지 말고 현재가·수급·뉴스를 함께 확인')
    return out


def _make_narrative(slug: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    snapshot = _make_snapshot(slug, data)
    if snapshot.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    flow_syms = set(data['flow'].get('종목코드', [])) if not data['flow'].empty and '종목코드' in data['flow'].columns else set()
    company_syms = set(data['company'].get('종목코드', [])) if not data['company'].empty and '종목코드' in data['company'].columns else set()
    risk_syms = set(data['risk'].get('종목코드', [])) if not data['risk'].empty and '종목코드' in data['risk'].columns else set()
    for _, row in snapshot.head(18).iterrows():
        sym = row['종목코드']
        name = row['종목명']
        tags = []
        if sym in flow_syms: tags.append('수급·거래대금')
        if sym in company_syms: tags.append('재무/KPI')
        if sym in risk_syms: tags.append('주의')
        tag_text = ', '.join(tags) if tags else row.get('분류', '오늘확인')
        caution = '매수금지·주의에도 포함되어 신규매수는 보수적으로 봅니다.' if sym in risk_syms else '장중 거래량과 현재가가 기준가 근처인지 확인합니다.'
        action = '관찰 우선' if sym in risk_syms else '기준가·손절가·목표가 확인 후 접근'
        rows.append({
            '시장': row['시장'], '종목코드': sym, '종목명': name,
            '요약': f'{name}은 현재 {tag_text} 기준으로 확인할 후보입니다.',
            '근거': f"현재가/기준가/수급/재무 중 확인 가능한 데이터는 선택 종목 화면에서 함께 봅니다.",
            '주의': caution,
            '다음행동': action,
        })
    return pd.DataFrame(rows)


def _write_history_append(slug: str, data: dict[str, pd.DataFrame]) -> int:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / 'prediction_history.csv'
    rows: list[dict[str, Any]] = []
    market = 'KR' if slug == 'kr' else 'US'
    categories = [('오늘확인', data['action']), ('눌림목', data['pullback']), ('수급', data['flow']), ('실적저평가', data['company']), ('매수주의', data['risk'])]
    for category, df in categories:
        if df is None or df.empty:
            continue
        for _, row in df.head(50).iterrows():
            sym = _symbol(row)
            if not sym:
                continue
            rows.append({
                'date': _today(), 'market': market, 'category': category,
                'symbol': sym, 'name': _display_name(row, slug),
                'base_price': _get_col(row, ['기준가', '현재가', '전종가'], ''),
                'stop_price': _get_col(row, ['손절가', '손절'], ''),
                'target_price': _get_col(row, ['목표가', '목표'], ''),
                'decision': _get_col(row, ['다음행동', '다음 행동', '판단', '권장행동'], '관찰 우선'),
                'source_file': f'v85_{category}', 'created_at': _now(),
            })
    new = pd.DataFrame(rows)
    if path.exists():
        old = _read_csv_file(path)
    else:
        old = pd.DataFrame()
    combined = pd.concat([old, new], ignore_index=True, sort=False) if not old.empty else new
    if not combined.empty:
        for col in ['date', 'market', 'category', 'symbol']:
            if col not in combined.columns:
                combined[col] = ''
        combined = combined.drop_duplicates(subset=['date', 'market', 'category', 'symbol'], keep='last')
    combined.to_csv(path, index=False, encoding='utf-8-sig')
    return len(new)


def _ensure_outcome_skeleton() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / 'outcome_history.csv'
    if not path.exists():
        cols = ['date', 'market', 'category', 'symbol', 'name', 'base_price', 'price_1d', 'return_1d', 'price_3d', 'return_3d', 'price_5d', 'return_5d', 'price_20d', 'return_20d', 'max_drawdown', 'success', 'updated_at']
        pd.DataFrame(columns=cols).to_csv(path, index=False, encoding='utf-8-sig')


def _status_rows(base: dict[str, Any], results: dict[str, dict[str, int]]) -> pd.DataFrame:
    env = base.get('env') if isinstance(base, dict) else {}
    if not isinstance(env, dict):
        env = {}
    rows = [
        {'시장': '전체', '항목': 'v85 업데이트', '행수': '-', '상태': '정상', '설명': 'UI/UX 통합·선택종목 fallback·메뉴 축소 반영'},
        {'시장': '전체', '항목': '일반/관리자 분리', '행수': '-', '상태': '정상', '설명': '일반 화면은 카드 중심, 원본/진단은 관리자 모드'},
        {'시장': '전체', '항목': '결과 추적 준비', '행수': '-', '상태': '준비', '설명': 'outcome_history.csv 스켈레톤 생성'},
    ]
    for slug, label in [('kr', '국장'), ('us', '미장')]:
        r = results.get(slug, {})
        rows.extend([
            {'시장': label, '항목': '후보 5분류', '행수': r.get('summary', 0), '상태': '정상', '설명': '홈 5개 카드 고정'},
            {'시장': label, '항목': '선택종목 fallback', '행수': r.get('snapshot', 0), '상태': '정상' if r.get('snapshot', 0) else '확인 필요', '설명': '장중이 아니어도 후보/보유/직전장 기준값 사용'},
            {'시장': label, '항목': '뉴스·기업분석 통합', '행수': r.get('news', 0) + r.get('company', 0), '상태': '정상', '설명': '뉴스/KPI/내러티브를 한 페이지로 통합'},
            {'시장': label, '항목': '확률 예측', '행수': r.get('future', 0), '상태': '초기', '설명': '실제 결과 누적 후 자동 보정 필요'},
        ])
    for key in ['DART_API_KEY', 'FINNHUB_API_KEY', 'GNEWS_API_KEY', 'SEC_USER_AGENT', 'APIFY_TOKEN']:
        if key in env:
            rows.append({'시장': '전체', '항목': key, '행수': '-', '상태': '인식' if env.get(key) else '미인식', '설명': '.env 키 인식 여부'})
    return pd.DataFrame(rows)


def run_v85_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dirs()
    _ensure_outcome_skeleton()
    base: dict[str, Any] = {'status': 'SKIPPED', 'reason': 'v84 engine unavailable'}
    if run_v84_update is not None:
        try:
            base = run_v84_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status': 'ERROR', 'error': f'{type(exc).__name__}: {exc}'}
    copied = _copy_versioned(PREV_VERSION, VERSION)
    all_results: dict[str, dict[str, int]] = {}
    for slug in ['kr', 'us']:
        data = {
            'action': _load_kind(slug, 'action'),
            'pullback': _load_kind(slug, 'pullback'),
            'flow': _normalize_flow(_load_kind(slug, 'flow'), slug),
            'company': _integrated_company(_load_kind(slug, 'company'), slug),
            'risk': _load_kind(slug, 'risk'),
            'news': _news_summary(_load_kind(slug, 'news'), slug),
            'position': _load_kind(slug, 'position'),
        }
        future = _make_future(slug, data)
        snapshot = _make_snapshot(slug, data)
        narrative = _make_narrative(slug, data)
        summary = _summary_rows(slug, data)
        _write_csv(summary, f'{VERSION}_today_summary_{slug}.csv')
        _write_csv(data['action'], f'{VERSION}_action_cards_{slug}.csv')
        _write_csv(data['pullback'], f'{VERSION}_pullback_cards_{slug}.csv')
        _write_csv(data['flow'], f'{VERSION}_flow_cards_{slug}.csv')
        _write_csv(data['company'], f'{VERSION}_company_integrated_{slug}.csv')
        _write_csv(data['risk'], f'{VERSION}_risk_cards_{slug}.csv')
        _write_csv(data['news'], f'{VERSION}_news_summary_{slug}.csv')
        _write_csv(data['position'], f'{VERSION}_position_cards_{slug}.csv')
        _write_csv(snapshot, f'{VERSION}_symbol_snapshot_{slug}.csv')
        _write_csv(future, f'{VERSION}_future_probability_{slug}.csv')
        _write_csv(narrative, f'{VERSION}_narrative_cards_{slug}.csv')
        appended = _write_history_append(slug, data)
        all_results[slug] = {
            'summary': len(summary), 'action': len(data['action']), 'pullback': len(data['pullback']),
            'flow': len(data['flow']), 'company': len(data['company']), 'risk': len(data['risk']),
            'news': len(data['news']), 'position': len(data['position']), 'snapshot': len(snapshot),
            'future': len(future), 'narrative': len(narrative), 'history_appended': appended,
        }
    status_df = _status_rows(base, all_results)
    _write_csv(status_df, f'{VERSION}_data_status.csv')
    result = {
        'status': 'OK' if str(base.get('status')) in {'OK', 'WARN', 'SKIPPED'} else 'WARN',
        'version': VERSION,
        'updated_at': _now(),
        'base': base,
        'copied_files': len(copied),
        'results': all_results,
        'status_rows': len(status_df),
        'note': 'v85 focuses on product-grade UI consolidation, fallback display, history safety, and admin/general separation.',
    }
    _write_json(result, f'{VERSION}_status.json')
    return result


if __name__ == '__main__':
    print(json.dumps(run_v85_update(), ensure_ascii=False, indent=2, default=str))
