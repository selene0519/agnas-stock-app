from __future__ import annotations

import json
import os
import re
import html
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import pandas as pd
import numpy as np
import requests

ROOT = Path('.').resolve()
REPORT_DIR = ROOT / 'reports'
DATA_DIR = ROOT / 'data'
REPORT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

KR_PREFERRED_SOURCES = (
    '연합뉴스', 'yna', '한국경제', '한경', '매일경제', 'mk', '머니투데이', '이데일리',
    '서울경제', '파이낸셜뉴스', '조선비즈', '비즈니스워치', 'Investing.com', '인베스팅',
    '아시아경제', '헤럴드경제', '데일리안', '뉴시스', '뉴스1'
)
US_PREFERRED_SOURCES = (
    'Reuters', 'CNBC', 'MarketWatch', 'Yahoo Finance', 'Bloomberg', 'AP News', 'The Wall Street Journal',
    'Financial Times', 'Investing.com', 'Barron', 'Nasdaq', 'Seeking Alpha'
)

NONE_SET = {'', '-', 'nan', 'none', 'null', 'nat', 'None', 'NaN'}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _load_dotenv_soft() -> None:
    """Load .env even when python-dotenv is missing."""
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ROOT / '.env')
    except Exception:
        pass
    envp = ROOT / '.env'
    if envp.exists():
        try:
            for line in envp.read_text(encoding='utf-8').splitlines():
                s = line.strip()
                if not s or s.startswith('#') or '=' not in s:
                    continue
                k, v = s.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            pass


def _env(name: str) -> str:
    _load_dotenv_soft()
    return os.getenv(name, '').strip()


def _read_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(p)
    except Exception:
        try:
            return pd.read_csv(p, encoding='cp949')
        except Exception:
            return pd.DataFrame()


def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding='utf-8-sig')


def _write_json(obj: Any, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _market_slug(market: str | None) -> str:
    m = str(market or '').lower()
    if any(x in m for x in ['한국', '국장', 'kr', 'korea', 'kospi', 'kosdaq']):
        return 'kr'
    return 'us'


def _market_name(slug: str) -> str:
    return '한국주식' if slug == 'kr' else '미국주식'


def _clean(v: Any) -> str:
    if v is None:
        return ''
    s = str(v).strip()
    if s.lower() in NONE_SET:
        return ''
    return s


def _symbol_from_text(value: Any) -> str:
    s = _clean(value).upper()
    if not s:
        return ''
    m = re.search(r'\(([A-Z0-9\.\-]{1,10})\)', s)
    if m:
        return m.group(1).strip()
    m = re.search(r'\b[0-9]{6}\b', s)
    if m:
        return m.group(0)
    m = re.search(r'\b[A-Z]{1,5}(?:\.[A-Z])?\b', s)
    if m:
        return m.group(0)
    return s.split()[0]


def _fmt(v: Any, suffix: str = '') -> str:
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return '-'
        if isinstance(v, (int, float)):
            if suffix == '%':
                return f'{float(v):.2f}%'
            return f'{float(v):,.2f}'
        s = str(v).strip()
        return s if s else '-'
    except Exception:
        return '-'


def _request_json(url: str, params: dict[str, Any], timeout: int = 12) -> tuple[int, dict[str, Any], str]:
    try:
        r = requests.get(url, params=params, timeout=timeout, headers={'User-Agent': 'MONE stock app contact: local-user'})
        txt = r.text[:500]
        if r.status_code == 200:
            try:
                return r.status_code, r.json(), txt
            except Exception:
                return r.status_code, {}, txt
        return r.status_code, {}, txt
    except Exception as exc:
        return 0, {}, f'{type(exc).__name__}: {exc}'


def _parse_google_news_rss(query: str, *, lang: str, country: str, max_items: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ceid = f'{country}:{lang}'
    url = f'https://news.google.com/rss/search?q={quote_plus(query)}&hl={lang}-{country}&gl={country}&ceid={ceid}'
    diag: dict[str, Any] = {'type': 'google_rss', 'query': query, 'url': url, 'rows': 0}
    rows: list[dict[str, Any]] = []
    try:
        r = requests.get(url, timeout=12, headers={'User-Agent': 'MONE stock app contact: local-user'})
        diag['status_code'] = r.status_code
        if r.status_code != 200:
            diag['error'] = r.text[:300]
            return rows, diag
        root = ET.fromstring(r.content)
        channel = root.find('channel')
        items = channel.findall('item') if channel is not None else []
        for item in items[:max_items]:
            title = html.unescape((item.findtext('title') or '').strip())
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            desc = html.unescape(re.sub('<[^<]+?>', ' ', item.findtext('description') or '').strip())
            source_el = item.find('source')
            source = html.unescape((source_el.text or '').strip()) if source_el is not None else '-'
            if not title:
                continue
            rows.append({'제목': title, '요약': desc, '출처': source, 'URL': link, '게시시간': pub, '검색어': query, '수집방식': 'Google News RSS'})
        diag['rows'] = len(rows)
    except Exception as exc:
        diag['error'] = f'{type(exc).__name__}: {exc}'
    return rows, diag


def _kr_source_priority(source: str, title: str) -> int:
    text = f'{source} {title}'
    if any(s.lower() in text.lower() for s in KR_PREFERRED_SOURCES):
        return 0
    if re.search(r'[가-힣]', text):
        return 1
    return 3


def _us_source_priority(source: str, title: str) -> int:
    text = f'{source} {title}'
    if any(s.lower() in text.lower() for s in US_PREFERRED_SOURCES):
        return 0
    return 1


def _basic_kr_interpretation(title: str, desc: str, market: str) -> str:
    text = f'{title} {desc}'.lower()
    pairs = [
        (('코스피','kospi','코스닥','kosdaq','한국 증시','korea stock'), '국내 증시 전반 뉴스입니다. 지수 방향과 외국인/기관 수급을 함께 확인하세요.'),
        (('삼성전자','하이닉스','반도체','hynix','semiconductor','chip'), '국내 반도체 관련 뉴스입니다. 삼성전자·SK하이닉스와 소재/장비 업종에 영향을 줄 수 있습니다.'),
        (('환율','원달러','달러','금리','국채','fed','연준'), '환율·금리 관련 뉴스입니다. 성장주와 외국인 수급에 영향을 줄 수 있습니다.'),
        (('실적','영업이익','매출','가이던스','earnings','revenue'), '실적 관련 뉴스입니다. 단순 호재/악재보다 실제 주가 반응과 거래량을 확인하세요.'),
        (('2차전지','배터리','전기차','ev'), '2차전지/전기차 관련 뉴스입니다. 소재·장비·셀 업체의 수급 반응을 확인하세요.'),
        (('로봇','방산','조선','바이오','ai'), '테마/성장 섹터 뉴스입니다. 추격매수보다 기준가 근처 대기를 우선합니다.'),
        (('nvidia','nvda','ai chip','gpu'), '엔비디아/AI 반도체 뉴스입니다. 미장 반도체와 국내 AI·반도체 관련주에 영향을 줄 수 있습니다.'),
        (('nasdaq','s&p','wall street','stock market'), '미국 증시 흐름 뉴스입니다. 국내 성장주와 반도체 투자심리에 영향을 줄 수 있습니다.'),
    ]
    for keys, msg in pairs:
        if any(k in text for k in keys):
            return msg
    return '시장 관련 뉴스입니다. 뉴스만으로 매수하지 말고 가격·거래량·기준가 반응을 함께 확인하세요.'


def _simple_title_ko(title: str) -> str:
    """AI 없이 미장 제목을 아주 짧게 한국어 해석한다. 완전 번역이 아니라 핵심 해석."""
    t = str(title or '')
    repl = [
        ('stock market', '증시'), ('stocks', '주식'), ('Nasdaq', '나스닥'), ('S&P 500', 'S&P500'),
        ('Dow', '다우'), ('Nvidia', '엔비디아'), ('AI', 'AI'), ('semiconductor', '반도체'),
        ('Federal Reserve', '연준'), ('Fed', '연준'), ('Treasury yields', '미 국채금리'),
        ('inflation', '물가'), ('earnings', '실적'), ('revenue', '매출'), ('guidance', '가이던스'),
        ('rises', '상승'), ('falls', '하락'), ('jumps', '급등'), ('drops', '하락'), ('slips', '하락'),
        ('beats', '예상 상회'), ('misses', '예상 하회'), ('cuts', '하향'), ('raises', '상향'),
    ]
    out = t
    for a, b in repl:
        out = re.sub(re.escape(a), b, out, flags=re.IGNORECASE)
    if out == t:
        return _basic_kr_interpretation(title, '', '미국주식')
    return f'제목 핵심 해석: {out}'


def _fetch_gnews(market: str, max_items: int = 30) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    key = _env('GNEWS_API_KEY')
    slug = _market_slug(market)
    rows: list[dict[str, Any]] = []
    diag: list[dict[str, Any]] = []
    if not key:
        diag.append({'type': 'gnews', 'status': 'NO_KEY'})
        return rows, diag
    if slug == 'kr':
        queries = [
            '코스피 코스닥 외국인 기관 수급',
            '한국 증시 반도체 삼성전자 SK하이닉스',
            'site:yna.co.kr 증시 코스피',
            'site:kr.investing.com 코스피 코스닥',
            'site:hankyung.com 증시 반도체',
        ]
        combos = [('ko','kr'), ('ko',''), ('en','kr')]
    else:
        queries = [
            'Nasdaq stock market Nvidia AI chip',
            'S&P 500 Federal Reserve Treasury yields stocks',
            'US stock market earnings guidance technology',
            'Reuters Nvidia AI semiconductor stocks',
            'CNBC Nasdaq Federal Reserve stocks',
        ]
        combos = [('en','us'), ('en','')]
    for q in queries:
        for lang, country in combos:
            params: dict[str, Any] = {'q': q, 'apikey': key, 'max': 10}
            if lang:
                params['lang'] = lang
            if country:
                params['country'] = country
            status, data, raw = _request_json('https://gnews.io/api/v4/search', params)
            info = {'type': 'gnews', 'q': q, 'lang': lang, 'country': country, 'status_code': status, 'articles': 0}
            if status == 200:
                arts = data.get('articles') or []
                info['articles'] = len(arts)
                for a in arts:
                    title = _clean(a.get('title'))
                    desc = _clean(a.get('description') or a.get('content'))
                    source = a.get('source') or {}
                    source_name = _clean(source.get('name') if isinstance(source, dict) else source) or '-'
                    if not title:
                        continue
                    rows.append({
                        '시장': _market_name(slug), '제목': title, '요약': desc, '출처': source_name,
                        'URL': a.get('url') or '', '게시시간': a.get('publishedAt') or '', '검색어': q, '수집방식': 'GNews',
                    })
            else:
                info['error'] = raw[:300]
            diag.append(info)
            if len(rows) >= max_items:
                return rows, diag
    return rows, diag


def _fetch_rss_fallback(market: str, max_items: int = 30) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    slug = _market_slug(market)
    if slug == 'kr':
        rss_queries = [
            '코스피 코스닥 외국인 기관 수급',
            '연합뉴스 증시 코스피 코스닥',
            'Investing.com 한국 증시 코스피',
            '삼성전자 SK하이닉스 반도체 증시',
            '한국경제 증시 반도체 2차전지',
        ]
        lang, country = 'ko', 'KR'
    else:
        rss_queries = [
            'Nasdaq stock market Nvidia AI chip',
            'S&P 500 Federal Reserve Treasury yields stocks',
            'Reuters US stock market earnings technology',
            'CNBC Nasdaq Nvidia stocks',
        ]
        lang, country = 'en', 'US'
    rows: list[dict[str, Any]] = []
    diag: list[dict[str, Any]] = []
    for q in rss_queries:
        got, info = _parse_google_news_rss(q, lang=lang, country=country, max_items=15)
        diag.append(info)
        rows.extend(got)
        if len(rows) >= max_items:
            break
    for r in rows:
        r['시장'] = _market_name(slug)
    return rows[:max_items], diag


def _build_news_cards(market: str, max_items: int = 25) -> tuple[pd.DataFrame, dict[str, Any]]:
    slug = _market_slug(market)
    rows, diag1 = _fetch_gnews(market, max_items=max_items)
    rss_rows, diag2 = _fetch_rss_fallback(market, max_items=max_items)
    rows.extend(rss_rows)
    diag = {'market': _market_name(slug), 'updated_at': _now(), 'env': {'GNEWS_API_KEY': bool(_env('GNEWS_API_KEY'))}, 'attempts': diag1 + diag2}
    if not rows:
        diag['status'] = 'ZERO_ROWS'
        return pd.DataFrame(columns=['시장','제목','요약','간략 번역','출처','URL','게시시간','검색어','수집방식','우선순위']), diag
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=['제목']).copy()
    if slug == 'kr':
        df['우선순위'] = [_kr_source_priority(str(s), str(t)) for s, t in zip(df.get('출처',''), df.get('제목',''))]
        # 국장은 한국어/국내 소스 우선. 영어 해외 뉴스는 마지막으로 밀어낸다.
        df = df.sort_values(['우선순위','게시시간'], ascending=[True, False]).head(max_items)
    else:
        df['우선순위'] = [_us_source_priority(str(s), str(t)) for s, t in zip(df.get('출처',''), df.get('제목',''))]
        df = df.sort_values(['우선순위','게시시간'], ascending=[True, False]).head(max_items)
    trans = []
    for _, r in df.iterrows():
        title = str(r.get('제목',''))
        desc = str(r.get('요약',''))
        if slug == 'us':
            trans.append(f'{_simple_title_ko(title)}\n{_basic_kr_interpretation(title, desc, market)}')
        else:
            trans.append(_basic_kr_interpretation(title, desc, market))
    df['간략 번역'] = trans
    diag['status'] = 'OK'
    diag['rows'] = len(df)
    diag['gnews_rows'] = len(pd.DataFrame(rows[0:0])) if False else sum(int(x.get('articles',0) or 0) for x in diag1 if x.get('type')=='gnews')
    diag['rss_rows'] = len(rss_rows)
    return df.reset_index(drop=True), diag


def _candidate_base(market: str) -> pd.DataFrame:
    slug = _market_slug(market)
    candidates = [
        REPORT_DIR / f'v67_action_board_{slug}.csv',
        REPORT_DIR / f'v67_pullback_{slug}.csv',
        REPORT_DIR / f'v52_action_board_{slug}.csv',
        REPORT_DIR / 'v52_action_board_light.csv',
        REPORT_DIR / 'v45_beginner_action_board.csv',
    ]
    for p in candidates:
        df = _read_csv(p)
        if not df.empty:
            if '시장' in df.columns:
                if slug == 'kr':
                    mask = df['시장'].astype(str).str.contains('한국|국장|KR|Korea|KOSPI|KOSDAQ', case=False, na=False)
                else:
                    mask = df['시장'].astype(str).str.contains('미국|미장|US|USA|NASDAQ|NYSE|AMEX', case=False, na=False)
                if mask.any():
                    df = df[mask].copy()
            return df.reset_index(drop=True)
    return pd.DataFrame()


def _fetch_us_fundamentals(symbol: str) -> dict[str, Any]:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        return {
            'PER': info.get('trailingPE') or info.get('forwardPE'),
            'PBR': info.get('priceToBook'),
            'ROE': (float(info.get('returnOnEquity')) * 100 if info.get('returnOnEquity') is not None else None),
            '매출성장률': (float(info.get('revenueGrowth')) * 100 if info.get('revenueGrowth') is not None else None),
            '부채비율': info.get('debtToEquity'),
            '시가총액': info.get('marketCap'),
        }
    except Exception:
        return {}


def _fundamental_sources() -> pd.DataFrame:
    parts = []
    for p in [REPORT_DIR/'fundamental_cache.csv', REPORT_DIR/'fundamental_report.csv', REPORT_DIR/'v65_company_analysis_cards.csv', REPORT_DIR/'v48_fundamental_cards.csv']:
        df = _read_csv(p)
        if not df.empty:
            df['_source_file'] = p.name
            parts.append(df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _build_company_cards(market: str, fetch_missing: bool = True) -> pd.DataFrame:
    slug = _market_slug(market)
    base = _candidate_base(market)
    fund = _fundamental_sources()
    rows: list[dict[str, Any]] = []
    if base.empty:
        base = pd.DataFrame([{'종목':'데이터 필요', '종목코드':'-', '시장':_market_name(slug)}])
    for _, r in base.head(12).iterrows():
        title = _clean(r.get('종목')) or _clean(r.get('종목명')) or _clean(r.get('종목코드')) or '-'
        sym = _symbol_from_text(_clean(r.get('종목코드')) or title)
        frow = pd.Series(dtype=object)
        if not fund.empty:
            cand = fund.copy()
            mask = pd.Series([False]*len(cand))
            for c in ['종목코드','symbol','ticker','종목','종목명']:
                if c in cand.columns:
                    mask = mask | cand[c].astype(str).str.upper().str.contains(re.escape(sym.upper()), na=False)
            if mask.any():
                frow = cand[mask].iloc[0]
        vals = {}
        for key, names in {
            'PER':['PER','per','trailingPE'], 'PBR':['PBR','pbr','priceToBook'], 'ROE':['ROE','roe','returnOnEquity'],
            '매출성장률':['매출성장률','revenueGrowth','growth'], '부채비율':['부채비율','debtToEquity'],
        }.items():
            for n in names:
                if n in frow.index and _clean(frow.get(n)):
                    vals[key] = frow.get(n); break
        if slug == 'us' and fetch_missing and sym and (not vals or all(not _clean(v) for v in vals.values())):
            vals.update({k:v for k,v in _fetch_us_fundamentals(sym).items() if v is not None})
        has_data = any(_clean(v) for v in vals.values())
        if has_data:
            status = '재무/KPI 일부 수신'
            interp = '장기 보유 판단에 일부 참고할 수 있습니다. 단, 값이 비어 있는 지표는 보수적으로 봅니다.'
            action = 'PER/PBR/ROE/성장률을 후보 점수와 함께 확인'
        else:
            status = '재무 데이터 부족'
            interp = '단기 매매 후보로는 볼 수 있지만 장기 보유 판단은 아직 보류합니다.'
            action = 'DART/Finnhub/yfinance 재무 갱신 후 재확인'
        rows.append({
            '시장': _market_name(slug), '종목': title, '종목코드': sym, '재무상태': status,
            'PER': _fmt(vals.get('PER')), 'PBR': _fmt(vals.get('PBR')), 'ROE': _fmt(vals.get('ROE'), '%'),
            '매출성장률': _fmt(vals.get('매출성장률'), '%'), '부채비율': _fmt(vals.get('부채비율')),
            '가치평가': '확인 가능' if has_data else '데이터 필요', 'KPI': '확인 가능' if has_data else '확인 필요',
            '초보자 해석': interp, '다음 행동': action,
        })
    return pd.DataFrame(rows)


def _fetch_index_snapshot(market: str) -> list[dict[str, Any]]:
    slug = _market_slug(market)
    rows: list[dict[str, Any]] = []
    try:
        import yfinance as yf
        tickers = {'us': {'S&P500':'^GSPC', 'NASDAQ':'^IXIC', 'VIX':'^VIX'}, 'kr': {'KOSPI':'^KS11', 'KOSDAQ':'^KQ11', 'USD/KRW':'KRW=X'}}[slug]
        for name, t in tickers.items():
            hist = yf.Ticker(t).history(period='5d', interval='1d', auto_adjust=False)
            if hist is None or hist.empty:
                continue
            close = hist['Close'].dropna()
            if close.empty:
                continue
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else last
            chg = (last/prev - 1)*100 if prev else 0
            rows.append({'시장': _market_name(slug), '지표': name, '값': f'{last:,.2f}', '등락률': f'{chg:.2f}%', '해석': '강세 참고' if chg>0 else '약세/주의 참고', '출처': 'yfinance 직전 장 기준'})
    except Exception:
        pass
    return rows


def _build_macro_cards(market: str) -> pd.DataFrame:
    slug = _market_slug(market)
    rows = _fetch_index_snapshot(market)
    if rows:
        return pd.DataFrame(rows)
    # fallback from benchmark csv
    b = _read_csv(DATA_DIR/'market'/'benchmark_daily.csv')
    if b.empty:
        b = _read_csv(REPORT_DIR/'operational_macro_kr.csv')
    if not b.empty:
        for col in b.columns[:5]:
            try:
                val = b[col].dropna().iloc[-1]
            except Exception:
                val = '-'
            rows.append({'시장': _market_name(slug), '지표': col, '값': val, '등락률': '-', '해석': '저장된 시장 기준 데이터입니다.', '출처': '저장 리포트'})
    if not rows:
        rows = [{'시장': _market_name(slug), '지표': '시장 데이터', '값': '-', '등락률': '-', '해석': '시장 지표 데이터가 아직 없습니다. 장마감/자동누적 후 다시 확인하세요.', '출처': '데이터 필요'}]
    return pd.DataFrame(rows)


def _build_narrative(market: str, news: pd.DataFrame, company: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    slug = _market_slug(market)
    base = _candidate_base(market)
    rows: list[dict[str, Any]] = []
    if base.empty:
        return pd.DataFrame([{'시장':_market_name(slug),'종목':'데이터 필요','내러티브':'후보 리포트가 아직 없습니다.','주의':'자동누적/장마감 갱신 후 확인'}])
    for _, r in base.head(12).iterrows():
        name = _clean(r.get('종목')) or _clean(r.get('종목명')) or _clean(r.get('종목코드')) or '-'
        sym = _symbol_from_text(_clean(r.get('종목코드')) or name)
        action = _clean(r.get('행동')) or _clean(r.get('상태')) or '관찰'
        news_hit = ''
        if not news.empty:
            mask = news.astype(str).apply(lambda s: s.str.contains(re.escape(sym), case=False, na=False) | s.str.contains(re.escape(name[:8]), case=False, na=False)).any(axis=1)
            if mask.any():
                news_hit = str(news[mask].iloc[0].get('간략 번역',''))
        comp = '재무/KPI 데이터 부족'
        if not company.empty:
            cm = company.astype(str).apply(lambda s: s.str.contains(re.escape(sym), case=False, na=False) | s.str.contains(re.escape(name[:8]), case=False, na=False)).any(axis=1)
            if cm.any():
                comp = str(company[cm].iloc[0].get('재무상태','재무 확인'))
        macro_hint = '시장 데이터 확인 필요'
        if not macro.empty:
            macro_hint = ' / '.join(macro.head(2)['해석'].astype(str).tolist())
        narrative = f'{name}은 현재 {action} 후보입니다. {comp}. {news_hit or "직접 연결된 뉴스는 아직 없으며, 시장 뉴스와 가격 반응을 함께 봅니다."}'
        rows.append({'시장':_market_name(slug), '종목':name, '종목코드':sym, '내러티브': narrative, '시장 배경': macro_hint, '주의':'뉴스·재무·차트가 동시에 맞을 때만 우선순위를 높입니다.'})
    return pd.DataFrame(rows)


def run_v68_update(fetch_news: bool = True, fetch_missing_fundamentals: bool = True) -> dict[str, Any]:
    _load_dotenv_soft()
    result: dict[str, Any] = {'status': 'OK', 'version': 'v68', 'updated_at': _now(), 'env': {'GNEWS_API_KEY': bool(_env('GNEWS_API_KEY')), 'FINNHUB_API_KEY': bool(_env('FINNHUB_API_KEY')), 'DART_API_KEY': bool(_env('DART_API_KEY'))}}
    for slug in ['kr','us']:
        market = _market_name(slug)
        if fetch_news:
            news, diag = _build_news_cards(market)
        else:
            news = _read_csv(REPORT_DIR/f'v68_news_cards_{slug}.csv')
            diag = {'status':'SKIPPED'}
        company = _build_company_cards(market, fetch_missing=fetch_missing_fundamentals)
        macro = _build_macro_cards(market)
        narrative = _build_narrative(market, news, company, macro)
        _write_csv(news, REPORT_DIR/f'v68_news_cards_{slug}.csv')
        _write_csv(company, REPORT_DIR/f'v68_company_cards_{slug}.csv')
        _write_csv(macro, REPORT_DIR/f'v68_macro_cards_{slug}.csv')
        _write_csv(narrative, REPORT_DIR/f'v68_narrative_{slug}.csv')
        _write_json(diag, REPORT_DIR/f'v68_news_diag_{slug}.json')
        result[slug] = {'news_rows': len(news), 'company_rows': len(company), 'macro_rows': len(macro), 'narrative_rows': len(narrative)}
    _write_json(result, REPORT_DIR/'v68_status.json')
    return result
