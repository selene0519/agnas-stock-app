"""
data_freshness_healthcheck.py — 데이터 신선도 헬스게이트 + 조용한 실패 탐지.

배경(CLAUDE.md #4): 워크플로에 `set +e`가 34곳, staleness alarm 0.
그래서 generate_kr_recommendations가 6/26부터 아무도 모르게 실패해도 CI는 green.
이 스크립트는:
  1) 핵심 산출물의 임베디드 날짜를 검사(파일 mtime은 git checkout에 리셋되므로 불신)
  2) 상태 JSON 안의 ERROR/실패 스텝을 재귀 탐지 (조용한 실패 표면화)
  3) reports/data_freshness_status.json 작성 (앱/대시보드가 읽어 배지 표시 가능)
  4) critical 항목이 STALE/ERROR/MISSING이면 exit 1 → 워크플로가 알람(텔레그램)

실행: python scripts/data_freshness_healthcheck.py [--max-stale-days N]
stdlib만 사용.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows 콘솔(cp949)은 em-dash를 못 찍고 UnicodeEncodeError로 죽는다.
# 헬스체크가 리포트 출력 중에 죽으면 exit code가 의미를 잃으므로 치환 출력으로 낮춘다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


def _parse_dt(s: str) -> datetime | None:
    s = str(s or "").strip()
    if not s:
        return None
    if s.upper().endswith(" KST"):
        s = f"{s[:-4].strip()}+09:00"
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _parse_collector_dt(s: str) -> datetime | None:
    """Collector reports are written by KST runners unless an offset is explicit."""
    raw = str(s or "").strip()
    if not raw:
        return None
    if raw.upper().endswith(" KST") or raw.endswith("Z"):
        return _parse_dt(raw)
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone(timedelta(hours=9)))
    except ValueError:
        pass
    return _parse_dt(raw)

def _age_days(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    return round((NOW - dt).total_seconds() / 86400.0, 2)


def _load_json(rel: str):
    p = ROOT / rel
    if not p.exists():
        return None
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return json.load(open(p, encoding=enc))
        except Exception:
            continue
    return None


def _newest_csv_date(rel_glob: str, sample: int = 5) -> str | None:
    """대표 CSV 몇 개의 마지막 행 date 중 최신값 (전량 로드 회피)."""
    files = sorted((ROOT).glob(rel_glob))
    if not files:
        return None
    newest = None
    for p in files[:sample] + files[-sample:]:
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                d = rows[-1].get("date") or rows[-1].get("Date")
                if d and (newest is None or d > newest):
                    newest = d
        except Exception:
            continue
    return newest


def _benchmark_ohlcv_state(symbol: str) -> tuple[str, str | None, str]:
    """Validate the exact regime benchmark, including its trailing bar."""
    path = ROOT / "data" / "market" / "ohlcv" / f"kr_{symbol}_daily.csv"
    if not path.exists() or path.stat().st_size == 0:
        return "MISSING", None, f"{path.name} unavailable"
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        return "ERROR", None, f"{path.name} unreadable: {exc}"
    if not rows:
        return "MISSING", None, f"{path.name} has no rows"
    row = rows[-1]
    day = str(row.get("date") or row.get("Date") or "")[:10] or None
    try:
        open_, high, low, close = (
            float(row.get(key) or row.get(key.title()) or "nan")
            for key in ("open", "high", "low", "close")
        )
    except (TypeError, ValueError):
        return "ERROR", day, f"{path.name} trailing bar is non-numeric, asOf={day}"
    values = (open_, high, low, close)
    valid = (
        all(math.isfinite(value) and value > 0 for value in values)
        and high >= max(open_, close, low)
        and low <= min(open_, close, high)
    )
    if not valid:
        return "ERROR", day, f"{path.name} trailing bar is invalid, asOf={day}"
    return "OK", day, f"{path.name} trailing OHLC is valid"

def _read_csv_rows(rel: str) -> list[dict]:
    p = ROOT / rel
    if not p.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(p, encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


# 정산 가능한(=승률 분모에 들어가는) 행만 통과시키는 필터.
# scripts/update_win_rates.py의 _is_realized_forward_result와 같은 기준.
_NON_ADMISSIBLE = {
    "", "PENDING", "DATA_PENDING", "NOT_EXECUTED",
    "CANCELLED", "INVALID_SYMBOL", "DATA_INVALID",
}


# CI 캡처가 처음으로 성공한 날. 이 이전 구간은 캡처 스텝이 아예 없었거나
# (스크립트 생성 2026-07-26, 51577cc) 루트 app.py가 백엔드 app 패키지를 가려
# 매 실행 죽던 구간이라(aafd943, 8c310be) 연속성 위반으로 세면 영영 빨간불이 된다.
# 새 결손이 생기면 그건 이 날 이후의 진짜 회귀다.
CAPTURE_CI_EPOCH = "2026-07-28"
# 연속성을 볼 창. 짧으면 한 번의 휴장/지연에 과민해지고, 길면 회귀를 늦게 잡는다.
CAPTURE_CONTINUITY_WINDOW_DAYS = 21


def _trading_days_since(start: str, sample: int = 5) -> list[str]:
    """장이 열린 날 목록을 OHLCV 봉에서 역산한다.

    공휴일 달력을 하드코딩하지 않으려는 것이다 — 하드코딩하면 그 표가 낡는 순간
    헬스체크가 거짓말을 시작하고, 이 레포는 이미 그 방식으로 세 번 당했다.
    거래정지/신규상장 종목은 봉이 빠지므로 여러 파일의 **합집합**을 쓴다.
    """
    files = sorted(ROOT.glob("data/market/ohlcv/kr_*_daily.csv"))
    if not files:
        return []
    days: set[str] = set()
    for p in files[:sample] + files[-sample:]:
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    d = str(row.get("date") or row.get("Date") or "")[:10]
                    if d >= start:
                        days.add(d)
        except Exception:
            continue
    return sorted(days)


def _capture_continuity_check() -> tuple:
    """캡처가 **매 거래일** 잡혔는지. (name, status, detail, critical)

    `prediction_capture`는 최신 캡처가 며칠 전인지만 본다. 그래서 어제 22건이
    들어왔으면 중간에 9일이 비어도 OK를 찍는다 — 2026-07-28에 배운 교훈
    ("파일 mtime은 새것이었다")과 똑같은 함정을 감시 장치 쪽에서 반복한 것이다.
    표본 축적 속도가 곧 엣지 판정의 분모라서, 결손일은 지연이 아니라 손실이다.
    """
    window_start = (NOW - timedelta(days=CAPTURE_CONTINUITY_WINDOW_DAYS)).strftime("%Y-%m-%d")
    start = max(CAPTURE_CI_EPOCH, window_start)
    expected = _trading_days_since(start)
    if not expected:
        return ("capture_continuity", "OK",
                f"판정 구간 없음 (기준일 {start} 이후 거래일 0일)", False)
    # 최신 거래일은 장마감 수집과 캡처 사이의 경합이 있으므로 1일 유예.
    # (accumulator는 KST 07:30 장전 / 16:30 장후에 도는데, 장후 실행에서
    #  OHLCV 갱신이 캡처보다 늦으면 그날 봉은 있는데 캡처는 아직 없을 수 있다.)
    expected = expected[:-1]
    if not expected:
        return ("capture_continuity", "OK",
                f"판정 구간 없음 (기준일 {start} 이후 확정 거래일 0일)", False)

    ledger = _read_csv_rows("reports/virtual_prediction_ledger.csv")
    captured = {str(r.get("createdAt") or "")[:10] for r in ledger if r.get("createdAt")}
    missing = [d for d in expected if d not in captured]
    detail = (f"거래일 {len(expected)}일 중 캡처 {len(expected) - len(missing)}일"
              f" (기준일 {start}~, 유예 1일)")
    if not missing:
        return ("capture_continuity", "OK", detail, True)
    detail += f" — 결손 {len(missing)}일: {', '.join(missing[:5])}"
    if len(missing) > 5:
        detail += f" 외 {len(missing) - 5}일"
    # 1일 결손은 CI 지연/일시 장애로도 생긴다. 2일부터는 캡처가 멈춘 것으로 본다.
    if len(missing) >= 2:
        return ("capture_continuity", "ERROR", detail + " — 캡처가 멈춘 것으로 보임", True)
    return ("capture_continuity", "WARN", detail, True)


def _learning_loop_stats() -> dict:
    """자가보정 루프가 실제로 살아있는지 보는 지표들.

    파일이 '최근에 쓰였는지'만 보면 부족하다. 정산 스크립트가 매일 돌아
    파일 mtime은 새것이어도, 새 예측이 하나도 안 잡히면 루프는 죽은 것이다.
    실제로 2026-07에 그 상태였다(6월 818건 → 7월 21건, clean window 표본 0건).
    """
    ledger = _read_csv_rows("reports/virtual_prediction_ledger.csv")
    results = _read_csv_rows("reports/virtual_validation_results.csv")
    marker = _load_json("reports/clean_window_marker.json") or {}
    clean_start = str(marker.get("cleanWindowStart") or "")[:10]

    created = sorted(str(r.get("createdAt") or "")[:10] for r in ledger if r.get("createdAt"))
    admissible = [
        r for r in results
        if str(r.get("result") or r.get("status") or "").upper().strip() not in _NON_ADMISSIBLE
    ]
    clean_admissible = [
        r for r in admissible
        if clean_start and str(r.get("createdAt") or "")[:10] >= clean_start
    ]
    # 만기가 지났는데 아직 PENDING인 행 = 진짜 적체.
    # settle_pending_validations.py의 `unsettled`는 **만기 전 대기**까지 세므로
    # (settle_pending_validations.py:327 `due_date > TODAY` 분기) 그 값으로
    # 적체를 판단하면 캡처가 건강해질수록 숫자가 커져 영영 경고가 뜬다.
    today = NOW.strftime("%Y-%m-%d")
    overdue = [
        r for r in ledger
        if str(r.get("status") or "").upper() == "PENDING"
        and str(r.get("validationDueDate") or "")[:10]
        and str(r.get("validationDueDate") or "")[:10] <= today
    ]
    pending = [r for r in ledger if str(r.get("status") or "").upper() == "PENDING"]
    return {
        "pendingTotal": len(pending),
        "overduePending": len(overdue),
        "newestCapture": created[-1] if created else None,
        "ledgerRows": len(ledger),
        "cleanWindowStart": clean_start or None,
        "admissibleTotal": len(admissible),
        "cleanWindowAdmissible": len(clean_admissible),
    }


# mone_v65_api_stabilizer.PUBLIC_QUANT_POLICY["minLiveCalibrationEffN"]와 같은 값.
# 헬스체크는 stdlib만 쓰므로 백엔드를 import 하지 않고 상수를 복제한다.
# (백엔드 쪽을 바꾸면 여기도 같이 바꿔야 한다 — 테스트가 두 값의 일치를 검사한다.)
LIVE_GATE_MIN_EFFN = 30.0


def _live_gate_promotion_check() -> tuple:
    """라이브 실측 게이트가 실제로 승격됐는지. (name, status, detail, critical)

    자동화의 진짜 위험은 "안 도는 것"이 아니라 **돌았는지 아무도 모르는 것**이다.
    표본이 쌓이면 게이트 소스가 백테스트→라이브로 저절로 바뀌게 해뒀으니,
    지금 몇 개 셀이 그 기준을 넘겼는지 눈에 보여야 한다.
    """
    cal = _load_json("reports/live_calibration_kr.json")
    if not cal:
        return ("live_gate_promotion", "MISSING", "live_calibration_kr.json 없음", False)
    table = cal.get("table") or {}
    if not table:
        return ("live_gate_promotion", "WARN", "라이브 보정 테이블이 비어 있음", False)
    promoted = [k for k, v in table.items() if float((v or {}).get("effN") or 0) >= LIVE_GATE_MIN_EFFN]
    best = max((float((v or {}).get("effN") or 0) for v in table.values()), default=0.0)
    g = cal.get("global") or {}
    detail = (f"승격 {len(promoted)}/{len(table)}셀 (기준 effN≥{LIVE_GATE_MIN_EFFN:g}, "
              f"최대 {best:.1f}, global effN {float(g.get('effN') or 0):.1f} "
              f"승률 {g.get('winRate')}%)")
    if promoted:
        return ("live_gate_promotion", "OK", detail + f" — 활성: {', '.join(sorted(promoted)[:3])}", False)
    return ("live_gate_promotion", "WARN", detail + " — 아직 백테스트 소스 사용 중", False)


def _find_error_steps(obj, path="") -> list[str]:
    """상태 JSON에서 status가 ERROR/FAIL/실패인 노드 경로 수집 (조용한 실패)."""
    bad = []
    if isinstance(obj, dict):
        st = str(obj.get("status", "")).upper()
        if st in ("ERROR", "FAIL", "FAILED", "실패"):
            bad.append(f"{path or 'root'}={st}")
        for k, v in obj.items():
            bad += _find_error_steps(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += _find_error_steps(v, f"{path}[{i}]")
    return bad


def run(max_stale_days: float = 3.0) -> dict:
    checks: list[dict] = []

    def add(name, status, detail, critical, age=None):
        checks.append({"name": name, "status": status, "detail": detail,
                       "critical": critical, "ageDays": age})

    def check_date(name, dt_str, max_days, critical):
        dt = _parse_dt(dt_str) if dt_str else None
        age = _age_days(dt)
        if dt_str is None:
            add(name, "MISSING", "no source/date", critical)
        elif age is None:
            add(name, "MISSING", f"unparseable date: {dt_str}", critical)
        elif age > max_days:
            add(name, "STALE", f"{age}d old (>{max_days}d), asOf={dt_str}", critical, age)
        else:
            add(name, "OK", f"{age}d, asOf={dt_str}", critical, age)

    # 0) 측정 안정성 — 값이 흔들리면 나머지 신선도 검사가 의미를 잃는다.
    #    같은 예측에 답이 두 개면 "엣지가 얼마인가"에 답할 수 없다.
    ms = _load_json("reports/measurement_stability.json")
    if ms is None:
        add("measurement_stability", "MISSING",
            "no measurement_stability.json (scripts/check_measurement_stability.py)", False)
    else:
        idem = (ms.get("idempotency") or {})
        cross = (ms.get("crossLedger") or {})
        if not idem.get("ok"):
            add("measurement_stability", "ERROR",
                f"정산이 멱등하지 않다 — 판정 {idem.get('judgmentChanges')}행 재변경", True)
        elif not cross.get("ok"):
            add("measurement_stability", "WARN",
                f"두 원장 불일치 — 공통 {cross.get('sharedTrades')}건 중 "
                f"일치 {cross.get('agreeShare')} (기준 {cross.get('minAgreeShare')}), "
                f"평균차 {cross.get('meanDiffPp')}%p. 원인은 비용·창 설계 차이(사람 결정 필요)", False)
        else:
            add("measurement_stability", "OK",
                f"멱등 + 두 원장 일치 {cross.get('agreeShare')}", True)

    # 1) KR OHLCV 최신 봉 날짜
    check_date("kr_ohlcv", _newest_csv_date("data/market/ohlcv/kr_*_daily.csv"), max_stale_days + 1, True)
    # A fresh stock universe must not hide a stopped or NaN regime benchmark.
    for benchmark in ("KOSPI", "KOSDAQ"):
        state, day, detail = _benchmark_ohlcv_state(benchmark)
        if state != "OK":
            add(f"kr_{benchmark.lower()}_ohlcv", state, detail, True)
        else:
            check_date(f"kr_{benchmark.lower()}_ohlcv", day, max_stale_days + 1, True)
            checks[-1]["detail"] += f", {detail}"

    # 2) KR 추천 생성
    gen = _load_json("reports/kr_recommendation_gen_status.json")
    check_date("kr_recommendations", (gen or {}).get("generatedAt"), max_stale_days, True)
    # 3) 로컬/CI 수집기 스텝 에러(조용한 실패)
    lc = _load_json("reports/local_collector_status.json")
    cloud_reports = {
        "kis_live": _load_json("reports/kis_live_refresh_status.json"),
        "kr_close": _load_json("reports/kr_close_ohlcv_refresh_status.json"),
        "us_close": _load_json("reports/us_close_ohlcv_refresh_status.json"),
        "benchmarks": _load_json("reports/benchmark_fetch_status.json"),
    }
    available_cloud = {name: report for name, report in cloud_reports.items() if isinstance(report, dict)}
    cloud_errors = [
        f"{name}:{error}"
        for name, report in available_cloud.items()
        for error in _find_error_steps(report)
    ]
    if available_cloud and cloud_errors:
        add("collector_steps", "ERROR", "; ".join(cloud_errors[:5]), True)
    elif available_cloud:
        add("collector_steps", "OK", "cloud collector reports contain no error steps", True)
    elif lc is None:
        add("collector_steps", "MISSING", "no cloud or local collector status", True)
    else:
        errs = _find_error_steps(lc)
        if errs:
            add("collector_steps", "ERROR", "; ".join(errs[:5]), True)
        else:
            add("collector_steps", "OK", "local collector reports contain no error steps", True)

    collector_timestamps: list[tuple[datetime, str, str]] = []
    for source, report in available_cloud.items():
        candidates = [report.get("updatedAt"), report.get("completedAt"), report.get("startedAt")]
        markets = report.get("markets") if isinstance(report.get("markets"), dict) else {}
        candidates.extend(
            market_row.get("updatedAt")
            for market_row in markets.values()
            if isinstance(market_row, dict)
        )
        for raw in candidates:
            parsed = _parse_collector_dt(raw) if raw else None
            if parsed is not None:
                collector_timestamps.append((parsed, str(raw), f"cloud:{source}"))
    if isinstance(lc, dict):
        raw = lc.get("completedAt") or lc.get("startedAt")
        parsed = _parse_collector_dt(raw) if raw else None
        if parsed is not None:
            collector_timestamps.append((parsed, str(raw), "local"))

    if collector_timestamps:
        freshest_dt, freshest_raw, freshest_source = max(collector_timestamps, key=lambda row: row[0])
        check_date("collector_run", freshest_dt.isoformat(), max_stale_days, True)
        checks[-1]["detail"] += f", source={freshest_source}, reportedAt={freshest_raw}"
    else:
        add("collector_run", "MISSING", "no parseable cloud or local collector timestamp", True)

    if lc is None:
        add("local_collector_run", "WARN", "optional local collector status unavailable", False)
    else:
        local_errors = _find_error_steps(lc)
        local_raw = lc.get("completedAt") or lc.get("startedAt")
        local_dt = _parse_collector_dt(local_raw) if local_raw else None
        local_age = _age_days(local_dt)
        if local_errors:
            add("local_collector_run", "WARN", f"optional local collector errors: {'; '.join(local_errors[:3])}", False, local_age)
        elif local_age is None:
            add("local_collector_run", "WARN", "optional local collector date unavailable", False)
        elif local_age > max_stale_days:
            add("local_collector_run", "STALE", f"optional local collector {local_age}d old; cloud source remains authoritative", False, local_age)
        else:
            add("local_collector_run", "OK", f"optional local collector {local_age}d, asOf={local_raw}", False, local_age)
    # 4) VTJ 정산
    vtj = _load_json("reports/virtual_trade_journal_status.json")
    check_date("vtj_journal", (vtj or {}).get("lastRunAt"), max_stale_days, False)
    # 5) 라이브 보정
    lcal = _load_json("reports/live_calibration_kr.json")
    check_date("live_calibration", ((lcal or {}).get("params") or {}).get("asOf"), max_stale_days + 2, False)
    # 6) 전략 승률(정산)
    swr = _load_json("reports/strategy_win_rates.json")
    check_date("strategy_win_rates", (swr or {}).get("generatedAt") or (swr or {}).get("updatedAt"), max_stale_days, False)

    # 7) 예측 캡처 — 자가보정 루프의 입력. 여기가 멈추면 아무리 기다려도
    #    표본이 안 쌓이므로 "시간이 해결해준다"가 성립하지 않는다.
    #    주말(최대 2일)을 흡수하려고 +2일 여유를 준다.
    loop = _learning_loop_stats()
    check_date("prediction_capture", loop["newestCapture"], max_stale_days + 2, True)
    # 7-b) 캡처 **연속성**. 위 검사는 최신성만 보므로 중간 결손을 못 본다.
    add(*_capture_continuity_check())

    # 8) 정산 적체 — **만기가 지났는데도** PENDING인 건수만 센다.
    overdue = loop["overduePending"]
    pending = loop["pendingTotal"]
    detail = f"만기경과 미정산 {overdue}건 / 대기중 {pending}건"
    if overdue > 100:
        add("settlement_backlog", "ERROR", detail + " — 정산이 멈춘 것으로 보임", False)
    elif overdue > 20:
        add("settlement_backlog", "WARN", detail, False)
    else:
        add("settlement_backlog", "OK", detail, False)

    # 9) clean window 표본 축적 — 신뢰할 수 있는 구간에서 정산된 표본 수.
    #    엣지 판정의 분모라서, 0이면 화면의 승률이 전부 오염 구간 산출물이다.
    #    아직 쌓이는 중일 수 있으니 critical은 아니고 가시화가 목적.
    cw = loop["cleanWindowAdmissible"]
    detail = (f"clean window({loop['cleanWindowStart']}) 정산표본 {cw}건 "
              f"/ 전체 정산 {loop['admissibleTotal']}건 / 원장 {loop['ledgerRows']}행")
    if not loop["cleanWindowStart"]:
        add("clean_window_samples", "MISSING", "clean_window_marker.json 없음", False)
    elif cw <= 0:
        add("clean_window_samples", "ERROR", detail + " — 오염 구간 데이터만 서빙 중", False)
    elif cw < 30:
        add("clean_window_samples", "WARN", detail + " — 표본 부족(30건 미만)", False)
    else:
        add("clean_window_samples", "OK", detail, False)

    # 10) 자동 승격 현황 — "표본 쌓이면 자동으로 켜진다"가 실제로 켜졌는지.
    #     자동화의 위험은 안 도는 게 아니라 **돌았는지 아무도 모르는 것**이다.
    #     라이브 보정 셀 중 게이트 승격 기준(effN)을 넘긴 게 몇 개인지 보여준다.
    add(*_live_gate_promotion_check())

    crit_bad = [c for c in checks if c["critical"] and c["status"] != "OK"]
    # ERROR는 critical 여부와 무관하게 알람을 띄운다.
    #
    # 예전엔 critical 항목만 exit 1을 냈다. 그래서 clean_window_samples가
    # ERROR(=정산 표본 0건, 즉 화면 승률이 전부 오염 구간 산출물)여도 overall이
    # WARN에 그쳐 exit 0 → 텔레그램 알람이 안 갔다. 루프가 조용히 죽는 경로를
    # 막으려고 만든 검사가 정작 조용히 실패하는 구조였다.
    # STALE/WARN은 그대로 무알람(일시적 지연까지 알리면 알람이 무뎌진다).
    hard_bad = [c for c in checks if c["status"] in {"ERROR", "MISSING"}]
    overall = "ERROR" if (crit_bad or hard_bad) else (
        "WARN" if any(c["status"] != "OK" for c in checks) else "OK"
    )
    result = {
        "generatedAt": NOW.isoformat(),
        "overall": overall,
        "criticalFailures": len(crit_bad),
        "hardFailures": len(hard_bad),
        "maxStaleDays": max_stale_days,
        "checks": checks,
    }
    out = ROOT / "reports" / "data_freshness_status.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-stale-days", type=float, default=3.0)
    args = ap.parse_args()
    res = run(args.max_stale_days)
    print(f"=== 데이터 신선도: {res['overall']} (critical 실패 {res['criticalFailures']}건) ===")
    for c in res["checks"]:
        mark = {"OK": "[OK]", "WARN": "[!]", "STALE": "[X]", "ERROR": "[X]", "MISSING": "[?]"}.get(c["status"], "[?]")
        crit = "[critical]" if c["critical"] else ""
        print(f"  {mark} {c['name']:20s} {c['status']:8s} {crit:10s} {c['detail']}")
    # critical 노후/에러면 exit 1 → 워크플로가 알람 트리거
    sys.exit(1 if res["overall"] == "ERROR" else 0)
