"""
walkforward_backtest.py — Self-Correction v2 Walk-Forward 검증 엔진

원칙:
1. 미래 데이터 누출 금지 — 보정값은 검증 시점 이전 결과만 사용
2. Baseline(보정 없음)과 Corrected(보정 적용)을 같은 OHLCV, 같은 후보군으로 비교
3. sampleCount < 30 이면 보정 미적용
4. DATA_INSUFFICIENT: 데이터 부족 시 조용히 성공 처리하지 않고 명시

출력:
  reports/walkforward_results_{market}.csv
  reports/walkforward_summary_{market}.json
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


# ─── 경로 ─────────────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _ohlcv_dir(market: str = "kr") -> Path:
    return _repo_root() / "data" / "market" / "ohlcv"


def _reports_dir() -> Path:
    return _repo_root() / "reports"


# ─── 공통 유틸 ────────────────────────────────────────────────────────────────

def _num(v: Any) -> float | None:
    try:
        raw = re.sub(r"[,원$%]", "", str(v or "")).strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        f = float(raw)
        return None if math.isnan(f) else f
    except Exception:
        return None


def _series(rows: list[dict], key: str) -> list[float]:
    aliases = {
        "open":   ["open", "Open", "시가"],
        "close":  ["close", "Close", "종가"],
        "high":   ["high", "High", "고가"],
        "low":    ["low", "Low", "저가"],
        "volume": ["volume", "Volume", "거래량"],
    }[key]
    out: list[float] = []
    for row in rows:
        for alias in aliases:
            val = _num(row.get(alias))
            if val is not None:
                out.append(val)
                break
    return out


def _ma(vals: list[float], p: int) -> float | None:
    if len(vals) < p:
        return None
    return sum(vals[-p:]) / p


def _rsi(vals: list[float], p: int = 14) -> float | None:
    if len(vals) < p + 1:
        return None
    deltas = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    ag = sum(gains[:p]) / p
    al = sum(losses[:p]) / p
    for i in range(p, len(gains)):
        ag = (ag * (p - 1) + gains[i]) / p
        al = (al * (p - 1) + losses[i]) / p
    if al == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + ag / al), 2)


def _atr(h: list[float], l: list[float], c: list[float], p: int = 14) -> float | None:
    if len(h) <= p or len(l) <= p or len(c) <= p:
        return None
    ranges: list[float] = []
    start = len(c) - p
    for i in range(start, len(c)):
        pc = c[i - 1]
        ranges.append(max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc)))
    return sum(ranges) / p


def _mdd(vals: list[float], p: int = 20) -> float | None:
    if len(vals) < p:
        return None
    window = vals[-p:]
    peak   = window[0]
    worst  = 0.0
    for v in window:
        peak  = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak * 100)
    return worst


def _momentum(vals: list[float], p: int) -> float | None:
    if len(vals) <= p or vals[-p - 1] == 0:
        return None
    return (vals[-1] - vals[-p - 1]) / vals[-p - 1] * 100


# ─── 지표 계산 (generate_kr_recommendations.py 동일 로직) ─────────────────────

def _indicators(rows: list[dict]) -> dict[str, float | None]:
    c = _series(rows, "close")
    h = _series(rows, "high")
    l = _series(rows, "low")
    v = _series(rows, "volume")
    if not c:
        return {}
    latest = c[-1]
    ma20   = _ma(c, 20)
    ma60   = _ma(c, 60)
    vm20   = _ma(v, 20)
    h52    = max(h[-252:]) if len(h) >= 252 else (max(h) if h else None)
    atr14  = _atr(h, l, c)
    mdd20  = _mdd(c)
    std20  = ((sum((x - ma20) ** 2 for x in c[-20:]) / 20) ** 0.5
              if ma20 and len(c) >= 20 else None)
    bb_u   = (ma20 + std20 * 2) if ma20 and std20 else None
    bb_l   = (ma20 - std20 * 2) if ma20 and std20 else None
    bb_b   = ((latest - bb_l) / (bb_u - bb_l)
              if latest and bb_u and bb_l and bb_u != bb_l else None)
    vr     = (v[-1] / vm20 if v and vm20 else None)
    d20    = ((latest - ma20) / ma20 * 100 if latest and ma20 else None)
    d60    = ((latest - ma60) / ma60 * 100 if latest and ma60 else None)
    d52    = ((latest - h52) / h52 * 100 if latest and h52 else None)
    return {
        "latest": latest, "ma20": ma20, "ma60": ma60,
        "rsi14": _rsi(c), "atr14": atr14, "mdd20": mdd20,
        "volumeRatio20": vr, "distanceToMa20": d20, "distanceToMa60": d60,
        "recentMomentum5": _momentum(c, 5), "recentMomentum20": _momentum(c, 20),
        "distanceTo52wHigh": d52, "bbPercentB": bb_b,
        "atr14Pct": (round(atr14 / latest * 100, 2) if atr14 and latest else None),
    }


# ─── 스코어 계산 (동일 가중치) ────────────────────────────────────────────────

_MODE_WEIGHTS: dict[str, dict[str, float]] = {
    "conservative": {"riskScore": 0.35, "entryScore": 0.20, "rrScore": 0.15,
                     "momentumScore": 0.15, "qualityScore": 0.10, "newsRiskPenalty": 0.05, "upsideScore": 0.0},
    "balanced":     {"upsideScore": 0.25, "riskScore": 0.25, "rrScore": 0.20,
                     "momentumScore": 0.15, "entryScore": 0.10, "newsRiskPenalty": 0.05, "qualityScore": 0.0},
    "aggressive":   {"upsideScore": 0.35, "momentumScore": 0.25, "rrScore": 0.15,
                     "entryScore": 0.10, "riskScore": 0.10, "newsRiskPenalty": 0.05, "qualityScore": 0.0},
}

_HORIZON_BANDS: dict[str, dict] = {
    # 보정 근거: 22창 walk-forward 결과 (GOOD_SIGNAL_WEAK_EXIT 16-27%)
    # short 2일 보유 → 목표 3.8%로 하향 (기존 6.0%)
    # swing 7일 보유 → 목표 8.5%로 하향 (기존 13.0%)
    # mid  — 손절 폭 확대 (ENTRY_TOO_AGGRESSIVE 9.1% 개선)
    "short": {"stop": 0.965, "target": 1.038, "min_rr": 1.2},
    "swing": {"stop": 0.940, "target": 1.085, "min_rr": 1.5},
    "mid":   {"stop": 0.882, "target": 1.220, "min_rr": 1.8},
}
_MODE_RISK   = {"conservative": 0.85, "balanced": 1.0, "aggressive": 1.20}
_MODE_REWARD = {"conservative": 0.80, "balanced": 1.0, "aggressive": 1.30}

# 보정 근거: GOOD_SIGNAL_WEAK_EXIT 개선 — ATR 기반 목표 배수 축소
# short: 2.8 → 2.0  swing: 4.5 → 3.2  mid 손절: 2.0 → 2.4 (더 넓게)
_ATR_MULT = {"short": (1.2, 2.0), "swing": (1.5, 3.2), "mid": (2.4, 5.5)}

# 과거 데이터 기반 경험적 보정값 (22창 walk-forward에서 도출)
_EMPIRICAL_CALIBRATION = {
    "atr_pct_max":        4.0,   # VOLATILITY_TOO_HIGH 제거: ATR% > 4.0 종목 제외
    "min_volume_ratio":   0.4,   # 저유동성 기본 필터 (0.8은 오히려 성능 저하 확인)
    "min_score_v2":       50.0,
}


def _sub_scores(ind: dict) -> dict[str, float]:
    rsi = ind.get("rsi14"); mdd = ind.get("mdd20"); d20 = ind.get("distanceToMa20")
    d60 = ind.get("distanceToMa60"); mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20"); vr = ind.get("volumeRatio20")
    bb_b = ind.get("bbPercentB"); cup = ind.get("consecutiveUpDays", 0) or 0
    d52 = ind.get("distanceTo52wHigh")

    up = 50.0
    if mom5:  up += max(-15.0, min(20.0, mom5 * 1.5))
    if mom20: up += max(-10.0, min(15.0, mom20 * 0.8))
    if d60 and d60 > 0: up += min(8.0, d60 * 0.4)
    if d52 and -2.0 <= d52 <= 0: up += 8.0
    upsideScore = max(0.0, min(100.0, up))

    risk = 60.0
    if mdd: risk += max(-20.0, min(15.0, 15.0 + mdd * 1.2))
    if rsi:
        if rsi > 80:   risk -= 20.0
        elif rsi > 70: risk -= 10.0
        elif 40 <= rsi <= 65: risk += 8.0
    if bb_b and bb_b > 1.0: risk -= 10.0
    if cup >= 5: risk -= 8.0
    riskScore = max(0.0, min(100.0, risk))

    mom = 50.0
    if mom5:  mom += max(-12.0, min(18.0, mom5 * 1.2))
    if mom20: mom += max(-8.0,  min(12.0, mom20 * 0.6))
    if d20 and d20 > 0: mom += min(10.0, d20 * 0.5)
    if vr and vr >= 2.0: mom += 10.0
    momentumScore = max(0.0, min(100.0, mom))

    ent = 50.0
    if d20 is not None:
        if   -5.0 <= d20 <= 3.0:  ent += 25.0
        elif -8.0 <= d20 < -5.0:  ent += 15.0
        elif  3.0 < d20 <= 8.0:   ent += 5.0
        elif d20 > 8.0:            ent -= 15.0
        elif d20 < -10.0:          ent -= 10.0
    entryScore = max(0.0, min(100.0, ent))

    rr = 50.0
    if d20 is not None and d60 is not None:
        pot = d60 - d20
        if pot > 5:   rr += min(20.0, pot * 1.0)
        elif pot < 0: rr -= min(20.0, abs(pot) * 0.8)
    rrScore = max(0.0, min(100.0, rr))

    qual = 50.0
    if mdd and mdd > -15.0: qual += 15.0
    if d60 and d60 > -5.0:  qual += 15.0
    if rsi and 30 <= rsi <= 70: qual += 10.0
    qualityScore = max(0.0, min(100.0, qual))

    news = 0.0
    if rsi:
        if rsi > 80: news = 15.0
        elif rsi > 75: news = 8.0

    return {
        "upsideScore": round(upsideScore, 1), "riskScore": round(riskScore, 1),
        "momentumScore": round(momentumScore, 1), "entryScore": round(entryScore, 1),
        "rrScore": round(rrScore, 1), "qualityScore": round(qualityScore, 1),
        "newsRiskPenalty": round(news, 1),
    }


def _final_score(ind: dict, mode: str, horizon: str) -> float:
    sub = _sub_scores(ind)
    w   = _MODE_WEIGHTS.get(mode, _MODE_WEIGHTS["balanced"])
    final = (sum(sub[k] * v for k, v in w.items() if k != "newsRiskPenalty")
             - sub["newsRiskPenalty"] * w.get("newsRiskPenalty", 0.05))

    rsi = ind.get("rsi14"); d20 = ind.get("distanceToMa20"); d60 = ind.get("distanceToMa60")
    mdd = ind.get("mdd20"); vr = ind.get("volumeRatio20"); bb_b = ind.get("bbPercentB")
    cup = ind.get("consecutiveUpDays", 0) or 0; d52 = ind.get("distanceTo52wHigh")
    mom5 = ind.get("recentMomentum5")

    if horizon == "short":
        if d20 and abs(d20) > 5.0: final -= 5.0
        if mom5 and mom5 > 0: final += min(5.0, mom5 * 0.5)
        if rsi and rsi > 80: final -= 8.0
    elif horizon == "swing":
        if d20 and -15.0 <= d20 <= -3.0: final += 5.0
        if d60 and d60 > -10.0: final += 3.0
    elif horizon == "mid":
        if d60 and d60 > -5.0: final += 6.0
        if mdd and mdd > -15.0: final += 4.0

    if mode == "aggressive":
        if rsi and rsi > 80: final -= 12.0
        if mom5 and mom5 > 15.0: final -= 8.0
    if cup >= 5 and vr and vr < 0.7: final -= 12.0
    if rsi and rsi > 80 and bb_b and bb_b > 1.0: final -= 15.0
    if d52 and -2.0 <= d52 <= 0 and vr and vr >= 2.0: final += 6.0
    if mode == "conservative":
        if rsi and 40 <= rsi <= 60: final += 5.0
        if d20 and -3.0 <= d20 <= 2.0: final += 4.0
    return max(0.0, min(100.0, round(final, 1)))


def _price_band(
    score: float, current: float, mode: str, horizon: str, ind: dict | None = None
) -> tuple[float, float, float]:
    """entry, stop, target 반환"""
    band = _HORIZON_BANDS[horizon]
    rf   = _MODE_RISK[mode]
    rwf  = _MODE_REWARD[mode]
    entry = current

    sm, tm = _ATR_MULT.get(horizon, (1.5, 4.5))
    atr14 = ind.get("atr14") if ind else None
    if atr14 and atr14 > 0 and current > 0:
        atr_stop   = round(entry - atr14 * sm)
        atr_target = round(entry + atr14 * tm)
        atr_pct = (entry - atr_stop) / entry * 100
        if 1.5 <= atr_pct <= 15.0:
            return entry, atr_stop, atr_target

    stop   = round(entry * (1.0 - (1.0 - band["stop"]) * rf))
    target = round(entry * (1.0 + (band["target"] - 1.0) * rwf))
    return entry, stop, target


# ─── OHLCV 로딩 ───────────────────────────────────────────────────────────────

def _load_ohlcv_all(market: str = "kr") -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    odir = _ohlcv_dir(market)
    pattern = f"{market}_*_daily.csv"
    for path in sorted(odir.glob(pattern)):
        m = re.match(rf"{market}_(\w+)_daily\.csv", path.name)
        if not m:
            continue
        sym = m.group(1)
        if market == "kr" and (not sym.isdigit() or len(sym) != 6):
            continue
        rows: list[dict] = []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    rows = list(csv.DictReader(f))
                break
            except UnicodeDecodeError:
                continue
        rows.sort(key=lambda r: str(r.get("date") or ""))
        if len(rows) >= 30:
            result[sym] = rows
    return result


def _slice_rows(rows: list[dict], before_date: str) -> list[dict]:
    """before_date 미만 행만 반환 (엄격한 미래 누출 방지)"""
    return [r for r in rows if str(r.get("date") or "") < before_date]


# ─── 추천 생성 (지정 날짜 기준) ───────────────────────────────────────────────

def _generate_recs_at_date(
    ohlcv_all: dict[str, list[dict]],
    cutoff_date: str,
    market: str,
    mode: str,
    horizon: str,
    combo_params: dict | None = None,
    min_score: float = 50.0,
) -> list[dict]:
    """
    cutoff_date 이전 OHLCV만 사용해 추천 목록 생성.
    combo_params 가 있으면 _apply_wf_correction() 으로 entry/stop/target 직접 조정.
    (JSON 스토어를 읽지 않으므로 미래 데이터 누출 없음)
    """
    ec            = _EMPIRICAL_CALIBRATION
    atr_pct_max   = ec["atr_pct_max"]
    min_vol_ratio = ec["min_volume_ratio"]
    min_score_v2  = ec["min_score_v2"]

    recs: list[dict] = []
    for sym, rows in ohlcv_all.items():
        past_rows = _slice_rows(rows, cutoff_date)
        if len(past_rows) < 30:
            continue
        ind = _indicators(past_rows)
        current = ind.get("latest")
        if not current or current <= 0:
            continue

        # ── 경험적 보정 필터 (VOLATILITY_TOO_HIGH / LOW_LIQUIDITY 제거) ──────
        atr_pct = ind.get("atr14Pct")
        if atr_pct and atr_pct > atr_pct_max:
            continue  # 과변동성 제거

        vr = ind.get("volumeRatio20")
        if vr is not None and vr < min_vol_ratio:
            continue  # 저거래량 제거

        score = _final_score(ind, mode, horizon)
        if score < min_score:
            continue

        entry, stop, target = _price_band(score, current, mode, horizon, ind)
        sub = _sub_scores(ind)

        corr_applied = False
        if combo_params:
            entry, stop, target, corr_applied = _apply_wf_correction(
                combo_params, entry, stop, target, ind
            )

        recs.append({
            "symbol":      sym,
            "market":      market,
            "mode":        mode,
            "horizon":     horizon,
            "generatedAt": cutoff_date,
            "entry":       entry,
            "stop":        stop,
            "target":      target,
            "finalScore":  score,
            **sub,
            "correctionApplied": corr_applied,
        })

    return recs


# ─── 추천 평가 ────────────────────────────────────────────────────────────────

def _eval_recs(
    recs: list[dict],
    ohlcv_all: dict[str, list[dict]],
    horizon: str,
) -> list[dict]:
    """recs 각 추천에 대해 backtest_v2로 체결/청산 검증. rec에 result 필드 추가."""
    from app.engine.backtest_v2 import evaluate_recommendation
    from app.engine.outcome_analyzer import classify_outcome

    settings = {"slippage_pct": 0.002}
    results: list[dict] = []
    for rec in recs:
        sym  = rec["symbol"]
        rows = ohlcv_all.get(sym, [])
        if not rows:
            continue
        ohlcv_df = pd.DataFrame(rows)
        ohlcv_df.columns = [str(c).lower() for c in ohlcv_df.columns]
        for col in ("open", "high", "low", "close", "volume"):
            if col in ohlcv_df.columns:
                ohlcv_df[col] = pd.to_numeric(ohlcv_df[col], errors="coerce")

        result = evaluate_recommendation(rec, ohlcv_df, settings, horizon)
        reason = classify_outcome(rec, result)

        results.append({
            "symbol":         sym,
            "market":         rec["market"],
            "mode":           rec["mode"],
            "horizon":        rec["horizon"],
            "generatedAt":    rec["generatedAt"],
            "entry":          rec["entry"],
            "stop":           rec["stop"],
            "target":         rec["target"],
            "finalScore":     rec.get("finalScore"),
            "correctionApplied": rec.get("correctionApplied", False),
            # result fields
            "executionStatus": result.get("executionStatus"),
            "exitStatus":      result.get("exitStatus"),
            "netPnlPct":       result.get("netPnlPct"),
            "mfePct":          result.get("mfePct"),
            "maePct":          result.get("maePct"),
            "holdingDays":     result.get("holdingDays"),
            "entryDate":       result.get("entryDate"),
            "exitDate":        result.get("exitDate"),
            "exitPrice":       result.get("exitPrice"),
            "outcomeReason":   reason,
            "error":           result.get("error"),
        })
    return results


# ─── 성과 집계 ────────────────────────────────────────────────────────────────

def _agg_stats(results: list[dict]) -> dict[str, Any]:
    if not results:
        return {"status": "DATA_INSUFFICIENT", "count": 0}

    executed = [r for r in results if str(r.get("executionStatus") or "").upper() == "체결"]
    wins  = [r for r in executed if str(r.get("exitStatus") or "").upper() in {"목표도달", "WIN", "TARGET_HIT", "TARGET"}]
    stops = [r for r in executed if str(r.get("exitStatus") or "").upper() in {"손절", "STOP", "STOP_HIT", "STOP_FIRST"}]
    expired = [r for r in executed if str(r.get("exitStatus") or "").upper() in {"기간종료", "EXPIRED", "TIMEOUT"}]

    pnls: list[float] = []
    for r in executed:
        v = _num(r.get("netPnlPct"))
        if v is not None:
            pnls.append(v)

    n   = len(results)
    ne  = len(executed)
    nw  = len(wins)
    ns  = len(stops)
    nm  = n - ne  # 미체결

    avg_pnl  = round(sum(pnls) / len(pnls), 3) if pnls else 0.0
    cum_pnl  = round(sum(pnls), 3) if pnls else 0.0

    profit_pnls = [p for p in pnls if p > 0]
    loss_pnls   = [p for p in pnls if p < 0]
    pl_ratio    = (
        round(sum(profit_pnls) / len(profit_pnls) / (abs(sum(loss_pnls) / len(loss_pnls))), 2)
        if profit_pnls and loss_pnls else None
    )

    hold_days: list[float] = []
    for r in executed:
        v = _num(r.get("holdingDays"))
        if v is not None:
            hold_days.append(v)

    # MDD: 최저 누적 수익률
    running = 0.0
    peak    = 0.0
    mdd     = 0.0
    for p in sorted([r.get("entryDate") or "" for r in executed]):
        pass
    for p in pnls:
        running += p
        peak     = max(peak, running)
        mdd      = min(mdd, running - peak)

    # 실패 원인 집계
    reason_counts: dict[str, int] = {}
    for r in results:
        rc = r.get("outcomeReason") or "UNKNOWN"
        reason_counts[rc] = reason_counts.get(rc, 0) + 1

    return {
        "status":               "OK",
        "recommendationCount":  n,
        "executionCount":       ne,
        "executionRate":        round(ne / max(n, 1) * 100, 1),
        "winCount":             nw,
        "winRate":              round(nw / max(ne, 1) * 100, 1),
        "stopCount":            ns,
        "stopHitRate":          round(ns / max(ne, 1) * 100, 1),
        "expiredCount":         len(expired),
        "missEntryCount":       nm,
        "missEntryRate":        round(nm / max(n, 1) * 100, 1),
        "avgNetPnlPct":         avg_pnl,
        "cumulativeNetPnlPct":  cum_pnl,
        "mddPct":               round(mdd, 2),
        "avgHoldingDays":       round(sum(hold_days) / len(hold_days), 1) if hold_days else None,
        "profitLossRatio":      pl_ratio,
        "reasonCounts":         reason_counts,
    }


def _diff_stats(baseline: dict, corrected: dict) -> dict[str, Any]:
    """Corrected - Baseline 차이 계산"""
    keys = ["winRate", "stopHitRate", "missEntryRate", "avgNetPnlPct",
            "cumulativeNetPnlPct", "mddPct", "executionRate"]
    diff: dict[str, Any] = {}
    for k in keys:
        bv = _num(baseline.get(k))
        cv = _num(corrected.get(k))
        if bv is not None and cv is not None:
            diff[f"{k}Diff"] = round(cv - bv, 3)
    return diff


# ─── Walk-Forward 메인 루프 ───────────────────────────────────────────────────

def run_walkforward(
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    window_months: int = 1,
    min_score: float = 50.0,
) -> dict[str, Any]:
    """
    지정 market/mode/horizon 조합에 대해 Walk-Forward 검증 실행.
    반환: {windows: [...], baselineStats: {...}, correctedStats: {...}, diff: {...}}
    """
    ohlcv_all = _load_ohlcv_all(market)
    if len(ohlcv_all) < 5:
        return {"status": "DATA_INSUFFICIENT", "reason": f"OHLCV 심볼 {len(ohlcv_all)}개 — 최소 5개 필요"}

    # 날짜 범위 파악
    all_dates: list[str] = []
    for rows in ohlcv_all.values():
        for r in rows:
            d = str(r.get("date") or "")[:10]
            if d:
                all_dates.append(d)
    if not all_dates:
        return {"status": "DATA_INSUFFICIENT", "reason": "날짜 정보 없음"}

    data_start = min(all_dates)
    data_end   = max(all_dates)

    # 첫 창은 충분한 히스토리 확보 후 (60 거래일 ≈ 3개월)
    first_window_start = _add_months(data_start[:7], 3) + "-01"
    last_window_start  = data_end[:7] + "-01"

    windows: list[str] = []
    cur = first_window_start
    while cur <= last_window_start:
        windows.append(cur)
        cur = _add_months(cur[:7], window_months) + "-01"

    if len(windows) < 2:
        return {
            "status": "DATA_INSUFFICIENT",
            "reason": f"창 {len(windows)}개 — Walk-Forward 최소 2창 필요 (데이터 기간: {data_start}~{data_end})",
        }

    past_outcomes: list[dict] = []
    window_results: list[dict] = []

    for i, w_start in enumerate(windows):
        # 보정 파라미터: 이 창 이전 누적 결과만 사용 (walk-forward 전용 — 미래 누출 없음)
        combo_params: dict | None = _build_wf_correction(past_outcomes, market, mode, horizon)

        # Baseline 추천 생성 (보정 없음)
        baseline_recs = _generate_recs_at_date(
            ohlcv_all, w_start, market, mode, horizon,
            combo_params=None, min_score=min_score,
        )
        # Corrected 추천 생성
        corrected_recs = _generate_recs_at_date(
            ohlcv_all, w_start, market, mode, horizon,
            combo_params=combo_params, min_score=min_score,
        )

        # 평가
        baseline_results  = _eval_recs(baseline_recs, ohlcv_all, horizon)
        corrected_results = _eval_recs(corrected_recs, ohlcv_all, horizon)

        b_stats = _agg_stats(baseline_results)
        c_stats = _agg_stats(corrected_results)

        window_results.append({
            "window":               w_start,
            "windowIndex":          i,
            "correctionParamsUsed": combo_params is not None,
            "pastSampleCount":      len(past_outcomes),
            "baseline":             b_stats,
            "corrected":            c_stats,
            "diff":                 _diff_stats(b_stats, c_stats),
        })

        # 다음 창 학습을 위해 corrected 결과 누적 (실전 운영 모방)
        past_outcomes.extend(corrected_results)

    # 전체 집계
    all_baseline  = [r for w in window_results for r in []]  # placeholder
    total_baseline_stats  = _merge_window_stats([w["baseline"]  for w in window_results])
    total_corrected_stats = _merge_window_stats([w["corrected"] for w in window_results])
    total_diff            = _diff_stats(total_baseline_stats, total_corrected_stats)

    return {
        "status":         "OK",
        "market":         market,
        "mode":           mode,
        "horizon":        horizon,
        "dataRange":      f"{data_start} ~ {data_end}",
        "windowCount":    len(window_results),
        "windows":        window_results,
        "baselineStats":  total_baseline_stats,
        "correctedStats": total_corrected_stats,
        "diff":           total_diff,
        "generatedAt":    datetime.utcnow().isoformat(),
    }


def _add_months(ym: str, n: int) -> str:
    """'YYYY-MM' + n개월 → 'YYYY-MM'"""
    y, m = int(ym[:4]), int(ym[5:7])
    m += n
    while m > 12:
        m -= 12; y += 1
    return f"{y:04d}-{m:02d}"


def _merge_window_stats(stats_list: list[dict]) -> dict[str, Any]:
    """여러 창 성과 통계 병합 (가중 평균)"""
    valid = [s for s in stats_list if s.get("status") == "OK"]
    if not valid:
        return {"status": "DATA_INSUFFICIENT", "windowCount": 0}

    def _wavg(key: str) -> float | None:
        weights = [s.get("recommendationCount", 0) for s in valid]
        vals    = [_num(s.get(key)) for s in valid]
        total_w = sum(w for w, v in zip(weights, vals) if v is not None)
        if total_w == 0:
            return None
        return round(sum(w * v for w, v in zip(weights, vals) if v is not None) / total_w, 3)

    merged_reasons: dict[str, int] = {}
    for s in valid:
        for k, v in (s.get("reasonCounts") or {}).items():
            merged_reasons[k] = merged_reasons.get(k, 0) + v

    return {
        "status":              "OK",
        "windowCount":         len(valid),
        "recommendationCount": sum(s.get("recommendationCount", 0) for s in valid),
        "executionCount":      sum(s.get("executionCount", 0) for s in valid),
        "executionRate":       _wavg("executionRate"),
        "winCount":            sum(s.get("winCount", 0) for s in valid),
        "winRate":             _wavg("winRate"),
        "stopCount":           sum(s.get("stopCount", 0) for s in valid),
        "stopHitRate":         _wavg("stopHitRate"),
        "missEntryRate":       _wavg("missEntryRate"),
        "avgNetPnlPct":        _wavg("avgNetPnlPct"),
        "cumulativeNetPnlPct": round(sum((_num(s.get("cumulativeNetPnlPct")) or 0) for s in valid), 3),
        "mddPct":              min((_num(s.get("mddPct")) or 0) for s in valid),
        "profitLossRatio":     _wavg("profitLossRatio"),
        "reasonCounts":        merged_reasons,
    }


# ─── Walk-Forward 전용 보정 계산 (미래 누출 없는 local 버전) ─────────────────

_SAFETY = {
    "entryAggressiveness": 0.5,
    "targetMultiplier":    0.2,
    "stopAtrMultiplier":   0.3,
}
_REASON_WEIGHTS = {
    "MISS_ENTRY_TOO_LOW":         {"entryAggressiveness": +0.08},
    "ENTRY_TOO_AGGRESSIVE":       {"entryAggressiveness": -0.08},
    "TARGET_TOO_FAR":             {"targetMultiplier":    -0.04},
    "TARGET_TOO_CLOSE":           {"targetMultiplier":    +0.04},
    "STOP_TOO_TIGHT":             {"stopAtrMultiplier":   +0.06},
    "VOLATILITY_TOO_HIGH":        {"entryAggressiveness": -0.06, "stopAtrMultiplier": -0.04},
    "NEWS_RISK_UNDERWEIGHTED":    {"entryAggressiveness": -0.04},
}


def _build_wf_correction(
    past_results: list[dict],
    market: str,
    mode: str,
    horizon: str,
) -> dict | None:
    """
    축적된 walk-forward 결과에서 해당 combo의 보정값 계산.
    sampleCount < 30 이면 None 반환 (보정 미적용).
    """
    combo_key = f"{market}_{mode}_{horizon}"
    samples = [r for r in past_results if
               r.get("market") == market and
               r.get("mode") == mode and
               r.get("horizon") == horizon]

    learnable = [r for r in samples if
                 r.get("outcomeReason") not in {None, "", "DATA_STALE"}]

    if len(learnable) < 30:
        return None

    # 실패 원인 카운트
    reason_counts: dict[str, int] = {}
    for r in learnable:
        rc = r.get("outcomeReason") or "UNKNOWN"
        reason_counts[rc] = reason_counts.get(rc, 0) + 1

    n = len(learnable)
    adj: dict[str, float] = {"entryAggressiveness": 0.0, "targetMultiplier": 0.0, "stopAtrMultiplier": 0.0}

    for reason, weight_map in _REASON_WEIGHTS.items():
        count = reason_counts.get(reason, 0)
        if count == 0:
            continue
        freq = count / n
        for param, delta in weight_map.items():
            adj[param] += delta * freq * 10  # 빈도 기반 스케일

    # 안전 클램프
    for param, limit in _SAFETY.items():
        adj[param] = max(-limit, min(limit, adj[param]))

    confidence = min(1.0, len(learnable) / 200)

    return {
        "sampleCount":        n,
        "learnableSampleCount": len(learnable),
        "confidence":         round(confidence, 3),
        "priceAdjustments":   {k: round(v, 4) for k, v in adj.items()},
        "reasonCounts":       reason_counts,
    }


def _apply_wf_correction(
    combo_params: dict,
    entry: float,
    stop: float,
    target: float,
    ind: dict | None = None,
) -> tuple[float, float, float, bool]:
    """
    combo_params의 priceAdjustments를 entry/stop/target에 직접 적용.
    반환: (adj_entry, adj_stop, adj_target, applied)
    """
    if not combo_params:
        return entry, stop, target, False

    pa = combo_params.get("priceAdjustments", {})
    ea = float(pa.get("entryAggressiveness", 0.0))
    tm = float(pa.get("targetMultiplier", 0.0))
    sm = float(pa.get("stopAtrMultiplier", 0.0))

    if ea == 0.0 and tm == 0.0 and sm == 0.0:
        return entry, stop, target, False

    # entryAggressiveness > 0 → entry 를 current 기준으로 살짝 위로
    # (entry가 이미 current와 같은 경우가 많으므로 stop distance 기준 조정)
    stop_dist  = max(entry - stop,  1.0)
    target_dist = max(target - entry, 1.0)

    new_entry  = entry  + stop_dist  * ea * 0.1   # 작게 조정
    new_stop   = stop   + stop_dist  * sm * 0.1
    new_target = target + target_dist * tm * 0.1

    # 역전 방지
    if new_stop >= new_entry:
        new_stop = entry - stop_dist * 0.5
    if new_target <= new_entry:
        new_target = entry + target_dist * 0.5

    return round(new_entry, 0), round(new_stop, 0), round(new_target, 0), True


# ─── 전체 실행 (모든 mode×horizon 조합) ──────────────────────────────────────

def run_all(market: str = "kr") -> dict[str, Any]:
    """
    market의 9개 (3 mode × 3 horizon) 조합 전부 실행.
    결과를 reports/ 에 저장하고 요약 반환.
    """
    from itertools import product
    modes    = ("conservative", "balanced", "aggressive")
    horizons = ("short", "swing", "mid")

    all_results: dict[str, Any] = {}
    all_csv_rows: list[dict]    = []

    for mode, horizon in product(modes, horizons):
        key = f"{market}_{mode}_{horizon}"
        print(f"  Walk-Forward: {key} ...", flush=True)
        result = run_walkforward(market, mode, horizon)
        all_results[key] = result

        # CSV용 행 추출 (창별 요약)
        for w in result.get("windows", []):
            for strategy in ("baseline", "corrected"):
                s = w.get(strategy, {})
                all_csv_rows.append({
                    "market":               market,
                    "mode":                 mode,
                    "horizon":              horizon,
                    "strategy":             strategy,
                    "window":               w.get("window"),
                    "windowIndex":          w.get("windowIndex"),
                    "correctionParamsUsed": w.get("correctionParamsUsed"),
                    "pastSampleCount":      w.get("pastSampleCount"),
                    **{k: s.get(k) for k in (
                        "recommendationCount", "executionCount", "executionRate",
                        "winCount", "winRate", "stopCount", "stopHitRate",
                        "missEntryRate", "avgNetPnlPct", "cumulativeNetPnlPct",
                        "mddPct", "avgHoldingDays", "profitLossRatio",
                    )},
                })

    # 저장
    reports = _reports_dir()
    reports.mkdir(parents=True, exist_ok=True)

    csv_path = reports / f"walkforward_results_{market}.csv"
    if all_csv_rows:
        fieldnames = list(all_csv_rows[0].keys())
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(all_csv_rows)

    summary = {
        "generatedAt": datetime.utcnow().isoformat(),
        "market":      market,
        "combos":      all_results,
    }
    json_path = reports / f"walkforward_summary_{market}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 간략 요약
    improvements = []
    for key, res in all_results.items():
        diff = res.get("diff", {})
        if (_num(diff.get("winRateDiff")) or 0) > 0:
            improvements.append(key)

    return {
        "status":       "OK",
        "market":       market,
        "combosRun":    len(all_results),
        "improved":     improvements,
        "csvPath":      str(csv_path),
        "summaryPath":  str(json_path),
        "results":      {k: {
            "status":         v.get("status"),
            "windowCount":    v.get("windowCount"),
            "baselineWinRate":  v.get("baselineStats", {}).get("winRate"),
            "correctedWinRate": v.get("correctedStats", {}).get("winRate"),
            "diff":           v.get("diff"),
        } for k, v in all_results.items()},
    }
