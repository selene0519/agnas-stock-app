
from __future__ import annotations
import json, re, shutil
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd
try:
    from core.v72_visible_guard_quant_engine import run_v72_update
except Exception:
    run_v72_update = None
try:
    from core.v69_finance_api_engine import REPORT_DIR, _now, _read_csv, _write_csv, _write_json
except Exception:
    REPORT_DIR = Path('reports')
    def _now() -> str: return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    def _read_csv(path: str | Path) -> pd.DataFrame:
        p=Path(path)
        if p.exists() and p.stat().st_size:
            try: return pd.read_csv(p)
            except Exception:
                try: return pd.read_csv(p, encoding='utf-8-sig')
                except Exception: return pd.DataFrame()
        return pd.DataFrame()
    def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
        p=Path(path); p.parent.mkdir(parents=True, exist_ok=True); df.to_csv(p, index=False, encoding='utf-8-sig')
    def _write_json(data: dict[str, Any], path: str | Path) -> None:
        p=Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
US_TICKER_RE=re.compile(r'^[A-Z]{1,5}(?:[-.][A-Z])?$')
KR_CODE_RE=re.compile(r'^\d{5,6}$')
HANGUL_RE=re.compile(r'[가-힣]')
def _safe_read(name: str) -> pd.DataFrame: return _read_csv(REPORT_DIR/name)
def _is_empty(v: Any) -> bool:
    s=str(v).strip(); return not s or s.lower() in {'nan','none','null','nat','-'}
def _row_market_ok(row: pd.Series, slug: str) -> bool:
    vals=[str(v).strip() for v in row.to_dict().values() if not _is_empty(v)]
    text=' '.join(vals)
    market_text=' '.join(str(row.get(c,'')).strip() for c in ['시장','market','마켓'] if c in row.index)
    candidates=[]
    for c in ['종목코드','종목','종목명','symbol','ticker','티커','TOP']:
        if c in row.index and not _is_empty(row.get(c)): candidates.append(str(row.get(c)).strip())
    has_kr_code=any(KR_CODE_RE.match(x.zfill(6) if x.isdigit() and len(x)<6 else x) for x in candidates)
    has_hangul=bool(HANGUL_RE.search(text)); has_us_ticker=any(US_TICKER_RE.match(x) for x in candidates)
    if slug=='kr':
        if re.search(r'미국|미장|United States|NASDAQ|NYSE', market_text, re.I): return False
        if has_us_ticker and not has_kr_code and not has_hangul: return False
        return has_kr_code or has_hangul or not candidates
    if slug=='us':
        if re.search(r'한국|국장|KOSPI|KOSDAQ', market_text, re.I): return False
        if has_kr_code and not has_us_ticker: return False
        return has_us_ticker or ('미국주식' in text) or ('미국' in market_text) or not candidates
    return True
def _clean_market_df(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    if df is None or df.empty: return pd.DataFrame()
    return df.loc[[_row_market_ok(r, slug) for _, r in df.iterrows()]].copy().reset_index(drop=True)
def _first_value(df: pd.DataFrame, *cols: str) -> str:
    if df is None or df.empty: return '후보 없음'
    row=df.iloc[0]
    for c in list(cols)+['종목명','종목','종목코드','symbol','ticker','TOP']:
        if c in df.columns and not _is_empty(row.get(c)): return str(row.get(c)).strip()
    return '후보 있음'
def _company_valid(df: pd.DataFrame, slug: str) -> pd.DataFrame:
    out=_clean_market_df(df, slug)
    if out.empty: return pd.DataFrame()
    if '종목코드' in out.columns: out=out[~out['종목코드'].astype(str).str.strip().str.lower().isin(['','-','nan','none','null'])]
    if '재무상태' in out.columns:
        out['_ok']=out['재무상태'].astype(str).str.contains('수신|요약|가능|확인', regex=True, na=False).astype(int)
        out=out.sort_values('_ok', ascending=False).drop(columns=['_ok'], errors='ignore')
    return out.reset_index(drop=True)
def _build_today_summary(slug: str) -> pd.DataFrame:
    action=_clean_market_df(_safe_read(f'v67_action_board_{slug}.csv'), slug)
    pull=_clean_market_df(_safe_read(f'v67_pullback_{slug}.csv'), slug)
    flow=_clean_market_df(_safe_read(f'v67_flow_{slug}.csv'), slug)
    company=_company_valid(_safe_read(f'v70_company_cards_{slug}.csv'), slug)
    if company.empty: company=_company_valid(_safe_read(f'v69_company_cards_{slug}.csv'), slug)
    risk=_clean_market_df(_safe_read(f'v67_risk_{slug}.csv'), slug)
    for df,name in [(action,'action'),(pull,'pullback'),(flow,'flow'),(company,'company'),(risk,'risk')]: _write_csv(df, REPORT_DIR/f'v73_{name}_clean_{slug}.csv')
    rows=[
        {'카드':'오늘 우선 확인','아이콘':'🎯','설명':'진입가·손절가·목표가를 먼저 확인할 후보','건수':len(action),'TOP':_first_value(action),'상세파일':f'v73_action_clean_{slug}.csv','우선순위':1,'구분':'buy'},
        {'카드':'눌림목 진입 후보','아이콘':'🪜','설명':'추격보다 눌림/기준가 근처 진입을 기다릴 후보','건수':len(pull),'TOP':_first_value(pull),'상세파일':f'v73_pullback_clean_{slug}.csv','우선순위':2,'구분':'buy'},
        {'카드':'수급 급증 후보','아이콘':'💚','설명':'외국인·기관·거래대금 흐름을 우선 보는 후보','건수':len(flow),'TOP':_first_value(flow),'상세파일':f'v73_flow_clean_{slug}.csv','우선순위':3,'구분':'buy'},
        {'카드':'실적·저평가 후보','아이콘':'💎','설명':'재무·KPI·밸류에이션을 같이 확인할 후보','건수':len(company),'TOP':_first_value(company,'종목명','종목코드'),'상세파일':f'v73_company_clean_{slug}.csv','우선순위':4,'구분':'value'},
        {'카드':'매수금지·주의','아이콘':'🚫','설명':'신규매수보다 제외·관망이 우선인 후보','건수':len(risk),'TOP':_first_value(risk),'상세파일':f'v73_risk_clean_{slug}.csv','우선순위':5,'구분':'risk'}]
    out=pd.DataFrame(rows); _write_csv(out, REPORT_DIR/f'v73_today_summary_{slug}.csv'); return out
def _copy_if_exists(src: str, dst: str) -> bool:
    s=REPORT_DIR/src; d=REPORT_DIR/dst
    if s.exists() and s.stat().st_size: d.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(s,d); return True
    return False
def _build_manifest(base: dict[str, Any]) -> dict[str, Any]:
    rows=[]
    for slug,label in [('kr','국장'),('us','미장')]:
        for title,name in [('오늘 실행 5카드',f'v73_today_summary_{slug}.csv'),('정제 수급',f'v73_flow_clean_{slug}.csv'),('정제 재무',f'v73_company_clean_{slug}.csv'),('시장 가드',f'v73_market_guard_{slug}.csv'),('보유·매도 카드',f'v73_position_cards_{slug}.csv'),('뉴스 카드',f'v70_news_cards_{slug}.csv')]:
            p=REPORT_DIR/name; df=_read_csv(p); rows.append({'시장':label,'항목':title,'파일':name,'행수':0 if df.empty else len(df),'파일상태':'있음' if p.exists() and p.stat().st_size else '없음','마지막수정':datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S') if p.exists() else '-'})
    status_df=pd.DataFrame(rows); _write_csv(status_df, REPORT_DIR/'v73_visible_data_status.csv')
    manifest={'status':'OK','version':'v73','updated_at':_now(),'fixes':['final main hook moved to bottom','KR/US market contamination filter','five-card first screen visible'],'base_result':base,'data_status_rows':len(status_df)}
    _write_json(manifest, REPORT_DIR/'v73_status.json'); return manifest
def run_v73_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    # v73 is a screen-hook and market-clean hotfix. It uses the reports already created by v67/v70/v72,
    # then rebuilds market-safe v73 summary files so KR never displays US tickers such as GOOGL.
    base = {'status': 'SKIPPED', 'version': 'v73_hotfix', 'note': 'existing reports reused; run v70/v72 separately for fresh API collection'}
    result={'status':'OK','version':'v73','updated_at':_now(),'base':base}
    for slug in ['kr','us']:
        summary=_build_today_summary(slug)
        for src,dst in [(f'v72_market_guard_{slug}.csv',f'v73_market_guard_{slug}.csv'),(f'v72_sector_strength_{slug}.csv',f'v73_sector_strength_{slug}.csv'),(f'v72_position_cards_{slug}.csv',f'v73_position_cards_{slug}.csv'),(f'v72_signal_panel_{slug}.csv',f'v73_signal_panel_{slug}.csv')]:
            _copy_if_exists(src,dst)
        result[slug]={'today_cards':len(summary),'flow_clean_rows':len(_read_csv(REPORT_DIR/f'v73_flow_clean_{slug}.csv')),'company_clean_rows':len(_read_csv(REPORT_DIR/f'v73_company_clean_{slug}.csv'))}
    return _build_manifest(result)
