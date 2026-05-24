from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v70_news_finance_market_fix_engine import run_v70_update
except Exception:  # pragma: no cover
    run_v70_update = None

try:
    from core.v69_finance_api_engine import REPORT_DIR, _now, _read_csv, _write_csv, _write_json
except Exception:  # pragma: no cover
    REPORT_DIR = Path('reports')
    def _now() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    def _read_csv(path: str | Path) -> pd.DataFrame:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return pd.DataFrame()
        for enc in ('utf-8-sig','utf-8','cp949'):
            try:
                return pd.read_csv(p, encoding=enc)
            except Exception:
                pass
        return pd.DataFrame()
    def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False, encoding='utf-8-sig')
    def _write_json(data: dict[str, Any], path: str | Path) -> None:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

NONE_SET = {'', '-', 'nan', 'none', 'null', 'nat', 'None', 'NaN'}
US_TICKER_RE = re.compile(r'^[A-Z]{1,5}(?:[.-][A-Z])?$')
KR_CODE_RE = re.compile(r'^\d{5,6}$')
HANGUL_RE = re.compile(r'[가-힣]')

COMMON_US_TICKERS = {
    'AAPL','MSFT','GOOGL','GOOG','NVDA','TSLA','AMZN','META','NFLX','AMD','INTC','PLTR','LITE','SNDK','CAT','CRCL','NBIS',
    'AAOI','ASTS','BMNR','COIN','MSTR','AVGO','ORCL','SMCI','SPY','QQQ','DIA','IWM','VOO','VTI','XLF','XLK','XLE','XLV'
}

KR_NEWS_WORDS = (
    '코스피','코스닥','국내증시','한국증시','증시','외국인','기관','개인','수급','삼성전자','SK하이닉스','반도체','2차전지',
    '원화','환율','금리','한국거래소','장중','장마감','공시','실적','목표가','투자의견','연합뉴스','한국경제','매일경제','머니투데이',
    '이데일리','서울경제','파이낸셜뉴스','조선비즈','비즈워치','뉴시스','뉴스1','인베스팅닷컴'
)
KR_NEWS_SOURCES = (
    '연합뉴스','yna','한국경제','한경','매일경제','mk','머니투데이','이데일리','서울경제','파이낸셜뉴스','조선비즈',
    '비즈워치','비즈니스워치','뉴시스','뉴스1','인베스팅','investing.com','아시아경제','헤럴드경제','데일리안'
)
FOREIGN_ONLY_WORDS = (
    'Asian indices','Nikkei','Brent','US-Iran','Iran','Japan','Tokyo','Hong Kong','Wall Street','Dow Jones',
    'S&P 500','Nasdaq futures','Treasury yields','Federal Reserve','Fed officials','Oil prices','global markets'
)


def _ensure_dotenv() -> None:
    env_path = Path('.env')
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path)
    except Exception:
        pass
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding='utf-8').splitlines():
                s = line.strip()
                if not s or s.startswith('#') or '=' not in s:
                    continue
                k, v = s.split('=', 1)
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k and not os.environ.get(k):
                    os.environ[k] = v
        except Exception:
            pass


def _env(name: str) -> str:
    _ensure_dotenv()
    return os.environ.get(name, '').strip()


def _clean(v: Any) -> str:
    if v is None:
        return ''
    s = str(v).strip()
    if s.lower() in NONE_SET:
        return ''
    return s


def _safe_read(name: str | Path) -> pd.DataFrame:
    p = Path(name)
    if not p.is_absolute():
        p = REPORT_DIR / p
    try:
        return _read_csv(p)
    except Exception:
        return pd.DataFrame()


def _zcode(v: Any) -> str:
    s = _clean(v)
    if not s:
        return ''
    # 990.0, 990 -> 000990
    try:
        if re.fullmatch(r'\d+\.0', s):
            s = str(int(float(s)))
    except Exception:
        pass
    if re.fullmatch(r'\d{1,6}', s):
        return s.zfill(6)
    m = re.search(r'\b(\d{5,6})\b', s)
    if m:
        return m.group(1).zfill(6)
    return s


def _symbolish_values(row: pd.Series) -> list[str]:
    vals: list[str] = []
    for c in ['종목코드','종목','symbol','ticker','티커','코드','TOP']:
        if c in row.index and _clean(row.get(c)):
            vals.append(_clean(row.get(c)))
    # Pull codes inside parentheses too.
    for v in list(vals):
        for m in re.finditer(r'\(([A-Za-z0-9.\-]{1,10})\)', v):
            vals.append(m.group(1))
    return vals


def _name_values(row: pd.Series) -> str:
    vals = []
    for c in ['종목명','name','Name','카드제목','종목','TOP']:
        if c in row.index and _clean(row.get(c)):
            vals.append(_clean(row.get(c)))
    return ' '.join(vals)


def _has_us_symbol(row: pd.Series) -> bool:
    for v in _symbolish_values(row):
        s = _clean(v).upper()
        if s in COMMON_US_TICKERS:
            return True
        if US_TICKER_RE.fullmatch(s) and not KR_CODE_RE.fullmatch(s):
            return True
    return False


def _has_kr_symbol(row: pd.Series) -> bool:
    for v in _symbolish_values(row):
        z = _zcode(v)
        if KR_CODE_RE.fullmatch(z):
            return True
    return False


def _market_text(row: pd.Series) -> str:
    vals = []
    for c in ['시장','market','마켓']:
        if c in row.index:
            vals.append(_clean(row.get(c)))
    return ' '.join(vals)


def _row_market_ok(row: pd.Series, slug: str) -> bool:
    names = _name_values(row)
    market = _market_text(row)
    has_kr = _has_kr_symbol(row)
    has_us = _has_us_symbol(row)
    name_has_hangul = bool(HANGUL_RE.search(names))

    if slug == 'kr':
        # 핵심: 시장 컬럼이 한국주식이어도 종목코드가 GOOGL/NVDA 같은 미장 티커면 무조건 제외.
        if has_us and not has_kr:
            return False
        if re.search(r'미국|미장|NASDAQ|NYSE|AMEX|United States|US stock', market, re.I):
            return False
        return bool(has_kr or name_has_hangul)

    if slug == 'us':
        if has_kr and not has_us:
            return False
        if re.search(r'한국|국장|KOSPI|KOSDAQ|한국주식', market, re.I):
            return False
        return bool(has_us or re.search(r'미국|미장|NASDAQ|NYSE|미국주식', market, re.I))

    return True


def _clean_market_df(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    mask = [_row_market_ok(row, slug) for _, row in out.iterrows()]
    out = out.loc[mask].copy().reset_index(drop=True)
    if out.empty:
        return out
    out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    if slug == 'kr' and '종목코드' in out.columns:
        out['종목코드'] = out['종목코드'].apply(_zcode)
    return out


def _first_value(df: pd.DataFrame, *cols: str) -> str:
    if df is None or df.empty:
        return '후보 없음'
    row = df.iloc[0]
    for c in list(cols) + ['종목명','종목','종목코드','symbol','ticker','TOP']:
        if c in df.columns and _clean(row.get(c)):
            v = _clean(row.get(c))
            if c == '종목코드':
                v = _zcode(v)
            return v
    return '후보 있음'


def _pick_first_existing(names: list[str], slug: str) -> pd.DataFrame:
    for name in names:
        df = _safe_read(name.format(slug=slug))
        if not df.empty:
            return df
    return pd.DataFrame()


def _company_valid(slug: str) -> pd.DataFrame:
    df = _pick_first_existing([
        'v70_company_cards_{slug}.csv', 'v69_company_cards_{slug}.csv', 'v68_company_cards_{slug}.csv',
        'operational_financial_kpi_{slug}.csv', 'v50_fundamental_kpi_cards.csv'
    ], slug)
    df = _clean_market_df(df, slug)
    if df.empty:
        return pd.DataFrame()
    if '종목코드' in df.columns:
        df = df[~df['종목코드'].astype(str).str.strip().str.lower().isin(['', '-', 'nan', 'none', 'null'])]
    # Keep rows even when API failed, but real data first.
    score_col = None
    for c in ['DART상태','FINNHUB상태','SEC상태','재무상태','상태']:
        if c in df.columns:
            score_col = c; break
    if score_col:
        df['_ok'] = df[score_col].astype(str).str.contains('OK|수신|요약|가능|확인|200', case=False, regex=True, na=False).astype(int)
        df = df.sort_values('_ok', ascending=False).drop(columns=['_ok'], errors='ignore')
    return df.reset_index(drop=True)


def _domestic_news_only(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if slug == 'us':
        if '시장' in out.columns:
            out = out[~out['시장'].astype(str).str.contains('한국|국장|KOSPI|KOSDAQ', regex=True, na=False)]
        out['시장'] = '미국주식'
        return out.reset_index(drop=True)

    keep = []
    for _, row in out.iterrows():
        text = ' '.join(_clean(row.get(c)) for c in out.columns)
        text_l = text.lower()
        has_hangul = bool(HANGUL_RE.search(text))
        has_domestic_kw = any(w.lower() in text_l for w in KR_NEWS_WORDS)
        has_domestic_src = any(w.lower() in text_l for w in KR_NEWS_SOURCES)
        has_foreign_only = any(w.lower() in text_l for w in FOREIGN_ONLY_WORDS)
        # 국장 뉴스는 한글/국내 키워드/국내 출처 중 최소 2개 조건을 통과해야 표시.
        ok_score = int(has_hangul) + int(has_domestic_kw) + int(has_domestic_src)
        keep.append(ok_score >= 2 and not has_foreign_only)
    out = out.loc[keep].copy().reset_index(drop=True)
    if not out.empty:
        out['시장'] = '한국주식'
    return out


def _clean_macro(slug: str) -> pd.DataFrame:
    df = _pick_first_existing(['v70_macro_cards_{slug}.csv','v68_macro_cards_{slug}.csv','operational_macro_{slug}.csv'], slug)
    if df.empty:
        return pd.DataFrame(columns=['시장','카드','값','상태','해석','출처'])
    df = df.copy()
    df['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    for c in ['상태','해석','값','변화율']:
        if c in df.columns:
            df[c] = df[c].astype(str).replace({'ModuleNotFoundError':'수집 실패','nan':'-','None':'-','':'-'})
    return df.reset_index(drop=True)


def _position_cards(slug: str) -> pd.DataFrame:
    df = _pick_first_existing([
        'v73_position_cards_{slug}.csv','v72_position_cards_{slug}.csv','v71_position_cards_{slug}.csv',
        'v67_position_plan_{slug}.csv','v52_position_plan_light.csv','v51_position_plan_light.csv','v50_position_plan.csv'
    ], slug)
    df = _clean_market_df(df, slug)
    if df.empty:
        return pd.DataFrame()
    rows = []
    for _, r in df.iterrows():
        d = r.to_dict()
        code = _zcode(d.get('종목코드') or d.get('종목') or d.get('ticker') or d.get('symbol'))
        name = _clean(d.get('카드제목')) or _clean(d.get('종목명')) or _clean(d.get('종목')) or code or '-'
        action = _clean(d.get('판단')) or _clean(d.get('권장행동')) or '보유 점검'
        qty = _clean(d.get('보유수량')) or '-'
        avg = _clean(d.get('평단가')) or _clean(d.get('평단')) or '-'
        cur = _clean(d.get('현재가')) or '-'
        ret = _clean(d.get('수익률')) or '-'
        rec_qty = _clean(d.get('권장수량')) or '0'
        amt = _clean(d.get('예상금액')) or '-'
        src = _clean(d.get('가격출처표시')) or _clean(d.get('가격출처')) or '-'
        guide = _clean(d.get('다음행동표시')) or _clean(d.get('초보자 안내')) or _clean(d.get('다음 행동')) or '증권사 현재가 확인 후 결정'
        rows.append({**d, '시장':'한국주식' if slug=='kr' else '미국주식', '종목코드': code, '카드제목': name, '판단': action,
                     '핵심요약': f'보유 {qty} · 평단 {avg} · 현재가 {cur} · 수익률 {ret}',
                     '수량요약': f'권장수량 {rec_qty} · 예상금액 {amt}', '가격출처표시': src, '다음행동표시': guide})
    return pd.DataFrame(rows).reset_index(drop=True)


def _build_sector_strength(slug: str, action: pd.DataFrame, flow: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for df, w in [(action, 1.0), (flow, 1.5)]:
        if df is None or df.empty:
            continue
        col = next((c for c in ['섹터','업종','sector','업종명','테마'] if c in df.columns), None)
        if col:
            tmp = df[[col]].rename(columns={col:'섹터'}).copy()
            tmp['가중치'] = w
            parts.append(tmp)
    if not parts:
        return pd.DataFrame(columns=['섹터','후보수','강도점수','해석'])
    all_df = pd.concat(parts, ignore_index=True)
    all_df['섹터'] = all_df['섹터'].astype(str).replace({'nan':'미분류','None':'미분류','':'미분류','-':'미분류'})
    g = all_df.groupby('섹터', as_index=False).agg(후보수=('섹터','size'), 강도점수=('가중치','sum')).sort_values(['강도점수','후보수'], ascending=False)
    g['해석'] = g.apply(lambda r: f"후보 {int(r['후보수'])}개", axis=1)
    return g.head(12).reset_index(drop=True)


def _build_market_guard(slug: str, action: pd.DataFrame, flow: pd.DataFrame, risk: pd.DataFrame) -> pd.DataFrame:
    macro = _clean_macro(slug)
    sector = _build_sector_strength(slug, action, flow)
    changes = []
    if not macro.empty and '변화율' in macro.columns:
        for v in macro['변화율']:
            try:
                s = str(v).replace('%','').replace(',','').strip()
                if s and s not in {'-','nan','None','수집 실패'}:
                    changes.append(float(s))
            except Exception:
                pass
    avg = sum(changes)/len(changes) if changes else 0.0
    risk_ratio = len(risk) / max(len(action), 1) if len(action) else (1.0 if len(risk) else 0.0)
    score = round(max(0, min(100, 50 + avg*8 - min(risk_ratio*25, 25) + min(len(flow), 10))), 1)
    phase = '우호' if score >= 70 else ('중립' if score >= 50 else '주의')
    next_action = '정상 비중 가능' if phase == '우호' else ('분할/소액만' if phase == '중립' else '신규매수 축소')
    strongest = '-' if sector.empty else str(sector.iloc[0].get('섹터','-'))
    rows = [
        {'카드':'시장 국면','값':phase,'점수':score,'다음행동':next_action},
        {'카드':'시장 폭','값':f'{avg:.2f}%','점수':round(50+avg*10,1),'다음행동':'지수가 약하면 비중 축소'},
        {'카드':'섹터 강도','값':strongest,'점수':round(float(sector.iloc[0].get('강도점수',0)) if not sector.empty else 0,1),'다음행동':'강한 섹터만 우선'},
        {'카드':'리스크 룰','값':f'위험 {len(risk)}개','점수':round(100-min(risk_ratio*100,100),1),'다음행동':'위험 후보 제외'},
    ]
    return pd.DataFrame(rows)


def _make_action_frames(slug: str) -> dict[str, pd.DataFrame]:
    action = _clean_market_df(_pick_first_existing(['v67_action_board_{slug}.csv','v73_action_clean_{slug}.csv','v72_action_clean_{slug}.csv','swing_candidates_{slug}_A_top3.csv'], slug), slug)
    pull = _clean_market_df(_pick_first_existing(['v67_pullback_{slug}.csv','v73_pullback_clean_{slug}.csv','swing_candidates_{slug}_B_watch.csv'], slug), slug)
    flow = _clean_market_df(_pick_first_existing(['v67_flow_{slug}.csv','v73_flow_clean_{slug}.csv','intraday_flow_snapshot.csv'], slug), slug)
    risk = _clean_market_df(_pick_first_existing(['v67_risk_{slug}.csv','v73_risk_clean_{slug}.csv','v52_buy_risk_light.csv','swing_candidates_{slug}_C_excluded.csv'], slug), slug)
    company = _company_valid(slug)
    return {'action': action, 'pullback': pull, 'flow': flow, 'risk': risk, 'company': company}


def _write_all(slug: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    for key, df in frames.items():
        _write_csv(df, REPORT_DIR / f'v74_{key}_clean_{slug}.csv')
    rows = [
        {'카드':'오늘 우선 확인','아이콘':'🎯','설명':'기준가·손절가·목표가 먼저 확인','건수':len(frames['action']),'TOP':_first_value(frames['action']),'상세파일':f'v74_action_clean_{slug}.csv','우선순위':1,'구분':'buy'},
        {'카드':'눌림목 진입 후보','아이콘':'🪜','설명':'추격보다 기준가 근처 대기','건수':len(frames['pullback']),'TOP':_first_value(frames['pullback']),'상세파일':f'v74_pullback_clean_{slug}.csv','우선순위':2,'구분':'buy'},
        {'카드':'수급 급증 후보','아이콘':'💚','설명':'거래대금·수급 흐름 확인','건수':len(frames['flow']),'TOP':_first_value(frames['flow']),'상세파일':f'v74_flow_clean_{slug}.csv','우선순위':3,'구분':'buy'},
        {'카드':'실적·저평가 후보','아이콘':'💎','설명':'재무·KPI·밸류 확인','건수':len(frames['company']),'TOP':_first_value(frames['company'],'종목명','종목코드'),'상세파일':f'v74_company_clean_{slug}.csv','우선순위':4,'구분':'value'},
        {'카드':'매수금지·주의','아이콘':'🚫','설명':'신규매수보다 제외·관망','건수':len(frames['risk']),'TOP':_first_value(frames['risk']),'상세파일':f'v74_risk_clean_{slug}.csv','우선순위':5,'구분':'risk'},
    ]
    summary = pd.DataFrame(rows)
    _write_csv(summary, REPORT_DIR / f'v74_today_summary_{slug}.csv')
    pos = _position_cards(slug)
    _write_csv(pos, REPORT_DIR / f'v74_position_cards_{slug}.csv')
    news = _domestic_news_only(_pick_first_existing(['v70_news_cards_{slug}.csv','v68_news_cards_{slug}.csv','gnews_latest_{slug}.csv'], slug), slug)
    _write_csv(news, REPORT_DIR / f'v74_news_cards_{slug}.csv')
    macro = _clean_macro(slug)
    _write_csv(macro, REPORT_DIR / f'v74_macro_cards_{slug}.csv')
    guard = _build_market_guard(slug, frames['action'], frames['flow'], frames['risk'])
    _write_csv(guard, REPORT_DIR / f'v74_market_guard_{slug}.csv')
    sector = _build_sector_strength(slug, frames['action'], frames['flow'])
    _write_csv(sector, REPORT_DIR / f'v74_sector_strength_{slug}.csv')
    return summary


def _build_status(result: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for slug, label in [('kr','국장'), ('us','미장')]:
        for title, name in [
            ('오늘 실행 5카드', f'v74_today_summary_{slug}.csv'), ('오늘 후보', f'v74_action_clean_{slug}.csv'),
            ('눌림목', f'v74_pullback_clean_{slug}.csv'), ('수급', f'v74_flow_clean_{slug}.csv'),
            ('재무', f'v74_company_clean_{slug}.csv'), ('위험', f'v74_risk_clean_{slug}.csv'),
            ('뉴스', f'v74_news_cards_{slug}.csv'), ('시장 가드', f'v74_market_guard_{slug}.csv'),
            ('보유·매도', f'v74_position_cards_{slug}.csv')]:
            p = REPORT_DIR / name
            df = _safe_read(name)
            rows.append({'시장':label,'항목':title,'파일':name,'행수':0 if df.empty else len(df),'상태':'있음' if p.exists() and p.stat().st_size else '없음'})
    status_df = pd.DataFrame(rows)
    _write_csv(status_df, REPORT_DIR / 'v74_data_status.csv')
    out = {'status':'OK','version':'v74','updated_at':_now(),'base_result':result,'env':{k: bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT']},'data_status_rows':len(status_df)}
    _write_json(out, REPORT_DIR / 'v74_status.json')
    return out


def run_v74_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dotenv()
    base: dict[str, Any] = {'status':'SKIPPED','note':'v70 engine not available'}
    has_any_api = any(_env(k) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT'])
    if run_v70_update is not None and has_any_api:
        try:
            base = run_v70_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status':'WARN','error':f'{type(exc).__name__}: {exc}'}
    elif run_v70_update is not None and not has_any_api:
        base = {'status':'SKIPPED','note':'API key not detected in this environment; existing reports cleaned only'}
    result: dict[str, Any] = {'status':'OK','version':'v74','updated_at':_now(),'base':base}
    for slug in ['kr','us']:
        frames = _make_action_frames(slug)
        summary = _write_all(slug, frames)
        result[slug] = {k: len(v) for k, v in frames.items()} | {'summary': len(summary)}
    return _build_status(result)
