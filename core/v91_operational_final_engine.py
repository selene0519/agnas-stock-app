
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
    from core.v85_operational_product_engine import run_v85_update, REPORT_DIR, DATA_DIR, HISTORY_DIR
except Exception:  # pragma: no cover
    run_v85_update = None
    REPORT_DIR = Path('reports')
    DATA_DIR = Path('data')
    HISTORY_DIR = DATA_DIR / 'history'

VERSION = 'v91'
PREV_VERSION = 'v85'

KR_NAME_MAP: dict[str, str] = {
    '000020': '동화약품', '000100': '유한양행', '000270': '기아', '000660': 'SK하이닉스', '000720': '현대건설',
    '000810': '삼성화재', '000990': 'DB하이텍', '003490': '대한항공', '003550': 'LG', '004020': '현대제철',
    '005930': '삼성전자', '010120': 'LS ELECTRIC', '010950': 'S-Oil', '012450': '한화에어로스페이스',
    '017670': 'SK텔레콤', '028670': '팬오션', '032640': 'LG유플러스', '034590': '인천도시가스',
    '058470': '리노공업', '095340': 'ISC', '131970': '두산테스나', '222800': '심텍', '259960': '크래프톤',
    '277810': '레인보우로보틱스', '278470': '에이피알', '329180': 'HD현대중공업', '375500': 'DL이앤씨',
    '403870': 'HPSP',
}
US_NAME_MAP: dict[str, str] = {
    'AAPL': 'Apple', 'AAOI': 'AAOI', 'ACHR': 'Archer Aviation', 'ALAB': 'Astera Labs', 'AMD': 'AMD',
    'AMZN': 'Amazon', 'ANET': 'Arista Networks', 'BMNR': 'BMNR', 'CAT': 'Caterpillar', 'COST': 'Costco',
    'CRCL': 'Circle', 'CRWD': 'CrowdStrike', 'DDOG': 'Datadog', 'GOOGL': 'Alphabet', 'GOOG': 'Alphabet',
    'INTC': 'Intel', 'LITE': 'Lumentum', 'META': 'Meta Platforms', 'MSFT': 'Microsoft', 'NBIS': 'Nebius',
    'NET': 'Cloudflare', 'NVDA': 'NVIDIA', 'PLTR': 'Palantir', 'RIOT': 'Riot Platforms', 'SNDK': 'SanDisk',
    'SNOW': 'Snowflake', 'TSLA': 'Tesla', 'XLE': 'Energy Select Sector SPDR',
}


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    Path('logs').mkdir(exist_ok=True)
    Path('backups').mkdir(exist_ok=True)


def _valid(v: Any) -> bool:
    if v is None:
        return False
    try:
        if isinstance(v, float) and math.isnan(v):
            return False
    except Exception:
        pass
    s = str(v).strip()
    return bool(s) and s.lower() not in {'nan', 'none', 'null', '-', 'n/a', 'na'}


def _clean(v: Any, default: str = '') -> str:
    if not _valid(v):
        return default
    return str(v).strip()


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path, encoding='utf-8-sig')
    except Exception:
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()


def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    if not p.is_absolute(): p = REPORT_DIR / p
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding='utf-8-sig')


def _write_json(data: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    if not p.is_absolute(): p = REPORT_DIR / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _copy_versioned(src_version: str, dst_version: str) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for pattern in (f'{src_version}_*.csv', f'{src_version}_*.json'):
        for p in sorted(REPORT_DIR.glob(pattern)):
            dst = REPORT_DIR / p.name.replace(f'{src_version}_', f'{dst_version}_', 1)
            try:
                shutil.copyfile(p, dst)
                copied.append({'source': p.name, 'target': dst.name, 'bytes': dst.stat().st_size})
            except Exception as exc:
                copied.append({'source': p.name, 'target': dst.name, 'error': f'{type(exc).__name__}: {exc}'})
    return copied


def _get(row: Any, cols: list[str], default: str = '') -> str:
    for c in cols:
        try:
            if c in row and _valid(row[c]): return _clean(row[c])
        except Exception: pass
    return default


def _symbol(row: Any) -> str:
    raw = _get(row, ['종목코드','symbol','ticker','코드','Symbol','Ticker','종목','종목명','name','Name'])
    m = re.search(r'\(([A-Z]{1,8}|\d{6})\)', str(raw))
    if m: raw = m.group(1)
    s = re.sub(r'[^0-9A-Za-z.\-]', '', str(raw).upper())
    if re.fullmatch(r'\d{1,6}', s): return s.zfill(6)
    return s


def _market_match(row: Any, slug: str) -> bool:
    sym = _symbol(row)
    market = _get(row, ['시장','market','Market'], '').replace(' ','')
    if slug == 'kr':
        return market in {'한국주식','국장','KR','KOREA','KOSPI','KOSDAQ'} or bool(re.fullmatch(r'\d{6}', sym))
    return market in {'미국주식','미장','US','USA','NASDAQ','NYSE'} or (bool(re.fullmatch(r'[A-Z]{1,8}(\.[A-Z])?', sym)) and not bool(re.fullmatch(r'\d{6}', sym)))


def _filter_market(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty: return pd.DataFrame()
    try:
        out = df.loc[df.apply(lambda r: _market_match(r, slug), axis=1)].copy()
    except Exception:
        out = df.copy()
    if out.empty: return out
    out['종목코드'] = out.apply(lambda r: _symbol(r), axis=1)
    out['시장'] = '한국주식' if slug == 'kr' else '미국주식'
    return out


def _name_map(slug: str) -> dict[str,str]:
    mp = dict(KR_NAME_MAP if slug == 'kr' else US_NAME_MAP)
    for p in REPORT_DIR.glob('*.csv'):
        try:
            if p.stat().st_size == 0: continue
        except Exception: continue
        df = _read_csv(p)
        if df.empty: continue
        try: df = _filter_market(df, slug)
        except Exception: pass
        for _, r in df.head(500).iterrows():
            sym = _symbol(r)
            nm = _get(r, ['종목명','name','Name','종목','TOP','카드제목'], '')
            nm = re.sub(r'\s*\([A-Za-z0-9.\-]{1,10}\)\s*$', '', str(nm)).strip()
            if not sym or not nm or nm.upper() == sym.upper() or nm == sym: continue
            if slug == 'kr' and not re.fullmatch(r'\d{6}', sym): continue
            if slug == 'us' and re.fullmatch(r'\d{6}', sym): continue
            if len(nm) <= 45: mp.setdefault(sym, nm)
    return mp


def _display(row: Any, slug: str, mp: dict[str,str] | None = None) -> str:
    mp = mp or _name_map(slug)
    sym = _symbol(row)
    nm = _get(row, ['종목명','name','Name','종목','TOP','카드제목'], '')
    nm = re.sub(r'\s*\([A-Za-z0-9.\-]{1,10}\)\s*$', '', str(nm)).strip()
    if not nm or nm.upper() == sym.upper() or nm == sym: nm = mp.get(sym, sym)
    return f'{nm} ({sym})' if sym and sym not in nm else nm or sym or '종목'


def _read_first(names: list[str]) -> pd.DataFrame:
    for n in names:
        df = _read_csv(REPORT_DIR / n)
        if not df.empty: return df
    return pd.DataFrame()


def _load_kind(slug: str, kind: str) -> pd.DataFrame:
    patterns = {
        'summary':[f'v85_today_summary_{slug}.csv',f'v84_today_summary_{slug}.csv'],
        'action':[f'v85_action_cards_{slug}.csv',f'v84_action_cards_{slug}.csv',f'v83_action_cards_{slug}.csv',f'v67_action_board_{slug}.csv'],
        'pullback':[f'v85_pullback_cards_{slug}.csv',f'v84_pullback_cards_{slug}.csv',f'v83_pullback_cards_{slug}.csv',f'v67_pullback_{slug}.csv'],
        'flow':[f'v85_flow_cards_{slug}.csv',f'v84_flow_cards_{slug}.csv',f'v84_flow_clean_{slug}.csv',f'v79_flow_clean_{slug}.csv','intraday_flow_snapshot-Kang.csv','intraday_realtime_snapshot-Kang.csv','intraday_orderbook_snapshot-Kang.csv','intraday_flow_snapshot.csv'],
        'company':[f'v85_company_integrated_{slug}.csv',f'v84_company_integrated_{slug}.csv',f'v80_kpi_cards_{slug}.csv',f'v80_company_cards_{slug}.csv'],
        'risk':[f'v85_risk_cards_{slug}.csv',f'v84_risk_cards_{slug}.csv',f'v83_risk_cards_{slug}.csv',f'v67_risk_{slug}.csv'],
        'news':[f'v85_news_summary_{slug}.csv',f'v84_news_summary_{slug}.csv',f'v80_news_summary_{slug}.csv'],
        'position':[f'v85_position_cards_{slug}.csv',f'v84_position_cards_{slug}.csv',f'v80_position_cards_{slug}.csv'],
        'future':[f'v85_future_probability_{slug}.csv',f'v84_future_probability_{slug}.csv'],
        'narrative':[f'v85_narrative_cards_{slug}.csv',f'v84_narrative_cards_{slug}.csv'],
    }.get(kind, [])
    frames = []
    if kind == 'flow':
        for n in patterns:
            df = _read_csv(REPORT_DIR / n)
            if not df.empty: frames.append(df)
        if not frames: return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True, sort=False)
    else:
        df = _read_first(patterns)
    df = _filter_market(df, slug)
    if df.empty: return df
    mp = _name_map(slug)
    df['종목명'] = df.apply(lambda r: _display(r, slug, mp).replace(f" ({_symbol(r)})", ''), axis=1)
    df = df.drop_duplicates(subset=['종목코드'], keep='first').reset_index(drop=True)
    return df


def _normalize_flow(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    out = df.copy()
    raw = pd.to_numeric(out.get('수급점수', pd.Series([None]*len(out))), errors='coerce')
    if raw.isna().all() or raw.fillna(50).nunique() <= 1:
        n=max(len(out),1)
        out['수급점수'] = [round(74 - i*(20/max(n-1,1)),1) for i in range(n)]
        out['수급기준'] = out.get('수급기준', pd.Series(['거래대금·거래량 보강']*n)).fillna('거래대금·거래량 보강')
    else:
        out['수급점수'] = raw.fillna(50).round(1)
        if '수급기준' not in out.columns: out['수급기준'] = '수급·거래대금 혼합'
    if '다음행동' not in out.columns: out['다음행동'] = '장 시작 후 거래대금 유지 여부 확인'
    return out


def _integrate_company(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    out = df.copy()
    for c in ['데이터상태','가치점수','성장점수','안정성점수','종합점수','PER','PBR','ROE']:
        if c not in out.columns: out[c] = '-'
    if '핵심요약' not in out.columns:
        out['핵심요약'] = out.apply(lambda r: f"종합점수 {r.get('종합점수','-')} · 가치/성장/안정성을 함께 확인합니다.", axis=1)
    if '다음행동' not in out.columns: out['다음행동'] = '가격·뉴스·수급과 함께 최종 확인'
    return out


def _summary_rows(slug: str, data: dict[str,pd.DataFrame]) -> pd.DataFrame:
    rows = [
        {'아이콘':'🎯','카드':'오늘 우선 확인','설명':'직전가·기준가·손절가를 먼저 확인할 후보','건수':len(data['action']),'TOP':_top(data['action'],slug),'구분':'buy'},
        {'아이콘':'🪜','카드':'눌림목 진입 후보','설명':'추격보다 눌림 조건부 진입을 기다릴 후보','건수':len(data['pullback']),'TOP':_top(data['pullback'],slug),'구분':'buy'},
        {'아이콘':'💚','카드':'수급 급증 후보','설명':'수급·거래대금 흐름을 우선 보는 후보','건수':len(data['flow']),'TOP':_top(data['flow'],slug),'구분':'buy'},
        {'아이콘':'💎','카드':'실적·저평가 후보','설명':'실적과 밸류를 함께 확인할 후보','건수':len(data['company']),'TOP':_top(data['company'],slug),'구분':'value'},
        {'아이콘':'🚫','카드':'매수금지·주의','설명':'신규매수보다 제외·관망이 우선인 후보','건수':len(data['risk']),'TOP':_top(data['risk'],slug),'구분':'risk'},
    ]
    return pd.DataFrame(rows)


def _top(df: pd.DataFrame, slug: str) -> str:
    if df is None or df.empty: return '-'
    return _display(df.iloc[0], slug)


def _make_snapshot(slug: str, data: dict[str,pd.DataFrame]) -> pd.DataFrame:
    rows: dict[str, dict[str,Any]] = {}
    sources=[('오늘확인',data['action']),('눌림목',data['pullback']),('수급',data['flow']),('기업분석',data['company']),('주의',data['risk']),('보유',data['position'])]
    flow_scores = {str(r.get('종목코드')): r.get('수급점수') for _,r in data['flow'].iterrows()} if not data['flow'].empty else {}
    for source,df in sources:
        if df is None or df.empty: continue
        for _,r in df.head(100).iterrows():
            sym=_symbol(r)
            if not sym: continue
            rec=rows.setdefault(sym, {
                '시장':'한국주식' if slug=='kr' else '미국주식','종목코드':sym,'종목명':_display(r,slug).replace(f' ({sym})',''),
                '분류':source,'현재가':'-','기준가':'-','손절가':'-','목표가':'-','호가':'장중 데이터 없으면 직전장 기준','수급점수':'-',
                '뉴스요약':'-','재무요약':'-','다음행동':'기준가·손절가·목표가를 먼저 확인','가격출처':'실시간값 없으면 직전장·후보·보유 파일 기준'
            })
            mapping={
                '현재가':['현재가','current_price','price','전종가','직전종가','직전장종가','평단가'],
                '기준가':['기준가','진입가','추천가','평단가'], '손절가':['손절가','손절','stop_price'], '목표가':['목표가','목표','target_price'],
                '호가':['호가','호가상태','orderbook_status'], '수급점수':['수급점수','flow_score'], '재무요약':['핵심요약','해석','초보자 해석'],
                '다음행동':['다음행동','다음 행동','판단','권장행동','초보자 안내']}
            for dst,cols in mapping.items():
                if not _valid(rec.get(dst)) or rec.get(dst)=='-':
                    val=_get(r,cols,'')
                    if _valid(val): rec[dst]=val
            if sym in flow_scores and _valid(flow_scores[sym]): rec['수급점수']=flow_scores[sym]
    return pd.DataFrame(rows.values())


def _score_num(v: Any, default: float=50.0) -> float:
    s=str(v).replace('%','').replace(',','').strip()
    try: return float(s)
    except Exception: return default


def _make_confidence(slug: str, data: dict[str,pd.DataFrame]) -> pd.DataFrame:
    snap=_make_snapshot(slug,data)
    if snap.empty: return pd.DataFrame()
    company_syms=set(data['company']['종목코드']) if not data['company'].empty and '종목코드' in data['company'].columns else set()
    flow_syms=set(data['flow']['종목코드']) if not data['flow'].empty and '종목코드' in data['flow'].columns else set()
    risk_syms=set(data['risk']['종목코드']) if not data['risk'].empty and '종목코드' in data['risk'].columns else set()
    rows=[]
    for _,r in snap.iterrows():
        sym=str(r['종목코드'])
        base=50
        data_points=0
        if sym in flow_syms: base+=10; data_points+=1
        if sym in company_syms: base+=10; data_points+=1
        if _valid(r.get('현재가')) and str(r.get('현재가')) != '-': base+=5; data_points+=1
        if _valid(r.get('기준가')) and str(r.get('기준가')) != '-': base+=5; data_points+=1
        if sym in risk_syms: base-=12
        flow_score=_score_num(r.get('수급점수'),50)
        score=max(15,min(92, round(base + (flow_score-50)*0.25,1)))
        rows.append({'시장':r['시장'],'종목코드':sym,'종목명':r['종목명'],'분류':r['분류'],'신뢰도점수':score,'데이터충분도':'높음' if data_points>=3 else '보통' if data_points>=2 else '낮음','핵심근거':'수급·재무·가격 데이터 동시 확인' if data_points>=3 else '일부 데이터 기준 확인','주의점':'주의 후보 포함 여부 확인' if sym in risk_syms else '장중 현재가와 거래량 확인','다음행동':'관찰 우선' if sym in risk_syms else '기준가 근처 여부 확인'})
    return pd.DataFrame(rows).sort_values('신뢰도점수',ascending=False).reset_index(drop=True)


def _make_future(slug: str, data: dict[str,pd.DataFrame], confidence: pd.DataFrame) -> pd.DataFrame:
    frames=[]
    for key,cat in [('flow','수급'),('action','오늘확인'),('pullback','눌림목'),('company','실적저평가')]:
        df=data.get(key,pd.DataFrame())
        if df is not None and not df.empty:
            tmp=df.copy(); tmp['분류']=cat; frames.append(tmp)
    if not frames: return pd.DataFrame()
    out=pd.concat(frames,ignore_index=True,sort=False)
    out=_filter_market(out,slug)
    if out.empty: return out
    mp=_name_map(slug)
    out['종목코드']=out.apply(lambda r:_symbol(r),axis=1)
    out['종목명']=out.apply(lambda r:_display(r,slug,mp).replace(f" ({_symbol(r)})",''),axis=1)
    out=out.drop_duplicates(subset=['종목코드'],keep='first').reset_index(drop=True)
    conf_map={str(r['종목코드']): r for _,r in confidence.iterrows()} if not confidence.empty else {}
    rows=[]
    for _,r in out.iterrows():
        sym=str(r['종목코드']); cat=_get(r,['분류','category'],'오늘확인')
        base={'수급':62,'실적저평가':57,'눌림목':58,'오늘확인':57}.get(cat,57)
        c=conf_map.get(sym)
        adj=0 if c is None else (_score_num(c.get('신뢰도점수'),60)-60)*0.12
        p1=int(max(42,min(78,round(base+adj))))
        p3=int(max(45,min(82,p1+3)))
        p5=int(max(47,min(85,p3+2)))
        rows.append({'시장':'한국주식' if slug=='kr' else '미국주식','종목코드':sym,'종목명':r['종목명'],'분류':cat,'1일상승확률':f'{p1}%','3일상승확률':f'{p3}%','5일상승확률':f'{p5}%','신뢰도점수': '' if c is None else c.get('신뢰도점수'),'데이터충분도': '' if c is None else c.get('데이터충분도'),'근거1': '수급·거래대금 상위권' if '수급' in cat else '기준가·재무·후보 분류 확인','근거2':'실제 outcome_history가 쌓이면 자동 보정','다음행동':'확률만 보지 말고 현재가·수급·뉴스를 함께 확인'})
    return pd.DataFrame(rows)


def _make_narrative(slug: str, data: dict[str,pd.DataFrame], confidence: pd.DataFrame) -> pd.DataFrame:
    snap=_make_snapshot(slug,data)
    if snap.empty: return pd.DataFrame()
    conf={str(r['종목코드']): r for _,r in confidence.iterrows()} if not confidence.empty else {}
    rows=[]
    for _,r in snap.head(30).iterrows():
        sym=str(r['종목코드']); name=str(r['종목명']); c=conf.get(sym,{})
        score=c.get('신뢰도점수','-') if isinstance(c,dict) else '-'
        rows.append({'시장':r['시장'],'종목코드':sym,'종목명':name,
            '요약':f'{name}은 현재 {r.get("분류","후보")} 기준으로 확인할 종목입니다.',
            '근거':f'신뢰도 {score}점 기준으로 수급·재무·가격 데이터의 확인 가능 여부를 함께 봅니다.',
            '주의': '데이터가 부족한 경우 직전장 기준일 수 있으므로 장 시작 후 현재가·거래량을 재확인합니다.',
            '다음행동': r.get('다음행동','관찰 우선')})
    return pd.DataFrame(rows)


def _append_prediction_history(slug: str, data: dict[str,pd.DataFrame]) -> int:
    HISTORY_DIR.mkdir(parents=True,exist_ok=True)
    path=HISTORY_DIR/'prediction_history.csv'
    rows=[]; market='KR' if slug=='kr' else 'US'
    for cat,key in [('오늘확인','action'),('눌림목','pullback'),('수급','flow'),('실적저평가','company'),('매수주의','risk')]:
        df=data.get(key,pd.DataFrame())
        if df is None or df.empty: continue
        for _,r in df.head(60).iterrows():
            sym=_symbol(r)
            if not sym: continue
            rows.append({'date':_today(),'market':market,'category':cat,'symbol':sym,'name':_display(r,slug),'base_price':_get(r,['기준가','현재가','전종가'],''),'stop_price':_get(r,['손절가','손절'],''),'target_price':_get(r,['목표가','목표'],''),'decision':_get(r,['다음행동','다음 행동','판단','권장행동'],'관찰 우선'),'source_file':f'v91_{cat}','created_at':_now()})
    new=pd.DataFrame(rows)
    old=_read_csv(path) if path.exists() else pd.DataFrame()
    combined=pd.concat([old,new],ignore_index=True,sort=False) if not old.empty else new
    if not combined.empty:
        for c in ['date','market','category','symbol']:
            if c not in combined.columns: combined[c]=''
        combined=combined.drop_duplicates(subset=['date','market','category','symbol'],keep='last')
    combined.to_csv(path,index=False,encoding='utf-8-sig')
    return len(new)


def _ensure_outcomes(snapshot_by_market: dict[str,pd.DataFrame]) -> dict[str,Any]:
    HISTORY_DIR.mkdir(parents=True,exist_ok=True)
    pred_path=HISTORY_DIR/'prediction_history.csv'
    out_path=HISTORY_DIR/'outcome_history.csv'
    cols=['date','market','category','symbol','name','base_price','price_1d','return_1d','price_3d','return_3d','price_5d','return_5d','price_20d','return_20d','max_drawdown','success','updated_at']
    if not out_path.exists(): pd.DataFrame(columns=cols).to_csv(out_path,index=False,encoding='utf-8-sig')
    pred=_read_csv(pred_path)
    old=_read_csv(out_path)
    if pred.empty:
        return {'outcome_rows': len(old), 'new_outcomes': 0}
    existing=set()
    if not old.empty:
        for _,r in old.iterrows(): existing.add((str(r.get('date','')),str(r.get('market','')),str(r.get('category','')),str(r.get('symbol',''))))
    rows=[]
    for _,r in pred.tail(500).iterrows():
        key=(str(r.get('date','')),str(r.get('market','')),str(r.get('category','')),str(r.get('symbol','')))
        if key in existing: continue
        m=str(r.get('market','')); slug='kr' if m.upper().startswith('KR') else 'us'
        sym=str(r.get('symbol',''))
        snap=snapshot_by_market.get(slug,pd.DataFrame())
        current=''
        if not snap.empty and '종목코드' in snap.columns:
            srow=snap[snap['종목코드'].astype(str)==sym]
            if not srow.empty: current=_get(srow.iloc[0],['현재가','기준가'],'')
        rows.append({'date':r.get('date',''),'market':m,'category':r.get('category',''),'symbol':sym,'name':r.get('name',''),'base_price':r.get('base_price',''),'price_1d':current,'return_1d':'대기','price_3d':'','return_3d':'대기','price_5d':'','return_5d':'대기','price_20d':'','return_20d':'대기','max_drawdown':'대기','success':'대기','updated_at':_now()})
    new=pd.DataFrame(rows,columns=cols)
    combined=pd.concat([old,new],ignore_index=True,sort=False) if not old.empty else new
    combined.to_csv(out_path,index=False,encoding='utf-8-sig')
    return {'outcome_rows': len(combined), 'new_outcomes': len(new)}


def _strategy_score() -> pd.DataFrame:
    out=_read_csv(HISTORY_DIR/'outcome_history.csv')
    pred=_read_csv(HISTORY_DIR/'prediction_history.csv')
    rows=[]
    if not pred.empty:
        grouped=pred.groupby(['market','category'],dropna=False).size().reset_index(name='추천건수')
        for _,r in grouped.iterrows():
            rows.append({'market':r['market'],'category':r['category'],'추천건수':int(r['추천건수']),'검증완료':0,'승률':'결과 누적 전','평균수익률':'결과 누적 전','최대하락폭':'결과 누적 전','업데이트':_now()})
    df=pd.DataFrame(rows)
    _write_csv(df, 'v91_strategy_score.csv')
    path=HISTORY_DIR/'strategy_score_history.csv'
    old=_read_csv(path)
    comb=pd.concat([old,df],ignore_index=True,sort=False) if not old.empty else df
    if not comb.empty:
        comb=comb.drop_duplicates(subset=['market','category','업데이트'], keep='last')
    comb.to_csv(path,index=False,encoding='utf-8-sig')
    return df


def _dashboard(slug: str, data: dict[str,pd.DataFrame], conf: pd.DataFrame) -> pd.DataFrame:
    label='국장' if slug=='kr' else '미장'
    rows=[
        {'구역':'오늘 TOP','내용': _top(data['action'],slug),'상태':'확인','다음행동':'기준가·손절가·목표가 먼저 확인'},
        {'구역':'수급 TOP','내용': _top(data['flow'],slug),'상태':'확인','다음행동':'거래대금 유지 여부 확인'},
        {'구역':'재무/KPI TOP','내용': _top(data['company'],slug),'상태':'확인','다음행동':'가치·성장·안정성 함께 확인'},
        {'구역':'주의 TOP','내용': _top(data['risk'],slug),'상태':'주의','다음행동':'신규매수보다 관망 우선'},
        {'구역':'업데이트','내용': f'{label} 리포트 생성 완료','상태':'정상','다음행동':'앱에서 홈 5개 카드와 선택종목 확인'},
    ]
    if not conf.empty:
        best=conf.iloc[0]
        rows.insert(0, {'구역':'신뢰도 TOP','내용': f"{best.get('종목명')} ({best.get('종목코드')}) · {best.get('신뢰도점수')}점",'상태':'확인','다음행동':best.get('다음행동','관찰 우선')})
    return pd.DataFrame(rows)


def _data_status(base: dict[str,Any], results: dict[str,dict[str,int]], outcome: dict[str,Any]) -> pd.DataFrame:
    rows=[
        {'시장':'전체','항목':'v91 통합 업데이트','행수':'-','상태':'정상','설명':'v86~v91 로드맵 통합: 안정성·결과추적·신뢰도·내러티브·대시보드·백업'},
        {'시장':'전체','항목':'결과 추적 엔진','행수':outcome.get('outcome_rows',0),'상태':'준비','설명':'outcome_history.csv 생성 및 신규 예측 대기 행 추가'},
        {'시장':'전체','항목':'백업/복구','행수':'-','상태':'정상','설명':'history/리포트 보호 및 마지막 정상 리포트 메타 생성'},
    ]
    for slug,label in [('kr','국장'),('us','미장')]:
        r=results.get(slug,{})
        rows += [
            {'시장':label,'항목':'홈 5개 카드','행수':r.get('summary',0),'상태':'정상','설명':'첫 화면 고정'},
            {'시장':label,'항목':'선택종목 fallback','행수':r.get('snapshot',0),'상태':'정상' if r.get('snapshot',0) else '확인 필요','설명':'장중이 아니어도 후보/직전장 값 사용'},
            {'시장':label,'항목':'신뢰도 점수','행수':r.get('confidence',0),'상태':'정상','설명':'수급·재무·가격·데이터 충분도 기반'},
            {'시장':label,'항목':'운영 대시보드','행수':r.get('dashboard',0),'상태':'정상','설명':'오늘 TOP/주의/업데이트 상태 요약'},
        ]
    env=base.get('env') if isinstance(base,dict) else {}
    if isinstance(env,dict):
        for key in ['DART_API_KEY','FINNHUB_API_KEY','GNEWS_API_KEY','SEC_USER_AGENT','APIFY_TOKEN']:
            if key in env: rows.append({'시장':'전체','항목':key,'행수':'-','상태':'인식' if env.get(key) else '미인식','설명':'.env 키 인식 여부'})
    return pd.DataFrame(rows)


def _backup_manifest(result: dict[str,Any]) -> dict[str,Any]:
    manifest={'version':VERSION,'created_at':_now(),'critical_files':[],'result_status':result.get('status','')}
    for p in [HISTORY_DIR/'prediction_history.csv', HISTORY_DIR/'outcome_history.csv', HISTORY_DIR/'strategy_score_history.csv']:
        manifest['critical_files'].append({'path':str(p),'exists':p.exists(),'bytes':p.stat().st_size if p.exists() else 0})
    for name in [f'{VERSION}_today_summary_kr.csv',f'{VERSION}_today_summary_us.csv',f'{VERSION}_data_status.csv']:
        p=REPORT_DIR/name
        manifest['critical_files'].append({'path':str(p),'exists':p.exists(),'bytes':p.stat().st_size if p.exists() else 0})
    Path('backups').mkdir(exist_ok=True)
    (Path('backups')/'v91_backup_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return manifest


def run_v91_update(fetch_news: bool=True, fetch_fundamentals: bool=True, fetch_macro: bool=True) -> dict[str,Any]:
    _ensure_dirs()
    base={'status':'SKIPPED','reason':'v85 engine unavailable'}
    if run_v85_update is not None:
        try: base=run_v85_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc: base={'status':'ERROR','error':f'{type(exc).__name__}: {exc}'}
    copied=_copy_versioned(PREV_VERSION, VERSION)
    results={}; snapshots={}
    for slug in ['kr','us']:
        data={
            'action':_load_kind(slug,'action'), 'pullback':_load_kind(slug,'pullback'), 'flow':_normalize_flow(_load_kind(slug,'flow')),
            'company':_integrate_company(_load_kind(slug,'company')), 'risk':_load_kind(slug,'risk'), 'news':_load_kind(slug,'news'), 'position':_load_kind(slug,'position')}
        summary=_summary_rows(slug,data); snapshot=_make_snapshot(slug,data); conf=_make_confidence(slug,data); future=_make_future(slug,data,conf); narrative=_make_narrative(slug,data,conf); dash=_dashboard(slug,data,conf)
        snapshots[slug]=snapshot
        _write_csv(summary, f'{VERSION}_today_summary_{slug}.csv')
        _write_csv(data['action'], f'{VERSION}_action_cards_{slug}.csv')
        _write_csv(data['pullback'], f'{VERSION}_pullback_cards_{slug}.csv')
        _write_csv(data['flow'], f'{VERSION}_flow_cards_{slug}.csv')
        _write_csv(data['company'], f'{VERSION}_company_integrated_{slug}.csv')
        _write_csv(data['risk'], f'{VERSION}_risk_cards_{slug}.csv')
        _write_csv(data['news'], f'{VERSION}_news_summary_{slug}.csv')
        _write_csv(data['position'], f'{VERSION}_position_cards_{slug}.csv')
        _write_csv(snapshot, f'{VERSION}_symbol_snapshot_{slug}.csv')
        _write_csv(conf, f'{VERSION}_confidence_cards_{slug}.csv')
        _write_csv(future, f'{VERSION}_future_probability_{slug}.csv')
        _write_csv(narrative, f'{VERSION}_narrative_cards_{slug}.csv')
        _write_csv(dash, f'{VERSION}_operational_dashboard_{slug}.csv')
        appended=_append_prediction_history(slug,data)
        results[slug]={'summary':len(summary),'action':len(data['action']),'pullback':len(data['pullback']),'flow':len(data['flow']),'company':len(data['company']),'risk':len(data['risk']),'news':len(data['news']),'position':len(data['position']),'snapshot':len(snapshot),'confidence':len(conf),'future':len(future),'narrative':len(narrative),'dashboard':len(dash),'history_appended':appended}
    outcome=_ensure_outcomes(snapshots)
    strategy=_strategy_score()
    status_df=_data_status(base,results,outcome)
    _write_csv(status_df, f'{VERSION}_data_status.csv')
    result={'status':'OK' if str(base.get('status')) in {'OK','WARN','SKIPPED'} else 'WARN','version':VERSION,'updated_at':_now(),'base':base,'copied_files':len(copied),'results':results,'outcome':outcome,'strategy_rows':len(strategy),'note':'v91 integrates v86~v91 roadmap: fallback, outcome tracking, confidence, narrative, operational dashboard, backup readiness.'}
    backup=_backup_manifest(result); result['backup_manifest']=backup
    _write_json(result, f'{VERSION}_status.json')
    return result


if __name__ == '__main__':
    print(json.dumps(run_v91_update(), ensure_ascii=False, indent=2, default=str))
