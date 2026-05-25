
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
    from core.v78_record_flow_ui_engine import run_v78_update
except Exception:  # pragma: no cover
    run_v78_update = None

REPORT_DIR = Path('reports')
DATA_DIR = Path('data')
HISTORY_DIR = DATA_DIR / 'history'
KR_CODE_RE = re.compile(r'^\d{5,6}$')
HANGUL_RE = re.compile(r'[가-힣]')
COMMON_US = {
    'AAPL','MSFT','GOOGL','GOOG','NVDA','TSLA','AMZN','META','NFLX','AMD','INTC','PLTR','LITE','SNDK','CAT','CRCL','NBIS',
    'AAOI','ASTS','BMNR','COIN','MSTR','AVGO','ORCL','SMCI','SPY','QQQ','DIA','IWM','VOO','VTI','XLF','XLK','XLE','XLV',
    'NKE','JPM','BAC','C','WMT','COST','HD','LOW','DIS','PYPL','UBER','SHOP','SQ','AFRM','SOFI','RIVN','LCID','BABA','TSM',
    'DDOG','CRWD','S','NET','RIOT','SOXX','RKLB','LUNR','IONQ','OKLO','HUT','IREN','SNOW'
}

# 최소 내장 매핑. 실행 환경의 reports/data CSV에서 더 넓은 매핑을 자동 보강한다.
KR_NAME_FALLBACK = {
    '003550': 'LG', '010120': 'LS ELECTRIC', '259960': '크래프톤', '034590': '인천도시가스',
    '028670': '팬오션', '278470': '에이피알', '095340': 'ISC', '004020': '현대제철',
    '010950': 'S-Oil', '131970': '두산테스나', '012450': '한화에어로스페이스', '277810': '레인보우로보틱스',
    '000990': 'DB하이텍', '222800': '심텍', '403870': 'HPSP', '375500': 'DL이앤씨', '329180': 'HD현대중공업',
}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _ensure_dotenv() -> None:
    for p in [Path('.env'), Path.cwd() / '.env']:
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
    if s.lower() in {'', '-', 'nan', 'none', 'null', 'nat'}:
        return ''
    return s


def _read_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.is_absolute():
        if not p.exists():
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
    # 1.2억, 35만 같은 표현을 간단 보정
    mult = 1.0
    if s.endswith('억'):
        mult = 100000000.0; s = s[:-1]
    elif s.endswith('만'):
        mult = 10000.0; s = s[:-1]
    try:
        return float(s) * mult
    except Exception:
        return float('nan')


def _row_text(row: pd.Series) -> str:
    return ' '.join(_clean(row.get(c)) for c in row.index)


def _symbol_values(row: pd.Series) -> list[str]:
    vals: list[str] = []
    for c in ['종목코드','symbol','ticker','티커','코드','종목','종목명','name','TOP']:
        if c in row.index and _clean(row.get(c)):
            vals.append(_clean(row.get(c)))
    return vals


def _is_us_row(row: pd.Series) -> bool:
    text = _row_text(row)
    if any(x in text for x in ['미국주식','미장','NASDAQ','NYSE','AMEX']):
        return True
    for v in _symbol_values(row):
        token = v.upper().strip()
        if token in COMMON_US:
            return True
        if re.fullmatch(r'[A-Z]{1,6}(?:[.-][A-Z]{1,3})?', token) and not HANGUL_RE.search(v):
            return True
    return False


def _is_kr_row(row: pd.Series) -> bool:
    text = _row_text(row)
    if any(x in text for x in ['한국주식','국장','코스피','코스닥','KRX']):
        return True
    for v in _symbol_values(row):
        if KR_CODE_RE.fullmatch(_zcode(v)):
            return True
    return bool(HANGUL_RE.search(text)) and not _is_us_row(row)


def _first(row: pd.Series, candidates: list[str]) -> str:
    for c in candidates:
        if c in row.index and _clean(row.get(c)):
            return _clean(row.get(c))
    return ''


def _code_name_map() -> dict[str, str]:
    m = dict(KR_NAME_FALLBACK)
    roots = [REPORT_DIR, DATA_DIR]
    code_cols = ['종목코드','symbol','ticker','코드','종목']
    name_cols = ['종목명','name','종목','회사명','corp_name','stock_name','한글명']
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob('*.csv'):
            if p.stat().st_size > 5_000_000:
                continue
            df = _read_csv(p)
            if df.empty:
                continue
            for _, r in df.head(5000).iterrows():
                code = ''
                for c in code_cols:
                    if c in df.columns:
                        z = _zcode(r.get(c))
                        if KR_CODE_RE.fullmatch(z):
                            code = z; break
                if not code:
                    continue
                name = ''
                for c in name_cols:
                    if c in df.columns:
                        cand = _clean(r.get(c))
                        if cand and cand != code and HANGUL_RE.search(cand) and not re.fullmatch(r'\d{5,6}', cand):
                            name = cand; break
                if name:
                    m[code] = name
    return m


def _fix_kr_names(df: pd.DataFrame, name_map: dict[str, str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy().fillna('')
    if '종목코드' not in out.columns:
        return out
    out['종목코드'] = out['종목코드'].apply(_zcode)
    if '종목명' not in out.columns:
        out['종목명'] = ''
    def fix(row: pd.Series) -> str:
        code = _zcode(row.get('종목코드'))
        cur = _clean(row.get('종목명'))
        if code in name_map and (not cur or cur == code or re.fullmatch(r'\d{5,6}', cur)):
            return name_map[code]
        return cur or name_map.get(code, code)
    out['종목명'] = out.apply(fix, axis=1)
    return out


def _clean_market(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    for _, r in df.fillna('').iterrows():
        if slug == 'kr':
            if _is_kr_row(r) and not _is_us_row(r):
                rows.append(r)
        else:
            if _is_us_row(r):
                rows.append(r)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    if '종목코드' in out.columns:
        out['종목코드'] = out['종목코드'].apply(_zcode) if slug == 'kr' else out['종목코드'].astype(str).str.upper().str.strip()
    return out.reset_index(drop=True)


def _normalize_flow(df: pd.DataFrame, slug: str, source: str, name_map: dict[str, str]) -> pd.DataFrame:
    rows = _clean_market(df, slug)
    if rows.empty:
        return pd.DataFrame()
    out_rows: list[dict[str, Any]] = []
    for rank, (_, r) in enumerate(rows.iterrows(), start=1):
        raw = _first(r, ['종목코드','symbol','ticker','종목','코드'])
        code = _zcode(raw) if slug == 'kr' else raw.upper().strip()
        if slug == 'kr' and not KR_CODE_RE.fullmatch(code):
            continue
        if slug == 'us' and code in {'', '-'}:
            continue
        name = _first(r, ['종목명','name','종목','symbol','ticker']) or code
        if slug == 'kr' and (not name or name == code or re.fullmatch(r'\d{5,6}', name)):
            name = name_map.get(code, code)
        last = _first(r, ['현재가','last_price','current_price','price','close','직전종가']) or '-'
        chg = _first(r, ['등락률','intraday_change_pct','change_pct','pct_change']) or '-'
        vol = _first(r, ['거래량','intraday_volume','volume']) or '-'
        val = _first(r, ['거래대금','intraday_trading_value','trading_value','amount']) or '-'
        foreign = _first(r, ['foreign_net_buy','외국인순매수','외국인'])
        inst = _first(r, ['institution_net_buy','기관순매수','기관'])
        program = _first(r, ['program_net_buy','프로그램'])
        raw_score = _first(r, ['수급점수','intraday_flow_score','intraday_momentum_score','sector_intraday_strength_score'])
        score = _to_num(raw_score)
        # 점수가 없거나 전부 50으로만 잡히는 경우, 후보 순위/거래대금/등락률로 차등화한다.
        if math.isnan(score) or abs(score - 50.0) < 0.0001:
            score = 72.0 - rank * 1.7
            chg_num = abs(_to_num(chg))
            val_num = _to_num(val)
            vol_num = _to_num(vol)
            if not math.isnan(chg_num):
                score += min(8.0, chg_num * 0.8)
            if not math.isnan(val_num):
                score += min(10.0, math.log10(max(val_num, 1)) - 6)
            elif not math.isnan(vol_num):
                score += min(6.0, math.log10(max(vol_num, 1)) - 5)
            score = max(45.0, min(88.0, score))
        basis = '외국인·기관 수급' if (foreign or inst or program) else '거래대금·거래량 보강'
        out_rows.append({
            '종목코드': code,
            '종목명': name,
            '시장': '한국주식' if slug == 'kr' else '미국주식',
            '수급기준': basis,
            '현재가/직전종가': last,
            '등락률': chg,
            '거래량': vol,
            '거래대금': val,
            '수급점수': round(float(score), 1),
            '해석': '외국인·기관 수급값이 부족해 거래대금·거래량 기준으로 보강했습니다.' if basis.startswith('거래') else '외국인·기관·프로그램 흐름을 함께 확인합니다.',
            '다음 행동': '장 시작 후 거래대금 증가와 기준가 근접 여부를 확인하세요.',
            '데이터출처': source,
        })
    out = pd.DataFrame(out_rows)
    if not out.empty:
        out = out.drop_duplicates(subset=['종목코드'], keep='first').sort_values('수급점수', ascending=False).head(12).reset_index(drop=True)
    return out


def _build_flow(slug: str, name_map: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = [
        f'v78_flow_clean_{slug}.csv', f'v77_flow_clean_{slug}.csv', f'v76_flow_clean_{slug}.csv', f'v75_flow_clean_{slug}.csv', f'v74_flow_clean_{slug}.csv', f'v67_flow_{slug}.csv',
        'intraday_flow_snapshot-Kang.csv','intraday_realtime_snapshot-Kang.csv','intraday_orderbook_snapshot-Kang.csv',
        'intraday_flow_snapshot-kang.csv','intraday_realtime_snapshot-kang.csv','intraday_orderbook_snapshot-kang.csv',
        'intraday_flow_snapshot.csv','intraday_realtime_snapshot.csv','intraday_orderbook_snapshot.csv',
        'intraday_data_coverage_diagnosis-Kang.csv','intraday_data_coverage_diagnosis.csv',
    ]
    parts = []
    diag = []
    for fn in files:
        df = _read_csv(REPORT_DIR / fn)
        if df.empty:
            continue
        kr_cnt = sum(1 for _, r in df.iterrows() if _is_kr_row(r) and not _is_us_row(r))
        us_cnt = sum(1 for _, r in df.iterrows() if _is_us_row(r))
        norm = _normalize_flow(df, slug, fn, name_map)
        diag.append({'파일':fn,'원본행수':len(df),'KR행':kr_cnt,'US행':us_cnt,'선택행':len(norm),'사용시장':'한국주식' if slug=='kr' else '미국주식'})
        if not norm.empty:
            parts.append(norm)
    if parts:
        out = pd.concat(parts, ignore_index=True).drop_duplicates(subset=['종목코드'], keep='first')
        out = out.sort_values('수급점수', ascending=False).head(12).reset_index(drop=True)
    else:
        out = pd.DataFrame(columns=['종목코드','종목명','시장','수급기준','현재가/직전종가','등락률','거래량','거래대금','수급점수','해석','다음 행동','데이터출처'])
    return out, pd.DataFrame(diag)


def _first_report(names: list[str]) -> pd.DataFrame:
    for fn in names:
        df = _read_csv(REPORT_DIR / fn)
        if not df.empty:
            return df
    return pd.DataFrame()


def _fix_standard_report(df: pd.DataFrame, slug: str, name_map: dict[str, str]) -> pd.DataFrame:
    out = _clean_market(df, slug)
    if slug == 'kr':
        out = _fix_kr_names(out, name_map)
    return out


def _top(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return '-'
    r = df.iloc[0]
    for c in ['종목명','종목코드','symbol','ticker','종목','TOP']:
        if c in df.columns and _clean(r.get(c)):
            return _clean(r.get(c))
    return '-'


def _summary(slug: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame([
        {'카드':'오늘 우선 확인','아이콘':'🎯','설명':'직전가·가격 기준을 먼저 확인할 후보','건수':len(frames['action']),'TOP':_top(frames['action']),'상세파일':f'v79_action_clean_{slug}.csv','우선순위':1,'구분':'buy'},
        {'카드':'눌림목 진입 후보','아이콘':'🪜','설명':'추격보다 눌림 조건부 진입을 기다릴 후보','건수':len(frames['pullback']),'TOP':_top(frames['pullback']),'상세파일':f'v79_pullback_clean_{slug}.csv','우선순위':2,'구분':'buy'},
        {'카드':'수급 급증 후보','아이콘':'💚','설명':'수급·거래대금 흐름을 우선 보는 후보','건수':len(frames['flow']),'TOP':_top(frames['flow']),'상세파일':f'v79_flow_clean_{slug}.csv','우선순위':3,'구분':'buy'},
        {'카드':'실적·저평가 후보','아이콘':'💎','설명':'실적과 밸류를 같이 확인할 후보','건수':len(frames['company']),'TOP':_top(frames['company']),'상세파일':f'v79_company_clean_{slug}.csv','우선순위':4,'구분':'value'},
        {'카드':'매수금지·주의','아이콘':'🚫','설명':'신규매수보다 제외·관망이 우선인 후보','건수':len(frames['risk']),'TOP':_top(frames['risk']),'상세파일':f'v79_risk_clean_{slug}.csv','우선순위':5,'구분':'risk'},
    ])


def _history_rows(slug: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    today = datetime.now().strftime('%Y-%m-%d')
    rows = []
    for kind, label in [('action','오늘확인'),('pullback','눌림목'),('flow','수급'),('company','실적저평가'),('risk','매수주의')]:
        for _, r in frames.get(kind, pd.DataFrame()).iterrows():
            code = _clean(r.get('종목코드')) or _clean(r.get('symbol')) or _clean(r.get('ticker')) or _clean(r.get('종목'))
            code = _zcode(code) if slug == 'kr' else code.upper().strip()
            name = _clean(r.get('종목명')) or _clean(r.get('종목')) or code
            rows.append({'date':today,'updated_at':_now(),'market':'KR' if slug=='kr' else 'US','category':label,'symbol':code,'name':name,'base_price':_clean(r.get('기준가')) or _clean(r.get('현재가/직전종가')) or _clean(r.get('현재가')),'stop':_clean(r.get('손절가')),'target':_clean(r.get('목표가')),'decision':_clean(r.get('다음 행동')) or _clean(r.get('해석'))})
    return pd.DataFrame(rows)


def _append_history(parts: list[pd.DataFrame]) -> int:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / 'prediction_history.csv'
    new = pd.concat([p for p in parts if p is not None and not p.empty], ignore_index=True) if any(p is not None and not p.empty for p in parts) else pd.DataFrame()
    if path.exists():
        old = _read_csv(path)
    else:
        old = pd.DataFrame()
    all_df = pd.concat([old, new], ignore_index=True) if not old.empty else new
    if all_df.empty:
        all_df = pd.DataFrame(columns=['date','updated_at','market','category','symbol','name','base_price','stop','target','decision'])
    all_df = all_df.drop_duplicates(subset=['date','market','category','symbol'], keep='last')
    all_df.to_csv(path, index=False, encoding='utf-8-sig')
    return len(new)


def _future(slug: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for kind, label, p in [('action','오늘 확인',58),('pullback','눌림목',55),('flow','수급·거래대금',57),('company','실적·저평가',54),('risk','주의/제외',42)]:
        for _, r in frames.get(kind, pd.DataFrame()).head(40).iterrows():
            code = _clean(r.get('종목코드')) or _clean(r.get('symbol')) or _clean(r.get('ticker'))
            name = _clean(r.get('종목명')) or code
            adj = 0
            if kind == 'flow':
                sn = _to_num(r.get('수급점수'))
                if not math.isnan(sn):
                    adj = max(-5, min(7, (sn-55)/5))
            prob = round(max(30, min(78, p + adj)), 1)
            rows.append({'시장':'한국주식' if slug=='kr' else '미국주식','종목코드':_zcode(code) if slug=='kr' else code.upper(),'종목명':name,'분류':label,'기준가':_clean(r.get('기준가')) or _clean(r.get('현재가/직전종가')) or '-', '1일상승확률':f'{prob}%', '3일상승확률':f'{min(80, prob+3)}%', '5일상승확률':f'{min(82, prob+5)}%', '신뢰도':'기록 축적 중','다음 행동':'실제 결과가 쌓이면 자동 보정'})
    return pd.DataFrame(rows)


def _copy_v78_to_v79(slug: str, name_map: dict[str, str]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    frames = {}
    spec = {
        'action':[f'v78_action_clean_{slug}.csv', f'v77_action_clean_{slug}.csv', f'v75_action_clean_{slug}.csv', f'v67_action_board_{slug}.csv'],
        'pullback':[f'v78_pullback_clean_{slug}.csv', f'v77_pullback_clean_{slug}.csv', f'v75_pullback_clean_{slug}.csv', f'v67_pullback_{slug}.csv'],
        'risk':[f'v78_risk_clean_{slug}.csv', f'v77_risk_clean_{slug}.csv', f'v75_risk_clean_{slug}.csv', f'v67_risk_{slug}.csv'],
        'company':[f'v78_company_clean_{slug}.csv', f'v77_company_clean_{slug}.csv', f'v75_company_clean_{slug}.csv', f'v70_company_cards_{slug}.csv'],
        'position':[f'v78_position_cards_{slug}.csv', f'v77_position_cards_{slug}.csv', f'v75_position_cards_{slug}.csv', f'v67_position_plan_{slug}.csv'],
        'news':[f'v78_news_cards_{slug}.csv', f'v77_news_cards_{slug}.csv', f'v75_news_cards_{slug}.csv', f'v70_news_cards_{slug}.csv'],
        'macro':[f'v78_market_guard_{slug}.csv', f'v77_market_guard_{slug}.csv', f'v75_market_guard_{slug}.csv'],
        'sector':[f'v78_sector_strength_{slug}.csv', f'v77_sector_strength_{slug}.csv', f'v75_sector_strength_{slug}.csv'],
    }
    for kind, files in spec.items():
        df = _fix_standard_report(_first_report(files), slug, name_map)
        frames[kind] = df
    flow, flow_diag = _build_flow(slug, name_map)
    frames['flow'] = flow
    return frames, flow_diag


def _data_status(slug: str, frames: dict[str, pd.DataFrame], flow_diag: pd.DataFrame) -> pd.DataFrame:
    label = '국장' if slug == 'kr' else '미장'
    env = {k: bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT']}
    return pd.DataFrame([
        {'시장':label,'항목':'수급·거래대금','행수':len(frames.get('flow', [])),'상태':'정상' if len(frames.get('flow', [])) else '확인 필요','설명':'국장 원본을 내부 market/6자리 코드 기준으로 복구. 수급값 부족 시 거래대금 fallback 사용.'},
        {'시장':label,'항목':'실적·저평가','행수':len(frames.get('company', [])),'상태':'정상' if len(frames.get('company', [])) >= 5 else '데이터 부족','설명':'DART/Finnhub/SEC 재무 응답과 종목 매핑이 필요합니다.'},
        {'시장':label,'항목':'뉴스','행수':len(frames.get('news', [])),'상태':'정상' if len(frames.get('news', [])) else '확인 필요','설명':'뉴스 요약 카드용 원천 데이터'},
        {'시장':label,'항목':'API 키','행수':sum(env.values()),'상태':'인식' if any(env.values()) else '미인식','설명':json.dumps(env, ensure_ascii=False)},
        {'시장':label,'항목':'수급 원본 진단','행수':len(flow_diag),'상태':'관리자 확인','설명':'관리자모드에서 파일별 KR/US 행수 확인'},
    ])


def run_v79_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dotenv()
    base: dict[str, Any] = {'status':'SKIPPED'}
    if run_v78_update is not None:
        try:
            base = run_v78_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base = {'status':'WARN','error':f'{type(exc).__name__}: {exc}'}
    name_map = _code_name_map()
    history_parts: list[pd.DataFrame] = []
    status_parts: list[pd.DataFrame] = []
    result: dict[str, Any] = {'status':'OK','version':'v79','updated_at':_now(),'base':base}
    for slug in ['kr','us']:
        frames, flow_diag = _copy_v78_to_v79(slug, name_map)
        future = _future(slug, frames)
        summary = _summary(slug, frames)
        for kind, df in frames.items():
            _write_csv(df, f'v79_{kind}_clean_{slug}.csv' if kind not in {'position','news','macro','sector'} else {
                'position': f'v79_position_cards_{slug}.csv',
                'news': f'v79_news_cards_{slug}.csv',
                'macro': f'v79_market_guard_{slug}.csv',
                'sector': f'v79_sector_strength_{slug}.csv',
            }[kind])
        _write_csv(summary, f'v79_today_summary_{slug}.csv')
        _write_csv(future, f'v79_future_probability_{slug}.csv')
        _write_csv(flow_diag, f'v79_flow_source_diagnosis_{slug}.csv')
        status_parts.append(_data_status(slug, frames, flow_diag))
        history_parts.append(_history_rows(slug, frames))
        result[slug] = {k: len(v) for k, v in frames.items()} | {'summary':len(summary),'future':len(future),'flow_diag':len(flow_diag)}
    appended = _append_history(history_parts)
    result['history_appended_total'] = appended
    status = pd.concat(status_parts, ignore_index=True) if status_parts else pd.DataFrame()
    _write_csv(status, 'v79_data_status.csv')
    out = {'status':'OK','version':'v79','updated_at':_now(),'result':result,'env':{k: bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT']}}
    _write_json(out, 'v79_status.json')
    return out


if __name__ == '__main__':
    print(json.dumps(run_v79_update(), ensure_ascii=False, indent=2, default=str))
