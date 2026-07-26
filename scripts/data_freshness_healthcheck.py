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
import sys
from datetime import datetime, timezone
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
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


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
    return {
        "newestCapture": created[-1] if created else None,
        "ledgerRows": len(ledger),
        "cleanWindowStart": clean_start or None,
        "admissibleTotal": len(admissible),
        "cleanWindowAdmissible": len(clean_admissible),
    }


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

    # 1) KR OHLCV 최신 봉 날짜
    check_date("kr_ohlcv", _newest_csv_date("data/market/ohlcv/kr_*_daily.csv"), max_stale_days + 1, True)
    # 2) KR 추천 생성
    gen = _load_json("reports/kr_recommendation_gen_status.json")
    check_date("kr_recommendations", (gen or {}).get("generatedAt"), max_stale_days, True)
    # 3) 로컬/CI 수집기 스텝 에러(조용한 실패)
    lc = _load_json("reports/local_collector_status.json")
    if lc is None:
        add("collector_steps", "MISSING", "no local_collector_status.json", False)
    else:
        errs = _find_error_steps(lc)
        if errs:
            add("collector_steps", "ERROR", "; ".join(errs[:5]), True)
        else:
            add("collector_steps", "OK", "no error steps", True)
        check_date("collector_run", lc.get("completedAt") or lc.get("startedAt"), max_stale_days, True)
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

    # 8) 정산 적체 — 만기가 지났는데 정산이 안 된 건수.
    pss = _load_json("reports/pending_settlement_status.json") or {}
    unsettled = int(pss.get("unsettled") or 0)
    if unsettled > 200:
        add("settlement_backlog", "ERROR", f"미정산 {unsettled}건 (>200)", False)
    elif unsettled > 50:
        add("settlement_backlog", "WARN", f"미정산 {unsettled}건 (>50)", False)
    else:
        add("settlement_backlog", "OK", f"미정산 {unsettled}건", False)

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

    crit_bad = [c for c in checks if c["critical"] and c["status"] != "OK"]
    overall = "ERROR" if crit_bad else ("WARN" if any(c["status"] != "OK" for c in checks) else "OK")
    result = {
        "generatedAt": NOW.isoformat(),
        "overall": overall,
        "criticalFailures": len(crit_bad),
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
