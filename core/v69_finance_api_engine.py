
from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests

from core.v68_news_finance_market_engine import (
    _load_dotenv_soft, _env, _read_csv, _write_csv, _write_json, _market_slug, _market_name,
    _clean, _fmt, _symbol_from_text, _build_news_cards, _build_macro_cards, _build_narrative,
    _candidate_base, _basic_kr_interpretation, _simple_title_ko, _request_json,
)

ROOT = Path('.').resolve()
REPORT_DIR = ROOT / 'reports'
DATA_DIR = ROOT / 'data'
FUND_DIR = DATA_DIR / 'fundamental'
NEWS_DIR = DATA_DIR / 'news'
REPORT_DIR.mkdir(parents=True, exist_ok=True)
FUND_DIR.mkdir(parents=True, exist_ok=True)
NEWS_DIR.mkdir(parents=True, exist_ok=True)

NONE_SET = {'', '-', 'nan', 'none', 'null', 'nat', 'None', 'NaN'}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _to_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        if isinstance(v, float) and np.isnan(v):
            return None
        s = str(v).replace(',', '').replace('%', '').strip()
        if not s or s.lower() in NONE_SET:
            return None
        # DART values sometimes contain parentheses for negatives
        neg = s.startswith('(') and s.endswith(')')
        s = s.strip('()')
        x = float(s)
        return -x if neg else x
    except Exception:
        return None


def _ratio(n: Any, d: Any, scale: float = 100.0) -> float | None:
    a = _to_float(n); b = _to_float(d)
    if a is None or b in (None, 0):
        return None
    return a / b * scale


def _fmt_num(v: Any, suffix: str = '') -> str:
    x = _to_float(v)
    if x is None:
        return '-'
    if suffix == '%':
        return f'{x:.2f}%'
    if abs(x) >= 1_000_000_000_000:
        return f'{x/1_000_000_000_000:.2f}조'
    if abs(x) >= 100_000_000:
        return f'{x/100_000_000:.2f}억'
    return f'{x:,.2f}'


def _symbol_candidates(market: str, limit: int = 30) -> pd.DataFrame:
    slug = _market_slug(market)
    parts: list[pd.DataFrame] = []
    # 후보 리포트 우선
    try:
        base = _candidate_base(market)
        if not base.empty:
            parts.append(base)
    except Exception:
        pass
    # 관심/보유 종목 보강
    search_paths = [
        DATA_DIR / f'watchlist_{slug}.csv', DATA_DIR / f'holdings_{slug}.csv',
        ROOT / f'watchlist_{slug}.csv', ROOT / f'holdings_{slug}.csv',
        REPORT_DIR / f'v67_action_board_{slug}.csv', REPORT_DIR / f'v52_action_board_{slug}.csv',
    ]
    for p in search_paths:
        df = _read_csv(p)
        if not df.empty:
            parts.append(df)
    if not parts:
        defaults = {'kr': [('005930','삼성전자'), ('000660','SK하이닉스'), ('035420','NAVER'), ('005380','현대차')],
                    'us': [('NVDA','NVIDIA'), ('GOOGL','Alphabet'), ('MSFT','Microsoft'), ('AAPL','Apple'), ('AMZN','Amazon')]}
        return pd.DataFrame([{'종목코드':s,'종목명':n,'시장':_market_name(slug)} for s,n in defaults[slug]])
    out = pd.concat(parts, ignore_index=True, sort=False)
    code_col = next((c for c in ['종목코드','symbol','ticker','티커','code'] if c in out.columns), None)
    name_col = next((c for c in ['종목명','종목','name','Name'] if c in out.columns), None)
    rows=[]; seen=set()
    for _, r in out.iterrows():
        raw_code = _clean(r.get(code_col)) if code_col else ''
        raw_name = _clean(r.get(name_col)) if name_col else ''
        sym = _symbol_from_text(raw_code or raw_name)
        if not sym or sym.lower() in NONE_SET:
            continue
        if slug == 'kr':
            m = re.search(r'\b\d{6}\b', sym) or re.search(r'\b\d{6}\b', raw_code + ' ' + raw_name)
            if not m:
                continue
            sym = m.group(0)
        else:
            sym = sym.upper()
            if sym.isdigit():
                continue
        if sym in seen:
            continue
        seen.add(sym)
        rows.append({'종목코드': sym, '종목명': raw_name or sym, '시장': _market_name(slug)})
        if len(rows) >= limit:
            break
    return pd.DataFrame(rows)


# ---------- Finnhub / SEC for US ----------

def _finnhub_metric(symbol: str) -> dict[str, Any]:
    key = _env('FINNHUB_API_KEY')
    if not key:
        return {'_status': 'NO_KEY'}
    status, data, raw = _request_json('https://finnhub.io/api/v1/stock/metric', {'symbol': symbol, 'metric': 'all', 'token': key}, timeout=15)
    if status != 200:
        return {'_status': f'HTTP_{status}', '_error': raw[:250]}
    metric = data.get('metric') or {}
    if not isinstance(metric, dict) or not metric:
        return {'_status': 'EMPTY'}
    return {
        '_status': 'OK',
        'PER': metric.get('peNormalizedAnnual') or metric.get('peTTM'),
        'PBR': metric.get('pbAnnual') or metric.get('pbQuarterly'),
        'ROE': metric.get('roeTTM') or metric.get('roeRfy'),
        '매출성장률': metric.get('revenueGrowthTTMYoy') or metric.get('revenueGrowthQuarterlyYoy'),
        '영업이익률': metric.get('operatingMarginTTM') or metric.get('operatingMarginAnnual'),
        '순이익률': metric.get('netProfitMarginTTM') or metric.get('netProfitMarginAnnual'),
        '부채비율': metric.get('totalDebt/totalEquityAnnual') or metric.get('totalDebt/totalEquityQuarterly'),
        '베타': metric.get('beta'),
        '52주고가': metric.get('52WeekHigh'),
        '52주저가': metric.get('52WeekLow'),
        '_raw_keys': len(metric),
    }


def _sec_ticker_map() -> dict[str, str]:
    cache = FUND_DIR / 'sec_ticker_cik_map.json'
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except Exception:
            pass
    ua = _env('SEC_USER_AGENT') or 'MONE stock app local research contact@example.com'
    try:
        r = requests.get('https://www.sec.gov/files/company_tickers.json', headers={'User-Agent': ua}, timeout=20)
        if r.status_code != 200:
            return {}
        data = r.json()
        mp = {}
        for item in data.values():
            t = str(item.get('ticker','')).upper()
            cik = str(item.get('cik_str','')).zfill(10)
            if t and cik:
                mp[t] = cik
        cache.write_text(json.dumps(mp, ensure_ascii=False, indent=2), encoding='utf-8')
        return mp
    except Exception:
        return {}


def _latest_usgaap_value(facts: dict[str, Any], names: list[str]) -> float | None:
    usgaap = facts.get('facts', {}).get('us-gaap', {}) if isinstance(facts, dict) else {}
    best = None
    best_key = ''
    for name in names:
        obj = usgaap.get(name)
        if not isinstance(obj, dict):
            continue
        units = obj.get('units') or {}
        vals = []
        for unit in ['USD', 'shares', 'USD/shares']:
            vals.extend(units.get(unit) or [])
        # prefer 10-K annual FY entries, latest by filed/end
        vals = [v for v in vals if v.get('val') is not None]
        vals.sort(key=lambda x: (str(x.get('fy','')), str(x.get('filed','')), str(x.get('end',''))), reverse=True)
        for v in vals:
            if v.get('form') in ('10-K','10-Q','20-F','40-F'):
                best = _to_float(v.get('val'))
                best_key = name
                break
        if best is not None:
            break
    return best


def _sec_company_facts(symbol: str) -> dict[str, Any]:
    cik = _sec_ticker_map().get(symbol.upper())
    if not cik:
        return {'_status': 'NO_CIK'}
    cache = FUND_DIR / f'sec_companyfacts_{symbol.upper()}.json'
    data: dict[str, Any] = {}
    if cache.exists() and cache.stat().st_size > 0:
        try:
            data = json.loads(cache.read_text(encoding='utf-8'))
        except Exception:
            data = {}
    if not data:
        ua = _env('SEC_USER_AGENT') or 'MONE stock app local research contact@example.com'
        try:
            r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers={'User-Agent': ua}, timeout=25)
            if r.status_code != 200:
                return {'_status': f'HTTP_{r.status_code}', '_error': r.text[:250], 'CIK': cik}
            data = r.json()
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        except Exception as exc:
            return {'_status': f'{type(exc).__name__}: {exc}', 'CIK': cik}
    revenue = _latest_usgaap_value(data, ['Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','SalesRevenueNet'])
    opinc = _latest_usgaap_value(data, ['OperatingIncomeLoss','IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'])
    net = _latest_usgaap_value(data, ['NetIncomeLoss','ProfitLoss'])
    assets = _latest_usgaap_value(data, ['Assets'])
    liab = _latest_usgaap_value(data, ['Liabilities'])
    equity = _latest_usgaap_value(data, ['StockholdersEquity','StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'])
    return {
        '_status': 'OK', 'CIK': cik,
        '매출액': revenue, '영업이익': opinc, '순이익': net, '자산총계': assets, '부채총계': liab, '자본총계': equity,
        'ROE_SEC': _ratio(net, equity), '부채비율_SEC': _ratio(liab, equity),
        '영업이익률_SEC': _ratio(opinc, revenue), '순이익률_SEC': _ratio(net, revenue),
    }


def _us_fundamental_summary(symbol: str, name: str) -> dict[str, Any]:
    fin = _finnhub_metric(symbol)
    sec = _sec_company_facts(symbol)
    merged = {'시장': '미국주식', '종목코드': symbol, '종목명': name, 'Finnhub상태': fin.get('_status'), 'SEC상태': sec.get('_status')}
    # Finnhub first for ratios, SEC first for raw statements
    for k in ['PER','PBR','ROE','매출성장률','영업이익률','순이익률','부채비율','베타','52주고가','52주저가']:
        merged[k] = fin.get(k)
    for k in ['CIK','매출액','영업이익','순이익','자산총계','부채총계','자본총계']:
        merged[k] = sec.get(k)
    # fill missing ratios from SEC
    merged['ROE'] = merged.get('ROE') if _to_float(merged.get('ROE')) is not None else sec.get('ROE_SEC')
    merged['부채비율'] = merged.get('부채비율') if _to_float(merged.get('부채비율')) is not None else sec.get('부채비율_SEC')
    merged['영업이익률'] = merged.get('영업이익률') if _to_float(merged.get('영업이익률')) is not None else sec.get('영업이익률_SEC')
    merged['순이익률'] = merged.get('순이익률') if _to_float(merged.get('순이익률')) is not None else sec.get('순이익률_SEC')
    ok = any(_to_float(merged.get(k)) is not None for k in ['PER','PBR','ROE','매출액','순이익','자산총계'])
    merged['재무상태'] = '재무/KPI 수신' if ok else '재무 데이터 부족'
    merged['데이터출처'] = 'Finnhub + SEC' if ok else f"Finnhub:{fin.get('_status')} / SEC:{sec.get('_status')}"
    merged['초보자 해석'] = _interpret_fundamental(merged)
    return merged


# ---------- DART for KR ----------

def _dart_corp_map() -> pd.DataFrame:
    cache = FUND_DIR / 'dart_corp_map.csv'
    if cache.exists() and cache.stat().st_size > 0:
        return _read_csv(cache)
    key = _env('DART_API_KEY')
    if not key:
        return pd.DataFrame()
    try:
        r = requests.get('https://opendart.fss.or.kr/api/corpCode.xml', params={'crtfc_key': key}, timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_bytes = z.read(z.namelist()[0])
        root = ET.fromstring(xml_bytes)
        rows=[]
        for item in root.findall('list'):
            rows.append({
                'corp_code': (item.findtext('corp_code') or '').strip(),
                'corp_name': (item.findtext('corp_name') or '').strip(),
                'stock_code': (item.findtext('stock_code') or '').strip(),
                'modify_date': (item.findtext('modify_date') or '').strip(),
            })
        df = pd.DataFrame(rows)
        df = df[df['stock_code'].astype(str).str.match(r'^\d{6}$', na=False)].copy()
        _write_csv(df, cache)
        return df
    except Exception:
        return pd.DataFrame()


def _dart_value(rows: pd.DataFrame, patterns: list[str]) -> float | None:
    if rows.empty or 'account_nm' not in rows.columns:
        return None
    for pat in patterns:
        mask = rows['account_nm'].astype(str).str.contains(pat, regex=True, na=False)
        if mask.any():
            for col in ['thstrm_amount','frmtrm_amount','bfefrmtrm_amount']:
                if col in rows.columns:
                    for val in rows.loc[mask, col].tolist():
                        x = _to_float(val)
                        if x is not None:
                            return x
    return None


def _dart_financials(symbol: str, name: str) -> dict[str, Any]:
    key = _env('DART_API_KEY')
    if not key:
        return {'시장':'한국주식','종목코드':symbol,'종목명':name,'DART상태':'NO_KEY'}
    mp = _dart_corp_map()
    if mp.empty:
        return {'시장':'한국주식','종목코드':symbol,'종목명':name,'DART상태':'NO_CORP_MAP'}
    m = mp[mp['stock_code'].astype(str).str.zfill(6) == str(symbol).zfill(6)]
    if m.empty:
        return {'시장':'한국주식','종목코드':symbol,'종목명':name,'DART상태':'NO_CORP_CODE'}
    corp_code = str(m.iloc[0]['corp_code'])
    corp_name = str(m.iloc[0]['corp_name']) or name
    current_year = datetime.now().year
    last_error = ''
    for year in [current_year-1, current_year-2, current_year-3]:
        for fs_div in ['CFS','OFS']:
            params = {'crtfc_key': key, 'corp_code': corp_code, 'bsns_year': str(year), 'reprt_code': '11011', 'fs_div': fs_div}
            status, data, raw = _request_json('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json', params, timeout=25)
            if status != 200:
                last_error = raw[:200]
                continue
            if str(data.get('status')) not in {'000','013'}:
                last_error = str(data.get('message') or data.get('status'))
            items = data.get('list') or []
            if not items:
                continue
            df = pd.DataFrame(items)
            revenue = _dart_value(df, ['매출액', r'수익\(매출액\)', '영업수익'])
            opinc = _dart_value(df, ['영업이익'])
            net = _dart_value(df, ['당기순이익', '분기순이익', '연결당기순이익'])
            assets = _dart_value(df, ['자산총계'])
            liab = _dart_value(df, ['부채총계'])
            equity = _dart_value(df, ['자본총계'])
            out = {
                '시장':'한국주식','종목코드':symbol,'종목명':corp_name,'corp_code':corp_code,'사업연도':year,'재무제표':fs_div,
                '매출액':revenue,'영업이익':opinc,'순이익':net,'자산총계':assets,'부채총계':liab,'자본총계':equity,
                'ROE':_ratio(net, equity),'부채비율':_ratio(liab, equity),'영업이익률':_ratio(opinc, revenue),'순이익률':_ratio(net, revenue),
                'DART상태':'OK','데이터출처':'DART 재무제표',
            }
            # try market cap using yfinance .KS/.KQ
            mcap = _try_yfinance_mcap(symbol)
            if mcap and net:
                out['PER'] = _ratio(mcap, net, scale=1.0)
            if mcap and equity:
                out['PBR'] = _ratio(mcap, equity, scale=1.0)
            out['재무상태'] = '재무/KPI 수신'
            out['초보자 해석'] = _interpret_fundamental(out)
            return out
    return {'시장':'한국주식','종목코드':symbol,'종목명':name,'DART상태':'NO_FINANCIALS','오류':last_error,'재무상태':'재무 데이터 부족','데이터출처':'DART 응답 없음'}


def _try_yfinance_mcap(symbol: str) -> float | None:
    try:
        import yfinance as yf
        for suffix in ['.KS','.KQ','']:
            info = yf.Ticker(str(symbol).zfill(6)+suffix).info or {}
            x = _to_float(info.get('marketCap'))
            if x:
                return x
    except Exception:
        return None
    return None


def _interpret_fundamental(row: dict[str, Any]) -> str:
    roe = _to_float(row.get('ROE'))
    debt = _to_float(row.get('부채비율'))
    per = _to_float(row.get('PER'))
    revg = _to_float(row.get('매출성장률'))
    bits=[]
    if roe is not None:
        bits.append('ROE 양호' if roe >= 10 else 'ROE 낮음/확인 필요')
    if debt is not None:
        bits.append('부채 부담 낮음' if debt <= 150 else '부채비율 높음')
    if per is not None:
        bits.append('PER 과열 확인' if per >= 40 else 'PER 참고 가능')
    if revg is not None:
        bits.append('매출 성장 양호' if revg >= 5 else '성장률 둔화 확인')
    if not bits:
        return '재무 원자료가 부족합니다. 단기 매매는 가능하지만 장기 보유 판단은 보류합니다.'
    return ' · '.join(bits) + ' — 가격·뉴스·차트와 함께 판단하세요.'


def _build_v69_company_cards(market: str, limit: int = 18) -> pd.DataFrame:
    slug = _market_slug(market)
    syms = _symbol_candidates(market, limit=limit)
    rows=[]
    for _, r in syms.iterrows():
        sym = str(r.get('종목코드','')).strip()
        name = str(r.get('종목명','') or sym).strip()
        if not sym:
            continue
        try:
            if slug == 'kr':
                row = _dart_financials(sym, name)
            else:
                row = _us_fundamental_summary(sym.upper(), name)
        except Exception as exc:
            row = {'시장':_market_name(slug),'종목코드':sym,'종목명':name,'재무상태':'ERROR','오류':f'{type(exc).__name__}: {exc}'}
        # presentation cols
        row['PER표시'] = _fmt_num(row.get('PER'))
        row['PBR표시'] = _fmt_num(row.get('PBR'))
        row['ROE표시'] = _fmt_num(row.get('ROE'), '%')
        row['매출표시'] = _fmt_num(row.get('매출액'))
        row['순이익표시'] = _fmt_num(row.get('순이익'))
        row['부채비율표시'] = _fmt_num(row.get('부채비율'), '%')
        row['영업이익률표시'] = _fmt_num(row.get('영업이익률'), '%')
        row['다음 행동'] = '장기 보유 판단에 사용 가능' if row.get('재무상태') == '재무/KPI 수신' else _missing_reason(row, slug)
        rows.append(row)
    df = pd.DataFrame(rows)
    _write_csv(df, REPORT_DIR / f'v69_company_cards_{slug}.csv')
    return df


def _missing_reason(row: dict[str, Any], slug: str) -> str:
    if slug == 'kr':
        st = row.get('DART상태')
        if st == 'NO_KEY': return 'DART_API_KEY가 인식되지 않습니다.'
        if st == 'NO_CORP_MAP': return 'DART corp_code 목록을 받지 못했습니다.'
        if st == 'NO_CORP_CODE': return '종목코드와 DART 고유번호 매칭 실패입니다.'
        if st == 'NO_FINANCIALS': return 'DART 재무제표 응답이 비어 있습니다. 사업연도/보고서 확인이 필요합니다.'
        return 'DART 재무 연결 상태 확인이 필요합니다.'
    else:
        fs = row.get('Finnhub상태'); ss = row.get('SEC상태')
        if fs == 'NO_KEY': return 'FINNHUB_API_KEY가 인식되지 않습니다. SEC만으로 일부 원자료는 가능하지만 KPI가 부족합니다.'
        return f'Finnhub 상태 {fs}, SEC 상태 {ss}. 티커/CIK 매핑 또는 API 응답을 확인하세요.'


# ---------- Apify news optional ----------

def _fetch_apify_news(market: str, max_items: int = 30) -> tuple[pd.DataFrame, dict[str, Any]]:
    token = _env('APIFY_TOKEN')
    actor = _env('APIFY_NEWS_ACTOR_ID') or _env('APIFY_ACTOR_ID') or _env('APIFY_NEWS_ACTOR')
    slug = _market_slug(market)
    diag = {'enabled': bool(token), 'actor_configured': bool(actor), 'rows': 0, 'status': 'SKIPPED'}
    if not token or not actor:
        if token and not actor:
            diag['status'] = 'TOKEN_ONLY_NO_ACTOR_ID'
        return pd.DataFrame(), diag
    q = '코스피 코스닥 연합뉴스 인베스팅 한국 증시' if slug == 'kr' else 'US stock market Nvidia Nasdaq CNBC Reuters'
    url = f'https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items'
    try:
        r = requests.post(url, params={'token': token, 'format': 'json', 'clean': 'true'}, json={'query': q, 'queries':[q], 'maxItems': max_items}, timeout=90)
        diag['status_code'] = r.status_code
        if r.status_code not in (200,201):
            diag['status'] = 'HTTP_ERROR'; diag['error'] = r.text[:300]
            return pd.DataFrame(), diag
        data = r.json()
        if not isinstance(data, list):
            diag['status'] = 'NON_LIST_RESPONSE'
            return pd.DataFrame(), diag
        rows=[]
        for item in data[:max_items]:
            if not isinstance(item, dict):
                continue
            title = item.get('title') or item.get('headline') or item.get('name') or item.get('text') or ''
            desc = item.get('description') or item.get('summary') or item.get('snippet') or ''
            urlv = item.get('url') or item.get('link') or ''
            source = item.get('source') or item.get('siteName') or item.get('publisher') or 'Apify'
            if title:
                rows.append({'시장':_market_name(slug),'제목':title,'요약':desc,'출처':source,'URL':urlv,'게시시간':item.get('publishedAt') or item.get('date') or '', '검색어':q, '수집방식':'Apify Actor'})
        df = pd.DataFrame(rows)
        if not df.empty:
            df['간략 번역'] = [_simple_title_ko(str(t)) + '\n' + _basic_kr_interpretation(str(t), str(d), market) for t,d in zip(df.get('제목',''), df.get('요약',''))]
        diag['rows'] = len(df); diag['status'] = 'OK' if len(df) else 'ZERO_ROWS'
        return df, diag
    except Exception as exc:
        diag['status'] = f'{type(exc).__name__}: {exc}'
        return pd.DataFrame(), diag


def _build_v69_news_cards(market: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    slug = _market_slug(market)
    apify_df, apify_diag = _fetch_apify_news(market)
    gnews_df, gnews_diag = _build_news_cards(market)
    parts = [df for df in [apify_df, gnews_df] if not df.empty]
    df = pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
    if not df.empty:
        df = df.drop_duplicates(subset=['제목']).head(40).reset_index(drop=True)
        # 국장인데 외국/미국 일반 기사만 들어오는 문제 완화: 한글/국내 소스 우선
        if slug == 'kr':
            df['_prio'] = df.apply(lambda r: 0 if re.search(r'[가-힣]', str(r.get('제목','')) + str(r.get('출처',''))) else 2, axis=1)
            df = df.sort_values(['_prio','게시시간'], ascending=[True, False]).drop(columns=['_prio'], errors='ignore').head(30)
    diag = {'market':_market_name(slug),'updated_at':_now(),'apify':apify_diag,'gnews':gnews_diag,'rows':len(df)}
    _write_csv(df, REPORT_DIR / f'v69_news_cards_{slug}.csv')
    _write_json(diag, REPORT_DIR / f'v69_news_diag_{slug}.json')
    return df, diag


def run_v69_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _load_dotenv_soft()
    env_status = {k: bool(_env(k)) for k in ['GNEWS_API_KEY','FINNHUB_API_KEY','DART_API_KEY','APIFY_TOKEN','APIFY_NEWS_ACTOR_ID','SEC_USER_AGENT']}
    result: dict[str, Any] = {'status':'OK','version':'v69','updated_at':_now(),'env':env_status}
    for slug in ['kr','us']:
        market = _market_name(slug)
        if fetch_news:
            news, ndiag = _build_v69_news_cards(market)
        else:
            news = _read_csv(REPORT_DIR / f'v69_news_cards_{slug}.csv'); ndiag = {'status':'SKIPPED'}
        if fetch_fundamentals:
            company = _build_v69_company_cards(market)
        else:
            company = _read_csv(REPORT_DIR / f'v69_company_cards_{slug}.csv')
        macro = _build_macro_cards(market) if fetch_macro else _read_csv(REPORT_DIR / f'v68_macro_cards_{slug}.csv')
        _write_csv(macro, REPORT_DIR / f'v69_macro_cards_{slug}.csv')
        narrative = _build_narrative(market, news, company, macro)
        _write_csv(narrative, REPORT_DIR / f'v69_narrative_{slug}.csv')
        result[slug] = {'news_rows': len(news), 'company_rows': len(company), 'macro_rows': len(macro), 'narrative_rows': len(narrative), 'news_diag': ndiag.get('rows', 0)}
    _write_json(result, REPORT_DIR / 'v69_status.json')
    return result
