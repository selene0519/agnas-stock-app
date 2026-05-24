
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
import requests

from core.v69_finance_api_engine import (
    REPORT_DIR, DATA_DIR, FUND_DIR, NEWS_DIR,
    _now, _to_float, _fmt_num, _market_slug, _market_name,
    _read_csv, _write_csv, _write_json, _env, _load_dotenv_soft,
    _symbol_candidates, _build_v69_company_cards, _build_v69_news_cards,
    _build_macro_cards, _build_narrative,
)

KR_DOMESTIC_SOURCES = [
    '연합뉴스','Yonhap','Investing.com 한국','Investing.com','인베스팅','한국경제','한경','매일경제','머니투데이',
    '이데일리','서울경제','파이낸셜뉴스','조선비즈','비즈니스워치','아시아경제','헤럴드경제','뉴스1','뉴시스',
    '전자신문','ZDNet Korea','블로터','더벨','데일리안','SBS Biz','KBS','MBC','SBS','JTBC','매경',
]
KR_KEYWORDS = ['코스피','코스닥','국내 증시','한국 증시','삼성전자','SK하이닉스','외국인','기관','환율','원달러','반도체','2차전지','방산','로봇','조선','증권가']
FOREIGN_ONLY_HINTS = ['Free Press Journal','US-Iran','Nikkei','Brent','Asian Indices','Japan','South Korea consumer sentiment']


def _has_hangul(s: str) -> bool:
    return bool(re.search(r'[가-힣]', str(s or '')))


def _is_domestic_kr_news(row: dict[str, Any]) -> bool:
    text = ' '.join(str(row.get(k, '')) for k in ['제목','요약','출처','source','검색어'])
    if any(x.lower() in text.lower() for x in FOREIGN_ONLY_HINTS):
        return False
    if any(src.lower() in text.lower() for src in KR_DOMESTIC_SOURCES):
        return True
    if _has_hangul(text) and any(k in text for k in KR_KEYWORDS):
        return True
    if _has_hangul(text) and re.search(r'증시|코스피|코스닥|주식|반도체|외국인|기관', text):
        return True
    return False


def _google_news_rss(query: str, market: str, limit: int = 12) -> pd.DataFrame:
    slug = _market_slug(market)
    if slug == 'kr':
        url = 'https://news.google.com/rss/search?q=' + quote_plus(query) + '&hl=ko&gl=KR&ceid=KR:ko'
    else:
        url = 'https://news.google.com/rss/search?q=' + quote_plus(query) + '&hl=en-US&gl=US&ceid=US:en'
    rows=[]
    try:
        r = requests.get(url, timeout=15, headers={'User-Agent':'MONE stock app news fetcher'})
        if r.status_code != 200:
            return pd.DataFrame()
        root = ET.fromstring(r.content)
        for item in root.findall('.//item')[:limit]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            source = ''
            src = item.find('source')
            if src is not None and src.text:
                source = src.text.strip()
            if not source:
                # Google News title often has " - Source" suffix
                if ' - ' in title:
                    source = title.rsplit(' - ',1)[-1].strip()
            clean_title = title
            if ' - ' in clean_title:
                clean_title = clean_title.rsplit(' - ',1)[0].strip()
            rows.append({'시장':_market_name(slug),'제목':clean_title,'요약':'','출처':source or 'Google News RSS','URL':link,'게시시간':pub,'검색어':query,'수집방식':'Google News RSS'})
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _kr_news_strict() -> tuple[pd.DataFrame, dict[str, Any]]:
    queries = [
        '연합뉴스 코스피 코스닥 증시',
        '인베스팅닷컴 한국 증시 코스피 코스닥',
        '국내 증시 외국인 기관 수급 코스피 코스닥',
        '삼성전자 SK하이닉스 반도체 증시',
        '한국경제 코스피 코스닥 반도체 2차전지',
        '매일경제 코스피 코스닥 증시',
    ]
    parts=[]; attempts=[]
    # existing v69 first, but strict-filter it.
    try:
        base, diag = _build_v69_news_cards('한국주식')
        attempts.append({'source':'v69_base','rows':len(base)})
        if not base.empty:
            recs=[]
            for _, r in base.iterrows():
                d = r.to_dict()
                if _is_domestic_kr_news(d):
                    recs.append(d)
            if recs:
                parts.append(pd.DataFrame(recs))
    except Exception as exc:
        attempts.append({'source':'v69_base','error':f'{type(exc).__name__}: {exc}'})
    for q in queries:
        df = _google_news_rss(q, '한국주식', limit=12)
        attempts.append({'source':'rss','query':q,'rows':len(df)})
        if not df.empty:
            recs=[]
            for _, r in df.iterrows():
                d = r.to_dict()
                if _is_domestic_kr_news(d):
                    recs.append(d)
            if recs:
                parts.append(pd.DataFrame(recs))
    out = pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
    if not out.empty:
        out = out.drop_duplicates(subset=['제목']).head(30).reset_index(drop=True)
        out['간략 번역'] = out.apply(lambda r: _kr_interpret(str(r.get('제목','')), str(r.get('요약',''))), axis=1)
    diag = {'market':'한국주식','updated_at':_now(),'mode':'strict_domestic_kr_news','attempts':attempts,'rows':len(out)}
    return out, diag


def _kr_interpret(title: str, desc: str = '') -> str:
    text = title + ' ' + desc
    if '외국인' in text or '기관' in text or '수급' in text:
        return '국내 증시 수급 관련 뉴스입니다. 외국인·기관 흐름과 거래대금을 같이 확인하세요.'
    if '반도체' in text or '삼성전자' in text or 'SK하이닉스' in text:
        return '국내 반도체 섹터 관련 뉴스입니다. 삼성전자·SK하이닉스와 후공정/장비주 흐름을 함께 봅니다.'
    if '코스피' in text or '코스닥' in text or '증시' in text:
        return '국내 시장 흐름 뉴스입니다. 개별 종목보다 시장 방향 확인용으로 먼저 봅니다.'
    if '환율' in text or '원달러' in text:
        return '환율 관련 뉴스입니다. 외국인 수급과 수출주/성장주 변동성에 영향을 줄 수 있습니다.'
    return '국장 관련 뉴스입니다. 뉴스만으로 매수하지 말고 기준가·거래량·수급을 함께 확인하세요.'


def _us_news() -> tuple[pd.DataFrame, dict[str, Any]]:
    parts=[]; attempts=[]
    try:
        base, diag = _build_v69_news_cards('미국주식')
        attempts.append({'source':'v69_base','rows':len(base)})
        if not base.empty:
            parts.append(base)
    except Exception as exc:
        attempts.append({'source':'v69_base','error':f'{type(exc).__name__}: {exc}'})
    for q in ['US stock market Nasdaq S&P 500', 'Nvidia AI semiconductor stocks', 'Federal Reserve Treasury yields stocks']:
        df = _google_news_rss(q, '미국주식', limit=10)
        attempts.append({'source':'rss','query':q,'rows':len(df)})
        if not df.empty:
            parts.append(df)
    out = pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
    if not out.empty:
        out = out.drop_duplicates(subset=['제목']).head(30).reset_index(drop=True)
        out['간략 번역'] = out.apply(lambda r: _us_interpret(str(r.get('제목','')), str(r.get('요약',''))), axis=1)
    return out, {'market':'미국주식','updated_at':_now(),'mode':'us_news_with_brief_ko','attempts':attempts,'rows':len(out)}


def _us_interpret(title: str, desc: str = '') -> str:
    t = (title + ' ' + desc).lower()
    if any(k in t for k in ['nvidia','ai','semiconductor','chip']):
        return '간략 번역: AI·반도체 관련 뉴스입니다. 엔비디아와 반도체/AI 인프라 종목의 투자심리에 영향을 줄 수 있습니다.'
    if any(k in t for k in ['fed','federal reserve','treasury','yield','inflation','rate']):
        return '간략 번역: 연준·금리·물가 관련 뉴스입니다. 성장주와 기술주 변동성에 영향을 줄 수 있습니다.'
    if any(k in t for k in ['nasdaq','s&p','stock market','wall street']):
        return '간략 번역: 미국 증시 전반 흐름에 관한 뉴스입니다. 개별 종목보다 시장 방향 확인용으로 봅니다.'
    return '간략 번역: 미국 시장 관련 뉴스입니다. 기준가·거래량·시장 방향과 함께 확인하세요.'


def _build_v70_news_cards(market: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    slug = _market_slug(market)
    if slug == 'kr':
        df, diag = _kr_news_strict()
    else:
        df, diag = _us_news()
    _write_csv(df, REPORT_DIR / f'v70_news_cards_{slug}.csv')
    _write_json(diag, REPORT_DIR / f'v70_news_diag_{slug}.json')
    return df, diag


def _build_v70_company_cards(market: str) -> pd.DataFrame:
    # Use v69 API engine, then add clearer status/reasons and save as v70.
    slug = _market_slug(market)
    df = _build_v69_company_cards(market, limit=18)
    if df.empty:
        df = pd.DataFrame([{'시장':_market_name(slug),'종목코드':'-','종목명':'-','재무상태':'데이터 없음','데이터출처':'-','초보자 해석':'API 호출 결과가 비어 있습니다. .env 키와 종목 매핑을 확인하세요.','다음 행동':'데이터 연결 점검에서 DART/Finnhub/SEC 상태를 확인하세요.'}])
    else:
        def reason(row):
            st = str(row.get('재무상태',''))
            if st == '재무/KPI 수신':
                return '실제 재무/KPI 값 수신. 장기 보유 판단에 참고 가능합니다.'
            if slug == 'kr':
                return f"DART 상태: {row.get('DART상태','-')} / {row.get('오류','') or 'corp_code·사업연도·보고서 응답을 확인하세요.'}"
            return f"Finnhub 상태: {row.get('Finnhub상태','-')} / SEC 상태: {row.get('SEC상태','-')}"
        df['데이터상태설명'] = df.apply(reason, axis=1)
    _write_csv(df, REPORT_DIR / f'v70_company_cards_{slug}.csv')
    return df


def _yf_latest(ticker: str) -> dict[str, Any]:
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period='5d')
        if hist is None or hist.empty:
            return {'상태':'데이터 없음'}
        close = float(hist['Close'].dropna().iloc[-1])
        prev = float(hist['Close'].dropna().iloc[-2]) if len(hist['Close'].dropna()) >= 2 else None
        chg = (close/prev-1)*100 if prev else None
        return {'상태':'수신','값':close,'변화율':chg,'티커':ticker,'출처':'yfinance 직전 종가'}
    except Exception as exc:
        return {'상태':f'{type(exc).__name__}', '티커':ticker, '출처':'yfinance'}


def _build_v70_macro_cards(market: str) -> pd.DataFrame:
    slug = _market_slug(market)
    rows=[]
    if slug == 'kr':
        items=[('시장 국면','^KS11','KOSPI 직전 종가'),('시장 폭','^KQ11','KOSDAQ 직전 종가'),('환율','KRW=X','USD/KRW 참고')]
    else:
        items=[('시장 국면','^GSPC','S&P500 직전 종가'),('시장 폭','^IXIC','NASDAQ 직전 종가'),('변동성','^VIX','VIX 직전 종가')]
    for name,ticker,desc in items:
        d=_yf_latest(ticker)
        val=d.get('값')
        chg=d.get('변화율')
        해석='시장 참고 지표입니다.'
        if val is not None and chg is not None:
            해석 = '시장 흐름이 우호적입니다.' if chg >= 0 else '시장 흐름이 약합니다. 신규매수 비중을 낮춥니다.'
        rows.append({'시장':_market_name(slug),'카드':name,'지표':desc,'티커':ticker,'값':val if val is not None else '-','변화율':f'{chg:.2f}%' if chg is not None else '-', '상태':d.get('상태','-'),'해석':해석,'출처':d.get('출처','-')})
    df=pd.DataFrame(rows)
    _write_csv(df, REPORT_DIR / f'v70_macro_cards_{slug}.csv')
    return df


def _build_v70_narrative(market: str, news: pd.DataFrame, company: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    slug = _market_slug(market)
    syms = _symbol_candidates(market, limit=12)
    rows=[]
    news_hint = '국내 증시 뉴스 수집됨' if slug=='kr' and not news.empty else ('미국 증시 뉴스 수집됨' if not news.empty else '뉴스 데이터 부족')
    macro_hint = '' if macro.empty else ' / '.join([f"{r.get('카드','')}: {r.get('해석','')}" for _,r in macro.head(2).iterrows()])
    for _, r in syms.iterrows():
        sym=str(r.get('종목코드','')).strip(); name=str(r.get('종목명','') or sym)
        c = company[company.get('종목코드', pd.Series(dtype=str)).astype(str).str.upper()==sym.upper()] if not company.empty and '종목코드' in company.columns else pd.DataFrame()
        fstate = str(c.iloc[0].get('재무상태','재무 데이터 부족')) if not c.empty else '재무 데이터 부족'
        narrative = f"{name}({sym})은 {_market_name(slug)} 기준으로 뉴스·재무·시장 흐름을 함께 확인합니다. 뉴스 상태: {news_hint}. 재무 상태: {fstate}."
        rows.append({'시장':_market_name(slug),'종목코드':sym,'종목':name,'내러티브':narrative,'시장 배경':macro_hint or '시장·거시 데이터가 부족합니다.','주의':'뉴스만으로 매수하지 말고 기준가·거래량·리스크를 함께 확인하세요.'})
    df=pd.DataFrame(rows)
    _write_csv(df, REPORT_DIR / f'v70_narrative_{slug}.csv')
    return df


def run_v70_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _load_dotenv_soft()
    env_status = {k: bool(_env(k)) for k in ['GNEWS_API_KEY','FINNHUB_API_KEY','DART_API_KEY','APIFY_TOKEN','APIFY_NEWS_ACTOR_ID','SEC_USER_AGENT']}
    result: dict[str, Any] = {'status':'OK','version':'v70','updated_at':_now(),'env':env_status}
    for slug in ['kr','us']:
        market=_market_name(slug)
        news, ndiag = _build_v70_news_cards(market) if fetch_news else (_read_csv(REPORT_DIR / f'v70_news_cards_{slug}.csv'), {'status':'SKIPPED'})
        company = _build_v70_company_cards(market) if fetch_fundamentals else _read_csv(REPORT_DIR / f'v70_company_cards_{slug}.csv')
        macro = _build_v70_macro_cards(market) if fetch_macro else _read_csv(REPORT_DIR / f'v70_macro_cards_{slug}.csv')
        narrative = _build_v70_narrative(market, news, company, macro)
        result[slug] = {'news_rows':len(news),'company_rows':len(company),'macro_rows':len(macro),'narrative_rows':len(narrative),'news_diag':ndiag}
    _write_json(result, REPORT_DIR / 'v70_status.json')
    return result
