
"""v51 빠른 운용/데이터 점검 엔진.

목표
- 화면에서 무거운 계산을 반복하지 않고, 백그라운드/버튼 실행 시 가벼운 CSV를 미리 만듭니다.
- 국장/미장 통합 화면을 개별로 나눠 볼 수 있게 market 컬럼을 표준화합니다.
- nan/None/미수신 값을 사용자 화면에 그대로 노출하지 않도록 정리합니다.
- GNews 키가 있는데 뉴스가 0건일 때 원인을 더 명확하게 표시합니다.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from core.v43_operational_engine import (
        ROOT, DATA_DIR, REPORT_DIR, read_csv_safe, read_json_safe, write_json,
        get_secret, market_slug, label_for_symbol, discover_symbol_names, to_num, first,
        save_gnews_reports,
    )
except Exception:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / "data"
    REPORT_DIR = ROOT / "reports"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    def read_csv_safe(path: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    def read_json_safe(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() and path.stat().st_size else {}
        except Exception:
            return {}
    def write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    def get_secret(name: str) -> str:
        return str(os.environ.get(name, '') or '').strip()
    def market_slug(market: str) -> str:
        return 'kr' if str(market) in {'한국주식','국장','KR','kr'} else 'us'
    def label_for_symbol(symbol: str, market: str, names: dict[str,str]|None=None) -> str:
        return str(symbol)
    def discover_symbol_names(market: str) -> dict[str,str]:
        return {}
    def to_num(value: Any, default: float = math.nan) -> float:
        try:
            s = re.sub(r'[^0-9.\-]', '', str(value or ''))
            return float(s) if s not in {'','-','.'} else default
        except Exception:
            return default
    def first(row: Any, cols: Iterable[str], default: Any='-') -> Any:
        for c in cols:
            if c in getattr(row, 'index', []):
                v = row.get(c)
                if pd.notna(v) and str(v).strip() not in {'','-','nan','None'}:
                    return v
        return default
    def save_gnews_reports() -> dict[str, Any]:
        return {'status':'NO_GNEWS_ENGINE'}

try:
    from core.v50_stability_engine import run_v50_update
except Exception:  # pragma: no cover
    run_v50_update = None

ACTION_LIGHT_CSV = REPORT_DIR / 'v51_action_board_light.csv'
BUY_RISK_LIGHT_CSV = REPORT_DIR / 'v51_buy_risk_light.csv'
POSITION_LIGHT_CSV = REPORT_DIR / 'v51_position_plan_light.csv'
NEWS_STATUS_JSON = REPORT_DIR / 'v51_news_status.json'
DATA_STATUS_JSON = REPORT_DIR / 'v51_light_status.json'
STATUS_JSON = REPORT_DIR / 'v51_status.json'

BAD_TEXTS = {'', '-', 'nan', 'NaN', 'None', 'none', 'NULL', 'null'}


def now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def clean_text(value: Any, default: str = '-') -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    s = str(value).strip()
    if s in BAD_TEXTS:
        return default
    s = re.sub(r'\bnan\b', '', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s).strip()
    return s if s and s not in BAD_TEXTS else default


def norm_market(value: Any) -> str:
    s = clean_text(value, '')
    if s in {'한국주식','국장','KR','kr','KOSPI','KOSDAQ'} or '한국' in s or '국장' in s:
        return '한국주식'
    if s in {'미국주식','미장','US','us','USA','NASDAQ','NYSE'} or '미국' in s or '미장' in s:
        return '미국주식'
    # Korean six-digit code often means Korean market.
    if re.fullmatch(r'\d{6}', str(value or '').strip()):
        return '한국주식'
    return '미국주식'


def sym_clean(value: Any, market: str='') -> str:
    s = clean_text(value, '')
    if not s:
        return ''
    if market_slug(market or norm_market(s)) == 'kr':
        m = re.search(r'(\d{6})', s)
        if m:
            return m.group(1)
    m = re.search(r'\(([A-Za-z0-9.\-]{1,16})\)', s)
    if m:
        return m.group(1).upper()
    return re.sub(r'[^A-Za-z0-9.\-]', '', s.split()[0]).upper()


def good_symbol(sym: str) -> bool:
    s = clean_text(sym, '')
    return bool(s and s not in {'NONE','NAN','NULL'} and len(s) <= 16)


def fmt_money(value: Any, market: str) -> str:
    v = to_num(value)
    if math.isnan(v) or v <= 0:
        return '-'
    return f'{v:,.0f}원' if market_slug(market) == 'kr' else f'${v:,.2f}'


_NAME_CACHE: dict[str, dict[str, str]] = {}

def names_for_market(market: str) -> dict[str, str]:
    mk = norm_market(market)
    if mk not in _NAME_CACHE:
        try:
            _NAME_CACHE[mk] = discover_symbol_names(mk)
        except Exception:
            _NAME_CACHE[mk] = {}
    return _NAME_CACHE[mk]

def add_symbol_label(symbol: str, name: str, market: str) -> str:
    sym = sym_clean(symbol, market)
    nm = clean_text(name, '')
    if not nm:
        nm = names_for_market(market).get(sym, '')
    return f'{nm} ({sym})' if nm else sym


def _read_first(paths: list[Path]) -> pd.DataFrame:
    for p in paths:
        df = read_csv_safe(p)
        if not df.empty:
            return df.copy()
    return pd.DataFrame()


def _market_filter_df(df: pd.DataFrame, market: str | None) -> pd.DataFrame:
    if df.empty or not market or market == '통합':
        return df
    if '시장' in df.columns:
        return df[df['시장'].astype(str).map(norm_market).eq(market)].copy()
    if 'market' in df.columns:
        return df[df['market'].astype(str).map(norm_market).eq(market)].copy()
    return df


def build_action_board_light() -> pd.DataFrame:
    paths = [
        REPORT_DIR / 'v45_beginner_action_board.csv',
        REPORT_DIR / 'v44_beginner_action_board.csv',
        REPORT_DIR / 'v45_calibrated_candidates.csv',
    ]
    src = _read_first(paths)
    rows: list[dict[str, Any]] = []
    if src.empty:
        return pd.DataFrame(columns=['시장','우선순위','행동','종목','기준가','손절가','목표가','초보자 안내','이유'])
    for _, r in src.head(250).iterrows():
        market = norm_market(first(r, ['시장','market'], ''))
        symbol_raw = first(r, ['종목코드','symbol','ticker','종목','code'], '')
        # Some boards already use 종목 as label.
        if not symbol_raw:
            symbol_raw = first(r, ['종목'], '')
        sym = sym_clean(symbol_raw, market)
        name = first(r, ['종목명','name','company'], '')
        label = add_symbol_label(sym or symbol_raw, name, market) if (sym or clean_text(symbol_raw,'')) else clean_text(first(r, ['종목'], '종목 미확인'))
        if clean_text(label, '') in {'', '종목 미확인'}:
            continue
        action = clean_text(first(r, ['행동','추천행동','판단','action'], '진입가 대기'))
        priority = clean_text(first(r, ['우선순위','priority'], '중간'))
        guide = clean_text(first(r, ['초보자 안내','beginner_guide','안내'], ''), '')
        reason = clean_text(first(r, ['이유','사유','감점근거','reason'], ''), '')
        if not guide:
            guide = '기준가·손절가·뉴스·수급을 확인한 뒤 작은 비중부터 검토하세요.'
        rows.append({
            '시장': market,
            '우선순위': priority,
            '행동': action,
            '종목': label,
            '기준가': clean_text(first(r, ['기준가','우선진입가','entry_price'], '-')),
            '손절가': clean_text(first(r, ['손절가','stop_price'], '-')),
            '목표가': clean_text(first(r, ['목표가','1차 목표가','target_price'], '-')),
            '초보자 안내': guide,
            '이유': reason,
        })
    df = pd.DataFrame(rows).drop_duplicates(subset=['시장','종목','행동'], keep='first') if rows else pd.DataFrame()
    if not df.empty:
        order = {'높음':0, '중간':1, '낮음':2}
        df['_order'] = df['우선순위'].map(order).fillna(1)
        df = df.sort_values(['시장','_order','종목']).drop(columns=['_order'])
    df.to_csv(ACTION_LIGHT_CSV, index=False, encoding='utf-8-sig')
    return df


def build_buy_risk_light() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    candidates = [
        REPORT_DIR / 'v45_calibrated_candidates.csv',
        REPORT_DIR / 'v45_beginner_action_board.csv',
        REPORT_DIR / 'v44_beginner_action_board.csv',
        REPORT_DIR / 'risk_priority_summary.csv',
    ]
    for p in candidates:
        df = read_csv_safe(p)
        if not df.empty:
            df['_source'] = p.name
            frames.append(df)
    rows: list[dict[str, Any]] = []
    for df in frames:
        for _, r in df.head(300).iterrows():
            market = norm_market(first(r, ['시장','market'], ''))
            symbol_raw = first(r, ['종목코드','symbol','ticker','종목','code'], '')
            sym = sym_clean(symbol_raw, market)
            name = first(r, ['종목명','name','company'], '')
            label = add_symbol_label(sym or symbol_raw, name, market) if (sym or clean_text(symbol_raw,'')) else clean_text(first(r, ['종목'], ''))
            combined = ' '.join(clean_text(r.get(c,''), '') for c in r.index)
            is_risk = any(k in combined for k in ['관망/제외','제외','매수금지','추격','과열','주의','신규매수 제외','손익비'])
            if not is_risk or not clean_text(label, ''):
                continue
            if '매수금지' in combined or '신규매수 제외' in combined or '관망/제외' in combined:
                risk = '신규매수 제외'
            elif '추격' in combined or '과열' in combined:
                risk = '추격/과열 주의'
            elif '손익비' in combined:
                risk = '손익비 부족'
            else:
                risk = '주의'
            reason = clean_text(first(r, ['핵심 사유','사유','이유','감점근거','reason'], ''), '')
            if not reason:
                reason = '지금 바로 매수하기보다 가격·손익비·뉴스를 다시 확인해야 합니다.'
            action = '신규매수 보류' if risk in {'신규매수 제외','추격/과열 주의'} else '진입가 대기/분할만 검토'
            rows.append({
                '시장': market,
                '종목': label,
                '위험 구분': risk,
                '초보자 해석': '지금 바로 매수하지 말고 관망 우선입니다.' if risk == '신규매수 제외' else '좋은 종목이어도 현재 위치가 부담일 수 있습니다.',
                '핵심 사유': reason,
                '권장 행동': action,
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates(subset=['시장','종목','위험 구분'], keep='first')
        order = {'신규매수 제외':0,'추격/과열 주의':1,'손익비 부족':2,'주의':3}
        out['_order'] = out['위험 구분'].map(order).fillna(9)
        out = out.sort_values(['시장','_order','종목']).drop(columns=['_order'])
    else:
        out = pd.DataFrame(columns=['시장','종목','위험 구분','초보자 해석','핵심 사유','권장 행동'])
    out.to_csv(BUY_RISK_LIGHT_CSV, index=False, encoding='utf-8-sig')
    return out


def build_position_plan_light() -> pd.DataFrame:
    src = _read_first([
        REPORT_DIR / 'v50_position_plan.csv',
        REPORT_DIR / 'operational_sell_budget_kr.csv',
        REPORT_DIR / 'operational_sell_budget_us.csv',
        DATA_DIR / 'holdings_kr.csv',
        DATA_DIR / 'holdings_us.csv',
        ROOT / 'holdings_kr.csv',
        ROOT / 'holdings_us.csv',
    ])
    rows: list[dict[str, Any]] = []
    if src.empty:
        out = pd.DataFrame(columns=['시장','종목','보유수량','평단가','현재가','수익률','권장행동','권장수량','예상금액','초보자 안내'])
        out.to_csv(POSITION_LIGHT_CSV, index=False, encoding='utf-8-sig')
        return out
    for _, r in src.head(200).iterrows():
        market = norm_market(first(r, ['시장','market'], '한국주식'))
        symbol_raw = first(r, ['종목코드','symbol','ticker','종목','code'], '')
        sym = sym_clean(symbol_raw, market)
        name = first(r, ['종목명','name','company'], '')
        if not good_symbol(sym) and not clean_text(name, ''):
            continue
        label = add_symbol_label(sym or symbol_raw, name, market)
        qty = clean_text(first(r, ['보유수량','quantity','shares','수량'], '0'))
        if qty in {'0','0주','0.0','0.0주'}:
            # Keep only real holdings for the beginner screen.
            continue
        cur = clean_text(first(r, ['현재가','current_price','price'], '-'))
        avg = clean_text(first(r, ['평단가','avg_price','average_price'], '-'))
        ret = clean_text(first(r, ['수익률','return_pct'], '-'))
        action = clean_text(first(r, ['권장행동','판단','action'], '보유 점검'))
        rec_qty = clean_text(first(r, ['권장수량','권장매도수량','recommended_qty'], '0'))
        amount = clean_text(first(r, ['예상금액','예상회수금액','amount'], '-'))
        guide = clean_text(first(r, ['초보자 안내','사유','reason'], ''), '')
        if cur == '-':
            guide = '현재가가 아직 미수신입니다. GitHub 동기화 또는 장중 갱신 후 다시 확인하세요.'
        elif not guide:
            guide = '실제 주문 전 증권사 화면의 현재가·보유수량과 반드시 비교하세요.'
        rows.append({
            '시장': market, '종목': label, '보유수량': qty, '평단가': avg, '현재가': cur,
            '수익률': ret, '권장행동': action, '권장수량': rec_qty, '예상금액': amount, '초보자 안내': guide,
        })
    out = pd.DataFrame(rows).drop_duplicates(subset=['시장','종목'], keep='first') if rows else pd.DataFrame(columns=['시장','종목','보유수량','평단가','현재가','수익률','권장행동','권장수량','예상금액','초보자 안내'])
    out.to_csv(POSITION_LIGHT_CSV, index=False, encoding='utf-8-sig')
    return out


def build_news_status(fetch_news: bool = False) -> dict[str, Any]:
    key_present = bool(get_secret('GNEWS_API_KEY') or get_secret('NEWS_API_KEY'))
    fetch_result: dict[str, Any] | None = None
    if fetch_news and key_present:
        try:
            fetch_result = save_gnews_reports()
        except Exception as exc:
            fetch_result = {'status':'ERROR', 'error': f'{type(exc).__name__}: {exc}'}
    summary = read_json_safe(REPORT_DIR / 'gnews_summary.json')
    kr = read_csv_safe(REPORT_DIR / 'gnews_latest_kr.csv')
    us = read_csv_safe(REPORT_DIR / 'gnews_latest_us.csv')
    cache = read_csv_safe(DATA_DIR / 'news' / 'gnews_cache.csv')
    ok_kr = int((kr.get('status', pd.Series(dtype=str)).astype(str).eq('OK')).sum()) if not kr.empty and 'status' in kr.columns else 0
    ok_us = int((us.get('status', pd.Series(dtype=str)).astype(str).eq('OK')).sum()) if not us.empty and 'status' in us.columns else 0
    errors: list[str] = []
    for df in [kr, us]:
        if not df.empty and 'error' in df.columns:
            errors += [clean_text(x, '') for x in df['error'].dropna().astype(str).tolist() if clean_text(x,'')]
    if not key_present:
        status = '키 미인식'
        guide = '로컬 앱 폴더의 .env 또는 GitHub Secrets에 GNEWS_API_KEY/NEWS_API_KEY를 넣어야 합니다.'
    elif ok_kr + ok_us > 0:
        status = '정상'
        guide = '뉴스가 수집되었습니다. 화면에는 중복 제거 후 카드로 표시됩니다.'
    elif errors:
        status = 'API 오류'
        guide = '키는 인식됐지만 API가 오류를 반환했습니다. 무료 한도, 키 값, GNews 대시보드를 확인하세요.'
    else:
        status = '0건'
        guide = '키는 인식됐지만 검색 결과가 0건입니다. 쿼리/언어/국가 조건 또는 API 무료 한도를 확인하세요.'
    data = {
        'updated_at': now(),
        'key_present': key_present,
        'status': status,
        'guide': guide,
        'kr_news': ok_kr,
        'us_news': ok_us,
        'cache_rows': int(len(cache)) if not cache.empty else 0,
        'summary': summary,
        'fetch_result': fetch_result,
        'errors': errors[:5],
    }
    write_json(NEWS_STATUS_JSON, data)
    return data


def run_v51_update(fetch_news: bool = False, include_v50: bool = False) -> dict[str, Any]:
    # v51 기본 실행은 빠른 light 리포트만 갱신합니다.
    # 무거운 v50 전체 계산은 필요할 때만 include_v50=True로 실행합니다.
    upstream = None
    if include_v50 and run_v50_update is not None:
        try:
            upstream = run_v50_update(fetch_news=False)
        except Exception as exc:
            upstream = {'status':'ERROR', 'error': f'{type(exc).__name__}: {exc}'}
    action = build_action_board_light()
    risk = build_buy_risk_light()
    pos = build_position_plan_light()
    news = build_news_status(fetch_news=fetch_news)
    status = {
        'status': 'OK',
        'updated_at': now(),
        'upstream_v50': upstream,
        'action_rows': int(len(action)),
        'risk_rows': int(len(risk)),
        'position_rows': int(len(pos)),
        'news_status': news,
        'note': 'v51은 화면 로딩을 가볍게 하기 위해 미리 만든 light CSV를 읽습니다.',
    }
    write_json(STATUS_JSON, status)
    write_json(DATA_STATUS_JSON, status)
    return status


if __name__ == '__main__':
    print(json.dumps(run_v51_update(fetch_news=False), ensure_ascii=False, indent=2, default=str))
