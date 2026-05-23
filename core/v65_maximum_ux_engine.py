
"""v65 maximum feasible UX/analysis implementation engine.

목표
- 실제 데이터가 없으면 가짜값을 만들지 않고, 가능한 카드/그래프/상태표를 생성한다.
- 고급 가치평가/재무제표/KPI/거시/내러티브/투자거장/기술특허/커스텀 지표를
  사용자가 이해하기 쉬운 요약 CSV/JSON으로 정리한다.
"""
from __future__ import annotations

import json, math, re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.v60_final_engine import ROOT, DATA_DIR, REPORT_DIR, run_v60_update, read_csv_safe, read_json_safe, write_json, norm_market, market_slug
except Exception:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / 'data'; REPORT_DIR = ROOT / 'reports'
    DATA_DIR.mkdir(parents=True, exist_ok=True); REPORT_DIR.mkdir(parents=True, exist_ok=True)
    def read_csv_safe(path: Path) -> pd.DataFrame:
        try: return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()
        except Exception: return pd.DataFrame()
    def read_json_safe(path: Path) -> dict[str, Any]:
        try: return json.loads(path.read_text(encoding='utf-8')) if path.exists() and path.stat().st_size else {}
        except Exception: return {}
    def write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    def norm_market(value: Any, symbol_hint: Any = '') -> str:
        t = f'{value} {symbol_hint}'
        return '한국주식' if ('한국' in t or '국장' in t or re.search(r'\b\d{6}\b', t)) else '미국주식'
    def market_slug(market: str) -> str: return 'kr' if market in {'한국주식','국장','KR','kr'} else 'us'
    def run_v60_update(*args, **kwargs): return {'status':'SKIPPED'}

V65_STATUS_JSON = REPORT_DIR / 'v65_status.json'
V65_FEATURE_MAP_CSV = REPORT_DIR / 'v65_feature_implementation_map.csv'
V65_COMPANY_CARDS_CSV = REPORT_DIR / 'v65_company_analysis_cards.csv'
V65_GURU_STYLE_CSV = REPORT_DIR / 'v65_guru_style_cards.csv'
V65_TECH_PATENT_CSV = REPORT_DIR / 'v65_tech_patent_cards.csv'
V65_MACRO_CARDS_CSV = REPORT_DIR / 'v65_macro_cards.csv'
V65_NARRATIVE_CARDS_CSV = REPORT_DIR / 'v65_narrative_cards.csv'
V65_CUSTOM_INDICATOR_CSV = REPORT_DIR / 'v65_custom_indicator_templates.csv'
V65_VISUAL_SUMMARY_JSON = REPORT_DIR / 'v65_visual_summary.json'


def now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _clean(value: Any, default: str = '-') -> str:
    s = '' if value is None else str(value).strip()
    return default if s == '' or s.lower() in {'nan','none','nat'} else s


def _read_first(paths: list[Path]) -> pd.DataFrame:
    for p in paths:
        df = read_csv_safe(p)
        if df is not None and not df.empty:
            return df
    return pd.DataFrame()


def _has_rows(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0 and len(read_csv_safe(path)) > 0
    except Exception:
        return False


def _detect_data_state(paths: list[str | Path]) -> tuple[str, str]:
    existing = []
    row_count = 0
    for x in paths:
        p = Path(x)
        if not p.is_absolute():
            p = ROOT / p
        if p.exists() and p.stat().st_size > 0:
            existing.append(str(p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p))
            if p.suffix.lower() == '.csv':
                row_count += len(read_csv_safe(p))
            else:
                row_count += 1
    if row_count > 0:
        return '데이터 있음', f'{row_count}개 행/항목 · ' + ', '.join(existing[:2])
    if existing:
        return '파일 있음·값 부족', ', '.join(existing[:2])
    return '데이터 필요', '자동누적 또는 API 연결 후 채워집니다.'


def build_feature_implementation_map() -> pd.DataFrame:
    specs = [
        ('고급 가치평가','부분 구현','일반','뉴스·재무·시장 → 기업분석 카드','PER/PBR/ROE/성장률 기반 요약 구조. 실제 값은 DART/Finnhub/재무 리포트 필요.', ['reports/v50_fundamental_cards.csv','reports/v40_fundamental_summary.csv','reports/v65_company_analysis_cards.csv']),
        ('재무제표 상세표','부분 구현','관리자 원본 + 일반 요약','일반은 카드, 원본표는 관리자모드','긴 재무표는 일반모드에서 숨기고 요약 카드만 표시합니다.', ['reports/v50_fundamental_cards.csv','reports/v60_fundamental_cards.csv','reports/v65_company_analysis_cards.csv']),
        ('KPI','부분 구현','일반','뉴스·재무·시장 → 기업분석 카드','성장성/수익성/안정성/밸류에이션 KPI 카드와 막대그래프를 표시합니다.', ['reports/v65_company_analysis_cards.csv','reports/v50_fundamental_cards.csv']),
        ('기술특허','기초 구현','관리자 상세 + 일반 요약','기업분석 카드에서 요약만','실제 특허 API는 미연결. 뉴스/R&D/섹터 키워드 기반 기술 테마 카드까지 구현했습니다.', ['reports/v65_tech_patent_cards.csv','reports/gnews_latest_us.csv','reports/gnews_latest_kr.csv']),
        ('거시경제 분석','부분 구현','일반','뉴스·재무·시장 → 시장·거시 카드','시장폭/시장국면/데이터상태를 카드형으로 표시합니다. 금리·VIX 등은 추가 데이터 연결 필요.', ['reports/v65_macro_cards.csv','reports/operational_macro_kr.csv','reports/operational_macro_us.csv']),
        ('커스텀 경제지표','기초 구현','관리자','관리자모드 → 고급 분석·설정','사용자 가중치 기반 지표 템플릿과 로컬 저장 구조를 추가했습니다.', ['reports/v65_custom_indicator_templates.csv','data/user_custom_indicator_settings.json']),
        ('투자거장 분석','기초 구현','관리자 상세 + 일반 요약','기업분석 카드에서 요약만','버핏/린치/모멘텀/방어형 스타일 점수 틀을 만들었습니다. 실제 대가 보유 종목 API는 미연결입니다.', ['reports/v65_guru_style_cards.csv']),
        ('종목 내러티브','기초 구현','일반','뉴스·재무·시장 → 종목 내러티브','뉴스/후보/리스크/재무 상태 기반 규칙형 내러티브를 생성합니다. LLM 있으면 고도화 가능.', ['reports/v65_narrative_cards.csv','reports/v60_news_cards.csv']),
    ]
    rows = []
    for name, status, area, location, desc, paths in specs:
        data_status, source = _detect_data_state(paths)
        rows.append({
            '기능': name,
            '구현상태': status,
            '표시위치': location,
            '일반/관리자': area,
            '데이터상태': data_status,
            '설명': desc,
            '확인/다음행동': source,
        })
    df = pd.DataFrame(rows)
    V65_FEATURE_MAP_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(V65_FEATURE_MAP_CSV, index=False, encoding='utf-8-sig')
    return df


def _symbol_columns(df: pd.DataFrame) -> tuple[str | None, str | None, str | None]:
    sym = next((c for c in df.columns if c in ['종목코드','symbol','Symbol','ticker','종목','code','Code']), None)
    name = next((c for c in df.columns if c in ['종목명','name','Name','company','기업명']), None)
    market = next((c for c in df.columns if c in ['시장','market','Market']), None)
    return sym, name, market


def _fundamental_sources() -> pd.DataFrame:
    df = _read_first([
        REPORT_DIR/'v50_fundamental_cards.csv',
        REPORT_DIR/'v60_fundamental_cards.csv',
        REPORT_DIR/'v40_fundamental_summary.csv',
        REPORT_DIR/'v65_company_analysis_cards.csv',
    ])
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _num_from_row(row: pd.Series, candidates: list[str]) -> float | None:
    for c in candidates:
        if c in row.index:
            try:
                v = pd.to_numeric(row.get(c), errors='coerce')
                if pd.notna(v): return float(v)
            except Exception:
                pass
    return None


def _score_text(value: float | None, good_low: bool = False) -> str:
    if value is None or not math.isfinite(value): return '값 필요'
    if good_low:
        if value <= 1: return '양호'
        if value <= 3: return '보통'
        return '주의'
    if value >= 15: return '양호'
    if value >= 5: return '보통'
    return '확인 필요'


def build_company_cards() -> pd.DataFrame:
    src = _fundamental_sources()
    rows: list[dict[str, Any]] = []
    if src.empty:
        # 최소 카드 구조: 실제값은 없지만 화면은 카드/그래프 구조로 유지
        for market in ['한국주식','미국주식']:
            for title, category in [('고급 가치평가','value'),('재무제표 상세표','financial'),('KPI','kpi'),('종목 내러티브','narrative')]:
                rows.append({'시장':market,'종목코드':'-','종목명':'-','카테고리':category,'카드제목':title,'상태':'데이터 필요','핵심값':'-','초보자 해석':'재무/KPI 데이터가 아직 연결되지 않았습니다. 단기 매매는 가능하지만 장기 보유 판단에는 데이터가 필요합니다.','다음 행동':'DART/Finnhub 키와 자동누적 결과를 확인하세요.','점수':0})
    else:
        sym_col, name_col, market_col = _symbol_columns(src)
        for _, r in src.head(80).iterrows():
            symbol = _clean(r.get(sym_col,'-') if sym_col else r.get('종목코드','-'))
            name = _clean(r.get(name_col,'-') if name_col else r.get('종목명', symbol))
            market = norm_market(r.get(market_col,'') if market_col else '', symbol)
            per = _num_from_row(r, ['PER','per','pe','P/E'])
            pbr = _num_from_row(r, ['PBR','pbr','pb','P/B'])
            roe = _num_from_row(r, ['ROE','roe'])
            growth = _num_from_row(r, ['성장률','매출성장률','growth','revenue_growth'])
            debt = _num_from_row(r, ['부채비율','debt_ratio','Debt Ratio'])
            value_state = '확인 필요'
            value_desc = []
            if per is not None: value_desc.append(f'PER {per:.2f}')
            if pbr is not None: value_desc.append(f'PBR {pbr:.2f}')
            if roe is not None: value_desc.append(f'ROE {roe:.2f}')
            if per is None and pbr is None and roe is None:
                value_state = '데이터 부족'
            elif (per is None or per < 35) and (pbr is None or pbr < 8) and (roe is None or roe >= 5):
                value_state = '검토 가능'
            rows.append({'시장':market,'종목코드':symbol,'종목명':name,'카테고리':'value','카드제목':'고급 가치평가','상태':value_state,'핵심값':' · '.join(value_desc) or '-','초보자 해석':'밸류에이션이 과하지 않은지 확인합니다. 값이 부족하면 매수 확신도를 낮춰야 합니다.','다음 행동':'가격보다 기업가치 근거가 있는지 확인','점수':60 if value_state=='검토 가능' else 35})
            kpi_bits = []
            if growth is not None: kpi_bits.append(f'성장률 {growth:.2f}')
            if roe is not None: kpi_bits.append(f'ROE {roe:.2f}')
            if debt is not None: kpi_bits.append(f'부채 {debt:.2f}')
            kpi_score = 0
            if growth is not None: kpi_score += 30 if growth > 10 else 15 if growth > 0 else 0
            if roe is not None: kpi_score += 35 if roe > 15 else 20 if roe > 5 else 0
            if debt is not None: kpi_score += 20 if debt < 100 else 10 if debt < 200 else 0
            rows.append({'시장':market,'종목코드':symbol,'종목명':name,'카테고리':'kpi','카드제목':'KPI','상태':'양호' if kpi_score>=50 else '확인 필요','핵심값':' · '.join(kpi_bits) or '-','초보자 해석':'성장성·수익성·안정성을 함께 봅니다. 한 항목만 좋다고 바로 매수하지 않습니다.','다음 행동':'KPI가 가격 흐름과 같이 개선되는지 확인','점수':kpi_score})
            rows.append({'시장':market,'종목코드':symbol,'종목명':name,'카테고리':'financial','카드제목':'재무제표 상세표','상태':'요약 가능','핵심값':'원본표는 관리자모드','초보자 해석':'긴 재무제표는 일반 화면에서 숨기고 핵심 KPI만 봅니다.','다음 행동':'상세 원본은 관리자모드에서 확인','점수':50})
            narrative = f'{name}({symbol})은 현재 재무/KPI 연결 상태를 기준으로 보수적으로 판단합니다.'
            rows.append({'시장':market,'종목코드':symbol,'종목명':name,'카테고리':'narrative','카드제목':'종목 내러티브','상태':'기초 생성','핵심값':narrative,'초보자 해석':'AI API가 없으면 뉴스·재무·리스크 기반의 규칙형 설명만 제공합니다.','다음 행동':'뉴스/수급/차트가 같은 방향인지 확인','점수':45})
    out = pd.DataFrame(rows)
    out.to_csv(V65_COMPANY_CARDS_CSV, index=False, encoding='utf-8-sig')
    return out


def build_guru_style_cards() -> pd.DataFrame:
    cards = build_company_cards()
    rows = []
    # 데이터가 없어도 기준 설명은 보여준다
    styles = [
        ('버핏식 퀄리티','ROE/안정성/부채를 중시. 단기 급등보다 오래 버틸 수 있는 기업을 선호.'),
        ('피터 린치식 성장','성장률과 이해 가능한 사업모델을 중시. 성장률 둔화는 감점.'),
        ('모멘텀 추세형','가격·수급·거래대금이 붙을 때만 접근. 추격과열은 감점.'),
        ('방어형 리스크 관리','손절폭/변동성/시장 약세를 우선 확인. 애매하면 관망.'),
    ]
    for market in ['한국주식','미국주식']:
        sub = cards[cards.get('시장','') == market] if not cards.empty and '시장' in cards.columns else pd.DataFrame()
        for style, desc in styles:
            score = 0
            if not sub.empty and '점수' in sub.columns:
                try: score = int(pd.to_numeric(sub['점수'], errors='coerce').fillna(0).mean())
                except Exception: score = 0
            rows.append({'시장':market,'분석스타일':style,'상태':'기초 구현','점수':score,'해석':desc,'주의':'실제 투자거장 보유 데이터/API는 아직 미연결입니다. 현재는 스타일 기준 점검표입니다.'})
    df = pd.DataFrame(rows)
    df.to_csv(V65_GURU_STYLE_CSV, index=False, encoding='utf-8-sig')
    return df


def build_tech_patent_cards() -> pd.DataFrame:
    news = _read_first([REPORT_DIR/'gnews_latest_kr.csv', REPORT_DIR/'gnews_latest_us.csv', REPORT_DIR/'v60_news_cards.csv'])
    keywords = ['AI','semiconductor','chip','battery','robot','defense','cloud','software','patent','R&D','반도체','배터리','로봇','방산','특허','기술','인공지능']
    rows = []
    for market in ['한국주식','미국주식']:
        text = ''
        if not news.empty:
            mcol = next((c for c in news.columns if c in ['시장','market']), None)
            sub = news
            if mcol:
                sub = news[news[mcol].apply(lambda x: norm_market(x)==market)]
            for c in ['title','제목','summary','description','내용']:
                if c in sub.columns:
                    text += ' '.join(sub[c].dropna().astype(str).head(80).tolist()) + ' '
        found = [k for k in keywords if k.lower() in text.lower()]
        rows.append({'시장':market,'카드제목':'기술·특허 기초 카드','상태':'기초 구현' if found else '데이터 필요','키워드':', '.join(found[:10]) if found else '-','해석':'실제 특허 API가 아니라 뉴스/R&D 키워드 기반 기술 테마 감지입니다.','다음 행동':'특허 API 또는 R&D 데이터 소스 연결 시 정량화 가능'})
    df = pd.DataFrame(rows)
    df.to_csv(V65_TECH_PATENT_CSV, index=False, encoding='utf-8-sig')
    return df


def build_macro_cards() -> pd.DataFrame:
    rows = []
    for market, candidates in {
        '한국주식':[REPORT_DIR/'operational_macro_kr.csv', REPORT_DIR/'v60_macro_kr.csv'],
        '미국주식':[REPORT_DIR/'operational_macro_us.csv', REPORT_DIR/'v60_macro_us.csv'],
    }.items():
        df = _read_first(candidates)
        if df.empty:
            rows.append({'시장':market,'카드':'시장 국면','상태':'데이터 필요','값':'-','해석':'시장 국면 데이터가 부족합니다. 시장이 약하면 좋은 종목도 비중을 줄이는 것이 안전합니다.','점수':0})
            continue
        # 첫 몇 행을 카드로 변환
        for _, r in df.head(8).iterrows():
            label = _clean(r.get('구분', r.get('지표', r.get('항목','시장 지표'))))
            value = _clean(r.get('값', r.get('value', r.get('데이터상태','-'))))
            interp = _clean(r.get('해석', r.get('초보자 해석', '시장 참고 지표입니다.')))
            rows.append({'시장':market,'카드':label,'상태':'확인','값':value,'해석':interp,'점수':50})
    out = pd.DataFrame(rows)
    out.to_csv(V65_MACRO_CARDS_CSV, index=False, encoding='utf-8-sig')
    return out


def build_narrative_cards() -> pd.DataFrame:
    action = read_csv_safe(REPORT_DIR/'v52_action_board_light.csv')
    risk = read_csv_safe(REPORT_DIR/'v52_buy_risk_light.csv')
    company = build_company_cards()
    rows = []
    base = action if not action.empty else company
    if base.empty:
        for market in ['한국주식','미국주식']:
            rows.append({'시장':market,'종목코드':'-','종목명':'-','내러티브':'아직 후보/뉴스/재무 데이터가 부족합니다. 자동누적 후 다시 확인하세요.','매수판단 영향':'관망','주의':'데이터 부족'})
    else:
        sym_col, name_col, mcol = _symbol_columns(base)
        for _, r in base.head(60).iterrows():
            sym = _clean(r.get(sym_col,'-') if sym_col else r.get('종목코드','-'))
            name = _clean(r.get(name_col,'-') if name_col else r.get('종목명', sym))
            market = norm_market(r.get(mcol,'') if mcol else r.get('시장',''), sym)
            risk_count = 0
            if not risk.empty:
                rc = next((c for c in risk.columns if c in ['종목코드','종목','symbol']), None)
                if rc:
                    risk_count = int((risk[rc].astype(str) == str(sym)).sum())
            narrative = f'{name}({sym})은 {market} 기준으로 후보/위험/재무 데이터를 종합해 확인합니다.'
            if risk_count:
                impact = '관망 또는 진입가 대기'
                warn = '매수 위험·제외 목록에 포함된 이력이 있습니다.'
            else:
                impact = _clean(r.get('행동', r.get('권장행동', '확인')))
                warn = '기준가·손절가·뉴스·수급을 함께 확인하세요.'
            rows.append({'시장':market,'종목코드':sym,'종목명':name,'내러티브':narrative,'매수판단 영향':impact,'주의':warn})
    df = pd.DataFrame(rows)
    df.to_csv(V65_NARRATIVE_CARDS_CSV, index=False, encoding='utf-8-sig')
    return df


def build_custom_indicator_templates() -> pd.DataFrame:
    rows = [
        {'이름':'균형형 기본 지표','시장폭':25,'뉴스':20,'재무':20,'수급':20,'퀀트':15,'설명':'초보자 기본값. 특정 항목에 과도하게 의존하지 않음.'},
        {'이름':'리스크 우선 지표','시장폭':30,'뉴스':10,'재무':15,'수급':20,'퀀트':25,'설명':'하락장/변동성 높은 장에서 보수적으로 사용.'},
        {'이름':'성장 모멘텀 지표','시장폭':15,'뉴스':25,'재무':20,'수급':25,'퀀트':15,'설명':'미장 성장주/테마주 확인용. 추격매수 위험은 별도 확인.'},
    ]
    df = pd.DataFrame(rows)
    df.to_csv(V65_CUSTOM_INDICATOR_CSV, index=False, encoding='utf-8-sig')
    return df


def run_v65_update(fetch_news: bool = True, fetch_missing_prices: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {'status':'OK','updated_at':now(),'version':'v65'}
    try:
        result['base_v60'] = run_v60_update(fetch_news=fetch_news, fetch_missing_prices=fetch_missing_prices)
    except Exception as exc:
        result['status'] = 'PARTIAL'
        result['base_v60_error'] = f'{type(exc).__name__}: {exc}'
    try:
        result['feature_rows'] = len(build_feature_implementation_map())
        result['company_cards'] = len(build_company_cards())
        result['guru_cards'] = len(build_guru_style_cards())
        result['tech_patent_cards'] = len(build_tech_patent_cards())
        result['macro_cards'] = len(build_macro_cards())
        result['narrative_cards'] = len(build_narrative_cards())
        result['custom_indicator_templates'] = len(build_custom_indicator_templates())
    except Exception as exc:
        result['status'] = 'ERROR'
        result['v65_error'] = f'{type(exc).__name__}: {exc}'
    write_json(V65_STATUS_JSON, result)
    write_json(V65_VISUAL_SUMMARY_JSON, {
        'updated_at':now(),
        'cards':{k: result.get(k,0) for k in ['company_cards','guru_cards','tech_patent_cards','macro_cards','narrative_cards']},
        'note':'일반모드는 카드/그래프, 관리자모드는 원본/진단 중심으로 분리했습니다.'
    })
    return result
