
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
import requests

ROOT = Path('.').resolve()
REPORT_DIR = ROOT / 'reports'
DATA_DIR = ROOT / 'data'
REPORT_DIR.mkdir(exist_ok=True)

NONE_SET = {'', '-', 'nan', 'none', 'null', 'nat', 'None', 'NaN'}

def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _read_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(p)
    except Exception:
        try:
            return pd.read_csv(p, encoding='cp949')
        except Exception:
            return pd.DataFrame()

def _write_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding='utf-8-sig')

def _market_slug(market: str) -> str:
    return 'kr' if '한국' in str(market) or '국장' in str(market) else 'us'

def _market_name(slug: str) -> str:
    return '한국주식' if slug == 'kr' else '미국주식'

def _market_filter(df: pd.DataFrame, market: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    m = _market_name(_market_slug(market))
    for c in ['시장','market','마켓']:
        if c in out.columns:
            s = out[c].astype(str)
            if m == '한국주식':
                mask = s.str.contains('한국|국장|KR|Korea|KOSPI|KOSDAQ', case=False, na=False)
            else:
                mask = s.str.contains('미국|미장|US|USA|NASDAQ|NYSE|AMEX', case=False, na=False)
            if mask.any():
                out = out[mask].copy()
            break
    return out.reset_index(drop=True)

def _clean(v: Any) -> str:
    if v is None:
        return ''
    s = str(v).strip()
    if s.lower() in NONE_SET:
        return ''
    return s

def _first(row: pd.Series, *keys: str, default: str = '') -> str:
    for k in keys:
        if k in row.index:
            s = _clean(row.get(k))
            if s:
                return s
    return default

def _symbol_from_text(value: Any) -> str:
    s = _clean(value).upper()
    if not s:
        return ''
    m = re.search(r'\(([A-Z0-9\.\-]{1,10})\)', s)
    if m:
        return m.group(1).strip()
    m = re.search(r'\b[0-9]{6}\b', s)
    if m:
        return m.group(0)
    m = re.search(r'\b[A-Z]{1,5}(?:\.[A-Z])?\b', s)
    if m:
        return m.group(0)
    return s.split()[0].strip()

def _parse_num(v: Any) -> float:
    s = _clean(v)
    if not s:
        return float('nan')
    s = s.replace('$','').replace('원','').replace(',','').replace('%','').strip()
    try:
        return float(s)
    except Exception:
        return float('nan')

def _fmt_price(v: float, market: str) -> str:
    if v is None or np.isnan(v) or v <= 0:
        return '-'
    if _market_slug(market) == 'kr':
        return f'{v:,.0f}원'
    return f'${v:,.2f}'

def _price_lookup_table() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    sources = [
        REPORT_DIR/'intraday_realtime_snapshot.csv',
        REPORT_DIR/'intraday_flow_snapshot.csv',
        REPORT_DIR/'v52_action_board_light.csv',
        REPORT_DIR/'v51_action_board_light.csv',
        REPORT_DIR/'v45_beginner_action_board.csv',
    ]
    for p in sources:
        df = _read_csv(p)
        if df.empty:
            continue
        for _, r in df.iterrows():
            market = _first(r, '시장','market', default='')
            sym = _first(r, '종목코드','symbol','ticker','code','종목', default='')
            if not sym:
                sym = _symbol_from_text(_first(r, '종목','종목명','name', default=''))
            sym = _symbol_from_text(sym)
            if not sym:
                continue
            price = float('nan')
            for c in ['last_price','current_price','현재가','price','quote_fallback_price','기준가','진입 기준','entry','entry_price']:
                if c in r.index:
                    price = _parse_num(r.get(c))
                    if not np.isnan(price) and price > 0:
                        break
            if np.isnan(price) or price <= 0:
                continue
            rows.append({'symbol': sym, '시장': market or ('한국주식' if re.fullmatch(r'\d{6}', sym) else '미국주식'), 'price': price, 'source': p.name, 'updated_at': _now()})
    if not rows:
        return pd.DataFrame(columns=['symbol','시장','price','source','updated_at'])
    out = pd.DataFrame(rows).drop_duplicates(subset=['symbol','시장'], keep='first')
    return out

def _fetch_last_close(symbol: str, market: str) -> tuple[float, str]:
    if not symbol:
        return float('nan'), 'symbol missing'
    try:
        if _market_slug(market) == 'us':
            import yfinance as yf
            hist = yf.Ticker(symbol).history(period='7d', interval='1d', auto_adjust=False)
            if hist is not None and not hist.empty:
                price = float(hist['Close'].dropna().iloc[-1])
                return price, 'yfinance 직전 종가'
        else:
            import FinanceDataReader as fdr
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - pd.Timedelta(days=14)).strftime('%Y-%m-%d')
            hist = fdr.DataReader(symbol, start, end)
            if hist is not None and not hist.empty:
                price = float(hist['Close'].dropna().iloc[-1])
                return price, 'FinanceDataReader 직전 종가'
    except Exception as exc:
        return float('nan'), f'직전 종가 조회 실패: {type(exc).__name__}'
    return float('nan'), '직전 종가 없음'

def _get_price(symbol: str, market: str, table: pd.DataFrame | None = None, fetch: bool = True) -> tuple[float, str]:
    symbol = _symbol_from_text(symbol)
    if table is None:
        table = _price_lookup_table()
    if table is not None and not table.empty:
        m = _market_name(_market_slug(market))
        x = table[(table['symbol'].astype(str).str.upper() == symbol.upper())]
        if '시장' in x.columns:
            xm = x[x['시장'].astype(str).str.contains('한국|미국|국장|미장|US|KR|Korea|USA', case=False, na=False)]
            if not xm.empty:
                x = xm
        if not x.empty:
            val = _parse_num(x.iloc[0].get('price'))
            if not np.isnan(val) and val > 0:
                return val, str(x.iloc[0].get('source','저장 리포트'))
    if fetch:
        return _fetch_last_close(symbol, market)
    return float('nan'), '저장 가격 없음'

def _fill_prices_for_action(df: pd.DataFrame, market: str, fetch: bool = True) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=['시장','우선순위','행동','종목','기준가','손절가','목표가','초보자 안내','이유','가격기준'])
    out = _market_filter(df, market).copy()
    if out.empty:
        return out
    price_table = _price_lookup_table()
    rows = []
    for _, r in out.iterrows():
        row = dict(r)
        sym = _symbol_from_text(_first(r, '종목코드','symbol','ticker','종목', default=''))
        price, src = _get_price(sym, market, price_table, fetch=fetch)
        current_entry = _parse_num(row.get('기준가'))
        if (np.isnan(current_entry) or current_entry <= 0) and not np.isnan(price) and price > 0:
            row['기준가'] = _fmt_price(price, market)
            row['손절가'] = _fmt_price(price * 0.95, market)
            row['목표가'] = _fmt_price(price * 1.10, market)
            row['가격기준'] = f'직전 장마감 기준 참고 · {src}'
            if not _clean(row.get('이유')) or row.get('이유') == '백테스트 참고':
                row['이유'] = '장전/장마감 시간이라 직전 장마감 가격으로 임시 기준을 표시합니다.'
        else:
            row['가격기준'] = src if not np.isnan(price) and price > 0 else '가격 미수신'
        rows.append(row)
    return pd.DataFrame(rows)

def _make_pullback(df_action: pd.DataFrame, market: str) -> pd.DataFrame:
    if df_action is None or df_action.empty:
        return pd.DataFrame(columns=['종목','시장','상태','기준가','손절가','목표가','해석','다음 행동'])
    rows = []
    for _, r in df_action.head(30).iterrows():
        action = _first(r, '행동', default='관찰')
        if any(k in action for k in ['제외','금지','손절']):
            continue
        rows.append({
            '종목': _first(r, '종목','종목명','종목코드', default='-'),
            '시장': _market_name(_market_slug(market)),
            '상태': '직전 장 기준 눌림/관찰',
            '기준가': _first(r, '기준가', default='-'),
            '손절가': _first(r, '손절가', default='-'),
            '목표가': _first(r, '목표가', default='-'),
            '해석': '장전/장마감 시간에는 실시간보다 직전 장마감 기준으로 후보를 확인합니다.',
            '다음 행동': '현재가가 기준가 근처인지 장 시작 후 확인',
        })
    return pd.DataFrame(rows)

def _make_flow(df_action: pd.DataFrame, market: str, fetch: bool = True) -> pd.DataFrame:
    flow = _market_filter(_read_csv(REPORT_DIR/'intraday_flow_snapshot.csv'), market)
    rows = []
    price_table = _price_lookup_table()
    if flow is not None and not flow.empty:
        for _, r in flow.head(40).iterrows():
            sym = _symbol_from_text(_first(r, 'symbol','종목코드','종목', default=''))
            price, src = _get_price(sym, market, price_table, fetch=fetch)
            rows.append({
                '종목코드': sym or '-',
                '시장': _market_name(_market_slug(market)),
                '수급 기준': '미국식 수급 대체' if _market_slug(market)=='us' else '국장 수급',
                '현재가/직전종가': _fmt_price(price, market) if not np.isnan(price) and price > 0 else '-',
                '등락률': _first(r, 'intraday_change_pct', default='-'),
                '거래량': _first(r, 'intraday_volume', default='-'),
                '거래대금': _first(r, 'intraday_trading_value', default='-'),
                '수급점수': _first(r, 'intraday_flow_score','flow_score','수급점수', default='50'),
                '상태': '직전 장 기준 참고' if src else '수급 미수신',
                '해석': '미장은 외국인/기관 수급 대신 거래량·모멘텀·호가 대체 지표로 봅니다.' if _market_slug(market)=='us' else '국장은 외국인/기관/프로그램 수급을 우선 봅니다.',
                '다음 행동': '장 시작 후 거래량 증가와 기준가 근접 여부 확인',
            })
    if rows:
        return pd.DataFrame(rows)
    # Fallback from action board
    if df_action is not None and not df_action.empty:
        for _, r in df_action.head(20).iterrows():
            rows.append({
                '종목코드': _symbol_from_text(_first(r, '종목','종목코드', default='')),
                '시장': _market_name(_market_slug(market)),
                '수급 기준': '장마감 대체 후보',
                '현재가/직전종가': _first(r, '기준가', default='-'),
                '등락률': '-', '거래량': '-', '거래대금': '-', '수급점수': '-',
                '상태': '수급 원본 없음 · 후보 기준 대체',
                '해석': '실시간 수급이 없으므로 직전 후보/기준가만 참고합니다.',
                '다음 행동': 'run_intraday_refresh 또는 장마감 업데이트 후 수급 확인',
            })
    return pd.DataFrame(rows)

def _make_position_plan(market: str, fetch: bool = True) -> pd.DataFrame:
    slug = _market_slug(market)
    holdings_paths = [ROOT/f'holdings_{slug}.csv', DATA_DIR/f'holdings_{slug}.csv', ROOT/'holdings.csv', DATA_DIR/'holdings.csv']
    h = pd.DataFrame()
    for p in holdings_paths:
        h = _read_csv(p)
        if not h.empty:
            break
    if h.empty:
        # keep previous position plan but filtered if available
        prev = _market_filter(_read_csv(REPORT_DIR/'v50_position_plan.csv'), market)
        return prev
    price_table = _price_lookup_table()
    rows = []
    for _, r in h.iterrows():
        sym = _symbol_from_text(_first(r, 'ticker','symbol','종목코드','code','종목', default=''))
        if not sym:
            continue
        name = _first(r, 'name','종목명','company_name', default=sym)
        shares = _parse_num(_first(r, 'shares','quantity','qty','보유수량','수량', default='0'))
        avg = _parse_num(_first(r, 'avg_price','average_price','avg_buy_price','평단가','매수가', default=''))
        price, src = _get_price(sym, market, price_table, fetch=fetch)
        pnl = float('nan')
        if not np.isnan(avg) and avg > 0 and not np.isnan(price) and price > 0:
            pnl = (price / avg - 1.0) * 100.0
        if np.isnan(pnl):
            action = '보유 점검'
            qty = 0
            amount = '-'
            guide = '평단가 또는 현재가가 부족합니다. 보유 파일과 현재가 갱신 상태를 확인하세요.'
        elif pnl >= 20:
            action = '일부 익절 검토'
            qty = max(0, int(round(shares * 0.25))) if shares > 0 else 0
            amount = _fmt_price(qty * price, market) if qty else '-'
            guide = '수익 구간입니다. 전량 매도보다 일부 익절/트레일링을 검토합니다.'
        elif pnl <= -10:
            action = '손절/축소 검토'
            qty = max(0, int(round(shares * 0.5))) if shares > 0 else 0
            amount = _fmt_price(qty * price, market) if qty else '-'
            guide = '손실 구간입니다. 손절가 이탈 여부를 먼저 확인합니다.'
        else:
            action = '보유 유지'
            qty = 0
            amount = '-'
            guide = '보유 유지 가능 구간입니다. 목표가 근처면 일부 익절을 검토합니다.'
        rows.append({
            '구분':'보유/매도', '종목':f'{name} ({sym})', '시장':_market_name(slug), '보유수량':shares,
            '평단가':_fmt_price(avg, market) if not np.isnan(avg) and avg>0 else '-',
            '현재가':_fmt_price(price, market) if not np.isnan(price) and price>0 else '-',
            '수익률':'-' if np.isnan(pnl) else f'{pnl:.2f}%',
            '권장행동':action, '권장수량':qty, '예상금액':amount,
            '가격출처':src, '초보자 안내':guide,
        })
    return pd.DataFrame(rows)

def _load_env_key(name: str) -> str:
    val = os.environ.get(name, '').strip()
    if val:
        return val
    envp = ROOT/'.env'
    try:
        if envp.exists():
            for line in envp.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith(name + '='):
                    return line.split('=',1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ''

def _news_translate_rule(title: str, desc: str, market: str) -> str:
    text = f'{title} {desc}'.lower()
    rules = [
        (('nvidia','nvda','gpu','ai chip','artificial intelligence'), '엔비디아/AI 반도체 관련 뉴스입니다. AI 인프라와 반도체 종목의 투자심리에 영향을 줄 수 있습니다.'),
        (('nasdaq','s&p','dow','wall street','stock market'), '미국 증시 전반의 흐름을 설명하는 뉴스입니다. 개별 종목보다 지수 방향 확인용으로 봅니다.'),
        (('federal reserve','fed','powell','treasury','yield','rate','inflation','cpi','ppi'), '연준·금리·물가 관련 뉴스입니다. 성장주와 기술주 변동성에 직접 영향을 줄 수 있습니다.'),
        (('earnings','revenue','profit','guidance','beat','miss'), '실적/가이던스 관련 뉴스입니다. 실적 자체보다 주가 반응과 거래량이 같이 붙는지 확인해야 합니다.'),
        (('oil','crude','war','iran','middle east'), '유가·지정학 이슈입니다. 물가와 금리 부담으로 이어질 수 있어 시장 변동성을 키울 수 있습니다.'),
        (('kospi','kosdaq','korea','samsung electronics','hynix','코스피','코스닥','삼성전자','하이닉스'), '국내 증시/반도체 관련 뉴스입니다. 외국인 수급과 업종 거래대금을 같이 확인해야 합니다.'),
    ]
    for keys, msg in rules:
        if any(k in text for k in keys):
            return msg
    if _market_slug(market) == 'us':
        return '미장 관련 뉴스입니다. 제목만으로 매수 판단하지 말고 지수·거래량·기준가 반응을 같이 확인합니다.'
    return '국장 관련 뉴스입니다. 관련 종목의 수급과 거래대금이 실제로 붙는지 확인합니다.'

def _fetch_gnews(market: str, max_items: int = 20) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _load_env_key('GNEWS_API_KEY')
    slug = _market_slug(market)
    diag: dict[str, Any] = {'market': _market_name(slug), 'key_present': bool(key), 'attempts': []}
    rows: list[dict[str, Any]] = []
    if not key:
        diag['status'] = 'NO_KEY'
        return pd.DataFrame(), diag
    if slug == 'us':
        queries = ['stock market', 'Nasdaq stocks', 'Nvidia AI semiconductor stocks', 'Federal Reserve Treasury yields stocks']
        lang_country = [('en','us'), ('en','')]
    else:
        queries = ['한국 증시 코스피 코스닥', '삼성전자 SK하이닉스 반도체', 'Korea stock market', '코스피 외국인 기관 수급']
        lang_country = [('ko','kr'), ('en','kr'), ('ko','')]
    for q in queries:
        for lang, country in lang_country:
            params = {'q': q, 'apikey': key, 'max': 10}
            if lang: params['lang'] = lang
            if country: params['country'] = country
            try:
                resp = requests.get('https://gnews.io/api/v4/search', params=params, timeout=12)
                info = {'q': q, 'lang': lang, 'country': country, 'status_code': resp.status_code}
                if resp.status_code == 200:
                    data = resp.json()
                    arts = data.get('articles') or []
                    info['articles'] = len(arts)
                    for a in arts:
                        title = str(a.get('title') or '').strip()
                        desc = str(a.get('description') or a.get('content') or '').strip()
                        if not title:
                            continue
                        rows.append({
                            '시장': _market_name(slug), '제목': title, '요약': desc, '간략 번역': _news_translate_rule(title, desc, market),
                            '출처': ((a.get('source') or {}).get('name') if isinstance(a.get('source'), dict) else a.get('source')) or '-',
                            'URL': a.get('url') or '', '게시시간': a.get('publishedAt') or '', '검색어': q,
                        })
                else:
                    info['error'] = resp.text[:200]
                diag['attempts'].append(info)
            except Exception as exc:
                diag['attempts'].append({'q': q, 'lang': lang, 'country': country, 'error': f'{type(exc).__name__}: {exc}'})
            if len(rows) >= max_items:
                break
        if len(rows) >= max_items:
            break
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates(subset=['제목']).head(max_items)
        diag['status'] = 'OK'
        diag['rows'] = len(out)
    else:
        diag['status'] = 'ZERO_ROWS'
        diag['rows'] = 0
    return out, diag

def run_v67_update(fetch_news: bool = True, fetch_missing_prices: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {'status': 'OK', 'version': 'v67', 'updated_at': _now()}
    price_table = _price_lookup_table()
    _write_csv(price_table, REPORT_DIR/'v67_price_lookup.csv')
    for slug in ['kr','us']:
        market = _market_name(slug)
        action_src = _read_csv(REPORT_DIR/'v52_action_board_light.csv')
        action = _fill_prices_for_action(action_src, market, fetch=fetch_missing_prices)
        _write_csv(action, REPORT_DIR/f'v67_action_board_{slug}.csv')
        pullback = _make_pullback(action, market)
        flow = _make_flow(action, market, fetch=fetch_missing_prices)
        risk = _market_filter(_read_csv(REPORT_DIR/'v52_buy_risk_light.csv'), market)
        pos = _make_position_plan(market, fetch=fetch_missing_prices)
        _write_csv(pullback, REPORT_DIR/f'v67_pullback_{slug}.csv')
        _write_csv(flow, REPORT_DIR/f'v67_flow_{slug}.csv')
        _write_csv(risk, REPORT_DIR/f'v67_risk_{slug}.csv')
        _write_csv(pos, REPORT_DIR/f'v67_position_plan_{slug}.csv')
        if fetch_news:
            news, diag = _fetch_gnews(market)
            if news.empty:
                # preserve previously stored news if available
                prev = _read_csv(REPORT_DIR/f'gnews_latest_{slug}.csv')
                if not prev.empty:
                    news = prev.copy()
                    if '간략 번역' not in news.columns:
                        news['간략 번역'] = [ _news_translate_rule(str(r.get('제목', r.get('title',''))), str(r.get('요약', r.get('description',''))), market) for _, r in news.iterrows() ]
            _write_csv(news, REPORT_DIR/f'v67_news_cards_{slug}.csv')
            (REPORT_DIR/f'v67_news_diag_{slug}.json').write_text(json.dumps(diag, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        result[slug] = {'action_rows': len(action), 'pullback_rows': len(pullback), 'flow_rows': len(flow), 'risk_rows': len(risk), 'position_rows': len(pos)}
    (REPORT_DIR/'v67_status.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return result
