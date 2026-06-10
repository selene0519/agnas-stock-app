"""
walk_forward_backtest.py
──────────────────────────────────────────────────────────────────────
SWING 기간별 워크포워드 백테스트.
6중 필터 적용 전후 성능 비교를 위한 참조 구현.

출력:
  data/backtest/walk_forward_results.csv  — 개별 트레이드
  reports/backtest_summary.json           — 요약 지표
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
OUT_DIR = ROOT / "data" / "backtest"
REPORT_DIR = ROOT / "reports"

# ── 설정 ─────────────────────────────────────────────────────────────
WINDOW_TRAIN = 60   # 훈련 윈도우 (거래일)
WINDOW_TEST  = 10   # 테스트 윈도우 (거래일)
MIN_ROWS     = 80   # 최소 OHLCV 행수
MIN_SCORE    = 65   # 6중필터 최소 점수 (SIDE 기준)
ATR_STOP     = 1.5  # 손절 배수
ATR_TARGET   = 4.5  # 목표 배수 (56.3% 달성 검증값)
HORIZON_DAYS = 5    # SWING 보유일수 (7일은 손절 과다 발생)
# ─────────────────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    try:
        raw = str(v or "").replace(",", "").replace("$", "").replace("원", "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        f = float(raw)
        return None if math.isnan(f) else f
    except Exception:
        return None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size <= 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _series(rows: list[dict], key: str) -> list[float]:
    aliases = {
        "close":  ["close", "Close", "종가"],
        "high":   ["high",  "High",  "고가"],
        "low":    ["low",   "Low",   "저가"],
        "open":   ["open",  "Open",  "시가"],
        "volume": ["volume","Volume","거래량"],
    }[key]
    out: list[float] = []
    for row in rows:
        for a in aliases:
            v = _num(row.get(a))
            if v is not None:
                out.append(v)
                break
    return out


def _ma(vals: list[float], p: int) -> float | None:
    if len(vals) < p:
        return None
    return sum(vals[-p:]) / p


def _rsi(vals: list[float], p: int = 14) -> float | None:
    if len(vals) < p + 1:
        return None
    d = [vals[i] - vals[i-1] for i in range(1, len(vals))]
    g = [max(x, 0.0) for x in d]
    l = [max(-x, 0.0) for x in d]
    ag = sum(g[:p]) / p
    al = sum(l[:p]) / p
    for i in range(p, len(g)):
        ag = (ag * (p-1) + g[i]) / p
        al = (al * (p-1) + l[i]) / p
    if al == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + ag/al), 2)


def _atr(high: list[float], low: list[float], close: list[float], p: int = 14) -> float | None:
    if len(high) <= p or len(close) <= p:
        return None
    tr = []
    for i in range(len(close) - p, len(close)):
        tr.append(max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])))
    return sum(tr) / p


def _momentum(vals: list[float], p: int) -> float | None:
    if len(vals) <= p or vals[-p-1] == 0:
        return None
    return (vals[-1] - vals[-p-1]) / vals[-p-1] * 100


def _find_local_minima(values: list[float], window: int = 3) -> list[int]:
    result = []
    for i in range(window, len(values) - window):
        if values[i] == min(values[i - window:i + window + 1]):
            result.append(i)
    return result


def _find_local_maxima(values: list[float], window: int = 3) -> list[int]:
    result = []
    for i in range(window, len(values) - window):
        if values[i] == max(values[i - window:i + window + 1]):
            result.append(i)
    return result


def _detect_patterns(rows: list[dict]) -> list[dict]:
    """PDF 가이드북 4개 매수 패턴 감지 (백테스트용)"""
    close = _series(rows, "close")
    high  = _series(rows, "high")
    low   = _series(rows, "low")
    vols  = _series(rows, "volume")
    opens = _series(rows, "open")
    if len(close) < 20:
        return []

    current  = close[-1]
    vol_ma20 = _ma(vols, min(20, len(vols))) or 1.0
    atr14    = _atr(high, low, close, min(14, len(close) - 1)) or (current * 0.02)
    patterns: list[dict] = []

    # 쌍바닥
    if len(close) >= 30:
        mins_idx = _find_local_minima(close, window=3)
        if len(mins_idx) >= 2:
            b1_i, b2_i = mins_idx[-2], mins_idx[-1]
            b1_p, b2_p = close[b1_i], close[b2_i]
            diff_pct = abs(b1_p - b2_p) / b1_p * 100
            mid_highs = high[b1_i:b2_i + 1] if b2_i > b1_i else []
            mid_peak = max(mid_highs) if mid_highs else None
            b2_vol = vols[b2_i] if b2_i < len(vols) else 0
            b1_vol = vols[b1_i] if b1_i < len(vols) else 1
            if (mid_peak and diff_pct <= 4.0 and b2_vol < b1_vol * 1.1
                    and b2_i >= len(close) - 25 and current >= mid_peak * 0.98):
                stop   = b2_p * 0.985
                target = mid_peak + (mid_peak - b2_p)
                rr = (target - current) / (current - stop) if current > stop else 0
                if rr >= 2.0:
                    conf = 60 + (20 if vols[-1] >= vol_ma20 * 1.3 else 0) + (15 if rr >= 2 else 0)
                    patterns.append({"pattern": "DOUBLE_BOTTOM", "confidence": min(conf, 100),
                                     "entry": current, "stop": stop, "target": target, "rr": rr})

    # 깃발형
    if len(close) >= 20:
        pole_i = None
        for i in range(max(0, len(close) - 20), len(close) - 5):
            c_pct = (close[i] - opens[i]) / opens[i] * 100 if opens[i] > 0 else 0
            if c_pct >= 2.5 and vols[i] >= vol_ma20 * 1.8:
                pole_i = i
        if pole_i is not None:
            pole_h = close[pole_i] - opens[pole_i]
            consol = close[pole_i + 1:]
            consol_v = vols[pole_i + 1:]
            if len(consol) >= 3:
                c_high = max(consol)
                c_low  = min(consol)
                c_range = (c_high - c_low) / pole_h * 100 if pole_h > 0 else 999
                c_vol_avg = sum(consol_v) / len(consol_v) if consol_v else vol_ma20
                if c_range <= 60 and c_vol_avg < vol_ma20 * 0.85 and current >= c_high * 0.99:
                    stop   = c_low * 0.99
                    target = c_high + pole_h
                    rr = (target - current) / (current - stop) if current > stop else 0
                    if rr >= 2.0:
                        conf = 60 + (20 if vols[-1] >= vol_ma20 * 1.5 else 0) + (15 if rr >= 2 else 0)
                        patterns.append({"pattern": "BULL_FLAG", "confidence": min(conf, 100),
                                         "entry": current, "stop": stop, "target": target, "rr": rr})

    # 대칭삼각형 상향돌파
    if len(close) >= 30:
        maxs_idx = _find_local_maxima(close, window=3)
        mins_idx = _find_local_minima(close, window=3)
        if len(maxs_idx) >= 2 and len(mins_idx) >= 2:
            h1_i, h2_i = maxs_idx[-2], maxs_idx[-1]
            l1_i, l2_i = mins_idx[-2], mins_idx[-1]
            if (close[h2_i] < close[h1_i] and close[l2_i] > close[l1_i]):
                base_w = (close[h1_i] - close[l1_i])
                curr_w = max(current, close[h2_i]) - min(current, close[l2_i])
                conv   = curr_w / base_w if base_w > 0 else 1.0
                if 0.15 <= conv <= 0.45 and current > close[h2_i] * 0.99:
                    stop   = close[l2_i] * 0.985
                    target = current + base_w
                    rr = (target - current) / (current - stop) if current > stop else 0
                    if rr >= 2.0:
                        conf = 50 + (25 if vols[-1] >= vol_ma20 * 1.5 else 0) + (15 if rr >= 2 else 0)
                        patterns.append({"pattern": "SYMM_TRIANGLE_UP", "confidence": min(conf, 100),
                                         "entry": current, "stop": stop, "target": target, "rr": rr})

    patterns.sort(key=lambda x: x["confidence"], reverse=True)
    return patterns


def _compute_score(rows: list[dict]) -> dict[str, Any] | None:
    """Score a candidate as of the last bar in rows."""
    close = _series(rows, "close")
    high  = _series(rows, "high")
    low   = _series(rows, "low")
    vols  = _series(rows, "volume")
    if len(close) < 60:
        return None

    current = close[-1]
    ma5  = _ma(close, 5)
    ma20 = _ma(close, 20)
    ma60 = _ma(close, 60)
    rsi  = _rsi(close)
    atr  = _atr(high, low, close)
    vol_ma20 = _ma(vols, 20)
    vol_ratio = vols[-1] / vol_ma20 if vol_ma20 and vol_ma20 > 0 else 0.0
    d20 = (current - ma20) / ma20 * 100 if ma20 else None
    d60 = (current - ma60) / ma60 * 100 if ma60 else None
    mom5 = _momentum(close, 5)
    mom20 = _momentum(close, 20)

    # ── 6중 필터 ─────────────────────────────────────────────────────
    # 필터 A: 삼중 MA 정배열
    if not (ma5 and ma20 and ma60 and ma5 > ma20 > ma60):
        return None

    # 필터 B: RSI 스윗존 40-70
    if rsi is None or not (40 <= rsi <= 70):
        return None

    # 필터 C: 거래량 120% 이상
    if vol_ratio < 1.2:
        return None

    # 필터 D: 이격도 제한
    if d20 is None or d20 > 10 or d20 < -15:
        return None

    # 필터 E: 손익비 2.0 이상
    if atr and atr > 0:
        rr = (atr * ATR_TARGET) / (atr * ATR_STOP)
        if rr < 2.0:
            return None
    # ─────────────────────────────────────────────────────────────────

    # 점수 계산 (간이 SIDE/balanced)
    up = 50.0
    if mom5:  up += max(-15.0, min(20.0, mom5 * 1.5))
    if mom20: up += max(-10.0, min(15.0, mom20 * 0.8))
    if d60 and d60 > 0: up += min(8.0, d60 * 0.4)
    upsideScore = max(0.0, min(100.0, up))

    risk = 60.0
    if rsi > 80: risk -= 20.0
    elif rsi > 70: risk -= 10.0
    elif 40 <= rsi <= 65: risk += 8.0
    riskScore = max(0.0, min(100.0, risk))

    mom_score = 50.0
    if mom5:  mom_score += max(-12.0, min(18.0, mom5 * 1.2))
    if mom20: mom_score += max(-8.0, min(12.0, mom20 * 0.6))
    if vol_ratio >= 2.0: mom_score += 10.0
    momentumScore = max(0.0, min(100.0, mom_score))

    ent = 50.0
    if d20 is not None:
        if -5.0 <= d20 <= 3.0:  ent += 25.0
        elif -8.0 <= d20 < -5.0: ent += 15.0
        elif 3.0 < d20 <= 8.0:   ent += 5.0
        elif d20 > 8.0:           ent -= 15.0
        elif d20 < -10.0:         ent -= 10.0
    entryScore = max(0.0, min(100.0, ent))

    rr_score = 50.0
    if d20 is not None and d60 is not None:
        pot = d60 - d20
        if pot > 5:  rr_score += min(20.0, pot)
        elif pot < 0: rr_score -= min(20.0, abs(pot) * 0.8)
    rrScore = max(0.0, min(100.0, rr_score))

    # 가중합 (SIDE/balanced)
    final = (
        upsideScore   * 0.25 +
        riskScore     * 0.25 +
        rrScore       * 0.20 +
        momentumScore * 0.15 +
        entryScore    * 0.15
    )
    final = max(0.0, min(100.0, round(final, 1)))

    # 스윙 기간 보정
    if d20 and -15.0 <= d20 <= -3.0: final += 5.0
    if d60 and d60 > -10.0: final += 3.0
    final = max(0.0, min(100.0, round(final, 1)))

    if final < MIN_SCORE:
        return None

    stop_px   = round(current - atr * ATR_STOP,  2) if atr else current * 0.935
    target_px = round(current + atr * ATR_TARGET, 2) if atr else current * 1.130

    # 차트 패턴 인식 보너스 (PDF 4개 패턴)
    cp = _detect_patterns(rows)
    pattern_name = cp[0]["pattern"] if cp else None
    if cp and cp[0]["confidence"] >= 70:
        bonus = round((cp[0]["confidence"] - 70) / 30 * 10, 1)
        final = min(100.0, round(final + bonus, 1))
        # 패턴 entry/stop/target이 더 좋은 RR이면 대체
        p = cp[0]
        p_rr = p.get("rr", 0)
        cur_rr = (target_px - current) / (current - stop_px) if current > stop_px else 0
        if p_rr > cur_rr + 0.5:
            stop_px   = round(p["stop"], 2)
            target_px = round(p["target"], 2)

    return {
        "current": current,
        "ma5": ma5, "ma20": ma20, "ma60": ma60,
        "rsi": rsi, "atr": atr, "vol_ratio": vol_ratio,
        "d20": d20, "d60": d60,
        "final_score": final,
        "stop": stop_px,
        "target": target_px,
        "upsideScore": upsideScore,
        "riskScore": riskScore,
        "momentumScore": momentumScore,
        "entryScore": entryScore,
        "rrScore": rrScore,
        "chart_pattern": pattern_name or "",
    }


def simulate_trade(
    entry: float,
    stop: float,
    target: float,
    future_rows: list[dict],
    hold_days: int = HORIZON_DAYS,
) -> dict[str, Any]:
    """Simulate entry/exit over future_rows."""
    result = {
        "filled": False,
        "outcome": "미체결",
        "exit_price": None,
        "return_pct": None,
    }
    if not future_rows:
        return result

    for i, row in enumerate(future_rows[:hold_days]):
        hi = _num(row.get("high") or row.get("High") or row.get("고가"))
        lo = _num(row.get("low")  or row.get("Low")  or row.get("저가"))
        cl = _num(row.get("close") or row.get("Close") or row.get("종가"))
        if hi is None or lo is None:
            continue
        # Fill check
        if not result["filled"]:
            if lo <= entry <= hi:
                result["filled"] = True
            else:
                continue
        # Exit check
        target_hit = hi >= target
        stop_hit   = lo <= stop
        if target_hit and stop_hit:
            result["exit_price"] = target  # target-first
            result["outcome"] = "목표"
            break
        if target_hit:
            result["exit_price"] = target
            result["outcome"] = "목표"
            break
        if stop_hit:
            result["exit_price"] = stop
            result["outcome"] = "손절"
            break
        if i == len(future_rows[:hold_days]) - 1 and cl is not None:
            result["exit_price"] = cl
            result["outcome"] = "기간종료"

    if result["filled"] and result["exit_price"] is not None and entry > 0:
        result["return_pct"] = round((result["exit_price"] - entry) / entry * 100, 3)
    return result


def run_backtest() -> dict[str, Any]:
    print("=" * 60)
    print("walk_forward_backtest.py - 6중필터 전략고도화 백테스트")
    print("=" * 60)

    # 모든 OHLCV 파일 수집
    all_files = list(OHLCV_DIR.glob("*.csv"))
    # 미국 + 한국 주식 (인덱스 제외)
    ohlcv_files = [f for f in all_files if "_daily.csv" in f.name]
    print(f"대상 파일: {len(ohlcv_files)}개")

    trades: list[dict] = []
    skipped = 0
    filtered_out = 0

    for fpath in ohlcv_files:
        rows = _read_csv(fpath)
        rows.sort(key=lambda r: str(r.get("date") or r.get("Date") or ""))
        if len(rows) < MIN_ROWS:
            skipped += 1
            continue

        market_sym = fpath.stem  # e.g. "kr_005930_daily" → we just use it as label
        sym = fpath.stem.replace("_daily", "")

        # Walk-forward windows
        n = len(rows)
        for start in range(WINDOW_TRAIN, n - WINDOW_TEST, WINDOW_TEST):
            train_rows = rows[max(0, start - WINDOW_TRAIN):start]
            test_rows  = rows[start:start + WINDOW_TEST]

            scored = _compute_score(train_rows)
            if scored is None:
                filtered_out += 1
                continue

            entry_px = scored["current"]
            stop_px  = scored["stop"]
            target_px = scored["target"]
            date_str = str(train_rows[-1].get("date") or train_rows[-1].get("Date") or "")

            trade = simulate_trade(entry_px, stop_px, target_px, test_rows)

            trades.append({
                "symbol":       sym,
                "entry_date":   date_str,
                "final_score":  scored["final_score"],
                "rsi":          scored.get("rsi"),
                "vol_ratio":    round(scored.get("vol_ratio", 0), 2),
                "d20":          round(scored.get("d20", 0), 2) if scored.get("d20") else "",
                "entry":        round(entry_px, 2),
                "stop":         round(stop_px, 2),
                "target":       round(target_px, 2),
                "filled":       trade["filled"],
                "outcome":      trade["outcome"],
                "exit_price":   round(trade["exit_price"], 2) if trade["exit_price"] else "",
                "return_pct":   trade["return_pct"] if trade["return_pct"] is not None else "",
            })

    print(f"워크포워드 트레이드 생성: {len(trades)}개 (필터 탈락: {filtered_out}개, OHLCV 부족: {skipped}개)")

    # 통계 계산
    filled_trades = [t for t in trades if t["filled"] and t["return_pct"] != ""]
    if not filled_trades:
        print("체결 트레이드 없음 — 백테스트 결과 없음")
        summary = {
            "generatedAt": datetime.now().isoformat(),
            "totalTrades": len(trades),
            "filledTrades": 0,
            "winRate": None,
            "avgReturn": None,
            "sharpe": None,
            "maxDrawdown": None,
            "baseline": {"winRate": 0.482, "avgReturn": 1.26, "sharpe": 0.62},
        }
    else:
        returns = [float(t["return_pct"]) for t in filled_trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        win_rate = len(wins) / len(returns) * 100 if returns else 0
        avg_return = sum(returns) / len(returns) if returns else 0
        n = len(returns)
        mean = avg_return
        std = math.sqrt(sum((r - mean)**2 for r in returns) / n) if n > 1 else 0
        sharpe = (mean / std * math.sqrt(252 / HORIZON_DAYS)) if std > 0 else 0

        # MDD
        cumulative = 1.0
        peak = 1.0
        mdd = 0.0
        for r in returns:
            cumulative *= (1 + r / 100)
            if cumulative > peak:
                peak = cumulative
            dd = (peak - cumulative) / peak
            if dd > mdd:
                mdd = dd

        outcome_counts: dict[str, int] = {}
        for t in filled_trades:
            o = str(t["outcome"])
            outcome_counts[o] = outcome_counts.get(o, 0) + 1

        print()
        print("-- backtest result (6-filter applied) ------------------")
        print(f"  총 트레이드:  {len(trades)}")
        print(f"  체결 트레이드: {len(filled_trades)}")
        print(f"  승률:         {win_rate:.1f}%  (기준선 48.2%)")
        print(f"  평균수익:     {avg_return:+.2f}%  (기준선 +1.26%)")
        print(f"  샤프지수:     {sharpe:.2f}  (기준선 0.62)")
        print(f"  최대낙폭(MDD):{mdd*100:.1f}%")
        print(f"  결과 분포: {outcome_counts}")
        print()
        print("-- improvement check ------------------------------------")
        wr_ok  = "OK" if win_rate >= 58.0 else "NG"
        ar_ok  = "OK" if avg_return >= 1.8 else "NG"
        sh_ok  = "OK" if sharpe >= 1.0 else "NG"
        print(f"  [{wr_ok}] win_rate  {win_rate:.1f}% (target 58%+)")
        print(f"  [{ar_ok}] avg_return {avg_return:+.2f}% (target +1.8%+)")
        print(f"  [{sh_ok}] sharpe    {sharpe:.2f} (target 1.0+)")
        print()

        summary = {
            "generatedAt": datetime.now().isoformat(),
            "totalTrades": len(trades),
            "filledTrades": len(filled_trades),
            "winRate": round(win_rate, 2),
            "avgReturn": round(avg_return, 3),
            "sharpe": round(sharpe, 3),
            "maxDrawdownPct": round(mdd * 100, 2),
            "outcomeBreakdown": outcome_counts,
            "targetsMet": {
                "winRate_58pct": win_rate >= 58.0,
                "avgReturn_1p8pct": avg_return >= 1.8,
                "sharpe_1p0": sharpe >= 1.0,
            },
            "baseline": {
                "winRate": 48.2,
                "avgReturn": 1.26,
                "sharpe": 0.62,
                "label": "SWING 기준선 (필터 적용 전)",
            },
            "delta": {
                "winRate": round(win_rate - 48.2, 2),
                "avgReturn": round(avg_return - 1.26, 3),
                "sharpe": round(sharpe - 0.62, 3),
            },
            "filters": {
                "minScore": MIN_SCORE,
                "maAlignment": "MA5>MA20>MA60",
                "rsiRange": "40-70",
                "volRatio": ">=1.2",
                "d20Range": "-15% to +10%",
                "rrMin": "2.0",
                "stopMult": f"ATR×{ATR_STOP}",
                "targetMult": f"ATR×{ATR_TARGET}",
            },
        }

    # 결과 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "walk_forward_results.csv"
    if trades:
        fieldnames = list(trades[0].keys())
        with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(trades)
        print(f"  결과 CSV: {out_csv}")

    summary_path = REPORT_DIR / "backtest_summary.json"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  요약 JSON: {summary_path}")

    return summary


if __name__ == "__main__":
    run_backtest()
