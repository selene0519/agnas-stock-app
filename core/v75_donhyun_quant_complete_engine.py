
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
    from core.v74_mone_complete_integration_engine import run_v74_update
except Exception:  # pragma: no cover
    run_v74_update = None

REPORT_DIR = Path('reports')
DATA_DIR = Path('data')
NONE_SET = {'', '-', 'nan', 'none', 'null', 'nat', 'None', 'NaN'}
KR_CODE_RE = re.compile(r'^\d{5,6}$')
US_TICKER_RE = re.compile(r'^[A-Z]{1,5}(?:[.-][A-Z])?$')
HANGUL_RE = re.compile(r'[가-힣]')
COMMON_US = {
    'AAPL','MSFT','GOOGL','GOOG','NVDA','TSLA','AMZN','META','NFLX','AMD','INTC','PLTR','LITE','SNDK','CAT','CRCL','NBIS',
    'AAOI','ASTS','BMNR','COIN','MSTR','AVGO','ORCL','SMCI','SPY','QQQ','DIA','IWM','VOO','VTI','XLF','XLK','XLE','XLV',
    'NKE','JPM','BAC','C','WMT','COST','HD','LOW','DIS','PYPL','UBER','SHOP','SQ','AFRM','SOFI','RIVN','LCID','BABA','TSM',
}
US_WORDS = {'NASDAQ','NYSE','AMEX','미국','미장','미국주식','US','USA','United States'}
KR_WORDS = {'한국','국장','한국주식','KOSPI','KOSDAQ','코스피','코스닥','KRX'}
KR_NEWS_WORDS = (
    '코스피','코스닥','국내증시','한국증시','증시','외국인','기관','개인','수급','삼성전자','SK하이닉스','반도체','2차전지',
    '원화','환율','금리','한국거래소','장중','장마감','공시','실적','목표가','투자의견','연합뉴스','한국경제','매일경제','머니투데이',
    '이데일리','서울경제','파이낸셜뉴스','조선비즈','비즈워치','뉴시스','뉴스1','인베스팅닷컴','국내 주식','한국 주식'
)
KR_NEWS_SOURCES = (
    '연합뉴스','yna','한국경제','한경','매일경제','mk','머니투데이','이데일리','서울경제','파이낸셜뉴스','조선비즈',
    '비즈워치','비즈니스워치','뉴시스','뉴스1','인베스팅','investing.com','아시아경제','헤럴드경제','데일리안','매경'
)
FOREIGN_NEWS_BLOCK = (
    'Asian indices','Nikkei','Brent','US-Iran','Iran','Japan','Tokyo','Hong Kong','Wall Street','Dow Jones','S&P 500',
    'Nasdaq futures','Treasury yields','Federal Reserve','Fed officials','Oil prices','global markets','China stocks','Europe stocks'
)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


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


def _ensure_schema(df: pd.DataFrame, kind: str, slug: str) -> pd.DataFrame:
    if df is not None and not df.empty:
        return df
    market = '한국주식' if slug == 'kr' else '미국주식'
    schemas = {
        'action': ['종목코드','종목명','시장','상태','기준가','손절가','목표가','해석','다음 행동'],
        'pullback': ['종목코드','종목명','시장','상태','기준가','손절가','목표가','해석','다음 행동'],
        'flow': ['종목코드','종목명','시장','상태','현재가','거래량','거래대금','수급점수','해석','다음 행동'],
        'risk': ['종목코드','종목명','시장','위험구분','해석','다음 행동'],
        'company': ['종목코드','종목명','시장','PER','PBR','ROE','성장률','상태','다음 행동'],
    }
    cols = schemas.get(kind, ['종목코드','종목명','시장','상태','해석','다음 행동'])
    return pd.DataFrame(columns=cols)


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
    if m:
        return m.group(1).zfill(6)
    return s


def _values(row: pd.Series, cols: list[str]) -> list[str]:
    out = []
    for c in cols:
        if c in row.index and _clean(row.get(c)):
            out.append(_clean(row.get(c)))
    for v in list(out):
        for m in re.finditer(r'\(([A-Za-z0-9.\-]{1,12})\)', v):
            out.append(m.group(1))
    return out


def _symbol_values(row: pd.Series) -> list[str]:
    return _values(row, ['종목코드','종목','symbol','ticker','티커','코드','TOP','카드제목','종목명'])


def _name_text(row: pd.Series) -> str:
    return ' '.join(_values(row, ['종목명','name','Name','카드제목','종목','TOP','회사명']))


def _market_text(row: pd.Series) -> str:
    return ' '.join(_values(row, ['시장','market','마켓','분류']))


def _is_known_us_token(s: str) -> bool:
    x = _clean(s).upper()
    if x in COMMON_US:
        return True
    if US_TICKER_RE.fullmatch(x) and not KR_CODE_RE.fullmatch(x):
        # 알파벳 대문자만 티커처럼 들어온 경우는 미장으로 본다.
        return True
    return False


def _has_us(row: pd.Series) -> bool:
    for v in _symbol_values(row):
        if _is_known_us_token(v):
            return True
    return any(w.lower() in _market_text(row).lower() for w in US_WORDS)


def _has_kr(row: pd.Series) -> bool:
    for v in _symbol_values(row):
        if KR_CODE_RE.fullmatch(_zcode(v)):
            return True
    names = _name_text(row)
    return bool(HANGUL_RE.search(names)) or any(w.lower() in _market_text(row).lower() for w in KR_WORDS)


def _row_ok(row: pd.Series, slug: str) -> bool:
    has_us = _has_us(row)
    has_kr = _has_kr(row)
    market = _market_text(row)
    if slug == 'kr':
        if has_us:
            return False
        if any(w.lower() in market.lower() for w in US_WORDS):
            return False
        return has_kr
    if slug == 'us':
        if has_kr and not has_us:
            return False
        if any(w.lower() in market.lower() for w in KR_WORDS):
            return False
        return has_us
    return True


def _clean_market_df(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    mask = [_row_ok(row, slug) for _, row in out.iterrows()]
    out = out.loc[mask].copy().reset_index(drop=True)
    if out.empty:
        return out
    out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    if '종목코드' in out.columns:
        if slug == 'kr':
            out['종목코드'] = out['종목코드'].apply(_zcode)
        else:
            out['종목코드'] = out['종목코드'].astype(str).str.upper().str.strip()
    # 보기 싫은 내부 열 제거는 UI에서도 하지만, 리포트도 정리한다.
    return out.reset_index(drop=True)


def _pick(names: list[str], slug: str) -> pd.DataFrame:
    for name in names:
        df = _read_csv(name.format(slug=slug))
        if not df.empty:
            return df
    return pd.DataFrame()


def _fallback_universe(slug: str) -> pd.DataFrame:
    p = DATA_DIR / 'reference_sources' / f'donhyun_candidate_universe_{slug}.csv'
    if not p.exists():
        return pd.DataFrame()
    df = _read_csv(p)
    if df.empty:
        # _read_csv above prepends reports for relative paths; direct read retry
        for enc in ('utf-8-sig','utf-8','cp949'):
            try:
                df = pd.read_csv(p, encoding=enc, dtype=str).fillna('')
                break
            except Exception:
                pass
    if df.empty:
        return df
    rows = []
    for _, r in df.head(30).iterrows():
        sym = _clean(r.get('symbol')) or _clean(r.get('ticker'))
        code = sym.replace('.KS','').replace('.KQ','') if slug == 'kr' else sym.upper()
        rows.append({
            '종목코드': _zcode(code) if slug == 'kr' else code,
            '종목명': _clean(r.get('name_kr')) or _clean(r.get('name')) or code,
            '시장': '한국주식' if slug == 'kr' else '미국주식',
            '섹터': _clean(r.get('sector')) or '미분류',
            '상태': '관찰 유니버스',
            '해석': '관찰 후보입니다.',
            '다음 행동': '가격·거래량 확인',
        })
    return pd.DataFrame(rows)


def _first(df: pd.DataFrame, *cols: str) -> str:
    if df is None or df.empty:
        return '-'
    r = df.iloc[0]
    for c in list(cols) + ['종목명','종목코드','종목','symbol','ticker','TOP']:
        if c in df.columns and _clean(r.get(c)):
            return _zcode(r.get(c)) if c == '종목코드' else _clean(r.get(c))
    return '-'


def _news_filter(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    keep = []
    for _, row in out.iterrows():
        text = ' '.join(_clean(row.get(c)) for c in out.columns)
        tl = text.lower()
        if slug == 'kr':
            has_hangul = bool(HANGUL_RE.search(text))
            has_kw = any(w.lower() in tl for w in KR_NEWS_WORDS)
            has_src = any(w.lower() in tl for w in KR_NEWS_SOURCES)
            blocked = any(w.lower() in tl for w in FOREIGN_NEWS_BLOCK)
            keep.append((int(has_hangul)+int(has_kw)+int(has_src) >= 2) and not blocked)
        else:
            # 미장은 한글 기사여도 국내증시 키워드가 강하면 제외
            domestic = any(w.lower() in tl for w in ['코스피','코스닥','국내증시','한국증시','한국거래소'])
            keep.append(not domestic)
    out = out.loc[keep].copy().reset_index(drop=True)
    if not out.empty:
        out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    return out


def _to_num(v: Any) -> float:
    s = _clean(v).replace('%','').replace('$','').replace('원','').replace(',','').strip()
    try:
        return float(s)
    except Exception:
        return float('nan')


def _sector_strength(slug: str, *dfs: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for df in dfs:
        if df is None or df.empty:
            continue
        col = next((c for c in ['섹터','업종','sector','업종명','테마','sector_proxy'] if c in df.columns), None)
        if col:
            t = df[[col]].rename(columns={col:'섹터'}).copy()
            t['가중치'] = 1
            parts.append(t)
    if not parts:
        return pd.DataFrame(columns=['섹터','후보수','강도점수','해석'])
    x = pd.concat(parts, ignore_index=True)
    x['섹터'] = x['섹터'].astype(str).replace({'':'미분류','-':'미분류','nan':'미분류','None':'미분류'})
    g = x.groupby('섹터', as_index=False).agg(후보수=('섹터','size'), 강도점수=('가중치','sum')).sort_values(['강도점수','후보수'], ascending=False)
    g['해석'] = g['후보수'].apply(lambda n: f'후보 {int(n)}개')
    return g.head(12).reset_index(drop=True)


def _market_guard(slug: str, action: pd.DataFrame, flow: pd.DataFrame, risk: pd.DataFrame, macro: pd.DataFrame, sector: pd.DataFrame) -> pd.DataFrame:
    nums = []
    for col in ['변화율','등락률','값','score','점수']:
        if not macro.empty and col in macro.columns:
            nums.extend([_to_num(v) for v in macro[col]])
    nums = [x for x in nums if not math.isnan(x) and abs(x) < 1000]
    avg = sum(nums) / len(nums) if nums else 0.0
    risk_ratio = len(risk) / max(len(action), 1) if len(action) else (1.0 if len(risk) else 0.0)
    score = round(max(0, min(100, 55 + avg * 4 + min(len(flow), 10) - min(risk_ratio * 25, 25))), 1)
    phase = '우호' if score >= 70 else ('중립' if score >= 50 else '주의')
    strongest = '-' if sector.empty else _clean(sector.iloc[0].get('섹터')) or '-'
    return pd.DataFrame([
        {'항목':'시장 가드','값':phase,'점수':score,'다음 행동':'우호=정상, 중립=분할, 주의=축소'},
        {'항목':'시장 폭','값':f'{avg:.2f}%','점수':round(50+avg*5,1),'다음 행동':'지수 방향 확인'},
        {'항목':'섹터 강도','값':strongest,'점수':_to_num(sector.iloc[0].get('강도점수')) if not sector.empty else 0,'다음 행동':'강한 섹터 우선'},
        {'항목':'위험 후보','값':f'{len(risk)}개','점수':round(100-min(risk_ratio*100,100),1),'다음 행동':'위험 후보 제외'},
    ])


def _company(slug: str) -> pd.DataFrame:
    df = _pick(['v74_company_clean_{slug}.csv','v70_company_cards_{slug}.csv','v69_company_cards_{slug}.csv','operational_financial_kpi_{slug}.csv'], slug)
    return _clean_market_df(df, slug)


def _positions(slug: str) -> pd.DataFrame:
    df = _pick(['v74_position_cards_{slug}.csv','v73_position_cards_{slug}.csv','v72_position_cards_{slug}.csv','v67_position_plan_{slug}.csv','v50_position_plan.csv'], slug)
    df = _clean_market_df(df, slug)
    if df.empty:
        return pd.DataFrame()
    rows = []
    for _, r in df.iterrows():
        code = _clean(r.get('종목코드')) or _clean(r.get('종목')) or _clean(r.get('ticker')) or _clean(r.get('symbol'))
        name = _clean(r.get('종목명')) or _clean(r.get('카드제목')) or code
        qty = _clean(r.get('보유수량')) or _clean(r.get('수량')) or '-'
        avg = _clean(r.get('평단가')) or _clean(r.get('평단')) or '-'
        cur = _clean(r.get('현재가')) or _clean(r.get('기준가격')) or '-'
        ret = _clean(r.get('수익률')) or '-'
        rq = _clean(r.get('권장수량')) or '0'
        amt = _clean(r.get('예상금액')) or '-'
        act = _clean(r.get('판단')) or _clean(r.get('권장행동')) or '보유 점검'
        rows.append({'종목코드': _zcode(code) if slug=='kr' else code.upper(), '종목명': name, '시장':'한국주식' if slug=='kr' else '미국주식', '판단': act,
                     '보유수량': qty, '평단': avg, '현재가': cur, '수익률': ret, '권장수량': rq, '예상금액': amt,
                     '가격출처': _clean(r.get('가격출처표시')) or _clean(r.get('가격출처')) or '-',
                     '다음 행동': _clean(r.get('다음행동표시')) or _clean(r.get('다음 행동')) or '증권사 화면과 비교'})
    return pd.DataFrame(rows)


def _portfolio_risk(slug: str, pos: pd.DataFrame) -> pd.DataFrame:
    if pos is None or pos.empty:
        return pd.DataFrame([{'항목':'보유종목','값':'0개','상태':'데이터 없음'}])
    vals = []
    for _, r in pos.iterrows():
        qty = _to_num(r.get('보유수량'))
        cur = _to_num(r.get('현재가'))
        if not math.isnan(qty) and not math.isnan(cur):
            vals.append(qty*cur)
    total = sum(vals)
    max_w = max(vals)/total*100 if total else 0
    risk = '주의' if max_w >= 45 else ('보통' if max_w >= 25 else '분산')
    var = total * 0.025 if total else 0
    cvar = total * 0.04 if total else 0
    return pd.DataFrame([
        {'항목':'총 평가액','값':round(total,2),'상태':'직전 가격 기준'},
        {'항목':'최대 비중','값':f'{max_w:.1f}%','상태':risk},
        {'항목':'VaR 95%','값':round(var,2),'상태':'간이 추정'},
        {'항목':'CVaR','값':round(cvar,2),'상태':'간이 추정'},
    ])


def _quant_panels(slug: str, pos: pd.DataFrame, action: pd.DataFrame, risk: pd.DataFrame) -> dict[str, pd.DataFrame]:
    risk_df = _portfolio_risk(slug, pos)
    scanner = action.head(30).copy() if not action.empty else _fallback_universe(slug).head(15).copy()
    if not scanner.empty:
        scanner['스캐너'] = 'QuantAI 카드형 후보'
    picks = action.head(10).copy() if not action.empty else pd.DataFrame()
    if not picks.empty:
        picks['추천사유'] = '시장가드·후보 점수 기준'
    corr = pd.DataFrame([
        {'페어':'시장 ETF x 성장주','상관':'확인 필요','해석':'가격 이력이 쌓이면 계산'},
        {'페어':'보유 1위 x 보유 2위','상관':'확인 필요','해석':'포트폴리오 분산 점검용'},
    ])
    backtest = pd.DataFrame([
        {'항목':'후보 수','값':len(action),'해석':'전략 표본'},
        {'항목':'위험 제외 수','값':len(risk),'해석':'리스크 필터'},
        {'항목':'백테스트 상태','값':'대기','해석':'가격 이력/추천 이력이 쌓이면 자동 계산'},
    ])
    return {'portfolio_risk': risk_df, 'scanner': scanner, 'picks': picks, 'correlation': corr, 'backtest': backtest}


def _summary(slug: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame([
        {'카드':'오늘 우선 확인','아이콘':'🎯','설명':'기준가·손절가·목표가','건수':len(frames['action']),'TOP':_first(frames['action']),'상세파일':f'v75_action_clean_{slug}.csv','우선순위':1,'구분':'buy'},
        {'카드':'눌림목 진입 후보','아이콘':'🪜','설명':'추격보다 기준가 대기','건수':len(frames['pullback']),'TOP':_first(frames['pullback']),'상세파일':f'v75_pullback_clean_{slug}.csv','우선순위':2,'구분':'buy'},
        {'카드':'수급 급증 후보','아이콘':'💚','설명':'거래대금·수급 흐름','건수':len(frames['flow']),'TOP':_first(frames['flow']),'상세파일':f'v75_flow_clean_{slug}.csv','우선순위':3,'구분':'buy'},
        {'카드':'실적·저평가 후보','아이콘':'💎','설명':'재무·KPI·밸류','건수':len(frames['company']),'TOP':_first(frames['company']),'상세파일':f'v75_company_clean_{slug}.csv','우선순위':4,'구분':'value'},
        {'카드':'매수금지·주의','아이콘':'🚫','설명':'제외·관망 우선','건수':len(frames['risk']),'TOP':_first(frames['risk']),'상세파일':f'v75_risk_clean_{slug}.csv','우선순위':5,'구분':'risk'},
    ])


def _frames(slug: str) -> dict[str, pd.DataFrame]:
    action = _clean_market_df(_pick(['v74_action_clean_{slug}.csv','v73_action_clean_{slug}.csv','v67_action_board_{slug}.csv','swing_candidates_{slug}_A_top3.csv'], slug), slug)
    pull = _clean_market_df(_pick(['v74_pullback_clean_{slug}.csv','v73_pullback_clean_{slug}.csv','v67_pullback_{slug}.csv','swing_candidates_{slug}_B_watch.csv'], slug), slug)
    flow = _clean_market_df(_pick(['v74_flow_clean_{slug}.csv','v73_flow_clean_{slug}.csv','v67_flow_{slug}.csv','intraday_flow_snapshot.csv'], slug), slug)
    risk = _clean_market_df(_pick(['v74_risk_clean_{slug}.csv','v73_risk_clean_{slug}.csv','v67_risk_{slug}.csv','v52_buy_risk_light.csv'], slug), slug)
    company = _company(slug)
    return {
        'action': _ensure_schema(action, 'action', slug),
        'pullback': _ensure_schema(pull, 'pullback', slug),
        'flow': _ensure_schema(flow, 'flow', slug),
        'risk': _ensure_schema(risk, 'risk', slug),
        'company': _ensure_schema(company, 'company', slug),
    }


def run_v75_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dotenv()
    base = {'status':'SKIPPED'}
    if run_v74_update is not None:
        try:
            base = run_v74_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status':'WARN','error':f'{type(exc).__name__}: {exc}'}
    result: dict[str, Any] = {'status':'OK','version':'v75','updated_at':_now(),'base':base}
    status_rows = []
    for slug, label in [('kr','국장'),('us','미장')]:
        frames = _frames(slug)
        macro = _clean_market_df(_pick(['v74_macro_cards_{slug}.csv','v70_macro_cards_{slug}.csv','operational_macro_{slug}.csv'], slug), slug)
        news = _news_filter(_pick(['v74_news_cards_{slug}.csv','v70_news_cards_{slug}.csv','gnews_latest_{slug}.csv'], slug), slug)
        pos = _positions(slug)
        sector = _sector_strength(slug, frames['action'], frames['flow'], frames['company'])
        guard = _market_guard(slug, frames['action'], frames['flow'], frames['risk'], macro, sector)
        summary = _summary(slug, frames)
        # write cleansed reports
        for key, df in frames.items():
            _write_csv(df, f'v75_{key}_clean_{slug}.csv')
        _write_csv(summary, f'v75_today_summary_{slug}.csv')
        _write_csv(macro, f'v75_macro_cards_{slug}.csv')
        _write_csv(news, f'v75_news_cards_{slug}.csv')
        _write_csv(pos, f'v75_position_cards_{slug}.csv')
        _write_csv(sector, f'v75_sector_strength_{slug}.csv')
        _write_csv(guard, f'v75_market_guard_{slug}.csv')
        quant = _quant_panels(slug, pos, frames['action'], frames['risk'])
        for k, df in quant.items():
            _write_csv(df, f'v75_quant_{k}_{slug}.csv')
        result[slug] = {k: len(v) for k, v in frames.items()} | {'summary': len(summary), 'news': len(news), 'positions': len(pos), 'sector': len(sector)}
        for title, name in [
            ('오늘 실행', f'v75_today_summary_{slug}.csv'), ('매수 후보', f'v75_action_clean_{slug}.csv'), ('수급', f'v75_flow_clean_{slug}.csv'),
            ('재무', f'v75_company_clean_{slug}.csv'), ('위험', f'v75_risk_clean_{slug}.csv'), ('뉴스', f'v75_news_cards_{slug}.csv'),
            ('시장 가드', f'v75_market_guard_{slug}.csv'), ('섹터', f'v75_sector_strength_{slug}.csv'), ('보유·매도', f'v75_position_cards_{slug}.csv'),
            ('퀀트', f'v75_quant_portfolio_risk_{slug}.csv')]:
            df = _read_csv(name)
            status_rows.append({'시장':label,'항목':title,'파일':name,'행수':0 if df.empty else len(df),'상태':'정상' if not df.empty else '비어 있음'})
    _write_csv(pd.DataFrame(status_rows), 'v75_data_status.csv')
    out = {'status':'OK','version':'v75','updated_at':_now(),'result':result,'env':{k: bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT']}}
    _write_json(out, 'v75_status.json')
    return out


if __name__ == '__main__':
    print(json.dumps(run_v75_update(), ensure_ascii=False, indent=2, default=str))
