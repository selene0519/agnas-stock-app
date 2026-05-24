from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v70_news_finance_market_fix_engine import run_v70_update
except Exception:  # pragma: no cover
    run_v70_update = None

try:
    from core.v69_finance_api_engine import REPORT_DIR, _now, _read_csv, _write_csv, _write_json, _market_name
except Exception:  # fallback for old bundles
    REPORT_DIR = Path('reports')
    def _now() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    def _read_csv(path: str | Path) -> pd.DataFrame:
        p=Path(path)
        if p.exists() and p.stat().st_size:
            try: return pd.read_csv(p)
            except Exception: return pd.DataFrame()
        return pd.DataFrame()
    def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
        p=Path(path); p.parent.mkdir(parents=True, exist_ok=True); df.to_csv(p, index=False, encoding='utf-8-sig')
    def _write_json(data: dict[str, Any], path: str | Path) -> None:
        p=Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    def _market_name(slug: str) -> str:
        return '한국주식' if slug == 'kr' else '미국주식'


def _safe_read(name: str) -> pd.DataFrame:
    return _read_csv(REPORT_DIR / name)


def _not_empty_value(v: Any) -> bool:
    s = str(v).strip()
    return bool(s) and s.lower() not in {'nan', 'none', 'null', 'nat', '-', ''}


def _first_value(df: pd.DataFrame, *cols: str) -> str:
    if df is None or df.empty:
        return '후보 없음'
    row = df.iloc[0]
    for c in cols:
        if c in df.columns and _not_empty_value(row.get(c)):
            return str(row.get(c)).strip()
    for c in ['종목명','종목','종목코드','symbol','ticker']:
        if c in df.columns and _not_empty_value(row.get(c)):
            return str(row.get(c)).strip()
    return '후보 있음'


def _company_valid(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if '종목코드' in out.columns:
        out = out[~out['종목코드'].astype(str).str.strip().str.lower().isin(['', '-', 'nan', 'none', 'null'])]
    if '재무상태' in out.columns:
        # keep both received and 부족 rows, but received rows first
        out['_ok'] = out['재무상태'].astype(str).str.contains('수신|요약|가능|확인', regex=True, na=False).astype(int)
        out = out.sort_values('_ok', ascending=False).drop(columns=['_ok'], errors='ignore')
    return out.reset_index(drop=True)


def _build_today_summary(slug: str) -> pd.DataFrame:
    action = _safe_read(f'v67_action_board_{slug}.csv')
    pull = _safe_read(f'v67_pullback_{slug}.csv')
    flow = _safe_read(f'v67_flow_{slug}.csv')
    company = _company_valid(_safe_read(f'v70_company_cards_{slug}.csv'))
    if company.empty:
        company = _company_valid(_safe_read(f'v69_company_cards_{slug}.csv'))
    risk = _safe_read(f'v67_risk_{slug}.csv')
    rows = [
        {'카드':'오늘 우선 확인','아이콘':'🎯','설명':'진입가·손절가·목표가를 먼저 확인할 후보','건수':len(action),'TOP':_first_value(action),'상세파일':f'v67_action_board_{slug}.csv','우선순위':1,'구분':'buy'},
        {'카드':'눌림목 진입 후보','아이콘':'🪜','설명':'추격보다 눌림/기준가 근처 진입을 기다릴 후보','건수':len(pull),'TOP':_first_value(pull),'상세파일':f'v67_pullback_{slug}.csv','우선순위':2,'구분':'buy'},
        {'카드':'수급 급증 후보','아이콘':'💚','설명':'외국인·기관·거래대금 흐름을 우선 보는 후보','건수':len(flow),'TOP':_first_value(flow),'상세파일':f'v67_flow_{slug}.csv','우선순위':3,'구분':'buy'},
        {'카드':'실적·저평가 후보','아이콘':'💎','설명':'재무·KPI·밸류에이션을 같이 확인할 후보','건수':len(company),'TOP':_first_value(company, '종목명','종목코드'),'상세파일':f'v70_company_cards_{slug}.csv','우선순위':4,'구분':'value'},
        {'카드':'매수금지·주의','아이콘':'🚫','설명':'신규매수보다 제외·관망이 우선인 후보','건수':len(risk),'TOP':_first_value(risk),'상세파일':f'v67_risk_{slug}.csv','우선순위':5,'구분':'risk'},
    ]
    df=pd.DataFrame(rows)
    _write_csv(df, REPORT_DIR / f'v71_today_summary_{slug}.csv')
    return df


def _build_position_cards(slug: str) -> pd.DataFrame:
    src = _safe_read(f'v67_position_plan_{slug}.csv')
    if src.empty:
        out=pd.DataFrame()
        _write_csv(out, REPORT_DIR / f'v71_position_cards_{slug}.csv')
        return out
    rows=[]
    for _, r in src.iterrows():
        name = str(r.get('종목', r.get('종목명', r.get('종목코드','-')))).strip()
        action = str(r.get('권장행동', r.get('판단','보유 점검'))).strip()
        ret = str(r.get('수익률','-')).strip()
        current = str(r.get('현재가','-')).strip()
        qty = str(r.get('보유수량','-')).strip()
        rec_qty = str(r.get('권장수량','-')).strip()
        amount = str(r.get('예상금액','-')).strip()
        source = str(r.get('가격출처','-')).strip()
        guide = str(r.get('초보자 안내', r.get('다음 행동','실제 주문 전 증권사 현재가와 비교하세요.'))).strip()
        rows.append({
            **r.to_dict(),
            '카드제목': name,
            '판단': action,
            '핵심요약': f'보유 {qty} · 현재가 {current} · 수익률 {ret}',
            '수량요약': f'권장수량 {rec_qty} · 예상금액 {amount}',
            '가격출처표시': source or '-',
            '다음행동표시': guide,
        })
    out=pd.DataFrame(rows)
    _write_csv(out, REPORT_DIR / f'v71_position_cards_{slug}.csv')
    return out


def _percent_from_text(x: Any) -> float | None:
    try:
        s=str(x).replace('%','').replace(',','').strip()
        if s in {'','-','nan','None'}: return None
        return float(s)
    except Exception:
        return None


def _build_market_guard(slug: str) -> pd.DataFrame:
    macro = _safe_read(f'v70_macro_cards_{slug}.csv')
    risk = _safe_read(f'v67_risk_{slug}.csv')
    action = _safe_read(f'v67_action_board_{slug}.csv')
    flow = _safe_read(f'v67_flow_{slug}.csv')
    sector = _build_sector_strength(slug, action, flow)
    changes=[]
    if not macro.empty and '변화율' in macro.columns:
        for v in macro['변화율'].tolist():
            pv=_percent_from_text(v)
            if pv is not None:
                changes.append(pv)
    avg = sum(changes)/len(changes) if changes else 0.0
    risk_ratio = (len(risk) / max(len(action),1)) if not action.empty else (1.0 if not risk.empty else 0.0)
    score = 50 + max(min(avg*8, 25), -25) - min(risk_ratio*25, 25) + min(len(flow),10)
    score = max(0, min(100, round(score, 1)))
    if score >= 70:
        phase, action_txt = '우호', '정상 비중 또는 분할 진입 가능'
    elif score >= 50:
        phase, action_txt = '중립', '기준가 확인 후 소액/분할만 고려'
    else:
        phase, action_txt = '주의', '신규매수 축소, 관망 우선'
    strongest = '데이터 필요'
    if not sector.empty:
        strongest = str(sector.iloc[0].get('섹터','데이터 필요'))
    rows=[
        {'카드':'시장 국면','값':phase,'점수':score,'해석':f'직전 지수 변화와 위험 후보 비중을 합산한 시장 점수입니다.','다음행동':action_txt,'출처':'v70_macro + v67_risk/action'},
        {'카드':'시장 폭','값':f'{avg:.2f}%','점수':round(50+avg*10,1),'해석':'KOSPI/KOSDAQ 또는 S&P/NASDAQ/VIX 직전 변화율을 참고합니다.','다음행동':'지수가 약하면 좋은 종목도 비중을 줄입니다.','출처':'yfinance 직전 종가'},
        {'카드':'섹터 강도','값':strongest,'점수':round(float(sector.iloc[0].get('강도점수',0)) if not sector.empty else 0,1),'해석':'후보·수급 리포트에 반복 등장하는 섹터를 우선 표시합니다.','다음행동':'강한 섹터 안에서만 종목을 고릅니다.','출처':'candidate/flow reports'},
        {'카드':'리스크 룰','값':f'위험 {len(risk)}개','점수':round(100-min(risk_ratio*100,100),1),'해석':'매수금지·주의 후보가 많으면 시장 난이도가 높다고 봅니다.','다음행동':'위험 후보가 많을수록 신규매수보다 관망합니다.','출처':'v67_risk'},
    ]
    out=pd.DataFrame(rows)
    _write_csv(out, REPORT_DIR / f'v71_market_guard_{slug}.csv')
    return out


def _build_sector_strength(slug: str, action: pd.DataFrame | None = None, flow: pd.DataFrame | None = None) -> pd.DataFrame:
    if action is None: action = _safe_read(f'v67_action_board_{slug}.csv')
    if flow is None: flow = _safe_read(f'v67_flow_{slug}.csv')
    parts=[]
    for df, w in [(action, 1.0), (flow, 1.5)]:
        if df is None or df.empty: continue
        col = None
        for c in ['섹터','업종','sector','업종명','테마']:
            if c in df.columns:
                col=c; break
        if col is None:
            continue
        tmp=df[[col]].copy(); tmp['가중치']=w; tmp=tmp.rename(columns={col:'섹터'})
        parts.append(tmp)
    if not parts:
        out=pd.DataFrame([{'섹터':'데이터 필요','후보수':0,'강도점수':0,'해석':'후보 리포트에 섹터/업종 컬럼이 아직 없습니다.'}])
    else:
        all_df=pd.concat(parts, ignore_index=True)
        all_df['섹터']=all_df['섹터'].astype(str).replace({'nan':'미분류','None':'미분류','':'미분류','-':'미분류'})
        g=all_df.groupby('섹터', as_index=False).agg(후보수=('섹터','size'), 강도점수=('가중치','sum')).sort_values(['강도점수','후보수'], ascending=False)
        g['해석']=g.apply(lambda r: f"후보 {int(r['후보수'])}개, 가중점수 {float(r['강도점수']):.1f}. 같은 섹터 내 종목만 비교하세요.", axis=1)
        out=g.head(12).reset_index(drop=True)
    _write_csv(out, REPORT_DIR / f'v71_sector_strength_{slug}.csv')
    return out


def _build_signal_panel(slug: str) -> pd.DataFrame:
    action=_safe_read(f'v67_action_board_{slug}.csv')
    pull=_safe_read(f'v67_pullback_{slug}.csv')
    flow=_safe_read(f'v67_flow_{slug}.csv')
    risk=_safe_read(f'v67_risk_{slug}.csv')
    rows=[
        {'지표':'오늘 우선 후보','값':len(action),'상태':'확인','해석':'기준가·손절가가 있는 후보 수입니다.'},
        {'지표':'눌림목 후보','값':len(pull),'상태':'관찰','해석':'추격 대신 대기할 후보 수입니다.'},
        {'지표':'수급·거래대금 후보','값':len(flow),'상태':'확인','해석':'국장은 수급, 미장은 거래량/거래대금 대체지표 중심입니다.'},
        {'지표':'매수금지·주의','값':len(risk),'상태':'주의' if len(risk) else '양호','해석':'위험 후보가 많으면 신규매수 난이도가 높습니다.'},
    ]
    out=pd.DataFrame(rows)
    _write_csv(out, REPORT_DIR / f'v71_signal_panel_{slug}.csv')
    return out


def run_v71_update(fetch_news: bool = True, fetch_fundamentals: bool = True, fetch_macro: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {'status':'OK','version':'v71','updated_at':_now(),'base':'v70 + Donhyun market guard + QuantAI card UX'}
    if run_v70_update is not None:
        try:
            result['v70'] = run_v70_update(fetch_news=fetch_news, fetch_fundamentals=fetch_fundamentals, fetch_macro=fetch_macro)
        except Exception as exc:
            result['status']='WARN'
            result['v70_error']=f'{type(exc).__name__}: {exc}'
    for slug in ['kr','us']:
        today=_build_today_summary(slug)
        pos=_build_position_cards(slug)
        guard=_build_market_guard(slug)
        sector=_safe_read(REPORT_DIR / f'v71_sector_strength_{slug}.csv')
        sig=_build_signal_panel(slug)
        result[slug] = {
            'today_cards': len(today),
            'position_cards': len(pos),
            'market_guard_cards': len(guard),
            'sector_rows': len(sector),
            'signal_rows': len(sig),
        }
    _write_json(result, REPORT_DIR / 'v71_status.json')
    return result
