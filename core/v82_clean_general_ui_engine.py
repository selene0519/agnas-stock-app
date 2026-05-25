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
    from core.v81_consolidated_ui_engine import (
        run_v81_update,
        _candidate_df,
        _normalize_candidate,
        _summary,
        _read_csv,
        _write_csv,
        _write_json,
        _code_name_map,
        _zcode,
        _clean,
        _first,
        _is_kr_row,
        _is_us_row,
        _is_us_symbol,
        _filter_market,
        KR_CODE_RE,
        REPORT_DIR,
        DATA_DIR,
        HISTORY_DIR,
    )
except Exception:  # pragma: no cover
    run_v81_update = None
    REPORT_DIR = Path('reports')
    DATA_DIR = Path('data')
    HISTORY_DIR = DATA_DIR / 'history'
    KR_CODE_RE = re.compile(r'^\d{5,6}$')

    def _clean(v: Any) -> str:
        return '' if v is None else str(v).strip()

    def _zcode(v: Any) -> str:
        s = _clean(v)
        return s.zfill(6) if re.fullmatch(r'\d{1,6}', s) else s

    def _read_csv(path: str | Path) -> pd.DataFrame:
        p = Path(path)
        if not p.is_absolute() and not p.exists():
            p = REPORT_DIR / p
        if not p.exists():
            return pd.DataFrame()
        return pd.read_csv(p, dtype=str, encoding='utf-8-sig').fillna('')

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
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _to_num(v: Any) -> float:
    s = _clean(v).replace('%', '').replace('$', '').replace('원', '').replace(',', '').strip()
    try:
        return float(s)
    except Exception:
        return float('nan')


def _valid(v: Any) -> bool:
    s = _clean(v)
    return bool(s and s.lower() not in {'nan', 'none', 'null', '-', '직전장 기준 확인 필요', '확인 필요'})


def _name_for(slug: str, code: str, raw_name: str = '') -> str:
    raw_name = _clean(raw_name)
    name_map = _code_name_map()
    if slug == 'kr':
        z = _zcode(code)
        if raw_name and raw_name != z and not re.fullmatch(r'\d{5,6}', raw_name):
            return raw_name
        return name_map.get(z, raw_name or z)
    if raw_name and raw_name.upper() != _clean(code).upper() and '(' not in raw_name:
        return raw_name
    return raw_name or _clean(code).upper()


def _format_price(v: Any, market: str) -> str:
    s = _clean(v)
    if not s:
        return ''
    if any(x in s for x in ['원', '$', '직전장']):
        return s
    x = _to_num(s)
    if math.isnan(x):
        return s
    if market == 'kr':
        return f'{x:,.0f}원'
    return f'${x:,.2f}'


def _read_candidates(slug: str, kind: str) -> pd.DataFrame:
    try:
        return _normalize_candidate(_candidate_df(slug, kind), slug, kind)
    except Exception:
        return pd.DataFrame()


def _raw_market_sources(slug: str) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    patterns = ['*flow*.csv', '*realtime*.csv', '*orderbook*.csv', '*position*.csv', '*company*.csv', '*kpi*.csv']
    files: list[Path] = []
    for pat in patterns:
        files.extend(REPORT_DIR.glob(pat))
    seen: set[Path] = set()
    for p in files:
        if p in seen or not p.exists() or p.stat().st_size == 0:
            continue
        seen.add(p)
        try:
            df = _read_csv(p)
            if df.empty:
                continue
            df['_source_file'] = p.name
            try:
                if slug == 'kr':
                    df = df[df.apply(_is_kr_row, axis=1)]
                else:
                    df = df[df.apply(_is_us_row, axis=1)]
            except Exception:
                pass
            if not df.empty:
                parts.append(df)
        except Exception:
            continue
    return pd.concat(parts, ignore_index=True).fillna('') if parts else pd.DataFrame()


def _code_from_row(row: pd.Series, slug: str) -> str:
    code = _first(row, ['종목코드', 'symbol', 'ticker', '티커', '코드', '종목'])
    if slug == 'kr':
        return _zcode(code)
    raw = _clean(code)
    m = re.search(r'\(([A-Z]{1,6})\)', raw)
    return (m.group(1) if m else raw).upper()


def _build_symbol_snapshot(slug: str) -> pd.DataFrame:
    normalized_parts = [_read_candidates(slug, k) for k in ['action', 'pullback', 'flow', 'company', 'risk', 'position']]
    raw = _raw_market_sources(slug)
    parts = [p for p in normalized_parts if not p.empty]
    if not raw.empty:
        parts.append(raw)
    if not parts:
        return pd.DataFrame()
    all_df = pd.concat(parts, ignore_index=True).fillna('')
    # 코드 보강
    all_df['_code'] = all_df.apply(lambda r: _code_from_row(r, slug), axis=1)
    if slug == 'kr':
        all_df = all_df[all_df['_code'].astype(str).str.match(r'^\d{6}$', na=False)]
    else:
        all_df = all_df[all_df['_code'].astype(str).str.match(r'^[A-Z]{1,6}([.-][A-Z]{1,3})?$', na=False)]
    rows = []
    seen: set[str] = set()
    for _, r in all_df.iterrows():
        code = _clean(r.get('_code'))
        if not code or code in seen:
            continue
        seen.add(code)
        sub = all_df[all_df['_code'].astype(str).eq(code)]

        def pick(cols: list[str]) -> str:
            for _, rr in sub.iterrows():
                for c in cols:
                    if c in rr.index and _valid(rr.get(c)):
                        return _clean(rr.get(c))
            return ''

        raw_name = pick(['종목명', 'name', '종목', '회사명', 'corp_name', 'stock_name'])
        name = _name_for(slug, code, raw_name)
        current = pick(['현재가', '현재가/직전종가', 'price', 'current_price', 'last', 'close', '직전종가', '종가'])
        base = pick(['기준가', '진입', '진입가', 'base_price', 'entry_price', '전일종가', '직전종가'])
        if not current and base:
            current = base
        stop = pick(['손절가', '손절', 'stop_price'])
        target = pick(['목표가', '목표', 'target_price'])
        flow_score = pick(['수급점수', 'flow_score', '점수', 'score', '종합점수'])
        bid = pick(['매수호가', 'bid', 'bid_price'])
        ask = pick(['매도호가', 'ask', 'ask_price'])
        quote = pick(['호가', '호가상태', 'orderbook'])
        if not quote and (bid or ask):
            quote = f"매수 {bid or '-'} / 매도 {ask or '-'}"
        elif not quote:
            quote = '직전장 기준 확인'
        rows.append({
            '시장': '한국주식' if slug == 'kr' else '미국주식',
            '종목코드': code,
            '종목명': name,
            '현재가': _format_price(current, slug) or '직전장 기준 확인 필요',
            '기준가': _format_price(base, slug) or '-',
            '손절가': _format_price(stop, slug) or '-',
            '목표가': _format_price(target, slug) or '-',
            '호가': quote,
            '수급점수': flow_score or '-',
            '다음행동': '장중이 아니면 직전장 기준가·거래대금·수급점수만 참고',
        })
    return pd.DataFrame(rows)


def _future(slug: str) -> pd.DataFrame:
    hist = _read_csv(HISTORY_DIR / 'prediction_history.csv')
    if hist.empty:
        hist = _candidate_df(slug, 'future')
    if hist.empty:
        return pd.DataFrame()
    if 'market' in hist.columns:
        if slug == 'kr':
            hist = hist[hist['market'].astype(str).isin(['KR', '한국주식', '국장'])]
        else:
            hist = hist[hist['market'].astype(str).isin(['US', '미국주식', '미장'])]
    if hist.empty:
        return pd.DataFrame()
    name_map = _code_name_map()
    rows = []
    seen: set[str] = set()
    for _, r in hist.iterrows():
        code = _code_from_row(r, slug)
        if slug == 'kr':
            code = _zcode(code)
            if not KR_CODE_RE.fullmatch(code):
                continue
            raw_name = _first(r, ['name', '종목명', '종목'])
            name = raw_name if raw_name and raw_name != code and not re.fullmatch(r'\d{5,6}', raw_name) else name_map.get(code, code)
        else:
            if not _is_us_symbol(code):
                continue
            raw_name = _first(r, ['name', '종목명', '종목'])
            name = raw_name if raw_name and raw_name.upper() != code and '(' not in raw_name else code
        key = (code, _first(r, ['category', '분류']) or '')
        # 같은 종목은 한 번만: 사용자는 종목별 확률을 보고 싶어 함
        if code in seen:
            continue
        seen.add(code)
        cat = _first(r, ['category', '분류']) or '오늘확인'
        base = 56
        if '수급' in cat:
            base = 62
        elif '실적' in cat or '저평가' in cat:
            base = 60
        elif '주의' in cat or '위험' in cat:
            base = 48
        rows.append({
            '시장': '한국주식' if slug == 'kr' else '미국주식',
            '종목코드': code,
            '종목명': name,
            '분류': cat,
            '1일상승확률': f'{base}%',
            '3일상승확률': f'{min(base+3, 80)}%',
            '5일상승확률': f'{min(base+5, 82)}%',
            '다음행동': '초기 추정치입니다. 실제 결과 누적 후 자동 보정',
        })
        if len(rows) >= 18:
            break
    return pd.DataFrame(rows)


def _integrated_company(slug: str) -> pd.DataFrame:
    parts = []
    for fn in [f'v80_kpi_cards_{slug}.csv', f'v80_company_cards_{slug}.csv', f'v80_advanced_valuation_{slug}.csv', f'v80_financial_statement_{slug}.csv']:
        df = _read_csv(fn)
        if not df.empty:
            try:
                df = _filter_market(df, slug)
            except Exception:
                pass
            if not df.empty:
                parts.append(df)
    if not parts:
        return pd.DataFrame()
    all_df = pd.concat(parts, ignore_index=True).fillna('')
    all_df['_code'] = all_df.apply(lambda r: _code_from_row(r, slug), axis=1)
    name_map = _code_name_map()
    rows = []
    seen = set()
    for _, r in all_df.iterrows():
        code = _clean(r.get('_code'))
        if not code or code in seen:
            continue
        seen.add(code)
        sub = all_df[all_df['_code'].astype(str).eq(code)]

        def pick(cols: list[str]) -> str:
            for _, rr in sub.iterrows():
                for c in cols:
                    if c in rr.index and _valid(rr.get(c)):
                        return _clean(rr.get(c))
            return ''

        raw_name = pick(['종목명', 'name', '종목', '회사명'])
        name = _name_for(slug, code, raw_name)
        rows.append({
            '시장': '한국주식' if slug == 'kr' else '미국주식',
            '종목코드': code,
            '종목명': name,
            '데이터상태': pick(['데이터상태', '재무상태']) or '확인 필요',
            '종합점수': pick(['종합점수', '점수']) or '-',
            '가치점수': pick(['가치점수']) or '-',
            '성장점수': pick(['성장점수']) or '-',
            '안정성점수': pick(['안정성점수', '안정점수']) or '-',
            'PER': pick(['PER', 'PER표시']) or '-',
            'PBR': pick(['PBR', 'PBR표시']) or '-',
            'ROE': pick(['ROE', 'ROE표시']) or '-',
            '매출': pick(['매출', '매출액']) or '-',
            '영업이익': pick(['영업이익']) or '-',
            '순이익': pick(['순이익']) or '-',
            '핵심요약': pick(['핵심요약', '해석', '초보자 해석']) or '재무·KPI·밸류를 함께 보는 통합 카드입니다.',
            '다음행동': pick(['다음행동', '다음 행동']) or '가격·뉴스·수급과 함께 최종 확인',
        })
    return pd.DataFrame(rows)


def _narrative(slug: str) -> pd.DataFrame:
    order = [('action', '오늘 확인'), ('flow', '수급'), ('company', '실적·저평가'), ('risk', '주의')]
    rows = []
    seen = set()
    for kind, label in order:
        df = _read_candidates(slug, kind)
        if df.empty:
            continue
        for _, r in df.head(8).iterrows():
            code = _clean(r.get('종목코드'))
            if not code or code in seen:
                continue
            seen.add(code)
            name = _clean(r.get('종목명')) or code
            if kind == 'risk':
                summary = f'{name}은 현재 신규매수보다 관망·제외를 먼저 검토할 후보입니다.'
                point = '기준가, 손절가, 뉴스 리스크를 다시 확인하세요.'
                action = '신규매수 보류 또는 비중 축소 검토'
            elif kind == 'flow':
                score = _clean(r.get('수급점수')) or _clean(r.get('점수')) or '-'
                summary = f'{name}은 거래대금·수급 흐름이 포착된 후보입니다.'
                point = f'수급점수 {score}. 장 시작 후 거래대금 지속 여부를 봅니다.'
                action = '추격매수보다 기준가 근처에서만 검토'
            elif kind == 'company':
                summary = f'{name}은 재무·KPI 기준으로 추가 확인할 후보입니다.'
                point = 'PER/PBR/ROE와 성장성·안정성 점수를 같이 확인하세요.'
                action = '단기 매매보다 가격 위치와 실적 근거를 함께 확인'
            else:
                summary = f'{name}은 오늘 우선 확인 후보입니다.'
                point = '현재가가 기준가에 가까운지, 손절가가 명확한지 확인합니다.'
                action = '기준가·손절가·목표가 확인 후 접근'
            rows.append({
                '시장': '한국주식' if slug == 'kr' else '미국주식',
                '종목코드': code,
                '종목명': name,
                '분류': label,
                '요약': summary,
                '확인포인트': point,
                '다음행동': action,
            })
            if len(rows) >= 12:
                return pd.DataFrame(rows)
    return pd.DataFrame(rows)


def _copy_base(slug: str) -> None:
    pairs = [
        ('news_summary', 'news_summary'), ('flow_clean', 'flow_clean'), ('position_cards', 'position_cards'),
        ('tech_patent', 'tech_patent'), ('macro_analysis', 'macro_analysis'), ('data_status', 'data_status'),
    ]
    for src_suffix, dst_suffix in pairs:
        for version in ['v81', 'v80', 'v79']:
            src = REPORT_DIR / f'{version}_{src_suffix}_{slug}.csv'
            if src.exists() and src.stat().st_size > 0:
                dst = REPORT_DIR / f'v82_{dst_suffix}_{slug}.csv'
                shutil.copyfile(src, dst)
                break


def run_v82_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dirs()
    base = {'status': 'SKIPPED'}
    if run_v81_update is not None:
        try:
            base = run_v81_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status': 'WARN', 'error': f'{type(exc).__name__}: {exc}'}
    result: dict[str, Any] = {'status': 'OK', 'version': 'v82', 'updated_at': _now(), 'base': base}
    status_rows = []
    for slug in ['kr', 'us']:
        action = _read_candidates(slug, 'action')
        pull = _read_candidates(slug, 'pullback')
        flow = _read_candidates(slug, 'flow')
        company = _integrated_company(slug)
        if company.empty:
            company = _read_candidates(slug, 'company')
        risk = _read_candidates(slug, 'risk')
        _write_csv(action, f'v82_action_cards_{slug}.csv')
        _write_csv(pull, f'v82_pullback_cards_{slug}.csv')
        _write_csv(flow, f'v82_flow_cards_{slug}.csv')
        _write_csv(company, f'v82_company_integrated_{slug}.csv')
        _write_csv(risk, f'v82_risk_cards_{slug}.csv')
        summ = _summary(slug, action, pull, flow, company, risk)
        _write_csv(summ, f'v82_today_summary_{slug}.csv')
        snapshot = _build_symbol_snapshot(slug)
        _write_csv(snapshot, f'v82_symbol_snapshot_{slug}.csv')
        fut = _future(slug)
        _write_csv(fut, f'v82_future_probability_{slug}.csv')
        narr = _narrative(slug)
        _write_csv(narr, f'v82_narrative_cards_{slug}.csv')
        _copy_base(slug)
        label = '국장' if slug == 'kr' else '미장'
        status_rows.extend([
            {'시장': label, '항목': '첫 화면 카드', '행수': len(summ), '상태': '정상' if len(summ) == 5 else '확인 필요', '설명': '일반 화면 5개 카드 고정'},
            {'시장': label, '항목': '선택종목 값', '행수': len(snapshot), '상태': '정상' if len(snapshot) else '확인 필요', '설명': '장중이 아니면 직전장/후보/수급 파일로 보강'},
            {'시장': label, '항목': '기업분석 통합', '행수': len(company), '상태': '정상' if len(company) else '확인 필요', '설명': '기업분석·가치평가·KPI를 한 화면에 통합'},
            {'시장': label, '항목': '미래확률 종목명', '행수': len(fut), '상태': '정상' if len(fut) else '확인 필요', '설명': '종목코드만 보이지 않도록 종목명 보강'},
            {'시장': label, '항목': '종목 내러티브', '행수': len(narr), '상태': '정상' if len(narr) else '확인 필요', '설명': '뉴스/재무/수급 설명 대신 짧은 행동 중심 문장'},
        ])
        result[slug] = {'summary': len(summ), 'action': len(action), 'pullback': len(pull), 'flow': len(flow), 'company': len(company), 'risk': len(risk), 'snapshot': len(snapshot), 'future': len(fut), 'narrative': len(narr)}
    status = pd.DataFrame(status_rows)
    _write_csv(status, 'v82_data_status.csv')
    _write_json(result, 'v82_status.json')
    return result


if __name__ == '__main__':
    print(json.dumps(run_v82_update(), ensure_ascii=False, indent=2, default=str))
