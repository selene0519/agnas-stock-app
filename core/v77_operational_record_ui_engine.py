
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v75_donhyun_quant_complete_engine import run_v75_update
except Exception:  # pragma: no cover
    run_v75_update = None

REPORT_DIR = Path('reports')
DATA_DIR = Path('data')
HISTORY_DIR = DATA_DIR / 'history'
NONE_SET = {'', '-', 'nan', 'none', 'null', 'nat', 'None', 'NaN'}
KR_CODE_RE = re.compile(r'^\d{5,6}$')
US_TICKER_RE = re.compile(r'^[A-Z]{1,5}(?:[.-][A-Z]{1,3})?$')
HANGUL_RE = re.compile(r'[가-힣]')
COMMON_US = {
    'AAPL','MSFT','GOOGL','GOOG','NVDA','TSLA','AMZN','META','NFLX','AMD','INTC','PLTR','LITE','SNDK','CAT','CRCL','NBIS',
    'AAOI','ASTS','BMNR','COIN','MSTR','AVGO','ORCL','SMCI','SPY','QQQ','DIA','IWM','VOO','VTI','XLF','XLK','XLE','XLV',
    'NKE','JPM','BAC','C','WMT','COST','HD','LOW','DIS','PYPL','UBER','SHOP','SQ','AFRM','SOFI','RIVN','LCID','BABA','TSM',
}
US_WORDS = {'NASDAQ','NYSE','AMEX','미국','미장','미국주식','US','USA','United States'}
KR_WORDS = {'한국','국장','한국주식','KOSPI','KOSDAQ','코스피','코스닥','KRX'}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _ensure_dotenv() -> None:
    paths = [Path('.env'), Path.cwd()/'.env']
    try:
        from dotenv import load_dotenv  # type: ignore
        for p in paths:
            if p.exists():
                load_dotenv(p, override=False)
    except Exception:
        pass
    for p in paths:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding='utf-8-sig', errors='ignore').splitlines():
                s = line.strip()
                if not s or s.startswith('#') or '=' not in s:
                    continue
                k, v = s.split('=', 1)
                k = k.strip().lstrip('\ufeff')
                v = v.strip().strip('"').strip("'")
                if k and v and not os.environ.get(k):
                    os.environ[k] = v
        except Exception:
            pass
    aliases = {
        'DART_API_KEY': ['DART_KEY','OPENDART_API_KEY','OPEN_DART_API_KEY','DART_API'],
        'FINNHUB_API_KEY': ['FINNHUB_KEY','FINNHUB_TOKEN'],
        'GNEWS_API_KEY': ['GNEWS_KEY','GNEWS_TOKEN'],
        'APIFY_TOKEN': ['APIFY_API_TOKEN'],
        'SEC_USER_AGENT': ['SEC_EMAIL','SEC_UA'],
    }
    for primary, alts in aliases.items():
        if not os.environ.get(primary):
            for alt in alts:
                if os.environ.get(alt):
                    os.environ[primary] = os.environ.get(alt, '')
                    break


def _env(name: str) -> str:
    _ensure_dotenv()
    return os.environ.get(name, '').strip()


def _clean(v: Any) -> str:
    if v is None:
        return ''
    s = str(v).strip()
    if s.lower() in {x.lower() for x in NONE_SET}:
        return ''
    return s


def _read_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.is_absolute():
        p = REPORT_DIR / p
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ('utf-8-sig','utf-8','cp949'):
        try:
            return pd.read_csv(p, encoding=enc, dtype=str).fillna('')
        except Exception:
            continue
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


def _row_text(row: pd.Series) -> str:
    return ' '.join(_clean(row.get(c)) for c in row.index)


def _symbols(row: pd.Series) -> list[str]:
    vals = []
    for c in ['종목코드','종목','symbol','ticker','티커','코드','TOP','카드제목','종목명']:
        if c in row.index and _clean(row.get(c)):
            vals.append(_clean(row.get(c)))
    text = ' '.join(vals)
    syms = [s.upper() for s in re.findall(r'\b[A-Z]{1,5}(?:[.-][A-Z]{1,3})?\b', text)]
    for v in vals:
        z = _zcode(v)
        if KR_CODE_RE.fullmatch(z):
            syms.append(z)
    return list(dict.fromkeys(syms))


def _row_ok(row: pd.Series, slug: str) -> bool:
    text = _row_text(row)
    syms = _symbols(row)
    has_us = any(s in COMMON_US or US_TICKER_RE.fullmatch(s) for s in syms)
    has_kr = any(KR_CODE_RE.fullmatch(_zcode(s)) for s in syms) or (bool(HANGUL_RE.search(text)) and not has_us)
    if slug == 'kr':
        if has_us or any(w.lower() in text.lower() for w in US_WORDS):
            return False
        return has_kr
    if slug == 'us':
        if has_kr and not has_us:
            return False
        if any(w.lower() in text.lower() for w in KR_WORDS):
            return False
        return has_us
    return True


def _clean_market_df(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy().fillna('')
    mask = [_row_ok(r, slug) for _, r in out.iterrows()]
    out = out.loc[mask].copy().reset_index(drop=True)
    if out.empty:
        return out
    out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    if '종목코드' in out.columns:
        out['종목코드'] = out['종목코드'].apply(_zcode) if slug == 'kr' else out['종목코드'].astype(str).str.upper().str.strip()
    return out


def _pick(names: list[str], slug: str) -> pd.DataFrame:
    for name in names:
        df = _read_csv(name.format(slug=slug))
        if not df.empty:
            return df
    return pd.DataFrame()


def _ensure_schema(df: pd.DataFrame, kind: str, slug: str) -> pd.DataFrame:
    if df is not None and not df.empty:
        return df
    market = '한국주식' if slug == 'kr' else '미국주식'
    cols = {
        'action': ['종목코드','종목명','시장','상태','기준가','손절가','목표가','해석','다음 행동'],
        'pullback': ['종목코드','종목명','시장','상태','기준가','손절가','목표가','해석','다음 행동'],
        'flow': ['종목코드','종목명','시장','수급기준','현재가/직전종가','등락률','거래량','거래대금','수급점수','해석','다음 행동'],
        'risk': ['종목코드','종목명','시장','위험구분','해석','다음 행동'],
        'company': ['종목코드','종목명','시장','PER','PBR','ROE','재무상태','데이터출처','다음 행동'],
    }.get(kind, ['종목코드','종목명','시장','상태','해석','다음 행동'])
    return pd.DataFrame(columns=cols)


def _first(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return '-'
    r = df.iloc[0]
    for c in ['종목명','종목코드','종목','symbol','ticker','TOP']:
        if c in df.columns and _clean(r.get(c)):
            return _clean(r.get(c))
    return '-'


def _to_num(v: Any) -> float:
    s = _clean(v).replace('%','').replace('$','').replace('원','').replace(',','').strip()
    try:
        return float(s)
    except Exception:
        return float('nan')


def _company(slug: str) -> pd.DataFrame:
    df = _pick(['v75_company_clean_{slug}.csv','v74_company_clean_{slug}.csv','v70_company_cards_{slug}.csv','v69_company_cards_{slug}.csv','operational_financial_kpi_{slug}.csv'], slug)
    return _clean_market_df(df, slug)


def _frames(slug: str) -> dict[str, pd.DataFrame]:
    action = _clean_market_df(_pick(['v75_action_clean_{slug}.csv','v74_action_clean_{slug}.csv','v73_action_clean_{slug}.csv','v67_action_board_{slug}.csv','swing_candidates_{slug}_A_top3.csv'], slug), slug)
    pull = _clean_market_df(_pick(['v75_pullback_clean_{slug}.csv','v74_pullback_clean_{slug}.csv','v73_pullback_clean_{slug}.csv','v67_pullback_{slug}.csv','swing_candidates_{slug}_B_watch.csv'], slug), slug)
    flow = _clean_market_df(_pick(['v75_flow_clean_{slug}.csv','v74_flow_clean_{slug}.csv','v73_flow_clean_{slug}.csv','v67_flow_{slug}.csv','intraday_flow_snapshot.csv'], slug), slug)
    risk = _clean_market_df(_pick(['v75_risk_clean_{slug}.csv','v74_risk_clean_{slug}.csv','v73_risk_clean_{slug}.csv','v67_risk_{slug}.csv','v52_buy_risk_light.csv'], slug), slug)
    company = _company(slug)
    return {k: _ensure_schema(v, k, slug) for k, v in {'action':action, 'pullback':pull, 'flow':flow, 'risk':risk, 'company':company}.items()}


def _news_filter(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = _clean_market_df(df, slug) if any(c in df.columns for c in ['종목코드','종목명','시장']) else df.copy().fillna('')
    keep = []
    for _, row in out.iterrows():
        text = _row_text(row)
        tl = text.lower()
        if slug == 'kr':
            domestic = bool(HANGUL_RE.search(text)) and any(k in text for k in ['코스피','코스닥','국내','한국','증시','외국인','기관','삼성전자','SK하이닉스','연합뉴스','한국경제','매일경제','머니투데이','이데일리'])
            foreign = any(k.lower() in tl for k in ['asian indices','nikkei','brent','us-iran','wall street','s&p 500','nasdaq futures','federal reserve'])
            keep.append(domestic and not foreign)
        else:
            keep.append(not any(k in text for k in ['코스피','코스닥','국내 증시','한국 증시']))
    out = out.loc[keep].copy().reset_index(drop=True)
    if not out.empty:
        out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    return out


def _positions(slug: str) -> pd.DataFrame:
    df = _pick(['v75_position_cards_{slug}.csv','v74_position_cards_{slug}.csv','v73_position_cards_{slug}.csv','v72_position_cards_{slug}.csv','v67_position_plan_{slug}.csv','v50_position_plan.csv'], slug)
    return _clean_market_df(df, slug)


def _sector_strength(slug: str, *dfs: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for df in dfs:
        if df is None or df.empty:
            continue
        col = next((c for c in ['섹터','업종','sector','업종명','테마','sector_proxy'] if c in df.columns), None)
        if col:
            t = df[[col]].rename(columns={col:'섹터'}).copy(); t['가중치'] = 1; parts.append(t)
    if not parts:
        return pd.DataFrame(columns=['섹터','후보수','강도점수','해석'])
    x = pd.concat(parts, ignore_index=True)
    x['섹터'] = x['섹터'].astype(str).replace({'':'미분류','-':'미분류','nan':'미분류','None':'미분류'})
    g = x.groupby('섹터', as_index=False).agg(후보수=('섹터','size'), 강도점수=('가중치','sum')).sort_values(['강도점수','후보수'], ascending=False)
    g['해석'] = g['후보수'].apply(lambda n: f'후보 {int(n)}개')
    return g.head(12).reset_index(drop=True)


def _market_guard(slug: str, frames: dict[str, pd.DataFrame], sector: pd.DataFrame) -> pd.DataFrame:
    risk_ratio = len(frames['risk']) / max(len(frames['action']), 1) if len(frames['action']) else (1.0 if len(frames['risk']) else 0.0)
    score = round(max(0, min(100, 55 + min(len(frames['flow']), 10) - min(risk_ratio * 25, 25))), 1)
    phase = '우호' if score >= 70 else ('중립' if score >= 50 else '주의')
    strongest = '-' if sector.empty else _clean(sector.iloc[0].get('섹터')) or '-'
    return pd.DataFrame([
        {'항목':'시장 가드','값':phase,'점수':score,'다음 행동':'우호=정상, 중립=분할, 주의=축소'},
        {'항목':'수급 후보','값':f"{len(frames['flow'])}개",'점수':min(100, len(frames['flow'])*10),'다음 행동':'거래대금 확인'},
        {'항목':'섹터 강도','값':strongest,'점수':_to_num(sector.iloc[0].get('강도점수')) if not sector.empty else 0,'다음 행동':'강한 섹터 우선'},
        {'항목':'위험 후보','값':f"{len(frames['risk'])}개",'점수':round(100-min(risk_ratio*100,100),1),'다음 행동':'위험 후보 제외'},
    ])


def _portfolio_risk(slug: str, pos: pd.DataFrame) -> pd.DataFrame:
    if pos is None or pos.empty:
        return pd.DataFrame([{'항목':'보유종목','값':'0개','상태':'데이터 없음'}])
    vals = []
    for _, r in pos.iterrows():
        qty = _to_num(r.get('보유수량'))
        cur = _to_num(r.get('현재가'))
        if not math.isnan(qty) and not math.isnan(cur): vals.append(qty*cur)
    total = sum(vals); max_w = max(vals)/total*100 if total else 0
    return pd.DataFrame([
        {'항목':'총 평가액','값':round(total,2),'상태':'직전 가격 기준'},
        {'항목':'최대 비중','값':f'{max_w:.1f}%','상태':'주의' if max_w >= 45 else '보통'},
        {'항목':'VaR 95%','값':round(total*0.025,2) if total else 0,'상태':'간이 추정'},
        {'항목':'CVaR','값':round(total*0.04,2) if total else 0,'상태':'간이 추정'},
    ])


def _summary(slug: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame([
        {'카드':'오늘 우선 확인','아이콘':'🎯','설명':'기준가·손절가·목표가','건수':len(frames['action']),'TOP':_first(frames['action']),'상세파일':f'v77_action_clean_{slug}.csv','우선순위':1,'구분':'buy'},
        {'카드':'눌림목 진입 후보','아이콘':'🪜','설명':'추격보다 기준가 대기','건수':len(frames['pullback']),'TOP':_first(frames['pullback']),'상세파일':f'v77_pullback_clean_{slug}.csv','우선순위':2,'구분':'buy'},
        {'카드':'수급 급증 후보','아이콘':'💚','설명':'거래대금·수급 흐름','건수':len(frames['flow']),'TOP':_first(frames['flow']),'상세파일':f'v77_flow_clean_{slug}.csv','우선순위':3,'구분':'buy'},
        {'카드':'실적·저평가 후보','아이콘':'💎','설명':'재무·KPI·밸류','건수':len(frames['company']),'TOP':_first(frames['company']),'상세파일':f'v77_company_clean_{slug}.csv','우선순위':4,'구분':'value'},
        {'카드':'매수금지·주의','아이콘':'🚫','설명':'제외·관망 우선','건수':len(frames['risk']),'TOP':_first(frames['risk']),'상세파일':f'v77_risk_clean_{slug}.csv','우선순위':5,'구분':'risk'},
    ])


def _future(slug: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for kind, label, base_prob in [('action','오늘 확인',58),('pullback','눌림목',55),('flow','수급',57),('company','실적·저평가',54),('risk','주의/제외',42)]:
        df = frames.get(kind, pd.DataFrame())
        for _, r in df.head(30).iterrows():
            code = _clean(r.get('종목코드')) or _clean(r.get('symbol')) or _clean(r.get('ticker'))
            name = _clean(r.get('종목명')) or _clean(r.get('종목')) or code
            rows.append({'시장':'한국주식' if slug=='kr' else '미국주식','종목코드':_zcode(code) if slug=='kr' else code.upper(),'종목명':name,'분류':label,'기준가':_clean(r.get('기준가')) or _clean(r.get('현재가/직전종가')) or '-', '1일상승확률':f'{base_prob}%', '3일상승확률':f'{min(75,base_prob+3)}%', '5일상승확률':f'{min(78,base_prob+5)}%', '신뢰도':'낮음' if label=='주의/제외' else '기록 축적 중','다음 행동':'실제 결과가 쌓이면 자동 보정'})
    return pd.DataFrame(rows)


def _quant_outputs(slug: str, frames: dict[str, pd.DataFrame], pos: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        'portfolio_risk': _portfolio_risk(slug, pos),
        'backtest': pd.DataFrame([{'항목':'전략 표본','값':len(frames['action']),'해석':'기록 축적 중'}, {'항목':'위험 제외','값':len(frames['risk']),'해석':'회피 성과 추적 중'}]),
        'correlation': pd.DataFrame([{'페어':'보유 1위 x 보유 2위','상관':'기록 부족','해석':'가격 기록이 쌓이면 계산'}, {'페어':'시장지수 x 후보군','상관':'기록 부족','해석':'시장 민감도 확인용'}]),
        'monte_carlo': pd.DataFrame([{'항목':'시뮬레이션 상태','값':'대기','해석':'수익률 이력이 쌓이면 표시'}, {'항목':'필요 기록','값':'20거래일 이상','해석':'최소 표본'}]),
    }


def _append_history(slug: str, frames: dict[str, pd.DataFrame]) -> int:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / 'prediction_history.csv'
    today = datetime.now().strftime('%Y-%m-%d')
    rows = []
    for kind, label in [('action','오늘확인'),('pullback','눌림목'),('flow','수급'),('company','실적저평가'),('risk','매수주의')]:
        df = frames.get(kind, pd.DataFrame())
        for _, r in df.iterrows():
            code = _clean(r.get('종목코드')) or _clean(r.get('symbol')) or _clean(r.get('ticker')) or _clean(r.get('종목'))
            name = _clean(r.get('종목명')) or _clean(r.get('종목')) or code
            rows.append({'date':today,'updated_at':_now(),'market':'KR' if slug=='kr' else 'US','category':label,'symbol':_zcode(code) if slug=='kr' else code.upper(),'name':name,'base_price':_clean(r.get('기준가')) or _clean(r.get('현재가/직전종가')) or _clean(r.get('현재가')),'stop':_clean(r.get('손절가')),'target':_clean(r.get('목표가')),'decision':_clean(r.get('다음 행동')) or _clean(r.get('해석'))})
    new = pd.DataFrame(rows)
    if new.empty: return 0
    old = _read_csv(path) if path.exists() else pd.DataFrame()
    all_df = pd.concat([old, new], ignore_index=True) if not old.empty else new
    all_df = all_df.drop_duplicates(subset=['date','market','category','symbol'], keep='last')
    all_df.to_csv(path, index=False, encoding='utf-8-sig')
    return len(new)


def _data_status(slug: str, frames: dict[str, pd.DataFrame], news: pd.DataFrame, pos: pd.DataFrame) -> pd.DataFrame:
    label = '국장' if slug=='kr' else '미장'
    env = {k: bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT']}
    return pd.DataFrame([
        {'시장':label,'항목':'오늘 후보','행수':len(frames['action']),'상태':'정상' if len(frames['action']) else '비어 있음','원인/설명':'기준가·손절가·목표가 후보'},
        {'시장':label,'항목':'수급·거래대금','행수':len(frames['flow']),'상태':'정상' if len(frames['flow']) else '적음/없음','원인/설명':'거래대금·거래량·수급점수 동시 통과 필요'},
        {'시장':label,'항목':'실적·저평가','행수':len(frames['company']),'상태':'정상' if len(frames['company']) else '적음/없음','원인/설명':'DART/Finnhub/SEC 응답·종목 매핑·PER/PBR/ROE 필요'},
        {'시장':label,'항목':'뉴스','행수':len(news),'상태':'정상' if len(news) else '없음','원인/설명':'국장은 국내뉴스 필터가 엄격함'},
        {'시장':label,'항목':'보유·매도','행수':len(pos),'상태':'정상' if len(pos) else '없음','원인/설명':'보유종목 파일 필요'},
        {'시장':label,'항목':'API 키','행수':sum(env.values()),'상태':'확인','원인/설명':json.dumps(env, ensure_ascii=False)},
    ])


def run_v77_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dotenv()
    base = {'status':'SKIPPED'}
    if run_v75_update is not None:
        try:
            base = run_v75_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status':'WARN','error':f'{type(exc).__name__}: {exc}'}
    status_parts = []
    result: dict[str, Any] = {'status':'OK','version':'v77','updated_at':_now(),'base':base}
    for slug in ['kr','us']:
        frames = _frames(slug)
        news = _news_filter(_pick(['v75_news_cards_{slug}.csv','v74_news_cards_{slug}.csv','v70_news_cards_{slug}.csv','gnews_latest_{slug}.csv'], slug), slug)
        pos = _positions(slug)
        sector = _sector_strength(slug, frames['action'], frames['flow'], frames['company'])
        guard = _market_guard(slug, frames, sector)
        summary = _summary(slug, frames)
        future = _future(slug, frames)
        for key, df in frames.items(): _write_csv(df, f'v77_{key}_clean_{slug}.csv')
        _write_csv(summary, f'v77_today_summary_{slug}.csv')
        _write_csv(news, f'v77_news_cards_{slug}.csv')
        _write_csv(pos, f'v77_position_cards_{slug}.csv')
        _write_csv(sector, f'v77_sector_strength_{slug}.csv')
        _write_csv(guard, f'v77_market_guard_{slug}.csv')
        _write_csv(future, f'v77_future_probability_{slug}.csv')
        q = _quant_outputs(slug, frames, pos)
        for k, df in q.items(): _write_csv(df, f'v77_quant_{k}_{slug}.csv')
        # alias for UI naming
        _write_csv(q['monte_carlo'], f'v77_monte_carlo_{slug}.csv')
        appended = _append_history(slug, frames)
        result[slug] = {k: len(v) for k, v in frames.items()} | {'summary':len(summary),'news':len(news),'positions':len(pos),'sector':len(sector),'future':len(future),'history_appended':appended}
        status_parts.append(_data_status(slug, frames, news, pos))
    status = pd.concat(status_parts, ignore_index=True) if status_parts else pd.DataFrame()
    _write_csv(status, 'v77_data_status.csv')
    out = {'status':'OK','version':'v77','updated_at':_now(),'result':result,'env':{k: bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT']}}
    _write_json(out, 'v77_status.json')
    return out


if __name__ == '__main__':
    print(json.dumps(run_v77_update(), ensure_ascii=False, indent=2, default=str))
