#!/usr/bin/env python3
"""
추천 예측 원장 캡처 — 자가보정 루프의 입력을 시간 구동으로 전환.

배경(왜 이 스크립트가 필요한가):
  `_record_virtual_ledger`는 `mone_v65_api_stabilizer._recommendations_payload`
  안에서만 호출된다. 즉 `reports/virtual_prediction_ledger.csv`는 **누군가
  /api/final/recommendations를 때려야만** 늘어나는 요청 시간 부작용이었다.
  배포 백엔드(Render)는 디스크가 휘발성이고 git push도 하지 않으므로, 원장에
  실제로 남은 행은 사용자가 로컬 백엔드를 띄운 날뿐이다.

  결과: 2026-06에 818건이 쌓였지만 2026-07은 21건(전부 PENDING),
  clean window(2026-07-10~) 안의 정산 가능 표본은 **0건**.
  "시간이 지나 표본이 쌓이면 자동 보정된다"는 전제가 깨져 있었다.

이 스크립트는 캡처를 CI 스케줄에서 결정론적으로 돌려 그 전제를 복구한다.
서빙 경로(`_recommendations_payload`)를 그대로 호출하므로 원장에 남는 내용은
앱이 실제로 내보내는 추천과 동일하다 — 캡처용 산식을 따로 만들지 않는다.
(이 레포는 이미 손절가 3중 계산 같은 중복 구현으로 고생한 이력이 있다.)

멱등: predictionId = market|symbol|mode|horizon|오늘날짜 이고
`_record_virtual_ledger`가 setdefault로 병합하므로 하루에 여러 번 돌려도 안전.

실행: python scripts/capture_recommendation_predictions.py [--market kr|us|all]
쓰기: reports/virtual_prediction_ledger.csv
      reports/recommendation_capture_status.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Windows 콘솔 기본 코드페이지(cp949)는 em-dash 등을 못 찍고 UnicodeEncodeError로
# 죽는다. 로그 한 줄 때문에 캡처 결과가 유실되지 않게 치환 출력으로 낮춘다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"
for _p in (str(ROOT), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")
LEDGER = ROOT / "reports" / "virtual_prediction_ledger.csv"
STATUS_JSON = ROOT / "reports" / "recommendation_capture_status.json"
OHLCV_GLOB = "data/market/ohlcv/kr_*_daily.csv"
# 장 마감 데이터가 이보다 낡으면 캡처하지 않는다. 휴장 연휴(최대 3영업일)를 넘기면
# 수집기가 죽은 것으로 보고 멈춘다 — 낡은 가격으로 예측을 만들어 원장에 남기면
# 표본이 오염되고, 그 오염은 나중에 되돌릴 수 없다.
MAX_QUOTE_STALE_DAYS = 4


def _newest_ohlcv_date() -> str | None:
    """대표 OHLCV 파일 몇 개의 마지막 봉 날짜 중 최신값."""
    import csv

    files = sorted(ROOT.glob(OHLCV_GLOB))
    if not files:
        return None
    newest = None
    for p in files[:5] + files[-5:]:
        try:
            with p.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                d = rows[-1].get("date") or rows[-1].get("Date")
                if d and (newest is None or str(d) > newest):
                    newest = str(d)[:10]
        except Exception:
            continue
    return newest


def _capture_precondition(today: datetime) -> tuple[bool, str]:
    """캡처해도 되는 날인지 판정. (허용여부, 사유)"""
    if today.weekday() >= 5:
        return False, f"WEEKEND ({today.strftime('%A')}) — 직전 거래일 가격이 재캡처되어 표본이 중복된다"
    newest = _newest_ohlcv_date()
    if not newest:
        return False, "NO_OHLCV — data/market/ohlcv 비어 있음"
    try:
        age = (today.date() - datetime.fromisoformat(newest).date()).days
    except Exception:
        return False, f"UNPARSEABLE_OHLCV_DATE ({newest})"
    if age > MAX_QUOTE_STALE_DAYS:
        return False, f"STALE_OHLCV — 최신 봉 {newest} ({age}일 전) > {MAX_QUOTE_STALE_DAYS}일"
    return True, f"OK — 최신 봉 {newest} ({age}일 전)"


def _ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    import csv

    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with LEDGER.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _count_today(rows: list[dict], today: str) -> int:
    return sum(1 for r in rows if str(r.get("createdAt") or "")[:10] == today)


def run(markets: tuple[str, ...], force: bool = False) -> dict:
    now = datetime.now()
    today = now.date().isoformat()
    allowed, reason = _capture_precondition(now)
    if not allowed and not force:
        result = {
            "runAt": now.isoformat(),
            "status": "SKIPPED",
            "skipReason": reason,
            "markets": list(markets),
            "rowsAdded": 0,
            "capturedToday": _count_today(_ledger_rows(), today),
        }
        STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
        STATUS_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    from app.engine import mone_v65_api_stabilizer as stab

    before = _ledger_rows()
    before_total, before_today = len(before), _count_today(before, today)

    steps: list[dict] = []
    for market in markets:
        for mode in MODES:
            for horizon in HORIZONS:
                label = f"{market}_{mode}_{horizon}"
                try:
                    # 서빙 경로 그대로 호출 → 내부에서 _record_virtual_ledger 실행.
                    payload = stab._recommendations_payload(
                        market, mode, horizon, cash=0.0, limit=50, watch_only=False
                    )
                    items = payload.get("items") or []
                    steps.append({"combo": label, "status": "OK", "items": len(items)})
                except Exception as exc:  # 한 조합 실패가 나머지를 막지 않게
                    steps.append({"combo": label, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})

    after = _ledger_rows()
    after_total, after_today = len(after), _count_today(after, today)
    errors = [s for s in steps if s["status"] == "ERROR"]

    result = {
        "runAt": now.isoformat(),
        # 캡처가 0건이면 그날 후보가 없었던 건지 파이프라인이 죽은 건지 구분해야
        # 하므로 조합별 결과를 그대로 남긴다.
        "status": "ERROR" if errors and not (after_total - before_total) else "OK",
        "precondition": reason,
        "forced": force,
        "markets": list(markets),
        "ledgerRowsBefore": before_total,
        "ledgerRowsAfter": after_total,
        "rowsAdded": after_total - before_total,
        "capturedToday": after_today,
        "capturedTodayBefore": before_today,
        "comboCount": len(steps),
        "errorCount": len(errors),
        "steps": steps,
    }
    STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="all", choices=["kr", "us", "all"])
    ap.add_argument("--force", action="store_true",
                    help="주말/노후 데이터 가드를 무시하고 캡처(테스트용). 표본이 오염되므로 상시 사용 금지.")
    args = ap.parse_args()
    markets = ("kr", "us") if args.market == "all" else (args.market,)

    res = run(markets, force=args.force)
    print(f"=== 추천 예측 캡처: {res['status']} ===")
    if res["status"] == "SKIPPED":
        print(f"  건너뜀: {res['skipReason']}")
        print(f"  오늘 캡처 누계: {res['capturedToday']}건")
        return 0
    print(f"  전제: {res['precondition']}")
    print(f"  원장 {res['ledgerRowsBefore']} → {res['ledgerRowsAfter']} (+{res['rowsAdded']})")
    print(f"  오늘({datetime.now().date().isoformat()}) 캡처 누계: {res['capturedToday']}건")
    if res["errorCount"]:
        print(f"  조합 실패 {res['errorCount']}/{res['comboCount']}건:")
        for s in res["steps"]:
            if s["status"] == "ERROR":
                print(f"    [X] {s['combo']}: {s['error'][:160]}")
    return 1 if res["status"] == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
