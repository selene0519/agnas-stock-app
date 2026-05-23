"""v45 추천 기준 자동 보정 엔진.

v44는 추천 기록/결과 추적을 만들었다. v45는 그 복기 결과를 오늘 후보 점수에
실제로 반영해 일반모드의 행동판을 더 보수적으로 만드는 단계다.

이 모듈은 주문을 실행하지 않는다. CSV/JSON 리포트만 생성한다.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from core.v43_operational_engine import (
        ROOT, DATA_DIR, REPORT_DIR, read_csv_safe, read_json_safe, write_json,
        market_slug, label_for_symbol, discover_symbol_names, to_num, first,
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
    def label_for_symbol(symbol: str, market: str, names: dict[str,str]|None=None) -> str:
        return str(symbol)
    def discover_symbol_names(market: str) -> dict[str,str]:
        return {}
    def to_num(value: Any, default: float = math.nan) -> float:
        try:
            s = re.sub(r'[^0-9.\-]', '', str(value or ''))
            return float(s) if s not in {'', '-', '.'} else default
        except Exception:
            return default
    def first(row: Any, cols: Iterable[str], default: Any='-') -> Any:
        for c in cols:
            if c in getattr(row, 'index', []):
                v = row.get(c)
                if pd.notna(v) and str(v).strip() not in {'', '-', 'nan', 'None'}:
                    return v
        return default

try:
    from core.v44_learning_calibration_engine import (
        run_v44_update,
        collect_current_recommendations,
        CONDITION_CSV as V44_CONDITION_CSV,
        CALIB_JSON as V44_CALIB_JSON,
        OUTCOME_CSV as V44_OUTCOME_CSV,
        ACTION_CSV as V44_ACTION_CSV,
    )
except Exception:  # pragma: no cover
    run_v44_update = None
    collect_current_recommendations = None
    V44_CONDITION_CSV = REPORT_DIR / 'v44_condition_performance.csv'
    V44_CALIB_JSON = REPORT_DIR / 'v44_calibration_summary.json'
    V44_OUTCOME_CSV = REPORT_DIR / 'v44_recommendation_outcomes.csv'
    V44_ACTION_CSV = REPORT_DIR / 'v44_beginner_action_board.csv'

CALIBRATED_CSV = REPORT_DIR / 'v45_calibrated_candidates.csv'
ACTION_CSV = REPORT_DIR / 'v45_beginner_action_board.csv'
CALIBRATION_JSON = REPORT_DIR / 'v45_score_calibration_summary.json'
DATA_HEALTH_CSV = REPORT_DIR / 'v45_data_health_center.csv'
DATA_HEALTH_JSON = REPORT_DIR / 'v45_data_health_center.json'
PERFORMANCE_JSON = REPORT_DIR / 'v45_performance_snapshot.json'
STATUS_JSON = REPORT_DIR / 'v45_status.json'


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _clean_symbol(value: Any, market: str) -> str:
    s = str(value or '').strip()
    if market_slug(market) == 'kr':
        m = re.search(r'(\d{6})', s)
        if m:
            return m.group(1)
    return re.sub(r'[^A-Za-z0-9.\-]', '', s.split()[0] if s else '').upper()


def _norm_market(value: Any) -> str:
    s = str(value or '').strip()
    if s in {'한국주식', '국장', 'KR', 'kr', 'KOSPI', 'KOSDAQ'}:
        return '한국주식'
    return '미국주식'


def _fmt_money(value: Any, market: str) -> str:
    v = to_num(value)
    if math.isnan(v) or v <= 0:
        return '-'
    return f"{v:,.0f}원" if market_slug(market) == 'kr' else f"${v:,.2f}"


def _extract_bad_good_keywords() -> tuple[dict[str, float], dict[str, float], list[str]]:
    """v44 조건별 성과에서 자동 감점/가점 키워드를 만든다."""
    cond = read_csv_safe(V44_CONDITION_CSV)
    bad: dict[str, float] = {}
    good: dict[str, float] = {}
    notes: list[str] = []
    if cond.empty:
        notes.append('아직 조건별 복기 데이터가 부족해 기본 보수 기준을 사용합니다.')
    else:
        for _, r in cond.iterrows():
            key = str(r.get('조건', '') or '').strip()
            if not key or key in {'-', 'nan'}:
                continue
            avg = to_num(r.get('평균수익률'))
            fail = to_num(r.get('실패율'))
            win = to_num(r.get('승률'))
            weight = 0.0
            if not math.isnan(avg) and avg < 0:
                weight += min(18.0, abs(avg) * 2.0 + 4.0)
            if not math.isnan(fail) and fail >= 60:
                weight += min(12.0, (fail - 50.0) / 2.0)
            if weight > 0:
                bad[key] = round(max(bad.get(key, 0.0), weight), 2)
            bonus = 0.0
            if not math.isnan(avg) and avg >= 2:
                bonus += min(10.0, avg * 1.2)
            if not math.isnan(win) and win >= 55:
                bonus += min(6.0, (win - 50.0) / 3.0)
            if bonus > 0:
                good[key] = round(max(good.get(key, 0.0), bonus), 2)
    # Always keep a conservative base penalty for common beginner-risk keywords.
    base_bad = {
        '추격': 12.0, '과열': 12.0, '손익비': 8.0, '악재': 10.0,
        '거래량 부족': 8.0, '수급 약함': 7.0, '매수금지': 25.0, '제외': 18.0,
    }
    for k, v in base_bad.items():
        bad[k] = max(bad.get(k, 0.0), v)
    return bad, good, notes


def _current_candidates() -> pd.DataFrame:
    if collect_current_recommendations is not None:
        try:
            df = collect_current_recommendations()
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    # Fallback: collect from obvious reports.
    rows: list[dict[str, Any]] = []
    sources = list(REPORT_DIR.glob('*candidate*.csv')) + list(REPORT_DIR.glob('operational_buy_budget_*.csv'))
    for p in sources[:30]:
        df = read_csv_safe(p)
        if df.empty:
            continue
        default_market = '한국주식' if '_kr' in p.name.lower() else '미국주식'
        for _, r in df.head(80).iterrows():
            market = _norm_market(first(r, ['시장','market'], default_market))
            sym = _clean_symbol(first(r, ['종목코드','symbol','ticker','종목','code'], ''), market)
            if not sym:
                continue
            rows.append({
                'market': market,
                'symbol': sym,
                'name': str(first(r, ['종목명','name','company'], '') or ''),
                'strategy': p.name,
                'action': str(first(r, ['판단','action','추천행동','최종판단'], '진입가 대기')),
                'entry_price': first(r, ['우선진입가','진입가','entry_price','현재가','current_price','Close'], ''),
                'stop_price': first(r, ['손절가','stop_price','stop'], ''),
                'target_price': first(r, ['1차 목표가','목표가','target_price','target'], ''),
                'score': first(r, ['상승확률','확률','score','final_score','confidence','종합점수'], ''),
                'reason': str(first(r, ['사유','reason','초보자 요약','내러티브'], p.name)),
                'source_file': p.name,
            })
    return pd.DataFrame(rows).drop_duplicates(subset=['market','symbol','strategy'], keep='first') if rows else pd.DataFrame()


def _score_row(r: pd.Series, bad_kw: dict[str, float], good_kw: dict[str, float]) -> dict[str, Any]:
    market = _norm_market(r.get('market'))
    sym = _clean_symbol(r.get('symbol'), market)
    name = str(r.get('name', '') or '').strip()
    score = to_num(r.get('score'), 55.0)
    if math.isnan(score):
        score = 55.0
    # If score looks like probability 0~1, convert.
    if 0 <= score <= 1:
        score *= 100
    score = max(0.0, min(100.0, score))
    entry = to_num(r.get('entry_price'))
    stop = to_num(r.get('stop_price'))
    target = to_num(r.get('target_price'))
    reason = ' '.join(str(r.get(c, '') or '') for c in ['reason', 'action', 'strategy', 'source_file'])
    penalties: list[str] = []
    bonuses: list[str] = []
    penalty = 0.0
    bonus = 0.0
    for k, w in bad_kw.items():
        if k and k in reason:
            penalty += float(w)
            penalties.append(f'{k} -{float(w):.0f}')
    for k, w in good_kw.items():
        if k and k in reason:
            bonus += float(w)
            bonuses.append(f'{k} +{float(w):.0f}')
    rr = math.nan
    if not math.isnan(entry) and not math.isnan(stop) and not math.isnan(target) and entry > stop:
        risk = entry - stop
        reward = target - entry
        rr = reward / risk if risk > 0 else math.nan
        if not math.isnan(rr) and rr < 1.5:
            penalty += 12
            penalties.append('손익비 1.5 미만 -12')
        elif not math.isnan(rr) and rr >= 2.0:
            bonus += 6
            bonuses.append('손익비 2 이상 +6')
    else:
        penalty += 5
        penalties.append('기준가/손절/목표 불완전 -5')
    calibrated = max(0.0, min(100.0, score + bonus - penalty))
    action_raw = str(r.get('action', '') or '')
    if any(x in action_raw + reason for x in ['매수금지', '제외']) or calibrated < 35:
        action = '관망/제외'
        beginner = '초보자는 매수하지 않고 제외 또는 관망합니다.'
        priority = '낮음'
    elif calibrated >= 72 and not any(x in action_raw + reason for x in ['추격', '과열']):
        action = '신규매수 가능 후보'
        beginner = '현재가가 기준가 근처이고 손절가를 지킬 수 있을 때만 분할 매수를 검토합니다.'
        priority = '높음'
    elif calibrated >= 55:
        action = '진입가 대기'
        beginner = '좋은 종목이어도 가격이 중요합니다. 기준가 근처까지 기다립니다.'
        priority = '중간'
    elif calibrated >= 42:
        action = '소액/분할만'
        beginner = '확신도가 높지 않습니다. 매수한다면 아주 작은 비중만 검토합니다.'
        priority = '중간'
    else:
        action = '관망/제외'
        beginner = '지금은 기대수익보다 리스크가 커 보입니다.'
        priority = '낮음'
    names = discover_symbol_names(market)
    label = f'{name} ({sym})' if name else label_for_symbol(sym, market, names)
    return {
        '우선순위': priority,
        '행동': action,
        '종목': label,
        '종목코드': sym,
        '시장': market,
        '원점수': round(score, 2),
        '보정점수': round(calibrated, 2),
        '보정': round(bonus - penalty, 2),
        '손익비': '-' if math.isnan(rr) else round(rr, 2),
        '기준가': _fmt_money(entry, market),
        '손절가': _fmt_money(stop, market),
        '목표가': _fmt_money(target, market),
        '가점근거': ', '.join(bonuses) if bonuses else '-',
        '감점근거': ', '.join(penalties) if penalties else '-',
        '이유': str(r.get('reason', '') or '')[:220],
        '초보자 안내': beginner,
        'source_file': str(r.get('source_file', '') or ''),
    }


def build_calibrated_candidates() -> pd.DataFrame:
    bad_kw, good_kw, notes = _extract_bad_good_keywords()
    cur = _current_candidates()
    rows: list[dict[str, Any]] = []
    if not cur.empty:
        for _, r in cur.iterrows():
            rows.append(_score_row(r, bad_kw, good_kw))
    out = pd.DataFrame(rows)
    if not out.empty:
        order = {'높음': 0, '중간': 1, '낮음': 2}
        out['_ord'] = out['우선순위'].map(order).fillna(9)
        out = out.sort_values(['_ord', '보정점수'], ascending=[True, False]).drop(columns=['_ord'])
        out = out.drop_duplicates(subset=['시장', '종목코드', '행동'], keep='first')
    out.to_csv(CALIBRATED_CSV, index=False, encoding='utf-8-sig')
    action = out.head(30).copy() if not out.empty else pd.DataFrame(columns=['우선순위','행동','종목','시장','기준가','손절가','목표가','보정점수','감점근거','초보자 안내'])
    action.to_csv(ACTION_CSV, index=False, encoding='utf-8-sig')
    summary = {
        'updated_at': _now(),
        'status': 'OK',
        'input_rows': int(len(cur)),
        'output_rows': int(len(out)),
        'bad_keywords': bad_kw,
        'good_keywords': good_kw,
        'notes': notes,
        'action_counts': out['행동'].value_counts().to_dict() if not out.empty and '행동' in out.columns else {},
    }
    write_json(CALIBRATION_JSON, summary)
    return out


def build_data_health_center() -> pd.DataFrame:
    checks = [
        ('뉴스', REPORT_DIR / 'gnews_summary.json', 'GNews/GitHub Actions 뉴스 수집 결과'),
        ('뉴스 캐시', DATA_DIR / 'news' / 'gnews_cache.csv', '뉴스 캐시'),
        ('재무·KPI', REPORT_DIR / 'v40_fundamental_kpi_summary.csv', '재무·가치·KPI 리포트'),
        ('시장·거시', REPORT_DIR / 'v40_macro_market_summary.csv', '시장·거시 리포트'),
        ('전략 백테스트', REPORT_DIR / 'v43_strategy_backtest_summary.csv', 'v43 전략 백테스트'),
        ('실전 복기', Path(V44_OUTCOME_CSV), 'v44 추천 결과 추적'),
        ('보정 행동판', ACTION_CSV, 'v45 보정 행동판'),
        ('클라우드 실행', REPORT_DIR / 'cloud_accumulator_last_run.json', 'GitHub Actions 마지막 실행'),
    ]
    rows = []
    now_ts = datetime.now().timestamp()
    for name, path, desc in checks:
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        age_h = round((now_ts - path.stat().st_mtime) / 3600, 2) if exists else None
        if not exists:
            status = '없음'
            guide = '자동누적 또는 해당 갱신 버튼을 먼저 실행하세요.'
        elif size == 0:
            status = '비어 있음'
            guide = '파일은 있지만 내용이 없습니다. API 키/데이터 원천을 확인하세요.'
        elif age_h is not None and age_h > 72:
            status = '오래됨'
            guide = '최근 데이터가 아닐 수 있습니다. GitHub Actions 또는 수동 갱신을 확인하세요.'
        else:
            status = '정상'
            guide = '사용 가능합니다.'
        rows.append({'구분': name, '상태': status, '파일': str(path.relative_to(ROOT)) if path.exists() or str(path).startswith(str(ROOT)) else str(path), '크기': size, '최근갱신_시간전': age_h if age_h is not None else '-', '설명': desc, '다음 행동': guide})
    df = pd.DataFrame(rows)
    df.to_csv(DATA_HEALTH_CSV, index=False, encoding='utf-8-sig')
    write_json(DATA_HEALTH_JSON, {'updated_at': _now(), 'rows': rows})
    return df


def build_performance_snapshot() -> dict[str, Any]:
    outcomes = read_csv_safe(Path(V44_OUTCOME_CSV))
    summary: dict[str, Any] = {'updated_at': _now(), 'status': 'OK'}
    if outcomes.empty:
        summary.update({'status': 'NO_DATA', 'message': '아직 실전 추적 결과가 없습니다.', 'rows': 0})
        write_json(PERFORMANCE_JSON, summary)
        return summary
    ret = pd.to_numeric(outcomes.get('final_return_pct'), errors='coerce')
    summary['rows'] = int(len(outcomes))
    summary['evaluated_rows'] = int(ret.notna().sum())
    summary['avg_return_pct'] = round(float(ret.mean()), 2) if ret.notna().any() else None
    summary['win_rate_pct'] = round(float((ret > 0).mean() * 100), 1) if ret.notna().any() else None
    summary['target_hit_count'] = int(outcomes.get('target_hit', pd.Series(dtype=object)).astype(str).str.lower().isin(['true','1']).sum()) if 'target_hit' in outcomes.columns else 0
    summary['stop_hit_count'] = int(outcomes.get('stop_hit', pd.Series(dtype=object)).astype(str).str.lower().isin(['true','1']).sum()) if 'stop_hit' in outcomes.columns else 0
    write_json(PERFORMANCE_JSON, summary)
    return summary


def run_v45_update() -> dict[str, Any]:
    v44_result = None
    if run_v44_update is not None:
        try:
            v44_result = run_v44_update()
        except Exception as exc:
            v44_result = {'status': 'ERROR', 'error': f'{type(exc).__name__}: {exc}'}
    candidates = build_calibrated_candidates()
    health = build_data_health_center()
    perf = build_performance_snapshot()
    status = {
        'status': 'OK',
        'updated_at': _now(),
        'v44': v44_result,
        'candidate_rows': int(len(candidates)),
        'data_health_rows': int(len(health)),
        'performance': perf,
        'paths': {
            'calibrated_candidates': str(CALIBRATED_CSV.relative_to(ROOT)),
            'action_board': str(ACTION_CSV.relative_to(ROOT)),
            'data_health': str(DATA_HEALTH_CSV.relative_to(ROOT)),
            'performance': str(PERFORMANCE_JSON.relative_to(ROOT)),
        },
    }
    write_json(STATUS_JSON, status)
    return status


if __name__ == '__main__':
    print(json.dumps(run_v45_update(), ensure_ascii=False, indent=2, default=str))
