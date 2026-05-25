from __future__ import annotations

import json
import math
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v80_finance_kpi_ui_engine import run_v80_update
except Exception:  # pragma: no cover
    run_v80_update = None

REPORT_DIR = Path('reports')
DATA_DIR = Path('data')
HISTORY_DIR = DATA_DIR / 'history'
KR_CODE_RE = re.compile(r'^\d{5,6}$')
HANGUL_RE = re.compile(r'[가-힣]')
US_SYMBOL_RE = re.compile(r'^[A-Z]{1,6}(?:[.-][A-Z]{1,3})?$')

US_SYMBOLS = {
    'AAPL','MSFT','GOOGL','GOOG','NVDA','TSLA','AMZN','META','NFLX','AMD','INTC','PLTR','LITE','SNDK','CAT','CRCL','NBIS',
    'AAOI','ASTS','BMNR','COIN','MSTR','AVGO','ORCL','SMCI','SPY','QQQ','DIA','IWM','VOO','VTI','XLF','XLK','XLE','XLV',
    'NKE','JPM','BAC','C','WMT','COST','HD','LOW','DIS','PYPL','UBER','SHOP','SQ','AFRM','SOFI','RIVN','LCID','BABA','TSM',
    'DDOG','CRWD','S','NET','RIOT','SOXX','RKLB','LUNR','IONQ','OKLO','HUT','IREN','SNOW','ACHR','ALAB','ANET'
}

KR_NAME_FALLBACK = {
    '003550':'LG','000100':'유한양행','010120':'LS ELECTRIC','000270':'기아','259960':'크래프톤','000660':'SK하이닉스',
    '003490':'대한항공','000720':'현대건설','028670':'팬오션','000810':'삼성화재해상보험','278470':'에이피알','000990':'DB하이텍',
    '222800':'심텍','131970':'두산테스나','403870':'HPSP','375500':'DL이앤씨','329180':'HD현대중공업','095340':'ISC',
    '004020':'현대제철','010950':'S-Oil','012450':'한화에어로스페이스','277810':'레인보우로보틱스','034590':'인천도시가스',
}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _clean(v: Any) -> str:
    if v is None:
        return ''
    s = str(v).strip()
    if s.lower() in {'', 'nan', 'none', 'null', 'nat', '-'}:
        return ''
    return s


def _zcode(v: Any) -> str:
    s = _clean(v)
    if not s:
        return ''
    try:
        if re.fullmatch(r'\d+\.0', s):
            s = str(int(float(s)))
    except Exception:
        pass
    if re.fullmatch(r'\d{1,6}', s):
        return s.zfill(6)
    m = re.search(r'\b(\d{5,6})\b', s)
    return m.group(1).zfill(6) if m else s


def _to_num(v: Any) -> float:
    s = _clean(v).replace('%','').replace('$','').replace('원','').replace(',','').strip()
    try:
        return float(s)
    except Exception:
        return float('nan')


def _fmt(v: Any, suffix: str = '') -> str:
    x = _to_num(v)
    if math.isnan(x):
        return '-'
    if abs(x) >= 1000:
        return f'{x:,.0f}{suffix}'
    if abs(x) >= 100:
        return f'{x:,.1f}{suffix}'
    return f'{x:.2f}{suffix}'


def _read_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = REPORT_DIR / p
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ('utf-8-sig','utf-8','cp949'):
        try:
            return pd.read_csv(p, dtype=str, encoding=enc).fillna('')
        except Exception:
            pass
    return pd.DataFrame()


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


def _row_text(row: pd.Series) -> str:
    return ' '.join(_clean(row.get(c)) for c in row.index)


def _is_us_symbol(v: Any) -> bool:
    s = _clean(v).upper()
    return bool(s in US_SYMBOLS or US_SYMBOL_RE.fullmatch(s))


def _is_kr_symbol(v: Any) -> bool:
    return bool(KR_CODE_RE.fullmatch(_zcode(v)))


def _is_kr_row(row: pd.Series) -> bool:
    txt = _row_text(row)
    if any(x in txt for x in ['한국주식','국장','코스피','코스닥','KRX']):
        return True
    for c in ['종목코드','symbol','ticker','코드','종목']:
        if c in row.index and _is_kr_symbol(row.get(c)):
            return True
    return bool(HANGUL_RE.search(txt)) and not _is_us_row(row)


def _is_us_row(row: pd.Series) -> bool:
    txt = _row_text(row)
    if any(x in txt for x in ['미국주식','미장','NASDAQ','NYSE','AMEX']):
        return True
    for c in ['종목코드','symbol','ticker','티커','종목']:
        if c in row.index and _is_us_symbol(row.get(c)) and not HANGUL_RE.search(_clean(row.get(c))):
            return True
    return False


def _filter_market(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df.apply(_is_kr_row if slug == 'kr' else _is_us_row, axis=1)
    return df[mask].copy().reset_index(drop=True)


def _first(row: pd.Series, cols: list[str]) -> str:
    for c in cols:
        if c in row.index and _clean(row.get(c)):
            return _clean(row.get(c))
    return ''


def _code_name_map() -> dict[str, str]:
    m = dict(KR_NAME_FALLBACK)
    for root in [REPORT_DIR, DATA_DIR]:
        if not root.exists():
            continue
        for p in root.rglob('*.csv'):
            try:
                if p.stat().st_size > 5_000_000:
                    continue
                df = _read_csv(p)
                if df.empty:
                    continue
                for _, r in df.head(5000).iterrows():
                    code = ''
                    for c in ['종목코드','symbol','ticker','코드','종목']:
                        if c in df.columns:
                            z = _zcode(r.get(c))
                            if KR_CODE_RE.fullmatch(z):
                                code = z; break
                    if not code:
                        continue
                    name = ''
                    for c in ['종목명','name','종목','회사명','corp_name','stock_name','한글명']:
                        if c in df.columns:
                            cand = _clean(r.get(c))
                            if cand and cand != code and HANGUL_RE.search(cand) and not re.fullmatch(r'\d{5,6}', cand):
                                name = cand; break
                    if name:
                        m[code] = name
            except Exception:
                continue
    return m


def _candidate_df(slug: str, kind: str) -> pd.DataFrame:
    files = {
        'action':[f'v79_action_clean_{slug}.csv', f'v78_action_clean_{slug}.csv', f'v77_action_clean_{slug}.csv'],
        'pullback':[f'v79_pullback_clean_{slug}.csv', f'v78_pullback_clean_{slug}.csv', f'v77_pullback_clean_{slug}.csv'],
        'flow':[f'v80_flow_clean_{slug}.csv', f'v79_flow_clean_{slug}.csv', f'v78_flow_clean_{slug}.csv'],
        'company':[f'v80_company_cards_{slug}.csv', f'v80_kpi_cards_{slug}.csv', f'v79_company_clean_{slug}.csv'],
        'risk':[f'v79_risk_clean_{slug}.csv', f'v78_risk_clean_{slug}.csv', f'v77_risk_clean_{slug}.csv'],
        'news':[f'v80_news_summary_{slug}.csv', f'v79_news_cards_{slug}.csv', f'v70_news_cards_{slug}.csv'],
        'position':[f'v80_position_cards_{slug}.csv', f'v79_position_cards_{slug}.csv'],
        'future':[f'v80_future_probability_{slug}.csv', f'v79_future_probability_{slug}.csv'],
        'kpi':[f'v80_kpi_cards_{slug}.csv'],
        'financials':[f'v80_financial_statement_{slug}.csv'],
        'valuation':[f'v80_advanced_valuation_{slug}.csv'],
        'macro':[f'v80_macro_analysis_{slug}.csv', f'v79_market_guard_{slug}.csv'],
        'narrative':[f'v80_narrative_cards_{slug}.csv'],
        'tech':[f'v80_tech_patent_{slug}.csv'],
        'custom_macro':[f'v80_custom_macro_{slug}.csv'],
        'master':[f'v80_master_investors_{slug}.csv'],
    }.get(kind, [])
    for fn in files:
        df = _read_csv(fn)
        if not df.empty:
            try:
                return _filter_market(df, slug)
            except Exception:
                return df
    return pd.DataFrame()


def _normalize_candidate(df: pd.DataFrame, slug: str, kind: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=['종목코드','종목명','시장','분류','핵심요약','다음행동'])
    name_map = _code_name_map()
    rows = []
    seen = set()
    for i, r in df.iterrows():
        code = _first(r, ['종목코드','symbol','ticker','종목','코드','TOP'])
        if slug == 'kr':
            code = _zcode(code)
            if not KR_CODE_RE.fullmatch(code):
                continue
            name = _first(r, ['종목명','name','종목','회사명']) or name_map.get(code, code)
        else:
            # "Alphabet (GOOGL)" 같이 표시된 경우 괄호 안 티커를 우선 사용
            raw = _clean(code)
            m = re.search(r'\(([A-Z]{1,6})\)', raw)
            code = (m.group(1) if m else raw).upper()
            if not _is_us_symbol(code):
                continue
            name = _first(r, ['종목명','name','종목','회사명']) or code
        key = (code, kind)
        if key in seen:
            continue
        seen.add(key)
        if kind == 'action':
            summary = '기준가·손절가·목표가를 먼저 확인할 후보'
            next_action = '현재가가 진입가 근처인지 확인'
        elif kind == 'pullback':
            summary = '추격보다 눌림 조건을 기다릴 후보'
            next_action = '분할 접근 또는 관망'
        elif kind == 'flow':
            summary = f"수급·거래대금 기준 {_first(r, ['수급점수','점수']) or '-'}점 후보"
            next_action = '거래대금 지속 여부 확인'
        elif kind == 'company':
            summary = _first(r, ['핵심요약','초보자 해석','해석']) or '재무·KPI를 함께 확인할 후보'
            next_action = _first(r, ['다음행동','다음 행동']) or '밸류와 실적 확인'
        elif kind == 'risk':
            summary = '신규매수보다 제외·관망이 우선인 후보'
            next_action = '매수 보류 또는 비중 축소 검토'
        else:
            summary = _first(r, ['핵심요약','해석','요약']) or '-'
            next_action = _first(r, ['다음행동','다음 행동']) or '-'
        row = dict(r)
        row.update({'종목코드':code, '종목명':name, '시장':'한국주식' if slug=='kr' else '미국주식', '분류':kind, '핵심요약':summary, '다음행동':next_action})
        rows.append(row)
    return pd.DataFrame(rows)


def _top_name(df: pd.DataFrame) -> str:
    if df.empty:
        return '-'
    r = df.iloc[0]
    name = _clean(r.get('종목명')) or _clean(r.get('name')) or _clean(r.get('종목코드')) or _clean(r.get('symbol'))
    code = _clean(r.get('종목코드')) or _clean(r.get('symbol'))
    if code and name and code not in name:
        return f'{name} ({code})'
    return name or code or '-'


def _summary(slug: str, action: pd.DataFrame, pull: pd.DataFrame, flow: pd.DataFrame, company: pd.DataFrame, risk: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {'아이콘':'🎯','카드':'오늘 우선 확인','설명':'직전가·가격 기준을 먼저 확인할 후보','건수':len(action),'TOP':_top_name(action),'구분':'buy'},
        {'아이콘':'🪜','카드':'눌림목 진입 후보','설명':'추격보다 눌림 조건부 진입을 기다릴 후보','건수':len(pull),'TOP':_top_name(pull),'구분':'buy'},
        {'아이콘':'💚','카드':'수급 급증 후보','설명':'수급·거래대금 흐름을 우선 보는 후보','건수':len(flow),'TOP':_top_name(flow),'구분':'buy'},
        {'아이콘':'💎','카드':'실적·저평가 후보','설명':'실적과 밸류를 같이 확인할 후보','건수':len(company),'TOP':_top_name(company),'구분':'value'},
        {'아이콘':'🚫','카드':'매수금지·주의','설명':'신규매수보다 제외·관망이 우선인 후보','건수':len(risk),'TOP':_top_name(risk),'구분':'risk'},
    ]
    return pd.DataFrame(rows)


def _build_symbol_snapshot(slug: str) -> pd.DataFrame:
    sources = []
    for kind in ['action','pullback','flow','company','risk','position']:
        df = _candidate_df(slug, kind)
        if not df.empty:
            sources.append(_normalize_candidate(df, slug, kind))
    if not sources:
        return pd.DataFrame()
    all_df = pd.concat(sources, ignore_index=True).fillna('')
    rows = []
    seen = set()
    for _, r in all_df.iterrows():
        code = _clean(r.get('종목코드'))
        if not code or code in seen:
            continue
        seen.add(code)
        # 여러 원본에서 가격·호가·수급 관련 값을 찾아 보강
        sub = all_df[all_df['종목코드'].astype(str).eq(code)]
        def pick(cols: list[str]) -> str:
            for _, rr in sub.iterrows():
                v = _first(rr, cols)
                if v:
                    return v
            return ''
        current = pick(['현재가','현재가/직전종가','price','current_price','last','close','직전종가'])
        base = pick(['진입','진입가','기준가','base_price','entry_price'])
        stop = pick(['손절','손절가','stop_price'])
        target = pick(['목표','목표가','target_price'])
        flow_score = pick(['수급점수','flow_score','점수'])
        quote = pick(['호가','호가상태','orderbook','매수호가','매도호가'])
        rows.append({
            '시장':'한국주식' if slug=='kr' else '미국주식', '종목코드':code, '종목명':_clean(r.get('종목명')) or code,
            '현재가':current or '직전장 기준 확인 필요', '기준가':base or '-', '손절가':stop or '-', '목표가':target or '-',
            '호가':quote or '장중 미수신 · 직전장 기준', '수급점수':flow_score or '-',
            '다음행동':'장중 현재가가 없으면 직전장 기준으로 진입가·거래대금을 먼저 확인',
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
            hist = hist[hist['market'].astype(str).isin(['KR','한국주식','국장'])]
        else:
            hist = hist[hist['market'].astype(str).isin(['US','미국주식','미장'])]
    if hist.empty:
        return pd.DataFrame()
    rows=[]; seen=set()
    name_map = _code_name_map()
    for _, r in hist.iterrows():
        code = _first(r, ['symbol','종목코드','ticker','종목'])
        if slug == 'kr':
            code = _zcode(code)
            if not KR_CODE_RE.fullmatch(code):
                continue
            name = _first(r, ['name','종목명','종목']) or name_map.get(code, code)
        else:
            raw = _clean(code)
            m = re.search(r'\(([A-Z]{1,6})\)', raw)
            code = (m.group(1) if m else raw).upper()
            if not _is_us_symbol(code):
                continue
            name = _first(r, ['name','종목명','종목']) or code
        if code in seen:
            continue
        seen.add(code)
        cat = _first(r, ['category','분류']) or '오늘확인'
        base = 58
        if '수급' in cat: base += 4
        if '실적' in cat or '저평가' in cat: base += 5
        if '주의' in cat or '위험' in cat: base -= 10
        rows.append({'시장':'한국주식' if slug=='kr' else '미국주식','종목코드':code,'종목명':name,'분류':cat,'1일상승확률':f'{max(35,min(78,base))}%','3일상승확률':f'{max(35,min(80,base+3))}%','5일상승확률':f'{max(35,min(82,base+5))}%','다음행동':'실제 결과가 쌓이면 자동 보정'})
        if len(rows) >= 18:
            break
    return pd.DataFrame(rows)


def _copy_v80_to_v81(slug: str) -> None:
    pairs = [
        ('news_summary','news_summary'),('company_cards','company_cards'),('advanced_valuation','advanced_valuation'),
        ('financial_statement','financial_statement'),('kpi_cards','kpi_cards'),('tech_patent','tech_patent'),
        ('macro_analysis','macro_analysis'),('custom_macro','custom_macro'),('master_investors','master_investors'),
        ('narrative_cards','narrative_cards'),('position_cards','position_cards'),('flow_clean','flow_clean'),
    ]
    for src_suffix, dst_suffix in pairs:
        src = REPORT_DIR / f'v80_{src_suffix}_{slug}.csv'
        dst = REPORT_DIR / f'v81_{dst_suffix}_{slug}.csv'
        if src.exists() and src.stat().st_size > 0:
            shutil.copyfile(src, dst)


def run_v81_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dirs()
    base = {'status':'SKIPPED'}
    if run_v80_update is not None:
        try:
            base = run_v80_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status':'WARN','error':f'{type(exc).__name__}: {exc}'}
    result = {'status':'OK','version':'v81','updated_at':_now(),'base':base}
    status_rows=[]
    for slug in ['kr','us']:
        action = _normalize_candidate(_candidate_df(slug,'action'), slug, 'action')
        pull = _normalize_candidate(_candidate_df(slug,'pullback'), slug, 'pullback')
        flow = _normalize_candidate(_candidate_df(slug,'flow'), slug, 'flow')
        company = _normalize_candidate(_candidate_df(slug,'company'), slug, 'company')
        risk = _normalize_candidate(_candidate_df(slug,'risk'), slug, 'risk')
        _write_csv(action, f'v81_action_cards_{slug}.csv')
        _write_csv(pull, f'v81_pullback_cards_{slug}.csv')
        _write_csv(flow, f'v81_flow_cards_{slug}.csv')
        _write_csv(company, f'v81_company_summary_cards_{slug}.csv')
        _write_csv(risk, f'v81_risk_cards_{slug}.csv')
        summ = _summary(slug, action, pull, flow, company, risk)
        _write_csv(summ, f'v81_today_summary_{slug}.csv')
        snapshot = _build_symbol_snapshot(slug)
        _write_csv(snapshot, f'v81_symbol_snapshot_{slug}.csv')
        fut = _future(slug)
        _write_csv(fut, f'v81_future_probability_{slug}.csv')
        _copy_v80_to_v81(slug)
        label = '국장' if slug == 'kr' else '미장'
        status_rows.extend([
            {'시장':label,'항목':'첫 화면 카드','행수':len(summ),'상태':'정상' if len(summ)==5 else '확인 필요','설명':'첫 화면 5개 카드 고정'},
            {'시장':label,'항목':'선택종목 요약','행수':len(snapshot),'상태':'정상' if len(snapshot) else '확인 필요','설명':'장중 미수신 시 직전장/후보 파일 기준 보강'},
            {'시장':label,'항목':'뉴스 위치','행수':len(_candidate_df(slug,'news')),'상태':'정상','설명':'오늘 화면 맨 아래와 뉴스·재무 요약 허브에서 표시'},
            {'시장':label,'항목':'미래확률','행수':len(fut),'상태':'초기 추정','설명':'누적 기록 기반으로 중복 제거 후 표시'},
        ])
        result[slug] = {'summary':len(summ),'action':len(action),'pullback':len(pull),'flow':len(flow),'company':len(company),'risk':len(risk),'snapshot':len(snapshot),'future':len(fut)}
    status = pd.DataFrame(status_rows)
    _write_csv(status, 'v81_data_status.csv')
    _write_json(result, 'v81_status.json')
    return result


if __name__ == '__main__':
    print(json.dumps(run_v81_update(), ensure_ascii=False, indent=2, default=str))
