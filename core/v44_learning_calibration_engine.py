
"""v44 실전 복기·오차 보정 엔진.

목표:
- 앱이 추천한 후보를 매일 자동으로 기록
- 1/3/5/20거래일 뒤 실제 결과를 추적
- 손절/목표가 도달 여부를 계산
- 실패 조건을 요약해 다음 후보 판단 보정에 사용할 수 있게 저장

주의: 이 모듈은 절대 주문을 실행하지 않습니다. CSV/JSON 리포트만 생성합니다.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from core.v43_operational_engine import (
        ROOT, DATA_DIR, REPORT_DIR, read_csv_safe, read_json_safe, write_json,
        market_slug, market_label, parse_symbol_label, label_for_symbol,
        discover_symbol_names, to_num, first,
    )
except Exception:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / 'data'
    REPORT_DIR = ROOT / 'reports'
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    def read_csv_safe(path: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(path) if path.exists() else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    def read_json_safe(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        except Exception:
            return {}
    def write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    def market_slug(market: str) -> str:
        return 'kr' if str(market) == '한국주식' else 'us'
    def market_label(market: str) -> str:
        return '한국주식' if market_slug(market) == 'kr' else '미국주식'
    def parse_symbol_label(label: str) -> str:
        s=str(label or '').strip(); m=re.search(r'(\d{6})',s)
        return m.group(1) if m else (s.split()[0].upper() if s else '')
    def label_for_symbol(symbol: str, market: str, names: dict[str,str]|None=None) -> str:
        return str(symbol)
    def discover_symbol_names(market: str) -> dict[str,str]:
        return {}
    def to_num(value: Any, default: float = math.nan) -> float:
        try:
            s=re.sub(r'[^0-9.\-]','',str(value)); return float(s) if s not in {'','-','.'} else default
        except Exception:
            return default
    def first(row: Any, cols: Iterable[str], default: Any='-') -> Any:
        for c in cols:
            if c in getattr(row, 'index', []):
                v=row.get(c)
                if pd.notna(v) and str(v).strip() not in {'','-','nan','None'}:
                    return v
        return default

LEARNING_DIR = DATA_DIR / 'learning'
LEARNING_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

REC_LOG = LEARNING_DIR / 'recommendation_log.csv'
OUTCOME_CSV = REPORT_DIR / 'v44_recommendation_outcomes.csv'
CONDITION_CSV = REPORT_DIR / 'v44_condition_performance.csv'
ACTION_CSV = REPORT_DIR / 'v44_beginner_action_board.csv'
CALIB_JSON = REPORT_DIR / 'v44_calibration_summary.json'
STATUS_JSON = REPORT_DIR / 'v44_learning_status.json'


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _clean_symbol(value: Any, market: str) -> str:
    sym = parse_symbol_label(str(value or ''))
    if market_slug(market) == 'kr':
        m = re.search(r'(\d{6})', sym)
        if m:
            return m.group(1)
    return sym.upper()


def _norm_market(value: Any, default: str = '미국주식') -> str:
    s = str(value or '').strip()
    if s in {'한국주식','국장','KR','kr','KOSPI','KOSDAQ'}:
        return '한국주식'
    if s in {'미국주식','미장','US','us','NASDAQ','NYSE'}:
        return '미국주식'
    return default


def _candidate_sources() -> list[tuple[Path, str, str]]:
    out: list[tuple[Path,str,str]] = []
    for market in ['한국주식','미국주식']:
        slug=market_slug(market)
        patterns = [
            (REPORT_DIR / f'swing_candidates_{slug}_A_top3.csv', '스윙 A 후보'),
            (REPORT_DIR / f'swing_candidates_{slug}_B_watch.csv', '관찰 후보'),
            (REPORT_DIR / f'operational_buy_budget_{slug}.csv', '예산 후보'),
            (REPORT_DIR / f'risk_priority_candidates_{slug}.csv', '리스크 우선 후보'),
            (REPORT_DIR / f'v43_strategy_backtest_summary.csv', '백테스트 참고'),
            (ROOT / f'predictions_{slug}.csv', '예측 후보'),
            (ROOT / 'predictions.csv', '예측 후보'),
            (DATA_DIR / f'watchlist_{slug}.csv', '관심종목'),
            (ROOT / f'watchlist_{slug}.csv', '관심종목'),
        ]
        for p, label in patterns:
            if p.exists():
                out.append((p, market, label))
    # include any obvious candidate files under reports
    for p in REPORT_DIR.glob('*candidate*.csv'):
        if not any(p == x[0] for x in out):
            out.append((p, '미국주식', '후보 리포트'))
    return out


def _extract_candidates_from_file(path: Path, default_market: str, source_label: str, limit: int = 80) -> pd.DataFrame:
    df = read_csv_safe(path)
    if df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    sym_cols = ['종목코드','symbol','ticker','티커','종목','code']
    name_cols = ['종목명','name','company','회사명','stock_name']
    market_cols = ['시장','market','market_label']
    entry_cols = ['우선진입가','진입가','entry_price','entry','buy_price','현재가','current_price','price','Close','close']
    stop_cols = ['손절가','stop_price','stop','stop_loss']
    target_cols = ['1차 목표가','목표가','target_price','target','take_profit']
    score_cols = ['상승확률','확률','score','final_score','confidence','종합점수','우선순위점수']
    reason_cols = ['사유','reason','판단','초보자 요약','내러티브','comment','signal_reason']
    action_cols = ['판단','action','추천행동','최종판단']
    for _, r in df.head(limit).iterrows():
        raw_sym = first(r, sym_cols, '')
        market = _norm_market(first(r, market_cols, default_market), default_market)
        sym = _clean_symbol(raw_sym, market)
        if not sym or sym in {'NAN','NONE','-'}:
            continue
        entry = to_num(first(r, entry_cols, math.nan))
        stop = to_num(first(r, stop_cols, math.nan))
        target = to_num(first(r, target_cols, math.nan))
        if math.isnan(stop) and not math.isnan(entry) and entry > 0:
            stop = entry * 0.95
        if math.isnan(target) and not math.isnan(entry) and entry > 0:
            target = entry * 1.10
        name = str(first(r, name_cols, '') or '').strip()
        if not name or name in {'-','nan','None'}:
            try:
                names=discover_symbol_names(market); name=names.get(sym, '')
            except Exception:
                name=''
        reason = str(first(r, reason_cols, source_label) or source_label).strip()
        action = str(first(r, action_cols, '진입가 대기') or '진입가 대기').strip()
        score = to_num(first(r, score_cols, math.nan))
        rows.append({
            'recommended_at': _today(),
            'market': market,
            'symbol': sym,
            'name': name,
            'strategy': source_label,
            'action': action,
            'entry_price': entry if not math.isnan(entry) else '',
            'stop_price': stop if not math.isnan(stop) else '',
            'target_price': target if not math.isnan(target) else '',
            'max_holding_days': 20,
            'score': score if not math.isnan(score) else '',
            'reason': reason[:300],
            'source_file': path.name,
        })
    return pd.DataFrame(rows)


def collect_current_recommendations() -> pd.DataFrame:
    frames=[]
    for p, market, label in _candidate_sources():
        part=_extract_candidates_from_file(p, market, label)
        if not part.empty:
            frames.append(part)
    if not frames:
        return pd.DataFrame(columns=['recommended_at','market','symbol','name','strategy','action','entry_price','stop_price','target_price','max_holding_days','score','reason','source_file'])
    df=pd.concat(frames, ignore_index=True)
    df=df.drop_duplicates(subset=['recommended_at','market','symbol','strategy'], keep='first')
    df['rec_id']=df.apply(lambda r: f"{r['recommended_at']}|{market_slug(r['market'])}|{r['symbol']}|{str(r['strategy'])[:18]}", axis=1)
    cols=['rec_id','recommended_at','market','symbol','name','strategy','action','entry_price','stop_price','target_price','max_holding_days','score','reason','source_file']
    return df[cols]


def update_recommendation_log() -> dict[str, Any]:
    current=collect_current_recommendations()
    old=read_csv_safe(REC_LOG)
    if old.empty:
        combined=current.copy()
    elif current.empty:
        combined=old.copy()
    else:
        combined=pd.concat([old, current], ignore_index=True)
        if 'rec_id' not in combined.columns:
            combined['rec_id']=combined.apply(lambda r: f"{r.get('recommended_at','')}|{market_slug(str(r.get('market','미국주식')))}|{r.get('symbol','')}|{str(r.get('strategy',''))[:18]}", axis=1)
        combined=combined.drop_duplicates(subset=['rec_id'], keep='first')
    REC_LOG.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(REC_LOG, index=False, encoding='utf-8-sig')
    return {'current_rows': int(len(current)), 'total_rows': int(len(combined)), 'path': str(REC_LOG.relative_to(ROOT))}


def _history_candidates(symbol: str, market: str) -> list[Path]:
    slug=market_slug(market); sym=str(symbol).upper()
    return [
        DATA_DIR / 'prices' / f'{sym}.csv',
        DATA_DIR / 'price' / f'{sym}.csv',
        DATA_DIR / 'ohlc' / f'{sym}.csv',
        REPORT_DIR / 'prices' / f'{sym}.csv',
        REPORT_DIR / f'price_{sym}.csv',
        REPORT_DIR / f'ohlc_{sym}.csv',
        REPORT_DIR / f'{sym}_price.csv',
        REPORT_DIR / f'{slug}_{sym}_price.csv',
    ]


def _load_local_history(symbol: str, market: str) -> pd.DataFrame:
    for p in _history_candidates(symbol, market):
        df=read_csv_safe(p)
        if df.empty:
            continue
        cols={c.lower(): c for c in df.columns}
        date_col=next((c for c in df.columns if str(c).lower() in {'date','datetime','time','날짜','일자'}), None)
        close_col=next((c for c in df.columns if str(c).lower() in {'close','adj close','adj_close','종가','현재가','price'}), None)
        high_col=next((c for c in df.columns if str(c).lower() in {'high','고가'}), None)
        low_col=next((c for c in df.columns if str(c).lower() in {'low','저가'}), None)
        open_col=next((c for c in df.columns if str(c).lower() in {'open','시가'}), None)
        if not date_col or not close_col:
            continue
        out=pd.DataFrame({
            'Date': pd.to_datetime(df[date_col], errors='coerce'),
            'Close': pd.to_numeric(df[close_col], errors='coerce'),
            'High': pd.to_numeric(df[high_col], errors='coerce') if high_col else pd.to_numeric(df[close_col], errors='coerce'),
            'Low': pd.to_numeric(df[low_col], errors='coerce') if low_col else pd.to_numeric(df[close_col], errors='coerce'),
            'Open': pd.to_numeric(df[open_col], errors='coerce') if open_col else pd.to_numeric(df[close_col], errors='coerce'),
        }).dropna(subset=['Date','Close']).sort_values('Date')
        if not out.empty:
            return out
    return pd.DataFrame()


def _download_history(symbol: str, market: str, start: str | None = None) -> pd.DataFrame:
    # yfinance is optional and may fail in CI; failure should not break app.
    import os
    if os.environ.get('V44_DISABLE_YFINANCE', '').strip() == '1':
        return pd.DataFrame()
    try:
        import yfinance as yf  # type: ignore
        ticker=str(symbol).upper()
        if market_slug(market)=='kr' and re.fullmatch(r'\d{6}', ticker):
            ticker=f'{ticker}.KS'
        if start is None:
            start=(datetime.now()-timedelta(days=520)).strftime('%Y-%m-%d')
        df=yf.download(ticker, start=start, progress=False, auto_adjust=False, threads=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df=df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns=[c[0] if isinstance(c, tuple) else c for c in df.columns]
        close_col='Adj Close' if 'Adj Close' in df.columns else 'Close'
        out=pd.DataFrame({
            'Date': pd.to_datetime(df['Date'], errors='coerce'),
            'Open': pd.to_numeric(df.get('Open', df[close_col]), errors='coerce'),
            'High': pd.to_numeric(df.get('High', df[close_col]), errors='coerce'),
            'Low': pd.to_numeric(df.get('Low', df[close_col]), errors='coerce'),
            'Close': pd.to_numeric(df[close_col], errors='coerce'),
        }).dropna(subset=['Date','Close']).sort_values('Date')
        return out
    except Exception:
        return pd.DataFrame()


def load_price_history(symbol: str, market: str, rec_date: str | None = None) -> pd.DataFrame:
    df=_load_local_history(symbol, market)
    if not df.empty:
        return df
    start=None
    try:
        if rec_date:
            start=(pd.to_datetime(rec_date)-pd.Timedelta(days=40)).strftime('%Y-%m-%d')
    except Exception:
        pass
    return _download_history(symbol, market, start=start)


def _next_rows_after(df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    if df.empty:
        return df
    d=pd.to_datetime(date_str, errors='coerce')
    if pd.isna(d):
        return df
    return df[pd.to_datetime(df['Date'], errors='coerce') > d].copy().sort_values('Date')


def _pct(a: float, b: float) -> float:
    if not a or math.isnan(a) or a <= 0 or math.isnan(b):
        return math.nan
    return (b/a-1.0)*100.0


def track_recommendation_outcomes(max_rows: int = 120) -> pd.DataFrame:
    log=read_csv_safe(REC_LOG)
    if log.empty:
        update_recommendation_log()
        log=read_csv_safe(REC_LOG)
    if log.empty:
        return pd.DataFrame()
    rows=[]
    for _, r in log.tail(max_rows).iterrows():
        market=_norm_market(r.get('market'), '미국주식')
        sym=_clean_symbol(r.get('symbol'), market)
        rec_date=str(r.get('recommended_at',''))[:10]
        hist=load_price_history(sym, market, rec_date)
        after=_next_rows_after(hist, rec_date)
        entry=to_num(r.get('entry_price'))
        if (math.isnan(entry) or entry<=0) and not after.empty:
            entry=to_num(after.iloc[0].get('Open'), math.nan)
            if math.isnan(entry) or entry<=0:
                entry=to_num(after.iloc[0].get('Close'), math.nan)
        stop=to_num(r.get('stop_price'))
        target=to_num(r.get('target_price'))
        if not math.isnan(entry) and entry>0:
            if math.isnan(stop) or stop<=0: stop=entry*0.95
            if math.isnan(target) or target<=0: target=entry*1.10
        status='대기'
        stop_hit=False; target_hit=False; hit_date=''
        returns={}
        if after.empty or math.isnan(entry) or entry<=0:
            status='가격데이터 없음'
            for h in [1,3,5,20]: returns[f'return_{h}d_pct']=''
        else:
            status='진행중'
            max_days=int(to_num(r.get('max_holding_days'),20) or 20)
            win=after.head(max_days)
            for _, pr in win.iterrows():
                hi=to_num(pr.get('High')); lo=to_num(pr.get('Low'))
                if not math.isnan(target) and hi>=target:
                    target_hit=True; hit_date=str(pr.get('Date'))[:10]; status='목표가 도달'; break
                if not math.isnan(stop) and lo<=stop:
                    stop_hit=True; hit_date=str(pr.get('Date'))[:10]; status='손절가 이탈'; break
            for h in [1,3,5,20]:
                if len(after) >= h:
                    close=to_num(after.iloc[h-1].get('Close'))
                    returns[f'return_{h}d_pct']=round(_pct(entry, close), 2)
                else:
                    returns[f'return_{h}d_pct']=''
            if not target_hit and not stop_hit and len(after)>=20:
                r20=returns.get('return_20d_pct')
                try:
                    status='20일 종료(수익)' if float(r20)>0 else '20일 종료(손실)'
                except Exception:
                    status='20일 종료'
        final_ret=''
        for key in ['return_20d_pct','return_5d_pct','return_3d_pct','return_1d_pct']:
            if returns.get(key) not in {'', None}:
                final_ret=returns.get(key); break
        rows.append({
            'rec_id': r.get('rec_id',''), 'recommended_at': rec_date, 'market': market,
            'symbol': sym, 'name': r.get('name',''), 'strategy': r.get('strategy',''),
            'action': r.get('action',''), 'entry_price': round(entry,4) if not math.isnan(entry) else '',
            'stop_price': round(stop,4) if not math.isnan(stop) else '',
            'target_price': round(target,4) if not math.isnan(target) else '',
            'status': status, 'hit_date': hit_date, 'target_hit': target_hit, 'stop_hit': stop_hit,
            **returns,
            'final_return_pct': final_ret,
            'reason': r.get('reason',''), 'source_file': r.get('source_file',''),
        })
    out=pd.DataFrame(rows)
    OUTCOME_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTCOME_CSV, index=False, encoding='utf-8-sig')
    return out


def build_condition_performance(outcomes: pd.DataFrame | None = None) -> pd.DataFrame:
    df = outcomes if outcomes is not None else read_csv_safe(OUTCOME_CSV)
    if df is None or df.empty:
        return pd.DataFrame(columns=['구분','조건','건수','승률','평균수익률','실패율','해석'])
    work=df.copy()
    work['ret']=pd.to_numeric(work.get('final_return_pct'), errors='coerce')
    work['success']=work['ret']>0
    work['failure']=(work['ret']<0) | (work.get('stop_hit', False).astype(str).str.lower().isin(['true','1']))
    rows=[]
    def add_group(kind: str, col: str):
        if col not in work.columns: return
        for key, g in work.dropna(subset=[col]).groupby(col):
            if len(g)<1: continue
            avg=g['ret'].mean(skipna=True)
            win=g['success'].mean()*100 if len(g) else math.nan
            fail=g['failure'].mean()*100 if len(g) else math.nan
            interp='좋음' if pd.notna(avg) and avg>2 and win>=50 else ('주의' if pd.notna(avg) and avg<0 else '관찰')
            rows.append({'구분':kind,'조건':str(key)[:60],'건수':int(len(g)),'승률':round(win,1) if pd.notna(win) else '-', '평균수익률':round(avg,2) if pd.notna(avg) else '-', '실패율':round(fail,1) if pd.notna(fail) else '-', '해석':interp})
    add_group('시장','market')
    add_group('전략','strategy')
    # reason keyword groups
    keywords=['추격','과열','뉴스','거래량','수급','실적','손익비','눌림','돌파','관망']
    for kw in keywords:
        g=work[work.get('reason','').astype(str).str.contains(kw, na=False)] if 'reason' in work.columns else pd.DataFrame()
        if not g.empty:
            avg=g['ret'].mean(skipna=True); win=g['success'].mean()*100; fail=g['failure'].mean()*100
            interp='감점 강화 필요' if pd.notna(avg) and avg<0 else ('유지 가능' if pd.notna(avg) and avg>0 else '관찰')
            rows.append({'구분':'키워드','조건':kw,'건수':int(len(g)),'승률':round(win,1),'평균수익률':round(avg,2) if pd.notna(avg) else '-', '실패율':round(fail,1),'해석':interp})
    out=pd.DataFrame(rows)
    out.to_csv(CONDITION_CSV, index=False, encoding='utf-8-sig')
    return out


def build_calibration_summary(outcomes: pd.DataFrame | None = None, cond: pd.DataFrame | None = None) -> dict[str, Any]:
    df=outcomes if outcomes is not None else read_csv_safe(OUTCOME_CSV)
    cond_df=cond if cond is not None else read_csv_safe(CONDITION_CSV)
    summary={'updated_at': _now(), 'status': 'OK', 'total_tracked': int(len(df)) if df is not None else 0, 'suggestions': []}
    if df is None or df.empty:
        summary.update({'status':'NO_DATA','message':'아직 추적할 추천 기록이 없습니다.'})
        write_json(CALIB_JSON, summary); return summary
    ret=pd.to_numeric(df.get('final_return_pct'), errors='coerce')
    summary['evaluated_rows']=int(ret.notna().sum())
    summary['avg_return_pct']=round(float(ret.mean()),2) if ret.notna().any() else None
    summary['win_rate_pct']=round(float((ret>0).mean()*100),1) if ret.notna().any() else None
    bad=[]
    if cond_df is not None and not cond_df.empty:
        for _, r in cond_df.iterrows():
            avg=to_num(r.get('평균수익률'))
            fail=to_num(r.get('실패율'))
            if (not math.isnan(avg) and avg<0) or (not math.isnan(fail) and fail>=60):
                bad.append(str(r.get('조건')))
    suggestions=[]
    if bad:
        suggestions.append(f"최근 실패가 많은 조건: {', '.join(bad[:5])}. 해당 조건 후보는 신규 매수보다 관망/소액 분할로 낮춥니다.")
    if summary.get('win_rate_pct') is not None and summary['win_rate_pct'] < 45:
        suggestions.append('전체 승률이 낮습니다. 진입 기준을 더 보수적으로 잡고 손익비 1:2 미만 후보는 제외하는 편이 안전합니다.')
    if summary.get('avg_return_pct') is not None and summary['avg_return_pct'] < 0:
        suggestions.append('평균수익률이 음수입니다. 추격매수/과열 후보 감점을 강화하고, 진입가 대기 비중을 높입니다.')
    if not suggestions:
        suggestions.append('아직 강한 감점 조건은 보이지 않습니다. 추천 기록이 더 쌓일 때까지 현재 기준을 유지합니다.')
    summary['suggestions']=suggestions
    write_json(CALIB_JSON, summary)
    return summary


def build_beginner_action_board(limit: int = 20) -> pd.DataFrame:
    current=collect_current_recommendations()
    calib=read_json_safe(CALIB_JSON)
    bad_text=' '.join(calib.get('suggestions', [])) if isinstance(calib, dict) else ''
    rows=[]
    if current.empty:
        out=pd.DataFrame(columns=['우선순위','행동','종목','시장','기준가','손절가','목표가','이유','초보자 안내'])
        out.to_csv(ACTION_CSV, index=False, encoding='utf-8-sig')
        return out
    for _, r in current.head(limit*3).iterrows():
        market=str(r.get('market','미국주식'))
        sym=str(r.get('symbol',''))
        entry=to_num(r.get('entry_price'))
        stop=to_num(r.get('stop_price'))
        target=to_num(r.get('target_price'))
        score=to_num(r.get('score'), 50)
        reason=str(r.get('reason',''))
        risk_words=['추격','과열','손익비 부족','매수금지','제외','주의']
        risky=any(w in reason or w in str(r.get('action','')) for w in risk_words)
        # apply calibration suggestion text as soft penalty
        if any(w in bad_text for w in ['추격','과열']) and any(w in reason for w in ['추격','과열']):
            risky=True
        if risky:
            action='관망/제외'
            guide='초보자는 바로 사지 말고, 가격이 진입가 근처로 내려오거나 위험 조건이 사라질 때까지 기다립니다.'
            prio='낮음'
        elif not math.isnan(score) and score>=70:
            action='진입가 대기'
            guide='현재가가 우선진입가 근처인지 확인한 뒤 분할 접근합니다. 손절가는 반드시 같이 확인합니다.'
            prio='높음'
        else:
            action='소액/분할 검토'
            guide='확신이 강하지 않으므로 한 번에 크게 사지 않고, 차트·수급 확인 후 작은 비중만 검토합니다.'
            prio='중간'
        name=str(r.get('name','')).strip()
        label=f"{name} ({sym})" if name else label_for_symbol(sym, market)
        rows.append({'우선순위':prio,'행동':action,'종목':label,'시장':market,'기준가':round(entry,4) if not math.isnan(entry) else '-', '손절가':round(stop,4) if not math.isnan(stop) else '-', '목표가':round(target,4) if not math.isnan(target) else '-', '이유':reason[:180], '초보자 안내':guide})
    order={'높음':0,'중간':1,'낮음':2}
    out=pd.DataFrame(rows).drop_duplicates(subset=['종목','행동'], keep='first')
    if not out.empty:
        out['_ord']=out['우선순위'].map(order).fillna(9)
        out=out.sort_values(['_ord','종목']).drop(columns=['_ord']).head(limit)
    out.to_csv(ACTION_CSV, index=False, encoding='utf-8-sig')
    return out


def run_v44_update() -> dict[str, Any]:
    rec_info=update_recommendation_log()
    outcomes=track_recommendation_outcomes()
    cond=build_condition_performance(outcomes)
    calib=build_calibration_summary(outcomes, cond)
    board=build_beginner_action_board()
    status={'status':'OK','updated_at':_now(),'recommendations':rec_info,'outcome_rows':int(len(outcomes)),'condition_rows':int(len(cond)),'action_rows':int(len(board)),'calibration':calib}
    write_json(STATUS_JSON, status)
    return status


if __name__ == '__main__':
    print(json.dumps(run_v44_update(), ensure_ascii=False, indent=2, default=str))
