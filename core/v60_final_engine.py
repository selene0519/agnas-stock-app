
"""v60 final operations engine.

목표
- v53~v60 누적 안정화: 데이터 연결 점검, 뉴스/재무/보유/차트/퀀트/속도/메뉴 정리.
- 화면은 가볍게 CSV/JSON만 읽고, 무거운 작업은 run_v60_update에서 백그라운드로 처리.
- 로컬 .env와 GitHub Secrets 차이를 명확히 표시.
- v61: 뉴스 키는 GNEWS_API_KEY를 기준으로 표시하고, 현재가 fallback은 기본 갱신에 포함.
"""
from __future__ import annotations

import json, os, re, subprocess, math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None

try:
    from core.v52_market_split_engine import (
        ROOT, DATA_DIR, REPORT_DIR,
        run_v52_update,
        ACTION_LIGHT_CSV as V52_ACTION_CSV,
        BUY_RISK_LIGHT_CSV as V52_RISK_CSV,
        POSITION_LIGHT_CSV as V52_POSITION_CSV,
        NEWS_STATUS_JSON as V52_NEWS_JSON,
        read_csv_safe, read_json_safe, write_json,
        clean_text, norm_market, market_slug,
    )
except Exception:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / 'data'; REPORT_DIR = ROOT / 'reports'
    DATA_DIR.mkdir(parents=True, exist_ok=True); REPORT_DIR.mkdir(parents=True, exist_ok=True)
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
    def clean_text(value: Any, default: str = '-') -> str:
        s = '' if value is None else str(value).strip()
        return default if s in {'', '-', 'nan', 'None'} else s
    def norm_market(value: Any, symbol_hint: Any = '') -> str:
        t = f'{value} {symbol_hint}'
        return '한국주식' if ('한국' in t or '국장' in t or re.search(r'\b\d{6}\b', t)) else '미국주식'
    def market_slug(market: str) -> str:
        return 'kr' if str(market) in {'한국주식','국장','KR','kr'} else 'us'
    def run_v52_update(*args, **kwargs): return {'status':'SKIPPED'}
    V52_ACTION_CSV = REPORT_DIR / 'v52_action_board_light.csv'
    V52_RISK_CSV = REPORT_DIR / 'v52_buy_risk_light.csv'
    V52_POSITION_CSV = REPORT_DIR / 'v52_position_plan_light.csv'
    V52_NEWS_JSON = REPORT_DIR / 'v52_news_status.json'

V60_STATUS_JSON = REPORT_DIR / 'v60_status.json'
V60_DATA_CENTER_CSV = REPORT_DIR / 'v60_data_connection_center.csv'
V60_DATA_CENTER_JSON = REPORT_DIR / 'v60_data_connection_center.json'
V60_NEWS_CARDS_CSV = REPORT_DIR / 'v60_news_cards.csv'
V60_QUANT_REVIEW_CSV = REPORT_DIR / 'v60_quant_review.csv'
V60_SPEED_PLAN_CSV = REPORT_DIR / 'v60_speed_plan.csv'
V60_MENU_MAP_CSV = REPORT_DIR / 'v60_menu_map.csv'
V60_BEGINNER_GUIDE_JSON = REPORT_DIR / 'v60_beginner_guide.json'

KEYS = ['GNEWS_API_KEY','FINNHUB_API_KEY','DART_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','KIS_APP_KEY','KIS_APP_SECRET']


def now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        if not path.exists():
            return data
        for line in path.read_text(encoding='utf-8-sig', errors='ignore').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k:
                data[k] = v
    except Exception:
        return data
    return data


def find_env_files() -> list[Path]:
    paths = []
    for p in [Path.cwd()/'.env', ROOT/'.env', ROOT.parent/'.env']:
        if p not in paths:
            paths.append(p)
    return paths


def env_values() -> tuple[dict[str, str], list[str]]:
    merged: dict[str, str] = {}
    found: list[str] = []
    for p in find_env_files():
        d = _parse_env(p)
        if d:
            found.append(str(p))
            merged.update(d)
    # OS env wins
    for k in KEYS:
        if os.environ.get(k):
            merged[k] = str(os.environ.get(k) or '')
    return merged, found


def get_key(name: str) -> str:
    vals, _ = env_values()
    return str(vals.get(name, '') or '').strip()


def key_present(name: str) -> bool:
    return bool(get_key(name))


def _file_state(path: Path, label: str, category: str) -> dict[str, Any]:
    try:
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        rows = 0
        if exists and size and path.suffix.lower() == '.csv':
            df = read_csv_safe(path)
            rows = int(len(df)) if df is not None else 0
        elif exists and size and path.suffix.lower() == '.json':
            data = read_json_safe(path)
            rows = int(len(data)) if isinstance(data, dict) else 0
        mt = datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S') if exists else '-'
        status = '정상' if exists and size > 0 and (rows > 0 or path.suffix.lower() != '.csv') else ('비어 있음' if exists else '없음')
        guide = '정상적으로 읽을 수 있습니다.' if status == '정상' else '자동누적/수동 갱신 또는 API 키를 확인하세요.'
        return {'구분': category, '항목': label, '상태': status, '행수': rows, '파일': str(path), '수정시각': mt, '다음 행동': guide}
    except Exception as exc:
        return {'구분': category, '항목': label, '상태': '오류', '행수': 0, '파일': str(path), '수정시각': '-', '다음 행동': f'{type(exc).__name__}: {exc}'}


def _git_info() -> dict[str, Any]:
    is_repo = (ROOT/'.git').exists()
    info = {'is_repo': is_repo, 'status': '정상' if is_repo else '로컬 폴더', 'message': ''}
    if not is_repo:
        info['message'] = '현재 폴더가 Git 저장소가 아닙니다. GitHub Desktop 저장소 폴더에서 실행하면 자동 pull 상태가 정상 표시됩니다.'
        return info
    try:
        res = subprocess.run(['git','status','--short'], cwd=str(ROOT), capture_output=True, text=True, timeout=8)
        info['dirty_count'] = len([x for x in res.stdout.splitlines() if x.strip()])
        info['message'] = '변경 파일 없음' if info['dirty_count'] == 0 else f"변경 파일 {info['dirty_count']}개 있음"
    except Exception as exc:
        info['status'] = '확인 실패'; info['message'] = f'{type(exc).__name__}: {exc}'
    return info


def gnews_direct_test(fetch: bool = False) -> dict[str, Any]:
    key = get_key('GNEWS_API_KEY') or get_key('NEWS_API_KEY')
    if not key:
        return {'status':'키 없음','key_present':False,'rows':0,'message':'로컬 .env 또는 GitHub Secrets에 GNEWS_API_KEY가 필요합니다. NEWS_API_KEY는 이 앱에서 기본 키가 아닙니다.'}
    if not fetch:
        return {'status':'키 인식','key_present':True,'rows':0,'message':'키는 인식됐습니다. 실제 호출은 뉴스 갱신 버튼에서 실행합니다.'}
    if requests is None:
        return {'status':'요청 불가','key_present':True,'rows':0,'message':'requests 패키지를 사용할 수 없습니다.'}
    try:
        url = 'https://gnews.io/api/v4/search'
        params = {'q':'stock OR market','lang':'en','max':3,'apikey':key}
        r = requests.get(url, params=params, timeout=12)
        if r.status_code != 200:
            return {'status':'API 오류','key_present':True,'rows':0,'http_status':r.status_code,'message':r.text[:220]}
        data = r.json()
        articles = data.get('articles') or []
        return {'status':'정상' if articles else '0건','key_present':True,'rows':len(articles),'message':'GNews 직접 호출 성공' if articles else '호출은 성공했지만 결과가 0건입니다.'}
    except Exception as exc:
        return {'status':'호출 실패','key_present':True,'rows':0,'message':f'{type(exc).__name__}: {exc}'}


def build_data_connection_center(fetch_news_test: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    vals, env_files = env_values()
    git = _git_info()
    gnews = gnews_direct_test(fetch=fetch_news_test)
    cloud = read_json_safe(REPORT_DIR/'cloud_accumulator_last_run.json')
    rows: list[dict[str, Any]] = []
    rows.append({'구분':'환경','항목':'.env 파일','상태':'있음' if env_files else '없음','행수':len(env_files),'파일':' / '.join(env_files) or '-', '수정시각':'-', '다음 행동':'GitHub 폴더 안에도 .env를 복사하세요.' if not env_files else 'API 키 파일을 인식했습니다.'})
    for k in ['GNEWS_API_KEY','FINNHUB_API_KEY','DART_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY']:
        rows.append({'구분':'API 키','항목':k,'상태':'인식됨' if vals.get(k) else '미설정','행수':1 if vals.get(k) else 0,'파일':'.env 또는 환경변수','수정시각':'-', '다음 행동':'정상' if vals.get(k) else ('AI 요약이 필요할 때만 설정' if k in {'OPENAI_API_KEY','ANTHROPIC_API_KEY'} else ('뉴스 수집은 GNEWS_API_KEY를 사용합니다.' if k == 'GNEWS_API_KEY' else '키를 .env/GitHub Secrets에 넣으세요.'))})
    rows.append({'구분':'GitHub','항목':'로컬 Git 동기화','상태':git.get('status','-'),'행수':git.get('dirty_count',0),'파일':str(ROOT),'수정시각':'-', '다음 행동':git.get('message','')})
    rows.append({'구분':'GitHub','항목':'Actions 마지막 실행','상태':cloud.get('status','없음') if cloud else '없음','행수':1 if cloud else 0,'파일':'reports/cloud_accumulator_last_run.json','수정시각':cloud.get('updated_at','-') if cloud else '-', '다음 행동':'정상' if cloud else 'GitHub Actions 자동 실행 후 Pull/동기화하세요.'})
    rows.append({'구분':'뉴스','항목':'GNews 직접 테스트','상태':gnews.get('status','-'),'행수':gnews.get('rows',0),'파일':'GGNews API','수정시각':now(), '다음 행동':gnews.get('message','')})
    files = [
        (REPORT_DIR/'v52_action_board_light.csv','오늘 행동판','행동판'),
        (REPORT_DIR/'v52_buy_risk_light.csv','매수 위험·제외','매수'),
        (REPORT_DIR/'v52_position_plan_light.csv','보유·매도 권장수량','보유'),
        (REPORT_DIR/'gnews_latest_kr.csv','국장 뉴스','뉴스'),
        (REPORT_DIR/'gnews_latest_us.csv','미장 뉴스','뉴스'),
        (REPORT_DIR/'v50_fundamental_cards.csv','재무·KPI','재무'),
        (REPORT_DIR/'v43_strategy_backtest_summary.csv','전략 백테스트','퀀트'),
        (REPORT_DIR/'v45_calibrated_candidates.csv','추천 보정 후보','퀀트'),
        (REPORT_DIR/'intraday_realtime_snapshot.csv','현재가 스냅샷','현재가'),
    ]
    rows += [_file_state(p, label, cat) for p, label, cat in files]
    df = pd.DataFrame(rows)
    df.to_csv(V60_DATA_CENTER_CSV, index=False, encoding='utf-8-sig')
    meta = {'updated_at':now(),'env_files':env_files,'keys':{k:bool(vals.get(k)) for k in KEYS},'git':git,'gnews_test':gnews,'cloud_status':cloud}
    write_json(V60_DATA_CENTER_JSON, meta)
    return df, meta


def build_news_cards() -> pd.DataFrame:
    rows = []
    for market, path in [('국장', REPORT_DIR/'gnews_latest_kr.csv'), ('미장', REPORT_DIR/'gnews_latest_us.csv')]:
        df = read_csv_safe(path)
        if df.empty:
            continue
        for _, r in df.head(30).iterrows():
            title = clean_text(r.get('title', r.get('제목','뉴스 제목 없음')), '뉴스 제목 없음')
            desc = clean_text(r.get('description', r.get('요약','')), '')
            source = clean_text(r.get('source', r.get('출처','')), '-')
            url = clean_text(r.get('url', r.get('링크','')), '')
            rows.append({'시장':market,'제목':title,'요약':desc or title,'출처':source,'링크':url,'초보자 해석':'뉴스는 가격·거래량·수급 확인 후 판단에 반영하세요.','매매 영향':'단독 매수 근거 아님'})
    out = pd.DataFrame(rows)
    if out.empty:
        out = pd.DataFrame(columns=['시장','제목','요약','출처','링크','초보자 해석','매매 영향'])
    out.to_csv(V60_NEWS_CARDS_CSV, index=False, encoding='utf-8-sig')
    return out


def build_quant_review() -> pd.DataFrame:
    rows = []
    sources = [
        ('전략 백테스트', REPORT_DIR/'v43_strategy_backtest_summary.csv'),
        ('복기 결과', REPORT_DIR/'v44_condition_performance.csv'),
        ('추천 보정', REPORT_DIR/'v45_score_calibration_summary.json'),
        ('베타 백테스트', REPORT_DIR/'backtest_beta_summary.csv'),
    ]
    for label, path in sources:
        if path.suffix == '.json':
            data = read_json_safe(path)
            if data:
                rows.append({'구분':label,'상태':'있음','핵심 요약':json.dumps(data, ensure_ascii=False)[:240],'초보자 안내':'이 결과는 추천 점수 보정의 참고값입니다.'})
            else:
                rows.append({'구분':label,'상태':'없음','핵심 요약':'아직 결과가 없습니다.','초보자 안내':'추천 기록이 쌓이면 자동 보정에 활용됩니다.'})
        else:
            df = read_csv_safe(path)
            if not df.empty:
                rows.append({'구분':label,'상태':f'{len(df)}건','핵심 요약':'성과/오차 기록이 있습니다.','초보자 안내':'승률보다 손익비와 최대손실을 함께 보세요.'})
            else:
                rows.append({'구분':label,'상태':'없음','핵심 요약':'아직 계산 결과가 없습니다.','초보자 안내':'GitHub 자동누적 또는 수동 갱신 후 채워집니다.'})
    out = pd.DataFrame(rows)
    out.to_csv(V60_QUANT_REVIEW_CSV, index=False, encoding='utf-8-sig')
    return out


def build_speed_plan() -> pd.DataFrame:
    rows = [
        {'항목':'화면 로딩','상태':'가벼움 우선','적용 내용':'일반모드는 light CSV/JSON을 먼저 읽습니다.','다음 행동':'무거운 원본표는 관리자모드에서만 펼쳐보세요.'},
        {'항목':'API 호출','상태':'버튼/백그라운드','적용 내용':'화면 진입 시 자동 API 호출을 최소화했습니다.','다음 행동':'뉴스/현재가 갱신 버튼 또는 GitHub Actions를 사용하세요.'},
        {'항목':'차트','상태':'선택 종목만','적용 내용':'차트는 차트·수급 화면에서 선택 종목 1개 중심으로 봅니다.','다음 행동':'매수 판단 화면에서는 차트를 중복 표시하지 않습니다.'},
        {'항목':'권장수량','상태':'백그라운드 보강','적용 내용':'보유 파일과 현재가 리포트를 합쳐 미리 계산합니다.','다음 행동':'값이 비면 데이터 연결 점검을 먼저 보세요.'},
    ]
    out = pd.DataFrame(rows)
    out.to_csv(V60_SPEED_PLAN_CSV, index=False, encoding='utf-8-sig')
    return out


def build_menu_map() -> pd.DataFrame:
    rows = [
        {'대분류':'오늘 실행','소분류':'오늘 행동판','용도':'국장/미장별로 오늘 먼저 볼 행동만 확인'},
        {'대분류':'오늘 실행','소분류':'데이터 연결 점검','용도':'뉴스/API/GitHub/리포트가 왜 비는지 확인'},
        {'대분류':'매수','소분류':'매수 위험·제외','용도':'지금 사면 안 되거나 대기해야 할 후보 확인'},
        {'대분류':'보유·매도','소분류':'보유·매도 권장수량','용도':'보유 종목의 익절/축소/보유 판단'},
        {'대분류':'차트·수급','소분류':'선택 종목 차트·수급','용도':'차트 1개와 수급/호가/현재가를 같이 확인'},
        {'대분류':'뉴스·재무·시장','소분류':'뉴스 카드','용도':'GNews 기반 뉴스와 매매 영향 확인'},
        {'대분류':'뉴스·재무·시장','소분류':'재무·KPI 카드','용도':'재무 체력과 가치평가 확인'},
        {'대분류':'퀀트','소분류':'퀀트 안내·복기','용도':'앱 추천이 과거에 맞았는지 확인'},
        {'대분류':'관심·설정','소분류':'v60 안정판 안내','용도':'하루 사용 순서와 실행 방법 확인'},
    ]
    out = pd.DataFrame(rows)
    out.to_csv(V60_MENU_MAP_CSV, index=False, encoding='utf-8-sig')
    return out


def run_v60_update(fetch_news: bool = False, fetch_missing_prices: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {'status':'OK','updated_at':now(),'version':'v60 final stable'}
    try:
        result['v52'] = run_v52_update(fetch_news=fetch_news, fetch_missing_prices=fetch_missing_prices)
    except Exception as exc:
        result['status'] = 'WARN'; result['v52_error'] = f'{type(exc).__name__}: {exc}'
    try:
        data_df, meta = build_data_connection_center(fetch_news_test=fetch_news)
        result['data_center_rows'] = int(len(data_df)); result['data_center'] = meta
    except Exception as exc:
        result['status'] = 'WARN'; result['data_center_error'] = f'{type(exc).__name__}: {exc}'
    try:
        result['news_rows'] = int(len(build_news_cards()))
    except Exception as exc:
        result['status'] = 'WARN'; result['news_error'] = f'{type(exc).__name__}: {exc}'
    try:
        result['quant_rows'] = int(len(build_quant_review()))
    except Exception as exc:
        result['status'] = 'WARN'; result['quant_error'] = f'{type(exc).__name__}: {exc}'
    result['speed_rows'] = int(len(build_speed_plan()))
    result['menu_rows'] = int(len(build_menu_map()))
    guide = {
        'daily_order':['1. 오늘 실행 → 데이터 연결 점검','2. 오늘 실행 → 오늘 행동판','3. 매수 → 매수 위험·제외','4. 보유·매도 → 보유·매도 권장수량','5. 차트·수급 → 선택 종목 차트·수급'],
        'beginner_rule':'오늘 행동판은 국장/미장 중 하나만 선택해서 보고, 매수 위험·제외에 있는 종목은 신규매수보다 관망을 우선하세요.',
        'sync_rule':'GitHub 자동누적은 서버에서 돌고, PC 앱은 START_HERE_V60_FIXED.bat로 최신 데이터를 동기화한 뒤 실행하세요.',
    }
    write_json(V60_BEGINNER_GUIDE_JSON, guide)
    write_json(V60_STATUS_JSON, result)
    return result


if __name__ == '__main__':
    print(json.dumps(run_v60_update(fetch_news=True, fetch_missing_prices=True), ensure_ascii=False, indent=2, default=str))
