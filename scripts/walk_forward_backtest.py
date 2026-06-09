"""
MONE 워크포워드 백테스트
- 과거 날짜별로 추천 로직을 실행하여 실제 성과 검증
- 출력: data/backtest/walk_forward_results.csv + 통계 요약
"""
import sys
import csv
import math
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Optional

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "mone-web-app" / "backend"))

OHLCV_DIR = REPO_ROOT / "data" / "market" / "ohlcv"
RESULT_DIR = REPO_ROOT / "data" / "backtest"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# 백테스트 설정
COST_KR_PCT = 0.09   # 수수료 0.03% + 슬리피지 0.06%
MIN_BARS    = 60     # 분석에 필요한 최소 봉 수
TEST_HORIZONS = {"short": 5, "swing": 10, "mid": 20}

def load_ohlcv(symbol: str) -> list[dict]:
    path = OHLCV_DIR / f"kr_{symbol}_daily.csv"
    if not path.exists():
        return []
    rows = []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(path, encoding=enc) as f:
                for r in csv.DictReader(f):
                    d = str(r.get("date") or r.get("Date", "")).strip()[:10]
                    try:
                        rows.append({
                            "date":   d,
                            "open":   float(r.get("open")   or r.get("Open")   or 0),
                            "high":   float(r.get("high")   or r.get("High")   or 0),
                            "low":    float(r.get("low")    or r.get("Low")    or 0),
                            "close":  float(r.get("close")  or r.get("Close")  or 0),
                            "volume": float(r.get("volume") or r.get("Volume") or 0),
                        })
                    except Exception:
                        continue
            rows.sort(key=lambda x: x["date"])
            return rows
        except Exception:
            continue
    return []

def score_as_of(rows: list[dict]) -> Optional[dict]:
    """quant_scanner 핵심 로직을 직접 구현 (임포트 불필요한 독립 버전)"""
    if len(rows) < MIN_BARS:
        return None
    closes = [r["close"] for r in rows]
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    vols   = [r["volume"] for r in rows]

    def ma(vs, n):
        return sum(vs[-n:]) / n if len(vs) >= n else None

    def stddev(vs, n):
        if len(vs) < n:
            return 0
        sl = vs[-n:]
        avg = sum(sl) / n
        return math.sqrt(sum((x - avg) ** 2 for x in sl) / n)  # 모집단σ

    # Wilder's RSI
    def rsi_wilder(vs, p=14):
        if len(vs) < p + 1:
            return None
        deltas = [vs[i] - vs[i - 1] for i in range(1, len(vs))]
        gains  = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        ag = sum(gains[:p]) / p
        al = sum(losses[:p]) / p
        for i in range(p, len(gains)):
            ag = (ag * (p - 1) + gains[i]) / p
            al = (al * (p - 1) + losses[i]) / p
        return 100.0 if al == 0 else round(100 - (100 / (1 + ag / al)), 2)

    # ATR
    def atr(rows, p=14):
        trs = []
        for i in range(1, len(rows)):
            h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) < p:
            return None
        return sum(trs[-p:]) / p

    ma5  = ma(closes, 5)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60)
    if not (ma5 and ma20):
        return None
    current = closes[-1]
    rsi = rsi_wilder(closes)
    atr_val = atr(rows)
    if not atr_val:
        return None

    # 볼린저
    bb_mid = ma20
    bb_std = stddev(closes, 20)
    bb_upper = bb_mid + bb_std * 2
    bb_lower = bb_mid - bb_std * 2

    # 이격도
    d5  = (current - ma5)  / ma5  * 100 if ma5  else 0
    d20 = (current - ma20) / ma20 * 100 if ma20 else 0

    # 거래량 평균 5일
    vol_ma5 = ma(vols, 5) or 1
    vol_ratio = vols[-1] / vol_ma5

    # 진입/손절/목표 (swing 기준)
    entry  = round(current * 1.001, 0)         # 현재가 근처
    stop   = round(current - atr_val * 2, 0)   # ATR×2 손절
    target = round(current + atr_val * 4, 0)   # ATR×4 목표 (RR=2.0)
    rr = (target - entry) / (entry - stop) if entry > stop else 0

    # 스코어링
    upside_score   = min(100, max(0, 50 + d20 * -2))  # 이격 적을수록 좋음
    rsi_score      = (100 - rsi) if rsi else 50
    momentum_score = min(100, vol_ratio * 30)
    rr_score       = min(100, rr * 40)
    entry_score    = 50 + max(-30, min(30, d20 * -1))

    final_score = (
        upside_score   * 0.25 +
        rsi_score      * 0.25 +
        rr_score       * 0.20 +
        momentum_score * 0.15 +
        entry_score    * 0.15
    )

    # 필터: RSI 과열, 데이터 부족, RR 미달
    if rsi and rsi > 80:
        return None
    if rr < 1.5:
        return None
    if final_score < 50:
        return None

    return {
        "finalScore":   round(final_score, 1),
        "entry":        entry,
        "stop":         stop,
        "target":       target,
        "rr":           round(rr, 2),
        "rsi":          rsi,
        "ma5":          ma5,
        "ma20":         ma20,
        "ma60":         ma60,
        "currentPrice": current,
    }

def check_outcome(rows: list[dict], from_idx: int, entry: float, stop: float, target: float, horizon_days: int) -> dict:
    """from_idx 이후 horizon_days 내에 entry 터치 → 결과 확인"""
    future = rows[from_idx:]
    if len(future) < 3:
        return {"result": "insufficient_data"}

    # 엔트리 체크 (3일 내 저가가 entry 이하 터치)
    entry_touched = any(r["low"] <= entry * 1.005 for r in future[:3])
    if not entry_touched:
        return {"result": "entry_not_touched"}

    # 결과 체크
    period = future[:horizon_days]
    target_day = next((i for i, r in enumerate(period) if r["high"] >= target), None)
    stop_day   = next((i for i, r in enumerate(period) if r["low"] <= stop),   None)

    if target_day is not None and stop_day is not None:
        # 동시 도달 — 먼저 도달한 쪽 (같으면 손절 우선, 보수적)
        if target_day < stop_day:
            result = "win"
            exit_price = target
        else:
            result = "loss"
            exit_price = stop
    elif target_day is not None:
        result = "win"
        exit_price = target
    elif stop_day is not None:
        result = "loss"
        exit_price = stop
    else:
        # 기간 내 미결 — 최종 종가
        exit_price = period[-1]["close"] if period else entry
        ret = (exit_price - entry) / entry * 100 - COST_KR_PCT
        result = "win" if ret > 0 else "hold_loss"

    gross = (exit_price - entry) / entry * 100
    net   = gross - COST_KR_PCT
    return {
        "result":         result,
        "exitPrice":      exit_price,
        "grossReturnPct": round(gross, 3),
        "netReturnPct":   round(net, 3),
    }

def get_test_dates(start_days_ago=120, interval_days=5) -> list[str]:
    """테스트 날짜 목록 (5일 간격, 과거 120일)"""
    today = date.today()
    dates = []
    d = today - timedelta(days=start_days_ago)
    while d < today - timedelta(days=21):  # 미래 검증 가능 날짜만
        if d.weekday() < 5:  # 평일만
            dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=interval_days)
    return dates

def get_symbols() -> list[str]:
    """sector_map_kr.csv에서 심볼"""
    import csv as _csv
    path = REPO_ROOT / "data" / "sector_map_kr.csv"
    syms = []
    if path.exists():
        with open(path, encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                s = str(r.get("symbol", "")).strip()
                if s:
                    syms.append(s)
    return syms[:80]

def main():
    symbols    = get_symbols()
    test_dates = get_test_dates(start_days_ago=120, interval_days=5)
    print(f"백테스트: {len(symbols)}종목 × {len(test_dates)}날짜 × {len(TEST_HORIZONS)}호라이즌")

    # OHLCV 사전 로드
    ohlcv_all: dict[str, list[dict]] = {}
    for sym in symbols:
        rows = load_ohlcv(sym)
        if rows:
            ohlcv_all[sym] = rows

    print(f"OHLCV 로드 완료: {len(ohlcv_all)}종목")

    all_results = []
    for test_date in test_dates:
        for sym, rows in ohlcv_all.items():
            # test_date 이전 데이터만 사용
            hist = [r for r in rows if r["date"] <= test_date]
            if len(hist) < MIN_BARS:
                continue

            score = score_as_of(hist)
            if not score:
                continue

            # test_date 이후 데이터로 결과 확인
            from_idx = len(hist)  # 전체 rows에서 test_date 이후 시작점

            for horizon_name, horizon_days in TEST_HORIZONS.items():
                outcome = check_outcome(
                    rows, from_idx,
                    score["entry"], score["stop"], score["target"], horizon_days
                )
                all_results.append({
                    "test_date":  test_date,
                    "symbol":     sym,
                    "horizon":    horizon_name,
                    "finalScore": score["finalScore"],
                    "entry":      score["entry"],
                    "stop":       score["stop"],
                    "target":     score["target"],
                    "rr":         score["rr"],
                    "rsi":        score["rsi"],
                    **outcome,
                })

    print(f"\n총 {len(all_results)}건 검증 결과")

    # 저장
    out_path = RESULT_DIR / "walk_forward_results.csv"
    if all_results:
        import csv as _csv_mod
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv_mod.DictWriter(f, fieldnames=list(all_results[0].keys()))
            w.writeheader()
            w.writerows(all_results)
        print(f"결과 저장: {out_path}")

    # 통계 계산
    print_stats(all_results)

def print_stats(results: list[dict]):
    from collections import defaultdict
    by_horizon = defaultdict(list)
    for r in results:
        if r.get("result") in ("win", "loss", "hold_loss"):
            by_horizon[r["horizon"]].append(r)

    print("\n" + "=" * 60)
    print("워크포워드 백테스트 통계 (수수료 0.09% 적용)")
    print("=" * 60)
    for horizon, rows in sorted(by_horizon.items()):
        wins   = [r for r in rows if r["result"] == "win"]
        losses = [r for r in rows if r["result"] in ("loss", "hold_loss")]
        total  = len(wins) + len(losses)
        if total == 0:
            continue

        win_rate = len(wins) / total * 100
        rets = [float(r.get("netReturnPct", 0)) for r in rows if r.get("netReturnPct", "") != ""]
        avg_ret = sum(rets) / len(rets) if rets else 0

        # 샤프지수 (무위험이자율 0% 가정)
        horizon_days = TEST_HORIZONS.get(horizon, 10)
        if len(rets) > 1:
            std_r = math.sqrt(sum((r - avg_ret) ** 2 for r in rets) / (len(rets) - 1))
            sharpe = (avg_ret / std_r * math.sqrt(252 / horizon_days)) if std_r > 0 else 0
        else:
            sharpe = 0

        max_dd = min(rets) if rets else 0

        print(f"\n[{horizon.upper()}] n={total}")
        print(f"  승률:       {win_rate:.1f}%")
        print(f"  평균수익률: {avg_ret:+.2f}%")
        print(f"  샤프지수:   {sharpe:.2f}")
        print(f"  최대손실:   {max_dd:+.2f}%")
        print(f"  평균score:  {sum(float(r.get('finalScore', 0)) for r in rows) / len(rows):.1f}")

    # 전체 통계
    all_exec = [r for r in results if r.get("result") in ("win", "loss", "hold_loss")]
    if all_exec:
        all_rets = [float(r.get("netReturnPct", 0)) for r in all_exec]
        print(f"\n[전체] n={len(all_exec)}")
        print(f"  승률:     {sum(1 for r in all_exec if r['result'] == 'win') / len(all_exec) * 100:.1f}%")
        print(f"  평균수익: {sum(all_rets) / len(all_rets):+.2f}%")
        print(f"  검증 날짜 범위: {min(r['test_date'] for r in results)} ~ {max(r['test_date'] for r in results)}")

if __name__ == "__main__":
    main()
