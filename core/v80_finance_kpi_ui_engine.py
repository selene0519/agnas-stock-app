
from __future__ import annotations

import json
import math
import os
import re
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import pandas as pd
import requests

try:
    from core.v79_polished_data_engine import run_v79_update
except Exception:  # pragma: no cover
    run_v79_update = None

REPORT_DIR = Path('reports')
DATA_DIR = Path('data')
CACHE_DIR = DATA_DIR / 'cache'
KR_CODE_RE = re.compile(r'^\d{5,6}$')
HANGUL_RE = re.compile(r'[가-힣]')

COMMON_US = {
    'AAPL','MSFT','GOOGL','GOOG','NVDA','TSLA','AMZN','META','NFLX','AMD','INTC','PLTR','LITE','SNDK','CAT','CRCL','NBIS',
    'AAOI','ASTS','BMNR','COIN','MSTR','AVGO','ORCL','SMCI','SPY','QQQ','DIA','IWM','VOO','VTI','XLF','XLK','XLE','XLV',
    'NKE','JPM','BAC','C','WMT','COST','HD','LOW','DIS','PYPL','UBER','SHOP','SQ','AFRM','SOFI','RIVN','LCID','BABA','TSM',
    'DDOG','CRWD','S','NET','RIOT','SOXX','RKLB','LUNR','IONQ','OKLO','HUT','IREN','SNOW'
}

KR_NAME_FALLBACK = {
    '003550':'LG','000100':'유한양행','010120':'LS ELECTRIC','000270':'기아','259960':'크래프톤','000660':'SK하이닉스',
    '003490':'대한항공','000720':'현대건설','028670':'팬오션','000810':'삼성화재해상보험','278470':'에이피알','000990':'DB하이텍',
    '222800':'심텍','131970':'두산테스나','403870':'HPSP','375500':'DL이앤씨','329180':'HD현대중공업','095340':'ISC',
    '004020':'현대제철','010950':'S-Oil','012450':'한화에어로스페이스','277810':'레인보우로보틱스','034590':'인천도시가스',
}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_dotenv() -> None:
    for p in [Path('.env'), Path.cwd()/'.env']:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding='utf-8-sig', errors='ignore').splitlines():
                s=line.strip()
                if not s or s.startswith('#') or '=' not in s:
                    continue
                k,v=s.split('=',1)
                k=k.strip().lstrip('\ufeff')
                v=v.strip().strip('"').strip("'")
                if k and v and not os.environ.get(k):
                    os.environ[k]=v
        except Exception:
            pass
    aliases={
        'DART_API_KEY':['DART_KEY','OPENDART_API_KEY','OPEN_DART_API_KEY','DART_API'],
        'FINNHUB_API_KEY':['FINNHUB_KEY','FINNHUB_TOKEN'],
        'GNEWS_API_KEY':['GNEWS_KEY','GNEWS_TOKEN'],
        'APIFY_TOKEN':['APIFY_API_TOKEN'],
        'SEC_USER_AGENT':['SEC_EMAIL','SEC_UA'],
        'KIS_APP_KEY':['KIS_APPKEY','KIS_API_KEY'],
        'KIS_APP_SECRET':['KIS_SECRET','KIS_APPSECRET'],
    }
    for primary, alts in aliases.items():
        if not os.environ.get(primary):
            for alt in alts:
                if os.environ.get(alt):
                    os.environ[primary]=os.environ.get(alt,'')
                    break


def _env(name: str) -> str:
    _ensure_dotenv()
    return os.environ.get(name, '').strip()


def _clean(v: Any) -> str:
    if v is None:
        return ''
    s=str(v).strip()
    if s.lower() in {'','-','nan','none','null','nat'}:
        return ''
    return s


def _zcode(v: Any) -> str:
    s=_clean(v)
    if not s:
        return ''
    try:
        if re.fullmatch(r'\d+\.0', s):
            s=str(int(float(s)))
    except Exception:
        pass
    if re.fullmatch(r'\d{1,6}', s):
        return s.zfill(6)
    m=re.search(r'\b(\d{5,6})\b', s)
    return m.group(1).zfill(6) if m else s


def _to_num(v: Any) -> float:
    s=_clean(v).replace('%','').replace('$','').replace('원','').replace(',','').strip()
    mult=1.0
    if s.endswith('조'):
        mult=1_000_000_000_000.0; s=s[:-1]
    elif s.endswith('억'):
        mult=100_000_000.0; s=s[:-1]
    elif s.endswith('만'):
        mult=10_000.0; s=s[:-1]
    try:
        return float(s)*mult
    except Exception:
        return float('nan')


def _fmt_num(v: Any, suffix: str = '') -> str:
    x=_to_num(v)
    if math.isnan(x):
        return '-'
    if abs(x) >= 1_000_000_000_000:
        return f'{x/1_000_000_000_000:.1f}조{suffix}'
    if abs(x) >= 100_000_000:
        return f'{x/100_000_000:.1f}억{suffix}'
    if abs(x) >= 10_000:
        return f'{x:,.0f}{suffix}'
    return f'{x:.2f}{suffix}' if abs(x) < 100 else f'{x:,.0f}{suffix}'


def _read_csv(path: str | Path) -> pd.DataFrame:
    p=Path(path)
    if not p.is_absolute() and not p.exists():
        p=REPORT_DIR/p
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ('utf-8-sig','utf-8','cp949'):
        try:
            return pd.read_csv(p, dtype=str, encoding=enc).fillna('')
        except Exception:
            pass
    return pd.DataFrame()


def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p=Path(path)
    if not p.is_absolute():
        p=REPORT_DIR/p
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding='utf-8-sig')


def _write_json(data: dict[str, Any], path: str | Path) -> None:
    p=Path(path)
    if not p.is_absolute():
        p=REPORT_DIR/p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _row_text(row: pd.Series) -> str:
    return ' '.join(_clean(row.get(c)) for c in row.index)


def _is_us_symbol(s: str) -> bool:
    t=_clean(s).upper()
    return bool(t in COMMON_US or re.fullmatch(r'[A-Z]{1,6}(?:[.-][A-Z]{1,3})?', t))


def _is_kr_symbol(s: str) -> bool:
    return bool(KR_CODE_RE.fullmatch(_zcode(s)))


def _is_us_row(row: pd.Series) -> bool:
    txt=_row_text(row)
    if any(x in txt for x in ['미국주식','미장','NASDAQ','NYSE','AMEX']):
        return True
    for c in ['종목코드','symbol','ticker','티커','종목','종목명','TOP']:
        if c in row.index and _is_us_symbol(row.get(c)) and not HANGUL_RE.search(_clean(row.get(c))):
            return True
    return False


def _is_kr_row(row: pd.Series) -> bool:
    txt=_row_text(row)
    if any(x in txt for x in ['한국주식','국장','코스피','코스닥','KRX']):
        return True
    for c in ['종목코드','symbol','ticker','코드','종목']:
        if c in row.index and _is_kr_symbol(row.get(c)):
            return True
    return bool(HANGUL_RE.search(txt)) and not _is_us_row(row)


def _first(row: pd.Series, cols: list[str]) -> str:
    for c in cols:
        if c in row.index and _clean(row.get(c)):
            return _clean(row.get(c))
    return ''


def _code_name_map() -> dict[str, str]:
    m=dict(KR_NAME_FALLBACK)
    for root in [REPORT_DIR, DATA_DIR]:
        if not root.exists():
            continue
        for p in root.rglob('*.csv'):
            if p.stat().st_size > 5_000_000:
                continue
            df=_read_csv(p)
            if df.empty:
                continue
            for _, r in df.head(5000).iterrows():
                code=''
                for c in ['종목코드','symbol','ticker','코드','종목']:
                    if c in df.columns:
                        z=_zcode(r.get(c))
                        if KR_CODE_RE.fullmatch(z):
                            code=z; break
                if not code:
                    continue
                name=''
                for c in ['종목명','name','종목','회사명','corp_name','stock_name','한글명']:
                    if c in df.columns:
                        cand=_clean(r.get(c))
                        if cand and cand != code and HANGUL_RE.search(cand) and not re.fullmatch(r'\d{5,6}', cand):
                            name=cand; break
                if name:
                    m[code]=name
    return m


def _candidate_symbols(slug: str, limit: int = 20) -> pd.DataFrame:
    files = [
        f'v79_company_clean_{slug}.csv', f'v79_flow_clean_{slug}.csv', f'v79_action_clean_{slug}.csv', f'v79_pullback_clean_{slug}.csv',
        f'v78_company_clean_{slug}.csv', f'v70_company_cards_{slug}.csv'
    ]
    rows=[]; seen=set(); name_map=_code_name_map()
    for fn in files:
        df=_read_csv(fn)
        if df.empty:
            continue
        for _, r in df.iterrows():
            code=_first(r, ['종목코드','symbol','ticker','종목','코드'])
            if slug=='kr':
                code=_zcode(code)
                if not KR_CODE_RE.fullmatch(code):
                    continue
                name=_first(r, ['종목명','name','종목']) or name_map.get(code, code)
            else:
                code=code.upper().strip()
                if not _is_us_symbol(code):
                    continue
                name=_first(r, ['종목명','name','종목']) or code
            if code in seen:
                continue
            seen.add(code)
            rows.append({'종목코드':code, '종목명':name, '시장':'한국주식' if slug=='kr' else '미국주식', '원천파일':fn})
            if len(rows) >= limit:
                return pd.DataFrame(rows)
    return pd.DataFrame(rows)


def _dart_corp_codes() -> pd.DataFrame:
    cache=CACHE_DIR/'dart_corp_codes.csv'
    if cache.exists() and cache.stat().st_size > 1000:
        df=_read_csv(cache)
        if not df.empty:
            return df
    key=_env('DART_API_KEY')
    if not key:
        return pd.DataFrame()
    try:
        url='https://opendart.fss.or.kr/api/corpCode.xml'
        resp=requests.get(url, params={'crtfc_key':key}, timeout=20)
        resp.raise_for_status()
        z=zipfile.ZipFile(BytesIO(resp.content))
        xml=z.read(z.namelist()[0])
        root=ET.fromstring(xml)
        rows=[]
        for el in root.findall('list'):
            rows.append({
                'corp_code': _clean(el.findtext('corp_code')),
                'corp_name': _clean(el.findtext('corp_name')),
                'stock_code': _zcode(el.findtext('stock_code')),
                'modify_date': _clean(el.findtext('modify_date')),
            })
        df=pd.DataFrame(rows)
        if not df.empty:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache, index=False, encoding='utf-8-sig')
        return df
    except Exception:
        return pd.DataFrame()


def _dart_financial(code: str, name: str) -> dict[str, Any]:
    key=_env('DART_API_KEY')
    if not key:
        return {'status':'NO_KEY','error':'DART_API_KEY 미인식'}
    corp_df=_dart_corp_codes()
    if corp_df.empty:
        return {'status':'NO_CORP_MAP','error':'DART corpCode 매핑 실패'}
    z=_zcode(code)
    hit=corp_df[corp_df.get('stock_code','').astype(str).str.zfill(6).eq(z)]
    if hit.empty:
        return {'status':'NO_CORP_CODE','error':'종목코드 corp_code 매핑 실패'}
    corp=hit.iloc[0].get('corp_code')
    year=str(datetime.now().year-1)
    endpoints=[]
    for fs_div in ['CFS','OFS']:
        endpoints.append({'corp_code':corp,'bsns_year':year,'reprt_code':'11011','fs_div':fs_div,'crtfc_key':key})
    data=[]; last_error=''
    for params in endpoints:
        try:
            r=requests.get('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json', params=params, timeout=12)
            js=r.json()
            if str(js.get('status')) == '000' and js.get('list'):
                data=js.get('list') or []
                break
            last_error=f"{js.get('status')} {js.get('message')}"
        except Exception as exc:
            last_error=f'{type(exc).__name__}: {exc}'
    if not data:
        return {'status':'NO_FINANCIALS','error':last_error or 'DART 응답 없음'}
    def amt_for(names: list[str]) -> float:
        for it in data:
            an=_clean(it.get('account_nm'))
            if any(n in an for n in names):
                x=_to_num(it.get('thstrm_amount'))
                if not math.isnan(x):
                    return x
        return float('nan')
    revenue=amt_for(['매출액','영업수익'])
    op=amt_for(['영업이익'])
    net=amt_for(['당기순이익','분기순이익','반기순이익'])
    assets=amt_for(['자산총계'])
    liabilities=amt_for(['부채총계'])
    equity=amt_for(['자본총계'])
    roe=(net/equity*100) if not math.isnan(net) and not math.isnan(equity) and equity else float('nan')
    debt=(liabilities/equity*100) if not math.isnan(liabilities) and not math.isnan(equity) and equity else float('nan')
    opm=(op/revenue*100) if not math.isnan(op) and not math.isnan(revenue) and revenue else float('nan')
    npm=(net/revenue*100) if not math.isnan(net) and not math.isnan(revenue) and revenue else float('nan')
    return {'status':'정상','source':'DART','corp_code':corp,'year':year,'revenue':revenue,'operating_income':op,'net_income':net,'assets':assets,'liabilities':liabilities,'equity':equity,'roe':roe,'debt_ratio':debt,'op_margin':opm,'net_margin':npm,'error':''}


def _finnhub_metric(ticker: str) -> dict[str, Any]:
    token=_env('FINNHUB_API_KEY')
    if not token:
        return {'status':'NO_KEY','error':'FINNHUB_API_KEY 미인식'}
    try:
        r=requests.get('https://finnhub.io/api/v1/stock/metric', params={'symbol':ticker.upper(),'metric':'all','token':token}, timeout=12)
        js=r.json()
        metric=js.get('metric') or {}
        if not metric:
            return {'status':'NO_METRIC','error':_clean(js.get('error')) or 'metric 없음'}
        def get(*keys):
            for k in keys:
                if k in metric and metric[k] not in [None, '']:
                    return metric[k]
            return float('nan')
        return {
            'status':'정상','source':'Finnhub','per':get('peBasicExclExtraTTM','peNormalizedAnnual','peTTM'),
            'pbr':get('pbAnnual','pbQuarterly'), 'roe':get('roeTTM','roeRfy'),
            'op_margin':get('operatingMarginTTM','operatingMarginAnnual'), 'net_margin':get('netProfitMarginTTM','netProfitMarginAnnual'),
            'revenue_growth':get('revenueGrowthTTMYoy','revenueGrowthQuarterlyYoy'), 'beta':get('beta'),
            'current_ratio':get('currentRatioAnnual','currentRatioQuarterly'), 'debt_to_equity':get('totalDebt/totalEquityAnnual','totalDebt/totalEquityQuarterly'),
            'revenue':float('nan'),'operating_income':float('nan'),'net_income':float('nan'),'assets':float('nan'),'liabilities':float('nan'),'equity':float('nan'),
            'error':''
        }
    except Exception as exc:
        return {'status':'ERROR','error':f'{type(exc).__name__}: {exc}'}


def _score_value(per: float, pbr: float, roe: float) -> float:
    score=50.0
    if not math.isnan(per):
        if per <= 12: score += 18
        elif per <= 20: score += 10
        elif per <= 35: score += 3
        else: score -= 6
    if not math.isnan(pbr):
        if pbr <= 1: score += 14
        elif pbr <= 2: score += 7
        elif pbr > 5: score -= 5
    if not math.isnan(roe):
        if roe >= 20: score += 16
        elif roe >= 10: score += 8
        elif roe < 0: score -= 12
    return round(max(0, min(100, score)),1)


def _score_growth(revenue_growth: float, op_margin: float, net_margin: float) -> float:
    score=50.0
    if not math.isnan(revenue_growth): score += max(-15, min(20, revenue_growth/2))
    if not math.isnan(op_margin): score += max(-10, min(15, op_margin/2))
    if not math.isnan(net_margin): score += max(-10, min(15, net_margin/2))
    return round(max(0, min(100, score)),1)


def _score_stability(debt_ratio: float, current_ratio: float) -> float:
    score=55.0
    if not math.isnan(debt_ratio):
        if debt_ratio < 80: score += 18
        elif debt_ratio < 150: score += 8
        elif debt_ratio > 250: score -= 18
    if not math.isnan(current_ratio):
        if current_ratio >= 1.5: score += 12
        elif current_ratio < 1: score -= 10
    return round(max(0, min(100, score)),1)


def _build_finance(slug: str, candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows=[]; financial_rows=[]; kpi_rows=[]
    for i, r in candidates.head(16).iterrows():
        code=_clean(r.get('종목코드'))
        name=_clean(r.get('종목명')) or code
        if slug=='kr':
            info=_dart_financial(code, name)
            per=pbr=float('nan')
            roe=_to_num(info.get('roe'))
            debt=_to_num(info.get('debt_ratio'))
            opm=_to_num(info.get('op_margin'))
            npm=_to_num(info.get('net_margin'))
            rev_growth=float('nan')
            current_ratio=float('nan')
        else:
            info=_finnhub_metric(code)
            per=_to_num(info.get('per'))
            pbr=_to_num(info.get('pbr'))
            roe=_to_num(info.get('roe'))
            debt=_to_num(info.get('debt_to_equity'))
            opm=_to_num(info.get('op_margin'))
            npm=_to_num(info.get('net_margin'))
            rev_growth=_to_num(info.get('revenue_growth'))
            current_ratio=_to_num(info.get('current_ratio'))
        status=_clean(info.get('status')) or '확인 필요'
        source=_clean(info.get('source')) or ('DART' if slug=='kr' else 'Finnhub')
        value_score=_score_value(per,pbr,roe)
        growth_score=_score_growth(rev_growth,opm,npm)
        stability_score=_score_stability(debt,current_ratio)
        composite=round(value_score*0.4+growth_score*0.3+stability_score*0.3,1)
        if status != '정상':
            composite=min(composite, 55.0)
        action='데이터 확인 후 판단' if status!='정상' else ('관심 유지 · 눌림 확인' if composite>=65 else '무리한 추격 금지')
        summary = '재무 데이터가 충분하지 않아 보수적으로 봅니다.' if status!='정상' else f'가치 {value_score}, 성장 {growth_score}, 안정성 {stability_score} 기준으로 종합 {composite}점입니다.'
        base={
            '시장':'한국주식' if slug=='kr' else '미국주식','종목코드':code,'종목명':name,'데이터상태':status,'데이터출처':source,
            'PER': '-' if math.isnan(per) else round(per,2),'PBR':'-' if math.isnan(pbr) else round(pbr,2),'ROE':'-' if math.isnan(roe) else round(roe,2),
            '매출':_fmt_num(info.get('revenue')),'영업이익':_fmt_num(info.get('operating_income')),'순이익':_fmt_num(info.get('net_income')),
            '자산':_fmt_num(info.get('assets')),'부채':_fmt_num(info.get('liabilities')),'자본':_fmt_num(info.get('equity')),
            '부채비율':'-' if math.isnan(debt) else round(debt,2),'영업이익률':'-' if math.isnan(opm) else round(opm,2),'순이익률':'-' if math.isnan(npm) else round(npm,2),
            '가치점수':value_score,'성장점수':growth_score,'안정성점수':stability_score,'종합점수':composite,
            '핵심요약':summary,'다음행동':action,'오류':_clean(info.get('error')),
        }
        rows.append(base)
        financial_rows.append({k: base[k] for k in ['시장','종목코드','종목명','데이터상태','데이터출처','매출','영업이익','순이익','자산','부채','자본','오류']})
        kpi_rows.append({k: base[k] for k in ['시장','종목코드','종목명','데이터상태','가치점수','성장점수','안정성점수','종합점수','PER','PBR','ROE','부채비율','영업이익률','순이익률','핵심요약','다음행동']})
        if slug=='us':
            time.sleep(0.25)
    return pd.DataFrame(rows), pd.DataFrame(financial_rows), pd.DataFrame(kpi_rows)


def _read_v79(slug: str, kind: str) -> pd.DataFrame:
    names={
        'summary':[f'v79_today_summary_{slug}.csv'], 'news':[f'v79_news_cards_{slug}.csv', f'v70_news_cards_{slug}.csv'],
        'macro':[f'v79_market_guard_{slug}.csv'], 'flow':[f'v79_flow_clean_{slug}.csv'], 'future':[f'v79_future_probability_{slug}.csv'],
        'position':[f'v79_position_cards_{slug}.csv'], 'company':[f'v79_company_clean_{slug}.csv']
    }.get(kind, [])
    for n in names:
        df=_read_csv(n)
        if not df.empty:
            return df
    return pd.DataFrame()


def _news_summary(slug: str, finance: pd.DataFrame) -> pd.DataFrame:
    news=_read_v79(slug,'news')
    out=[]
    for _, r in news.head(8).iterrows():
        title=_clean(r.get('제목')) or _clean(r.get('title')) or '뉴스'
        desc=_clean(r.get('요약')) or _clean(r.get('description')) or _clean(r.get('summary'))
        source=_clean(r.get('출처')) or _clean(r.get('source')) or '-'
        brief=desc[:130] if desc else ('국장 시장 흐름 관련 뉴스입니다.' if slug=='kr' else '미장 시장 흐름 관련 뉴스입니다. 간략 번역은 투자심리 점검용입니다.')
        out.append({'시장':'한국주식' if slug=='kr' else '미국주식','제목':title,'3줄요약':brief,'출처':source,'다음행동':'뉴스만으로 매수하지 말고 가격·수급·재무를 함께 확인'})
    return pd.DataFrame(out)


def _narrative(slug: str, finance: pd.DataFrame, flow: pd.DataFrame, news: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    if finance.empty:
        candidates=_candidate_symbols(slug, 8)
        finance=pd.DataFrame([{'종목코드':r['종목코드'],'종목명':r['종목명'],'데이터상태':'데이터 부족','종합점수':'-','핵심요약':'재무 데이터 보강 대기','다음행동':'가격·뉴스·수급 먼저 확인'} for _,r in candidates.iterrows()])
    flow_map={_clean(r.get('종목코드')):r for _,r in flow.iterrows()} if not flow.empty else {}
    top_news = _clean(news.iloc[0].get('3줄요약')) if not news.empty else '뉴스 요약 데이터가 부족합니다.'
    for _, r in finance.head(12).iterrows():
        code=_clean(r.get('종목코드')); name=_clean(r.get('종목명')) or code
        f=flow_map.get(code)
        flow_line='수급 데이터는 아직 부족합니다.' if f is None else f"수급점수 {_clean(f.get('수급점수'))}, 기준 {_clean(f.get('수급기준'))}입니다."
        rows.append({
            '시장':'한국주식' if slug=='kr' else '미국주식','종목코드':code,'종목명':name,
            '내러티브':f"{name}은 현재 {_clean(r.get('데이터상태')) or '확인 필요'} 상태입니다. {flow_line} {top_news} {_clean(r.get('핵심요약'))}",
            '다음행동':_clean(r.get('다음행동')) or '기준가·손절가·뉴스를 함께 확인하세요.',
        })
    return pd.DataFrame(rows)


def _simple_feature_files(slug: str, finance: pd.DataFrame, macro: pd.DataFrame) -> dict[str, pd.DataFrame]:
    market='한국주식' if slug=='kr' else '미국주식'
    tech = pd.DataFrame([{'시장':market,'항목':'기술·특허','상태':'준비 중','요약':'특허 API/기술 데이터 소스가 아직 연결되지 않았습니다. 일반 화면에는 투자 판단 보조 설명만 표시합니다.','다음행동':'관리자모드에서 특허 데이터 소스 연결 후 활성화'}])
    custom = pd.DataFrame([{'시장':market,'지표':'커스텀 경제지표','값':'설정 대기','해석':'사용자가 보고 싶은 환율·금리·원자재·섹터 지표를 선택하면 이곳에 표시합니다.','다음행동':'관리자모드에서 커스텀 지표 설정'}])
    masters=[]
    for _, r in finance.sort_values('종합점수', ascending=False).head(8).iterrows() if not finance.empty else pd.DataFrame().iterrows():
        masters.append({'시장':market,'종목코드':r.get('종목코드'),'종목명':r.get('종목명'),'거장식 해석':'가치·성장·안정성 점수가 함께 높은지 확인하는 참고 카드입니다. 실제 대가 매수 데이터는 별도 13F/DART 지분공시 연결이 필요합니다.','다음행동':r.get('다음행동','')})
    master_df=pd.DataFrame(masters) if masters else pd.DataFrame([{'시장':market,'종목코드':'-','종목명':'-','거장식 해석':'분석 후보가 아직 없습니다.','다음행동':'재무/KPI 데이터 갱신'}])
    return {'tech_patent':tech,'custom_macro':custom,'master_investors':master_df}


def _data_status(slug: str, candidates: pd.DataFrame, finance: pd.DataFrame, flow: pd.DataFrame, news: pd.DataFrame) -> pd.DataFrame:
    env={k:bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT','KIS_APP_KEY','KIS_APP_SECRET']}
    label='국장' if slug=='kr' else '미장'
    rows=[
        {'시장':label,'항목':'후보 원천','행수':len(candidates),'상태':'정상' if len(candidates) else '확인 필요','설명':'v79 후보/수급/기업분석에서 v80 분석 대상을 구성'},
        {'시장':label,'항목':'재무/KPI','행수':len(finance),'상태':'정상' if (not finance.empty and (finance['데이터상태'].astype(str)=='정상').any()) else '부분 연결','설명':'DART/Finnhub 응답을 기반으로 가치·성장·안정성 점수 계산'},
        {'시장':label,'항목':'수급·거래대금','행수':len(flow),'상태':'정상' if len(flow) else '확인 필요','설명':'v79에서 복구한 수급·거래대금 후보'},
        {'시장':label,'항목':'뉴스','행수':len(news),'상태':'정상' if len(news) else '확인 필요','설명':'일반 화면에는 3줄 요약만 표시'},
        {'시장':label,'항목':'API 키','행수':sum(env.values()),'상태':'인식' if any(env.values()) else '미인식','설명':json.dumps(env, ensure_ascii=False)},
    ]
    return pd.DataFrame(rows)


def run_v80_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    _ensure_dirs(); _ensure_dotenv()
    base={'status':'SKIPPED'}
    if run_v79_update is not None:
        try:
            base=run_v79_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            base={'status':'WARN','error':f'{type(exc).__name__}: {exc}'}
    result={'status':'OK','version':'v80','updated_at':_now(),'base':base}
    status_parts=[]
    for slug in ['kr','us']:
        candidates=_candidate_symbols(slug, 20)
        finance, financials, kpi = _build_finance(slug, candidates)
        flow=_read_v79(slug,'flow')
        news=_news_summary(slug, finance)
        macro=_read_v79(slug,'macro')
        narrative=_narrative(slug, finance, flow, news)
        features=_simple_feature_files(slug, finance, macro)
        valuation=finance.sort_values('종합점수', ascending=False).reset_index(drop=True) if not finance.empty else finance
        _write_csv(valuation, f'v80_advanced_valuation_{slug}.csv')
        _write_csv(financials, f'v80_financial_statement_{slug}.csv')
        _write_csv(kpi, f'v80_kpi_cards_{slug}.csv')
        _write_csv(finance, f'v80_company_cards_{slug}.csv')
        _write_csv(news, f'v80_news_summary_{slug}.csv')
        _write_csv(macro, f'v80_macro_analysis_{slug}.csv')
        _write_csv(narrative, f'v80_narrative_cards_{slug}.csv')
        for key, df in features.items():
            _write_csv(df, f'v80_{key}_{slug}.csv')
        # v79 핵심 파일은 v80 이름으로도 복사해 화면 연결을 명확히 한다.
        for kind, fn in [('summary',f'v79_today_summary_{slug}.csv'),('future',f'v79_future_probability_{slug}.csv'),('flow',f'v79_flow_clean_{slug}.csv'),('position',f'v79_position_cards_{slug}.csv')]:
            df=_read_csv(fn)
            if not df.empty:
                outname={'summary':f'v80_today_summary_{slug}.csv','future':f'v80_future_probability_{slug}.csv','flow':f'v80_flow_clean_{slug}.csv','position':f'v80_position_cards_{slug}.csv'}[kind]
                _write_csv(df,outname)
        status=_data_status(slug, candidates, finance, flow, news)
        _write_csv(status, f'v80_data_status_{slug}.csv')
        status_parts.append(status)
        result[slug]={'candidates':len(candidates),'finance':len(finance),'financials':len(financials),'kpi':len(kpi),'news':len(news),'narrative':len(narrative),'flow':len(flow)}
    all_status=pd.concat(status_parts, ignore_index=True) if status_parts else pd.DataFrame()
    _write_csv(all_status, 'v80_data_status.csv')
    out={'status':'OK','version':'v80','updated_at':_now(),'result':result,'env':{k:bool(_env(k)) for k in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','APIFY_TOKEN','SEC_USER_AGENT','KIS_APP_KEY']}}
    _write_json(out, 'v80_status.json')
    return out


if __name__ == '__main__':
    print(json.dumps(run_v80_update(), ensure_ascii=False, indent=2, default=str))
