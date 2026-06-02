"""
OHLCV + KIS 현재가 기반으로 KR 추천 파일 18개 직접 생성.
predictions.csv에 의존하지 않음 → GitHub Actions에서 매일 신선한 추천 생성 가능.

출력: reports/mone_v36_final_recommendations_kr_{mode}_{horizon}.csv  (9개)
      reports/mone_v36_final_trade_validation_kr_{mode}_{horizon}.csv (9개)
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
REPORTS = ROOT / "reports"
DATA_STOCKAPP = ROOT / "data" / "stockapp"

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")
MODE_LABELS = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
HORIZON_LABELS = {"short": "단기", "swing": "스윙", "mid": "중기"}

MIN_OHLCV_ROWS = 30
TOP_N = 12  # 조합당 최대 추천 수


# ── 지표 계산 (quant_scanner 독립 복사)

def _num(v: Any) -> float | None:
    try:
        raw = re.sub(r"[,원$%]", "", str(v or "")).strip()
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
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8-sig")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _series(rows: list[dict], key: str) -> list[float]:
    aliases = {
        "close": ["close", "Close", "종가"],
        "high":  ["high",  "High",  "고가"],
        "low":   ["low",   "Low",   "저가"],
        "volume":["volume","Volume","거래량"],
        "open":  ["open",  "Open",  "시가"],
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
    return sum(vals[-p:]) / p if len(vals) >= p else None


def _rsi(vals: list[float], p: int = 14) -> float | None:
    if len(vals) <= p:
        return None
    gains = [max(vals[i] - vals[i-1], 0) for i in range(len(vals)-p, len(vals))]
    losses = [abs(min(vals[i] - vals[i-1], 0)) for i in range(len(vals)-p, len(vals))]
    ag, al = sum(gains)/p, sum(losses)/p
    return 100.0 if al == 0 else 100 - 100/(1 + ag/al)


def _atr(h: list[float], l: list[float], c: list[float], p: int = 14) -> float | None:
    if len(c) <= p:
        return None
    rs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(len(c)-p, len(c))]
    return sum(rs) / p


def _mdd(vals: list[float], p: int = 20) -> float | None:
    if len(vals) < p:
        return None
    w, peak, worst = vals[-p:], vals[-p], 0.0
    for v in w:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak * 100)
    return worst


def _momentum(vals: list[float], p: int) -> float | None:
    if len(vals) <= p or vals[-p-1] == 0:
        return None
    return (vals[-1] - vals[-p-1]) / vals[-p-1] * 100


def indicators(rows: list[dict]) -> dict[str, float | None]:
    c = _series(rows, "close")
    h = _series(rows, "high")
    l = _series(rows, "low")
    v = _series(rows, "volume")
    latest = c[-1] if c else None
    ma20 = _ma(c, 20)
    ma60 = _ma(c, 60)
    vm20 = _ma(v, 20)
    h52 = max(h[-252:]) if len(h) >= 252 else (max(h) if h else None)
    std20 = (sum((x - ma20)**2 for x in c[-20:])/20)**0.5 if ma20 and len(c) >= 20 else None
    bb_u = (ma20 + std20*2) if ma20 and std20 else None
    bb_l = (ma20 - std20*2) if ma20 and std20 else None
    bb_b = ((latest - bb_l)/(bb_u - bb_l)) if latest and bb_u and bb_l and bb_u != bb_l else None
    gap = None
    if len(c) >= 2 and c[-2] > 0:
        op = _series(rows, "open")
        if op:
            gap = (op[-1] - c[-2]) / c[-2] * 100
    consec = 0
    for i in range(len(c)-1, 0, -1):
        if c[i] > c[i-1]:
            consec += 1
        else:
            break
    return {
        "ma5":  _ma(c, 5), "ma20": ma20, "ma60": ma60, "ma120": _ma(c, 120),
        "rsi14": _rsi(c), "atr14": _atr(h, l, c), "mdd20": _mdd(c),
        "volumeRatio20": (v[-1]/vm20 if v and vm20 else None),
        "volumeValue": (latest * v[-1] if latest and v else None),
        "distanceToMa20": ((latest - ma20)/ma20*100 if latest and ma20 else None),
        "distanceToMa60": ((latest - ma60)/ma60*100 if latest and ma60 else None),
        "recentMomentum5": _momentum(c, 5), "recentMomentum20": _momentum(c, 20),
        "distanceTo52wHigh": ((latest - h52)/h52*100 if latest and h52 else None),
        "bbPercentB": bb_b, "consecutiveUpDays": float(consec), "gapUpPct": gap,
        "latest": latest,
    }


_MODE_WEIGHTS: dict[str, dict[str, float]] = {
    "conservative": {"riskScore":0.35,"entryScore":0.20,"rrScore":0.15,"momentumScore":0.15,"qualityScore":0.10,"newsRiskPenalty":0.05,"upsideScore":0.0},
    "balanced":     {"upsideScore":0.25,"riskScore":0.25,"rrScore":0.20,"momentumScore":0.15,"entryScore":0.10,"newsRiskPenalty":0.05,"qualityScore":0.0},
    "aggressive":   {"upsideScore":0.35,"momentumScore":0.25,"rrScore":0.15,"entryScore":0.10,"riskScore":0.10,"newsRiskPenalty":0.05,"qualityScore":0.0},
}

_HORIZON_BANDS: dict[str, dict] = {
    "short": {"stop": 0.961, "target": 1.060, "min_rr": 1.5},
    "swing": {"stop": 0.935, "target": 1.130, "min_rr": 1.8},
    "mid":   {"stop": 0.905, "target": 1.220, "min_rr": 2.0},
}

_MODE_RISK   = {"conservative": 0.85, "balanced": 1.0, "aggressive": 1.20}
_MODE_REWARD = {"conservative": 0.80, "balanced": 1.0, "aggressive": 1.30}


def _sub_scores(ind: dict) -> dict[str, float]:
    rsi = ind.get("rsi14"); mdd = ind.get("mdd20"); d20 = ind.get("distanceToMa20")
    d60 = ind.get("distanceToMa60"); mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20"); vr = ind.get("volumeRatio20")
    bb_b = ind.get("bbPercentB"); cup = ind.get("consecutiveUpDays")
    d52 = ind.get("distanceTo52wHigh")

    up = 50.0
    if mom5:  up += max(-15.0, min(20.0, mom5*1.5))
    if mom20: up += max(-10.0, min(15.0, mom20*0.8))
    if d60 and d60 > 0: up += min(8.0, d60*0.4)
    if d52 and -2.0 <= d52 <= 0: up += 8.0
    upsideScore = max(0.0, min(100.0, up))

    risk = 60.0
    if mdd: risk += max(-20.0, min(15.0, 15.0 + mdd*1.2))
    if rsi:
        if rsi > 80:   risk -= 20.0
        elif rsi > 70: risk -= 10.0
        elif 40 <= rsi <= 65: risk += 8.0
    if bb_b and bb_b > 1.0: risk -= 10.0
    if cup and cup >= 5: risk -= 8.0
    riskScore = max(0.0, min(100.0, risk))

    mom = 50.0
    if mom5:  mom += max(-12.0, min(18.0, mom5*1.2))
    if mom20: mom += max(-8.0,  min(12.0, mom20*0.6))
    if d20 and d20 > 0: mom += min(10.0, d20*0.5)
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
        if pot > 5:    rr += min(20.0, pot*1.0)
        elif pot < 0:  rr -= min(20.0, abs(pot)*0.8)
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

    return {"upsideScore": round(upsideScore,1), "riskScore": round(riskScore,1),
            "momentumScore": round(momentumScore,1), "entryScore": round(entryScore,1),
            "rrScore": round(rrScore,1), "qualityScore": round(qualityScore,1), "newsRiskPenalty": round(news,1)}


def _final_score(ind: dict, mode: str, horizon: str) -> float:
    sub = _sub_scores(ind)
    w = _MODE_WEIGHTS.get(mode, _MODE_WEIGHTS["balanced"])
    final = sum(sub[k]*v for k, v in w.items() if k != "newsRiskPenalty") - sub["newsRiskPenalty"]*w.get("newsRiskPenalty", 0.05)

    rsi = ind.get("rsi14"); d20 = ind.get("distanceToMa20"); d60 = ind.get("distanceToMa60")
    mdd = ind.get("mdd20"); vr = ind.get("volumeRatio20"); bb_b = ind.get("bbPercentB")
    cup = ind.get("consecutiveUpDays"); gap = ind.get("gapUpPct"); d52 = ind.get("distanceTo52wHigh")
    mom5 = ind.get("recentMomentum5")

    if horizon == "short":
        if d20 and abs(d20) > 5.0: final -= 5.0
        if mom5 and mom5 > 0: final += min(5.0, mom5*0.5)
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
    if cup and cup >= 5 and vr and vr < 0.7: final -= 12.0
    if rsi and rsi > 80 and bb_b and bb_b > 1.0: final -= 15.0
    if gap and gap >= 15.0: final -= 15.0
    if d52 and -2.0 <= d52 <= 0 and vr and vr >= 2.0: final += 6.0
    if mode == "conservative":
        if rsi and 40 <= rsi <= 60: final += 5.0
        if d20 and -3.0 <= d20 <= 2.0: final += 4.0
    return max(0.0, min(100.0, round(final, 1)))


def _decide_timing(score: float, ind: dict, mode: str, horizon: str, ev: float | None) -> tuple[str, str, str]:
    """
    진입 타이밍 판단.
    반환: (decisionBucket, timingLabel, timingReason)

    decisionBucket:
      "오늘 진입"   — 지금이 최적 구간 (MA 근처 진입 / 신고가 돌파 / 스퀴즈 돌파)
      "대기 관찰"   — 1~수일 후 더 나은 진입 예상
      "기다림"      — 조건 미충족, 중기 대기
      "보류"        — EV 음수(보수) 또는 과열
    """
    d20 = ind.get("distanceToMa20")
    d60 = ind.get("distanceToMa60")
    rsi = ind.get("rsi14")
    mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20")
    bb_b = ind.get("bbPercentB")
    bb_squeeze = ind.get("bbSqueeze", False)
    ma_conv = _ma_convergence(ind)
    vr = ind.get("volumeRatio20")
    d52 = ind.get("distanceTo52wHigh")
    atr_pct = ind.get("atr14Pct")  # ATR/현재가 비율

    # ── 보류 조건
    if ev is not None and ev < 0 and mode == "conservative":
        return "보류", "매수 보류", "EV 음수 — 기댓값 불리"
    if rsi and rsi >= 80 and not (d52 and d52 >= -1.0 and vr and vr >= 2.0):
        # RSI 과열이어도 신고가 돌파+거래량이면 예외
        return "보류", "과열 대기", f"RSI {rsi:.0f} 과열 — 눌림 확인 후 재진입"
    if bb_b and bb_b > 1.0 and not bb_squeeze:
        return "보류", "과열 대기", "볼린저 상단 돌파 — 추격 금지"

    # ── 오늘 진입 Case 1: 52주 신고가 실제 돌파 (위에 매물 없음)
    # d52 >= 0 = 신고가 갱신 또는 초과, 위에 매물 없음 → 추격 가능
    if d52 is not None and d52 >= 0 and vr is not None and vr >= 1.5:
        if mode == "conservative":
            return "대기 관찰", "신고가 돌파 관찰", f"52주 신고가 돌파 — 보수형은 거래량 추가 확인 후 분할 진입"
        reason = f"52주 신고가 돌파 (d52 +{d52:.1f}%) + 거래량 {vr:.1f}x — 위에 매물 없음"
        return "오늘 진입", "신고가 돌파", reason

    # 신고가 근접 (3% 이내): 돌파 직전 — 대기 관찰로 처리
    if d52 is not None and -3.0 <= d52 < 0 and vr is not None and vr >= 1.3:
        reason = f"52주 신고가 {abs(d52):.1f}% 이내 — 돌파 확인 후 진입 고려"
        return "대기 관찰", "신고가 근접", reason

    # ── 오늘 진입 Case 2: 볼린저 스퀴즈 방향 확정
    if bb_squeeze and bb_b is not None and bb_b > 0.6 and score >= 55:
        reason = f"볼린저 스퀴즈 발산 (B% {bb_b:.2f}) — 상단 방향 확정"
        return "오늘 진입", "스퀴즈 돌파", reason

    # ── 오늘 진입 Case 3: 20일선 근처 + 조건 충족
    entry_zone = d20 is not None and -5.0 <= d20 <= 5.0
    trend_ok = (mom5 is not None and mom5 >= 0) or (mom20 is not None and mom20 >= 0)
    score_ok = score >= 60

    if score_ok and entry_zone and trend_ok:
        if ma_conv:
            return "오늘 진입", "수렴 진입", "이격도 수렴 완성 — 최적 진입 타이밍"
        if d20 is not None and -3.0 <= d20 <= 3.0:
            return "오늘 진입", "즉시 진입", f"20일선 {d20:+.1f}% — 최적 진입 구간"
        return "오늘 진입", "조건부 진입", "점수·추세·진입가 조건 충족"

    # ── 오늘 진입 Case 4: 이격도 수렴 + 모멘텀 전환
    if ma_conv and mom5 is not None and mom5 >= 0 and score >= 55:
        return "오늘 진입", "수렴 진입", "이격도 수렴 중 모멘텀 반등"

    # ── 대기 관찰: 눌리는 중 or 위에 있어서 눌림 기다리는 중
    falling = mom5 is not None and mom5 < 0
    above_ma = d20 is not None and d20 > 5.0
    approaching = d20 is not None and -10.0 <= d20 <= -2.0

    if approaching and falling and score >= 50:
        if horizon == "short":
            reason = f"단기 하락 중 ({mom5:+.1f}%), 1~2일 내 지지 확인 예정"
            return "대기 관찰", "1~2일 후 진입", reason
        elif horizon == "swing":
            reason = f"20일선 {d20:+.1f}%, 3~5일 후 반등 기대"
            return "대기 관찰", "3~5일 후 진입", reason
        else:
            reason = f"20일선 {d20:+.1f}%, 중기 지지선 테스트 — 다음 주 진입"
            return "대기 관찰", "다음 주 진입", reason

    if above_ma and score >= 50:
        if atr_pct and d20:
            pullback_days = max(3, int(d20 / max(atr_pct * 0.5, 0.1)))  # ATR로 눌림 소요 기간 추정
            if pullback_days <= 3:
                return "대기 관찰", "1~2일 후 진입", f"20일선 {d20:+.1f}% — ATR 기준 단기 눌림 가능"
            elif pullback_days <= 7:
                return "대기 관찰", "3~5일 후 진입", f"20일선 {d20:+.1f}% — ATR 기준 {pullback_days}일 눌림 예상"
        return "대기 관찰", "눌림 대기", f"20일선 {d20:+.1f}% 위 — 가격 조정 후 진입"

    if score >= 55 and not entry_zone:
        return "대기 관찰", "진입 조건 대기", "점수 충족, 진입 구간 도달 대기"

    return "기다림", "관망", "점수·추세 조건 미충족"


def _price_band(score: float, current: float, mode: str, horizon: str, ind: dict | None = None) -> tuple[float, float, float, float | None, str]:
    band = _HORIZON_BANDS[horizon]
    rf = _MODE_RISK[mode]; rwf = _MODE_REWARD[mode]
    entry = current

    # ATR 기반 손절가 (데이터 있으면 우선, 없으면 고정 %)
    atr14 = ind.get("atr14") if ind else None
    atr_mult = {"conservative": 1.5, "balanced": 2.0, "aggressive": 2.5}.get(mode, 2.0)
    if atr14 and atr14 > 0 and current > 0:
        atr_stop = round(entry - atr14 * atr_mult)
        fixed_stop = round(entry * (1.0 - (1.0 - band["stop"]) * rf))
        # ATR 손절이 합리적 범위(-3% ~ -15%) 내에 있으면 ATR 우선
        atr_pct = (entry - atr_stop) / entry * 100
        if 2.0 <= atr_pct <= 15.0:
            stop = atr_stop
        else:
            stop = fixed_stop
    else:
        stop = round(entry * (1.0 - (1.0 - band["stop"]) * rf))

    target = round(entry * (1.0 + (band["target"] - 1.0) * rwf))
    # 승률 보정: score는 기술 품질 점수, 승률이 아님 (45~58% 범위)
    _H_BASE  = {"short": 0.485, "swing": 0.505, "mid": 0.515}
    _H_SCALE = {"short": 0.12,  "swing": 0.14,  "mid": 0.15}
    base  = _H_BASE.get(horizon, 0.505)
    scale = _H_SCALE.get(horizon, 0.14)
    prob  = max(0.35, min(0.65, base + (score - 50.0) / 50.0 * scale))

    ev = None
    rr = None
    min_rr = _HORIZON_BANDS[horizon].get("min_rr", 1.5)
    if entry > 0 and stop > 0 and target > entry:
        rew      = (target - entry) / entry * 100
        risk_pct = abs((entry - stop) / entry * 100)
        if risk_pct > 0:
            rr = round(rew / risk_pct, 2)
            ev = round(prob * rew - (1 - prob) * risk_pct, 2)
            # 최소 RR 미달이면 EV 신뢰도 표시
            if rr < min_rr:
                ev = round(ev * 0.7, 2)   # 패널티 적용

    # 타이밍 판단
    if ind is not None:
        decision, timing_label, timing_reason = _decide_timing(score, ind, mode, horizon, ev)
    else:
        decision = "오늘 진입" if score >= 60 else ("대기 관찰" if score >= 50 else "기다림")
        timing_label, timing_reason = "", ""
    return entry, stop, target, ev, decision


def _fmt_krw(v: float) -> str:
    return f"{int(v):,}원"


def _ma_convergence(ind: dict) -> bool:
    """5/20/60일선 이격도 수렴 여부"""
    d20 = ind.get("distanceToMa20"); d60 = ind.get("distanceToMa60")
    ma5 = ind.get("ma5"); ma20 = ind.get("ma20")
    if d20 is None or d60 is None:
        return False
    d5 = (ma5 - ma20) / ma20 * 100 if ma5 and ma20 and ma20 > 0 else None
    within = abs(d20) <= 4.0 and abs(d60) <= 6.0
    if d5 is not None:
        within = within and abs(d5) <= 3.0
    vals = [v for v in [d5, d20, d60] if v is not None]
    spread = max(vals) - min(vals) if len(vals) >= 2 else 999
    return within and spread <= 5.0


def _strategy_tags(ind: dict) -> str:
    tags = []
    rsi = ind.get("rsi14"); d20 = ind.get("distanceToMa20")
    vr = ind.get("volumeRatio20"); mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20"); mdd = ind.get("mdd20"); d60 = ind.get("distanceToMa60")
    bb_b = ind.get("bbPercentB"); cup = ind.get("consecutiveUpDays"); gap = ind.get("gapUpPct")
    d52 = ind.get("distanceTo52wHigh")
    # 이격도 수렴 (우선 체크)
    if _ma_convergence(ind) and (not rsi or rsi < 75):
        tags.append("이격도 수렴")
    if d20 and -8 <= d20 <= 3 and (not rsi or rsi < 80): tags.append("눌림목 매수")
    if vr and vr >= 1.5: tags.append("거래대금 증가")
    if (mom5 and mom5 > 3) or (mom20 and mom20 > 8): tags.append("모멘텀 강세")
    if mdd and mdd > -12 and (not d60 or d60 > -8): tags.append("안정형")
    if (rsi and rsi >= 80) or (bb_b and bb_b > 1) or (gap and gap >= 15) or (cup and cup >= 5 and vr and vr < 0.7):
        tags.append("주의")
    return " | ".join(tags) if tags else "판단 대기"


def _load_market_regime() -> dict[str, Any]:
    """KOSPI benchmark_daily.csv에서 마켓 레짐 판단"""
    path = ROOT / "data" / "market" / "benchmark_daily.csv"
    rows = [r for r in _read_csv(path) if str(r.get("benchmark", "")).upper() == "KOSPI"]
    rows.sort(key=lambda r: str(r.get("date", "")))
    closes = [_num(r.get("close")) for r in rows]
    closes = [c for c in closes if c is not None]
    if len(closes) < 20:
        return {"regime": "SIDE", "label": "횡보장", "scoreAdjust": 0.0, "description": "데이터 부족"}
    latest = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    dist = (latest - ma20) / ma20 * 100
    mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
    if dist > 0 and mom5 > 0:
        return {"regime": "BULL", "label": "강세장", "scoreAdjust": +5.0,
                "description": f"KOSPI 20일선 {dist:+.1f}%, 5일 {mom5:+.1f}%",
                "kospiLatest": round(latest, 0), "distToMa20": round(dist, 2)}
    elif dist < -2.0 or mom5 < -2.0:
        return {"regime": "BEAR", "label": "약세장", "scoreAdjust": -8.0,
                "description": f"KOSPI 20일선 {dist:+.1f}%, 5일 {mom5:+.1f}%",
                "kospiLatest": round(latest, 0), "distToMa20": round(dist, 2)}
    return {"regime": "SIDE", "label": "횡보장", "scoreAdjust": 0.0,
            "description": f"KOSPI 20일선 {dist:+.1f}%, 5일 {mom5:+.1f}%",
            "kospiLatest": round(latest, 0), "distToMa20": round(dist, 2)}


# ── KIS 현재가 로드

def _load_kis_prices() -> dict[str, float]:
    prices: dict[str, float] = {}
    for p in [
        REPORTS / "kis_current_price_kr.csv",
        DATA_STOCKAPP / "kis_current_price_kr.csv",
        REPORTS / "intraday_realtime_snapshot_kr.csv",
    ]:
        for row in _read_csv(p):
            sym = str(row.get("symbol", "")).strip().lstrip("0") or str(row.get("symbol", "")).strip()
            # 원래 심볼도 저장
            sym_raw = str(row.get("symbol", "")).strip()
            price = _num(row.get("currentPrice") or row.get("current_price") or row.get("last_price"))
            ok = str(row.get("ok", "")).lower() in {"true", "1", "yes"}
            if price and price > 0 and ok:
                prices[sym_raw] = price
                prices[sym_raw.lstrip("0")] = price
    return prices


# ── 심볼 이름 맵 (watchlist, holdings, symbol master에서)

def _load_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    candidates = [
        ROOT / "watchlist_kr.csv",
        ROOT / "data" / "watchlist_kr.csv",
        ROOT / "holdings_kr.csv",
        ROOT / "data" / "holdings_kr.csv",
    ]
    # OHLCV 파일명에서 심볼 추출
    for path in candidates:
        for row in _read_csv(path):
            sym = str(row.get("symbol") or row.get("종목코드") or "").strip()
            name = str(row.get("name") or row.get("종목명") or "").strip()
            if sym and name:
                names[sym] = name
    return names


# ══════════════════════════════════════════════
# A-1: 뉴스/공시 감성 점수 (newsRiskPenalty 실제화)
# ══════════════════════════════════════════════

# 리스크 키워드 → 감점 / 호재 키워드 → 가산
_RISK_KEYWORDS: list[tuple[str, float]] = [
    # 매우 위험
    ("유상증자", -15.0), ("증자", -10.0), ("전환사채", -12.0), ("CB발행", -12.0),
    ("신주인수권", -10.0), ("BW발행", -10.0), ("관리종목", -20.0), ("상장폐지", -25.0),
    ("감자", -20.0), ("횡령", -20.0), ("배임", -18.0), ("불성실공시", -15.0),
    ("감사의견", -12.0), ("소송", -8.0), ("영업손실", -8.0), ("적자전환", -10.0),
    ("부도", -25.0), ("워크아웃", -20.0), ("법정관리", -25.0),
    # 경미한 위험
    ("주식분산", -5.0), ("지분변동", -4.0), ("최대주주변경", -6.0),
    ("임원보수", -3.0), ("스톡옵션", -3.0),
    # 매크로/실적 리스크
    ("어닝쇼크", -12.0), ("실적쇼크", -12.0), ("실적 하회", -10.0), ("가이던스 하향", -8.0),
    ("금리인상", -6.0), ("긴축", -5.0), ("관세", -6.0), ("무역분쟁", -5.0),
    ("환율 급등", -5.0), ("원/달러 급등", -5.0), ("인플레이션", -4.0),
]
_POSITIVE_KEYWORDS: list[tuple[str, float]] = [
    # 매우 긍정
    ("수주", +8.0), ("공급계약", +8.0), ("대형계약", +10.0), ("FDA승인", +12.0),
    ("임상성공", +10.0), ("흑자전환", +8.0), ("최대실적", +10.0), ("자사주매입", +6.0),
    ("배당증가", +5.0), ("배당확대", +5.0), ("자사주소각", +8.0),
    # 경미한 긍정
    ("수출증가", +4.0), ("매출증가", +3.0), ("영업이익증가", +5.0),
    ("신제품", +3.0), ("기술이전", +4.0), ("MOU", +3.0), ("협약", +2.0),
    # 매크로/실적 호재
    ("어닝서프라이즈", +10.0), ("실적 상회", +8.0), ("가이던스 상향", +7.0),
    ("금리인하", +5.0), ("금리 동결", +3.0), ("무역합의", +5.0),
    ("IPO 수혜", +4.0), ("신규상장", +3.0), ("MSCI 편입", +6.0),
    ("코스피 편입", +5.0), ("코스닥 편입", +4.0),
]


def _load_news_sentiment() -> dict[str, float]:
    """
    공시/뉴스 CSV에서 종목별 감성 점수 계산.
    반환: {symbol: news_penalty}  — 양수 = 리스크, 음수 = 호재
    (generate_kr_recommendations에서 newsRiskPenalty에 직접 반영)
    """
    scores: dict[str, list[float]] = {}

    def _score_text(text: str) -> float:
        s = 0.0
        for kw, v in _RISK_KEYWORDS:
            if kw in text:
                s += v
        for kw, v in _POSITIVE_KEYWORDS:
            if kw in text:
                s += v
        return s

    # 공시 데이터 (종목코드 직접 연결)
    for path in [ROOT / "data" / "disclosures" / "disclosures_kr.csv",
                 REPORTS / "disclosures_kr.csv"]:
        for row in _read_csv(path):
            sym = str(row.get("symbol", "")).strip()
            title = str(row.get("title", ""))
            if not sym or not title:
                continue
            s = _score_text(title)
            if s != 0:
                scores.setdefault(sym, []).append(s)
                scores.setdefault(sym.lstrip("0"), []).append(s)

    # 뉴스 데이터 (종목코드 있는 것만)
    for path in [REPORTS / "news_summary_kr.csv", REPORTS / "news_cards_kr.csv"]:
        for row in _read_csv(path):
            sym = str(row.get("종목코드", "") or row.get("symbol", "")).strip()
            title = str(row.get("제목", "") or row.get("title", "") or row.get("3줄요약", ""))
            if not sym or not title or sym == "종목":
                continue
            s = _score_text(title)
            if s != 0:
                scores.setdefault(sym, []).append(s)

    # 종목별 평균 → 감점 변환 (양수 = 리스크 감점)
    result: dict[str, float] = {}
    for sym, vals in scores.items():
        avg = sum(vals) / len(vals)
        # 리스크: 감점 (0~20), 호재: 감점 완화 (-5~0)
        penalty = max(-5.0, min(20.0, -avg))
        result[sym] = round(penalty, 1)
    return result


# ══════════════════════════════════════════════
# A-2: 재무 데이터 연결 (저평가 성장주 태그)
# ══════════════════════════════════════════════

def _load_financial_data() -> dict[str, dict[str, Any]]:
    """
    v93_company_integrated_kr.csv + v92_company_integrated_kr.csv에서
    종목별 재무 지표 로드.
    반환: {symbol: {roe, per, pbr, value_score, growth_score, stability_score}}
    """
    fin: dict[str, dict[str, Any]] = {}
    for path in [
        REPORTS / "v93_company_integrated_kr.csv",
        REPORTS / "v92_company_integrated_kr.csv",
        REPORTS / "v92_company_clean_kr.csv",
    ]:
        for row in _read_csv(path):
            sym = str(row.get("종목코드", "") or row.get("symbol", "")).strip()
            if not sym:
                continue
            roe = _num(row.get("ROE"))
            per = _num(row.get("PER"))
            pbr = _num(row.get("PBR"))
            value_score = _num(row.get("가치점수") or row.get("value_score"))
            growth_score = _num(row.get("성장점수") or row.get("growth_score"))
            stability_score = _num(row.get("안정성점수") or row.get("stability_score"))
            total_score = _num(row.get("종합점수") or row.get("total_score"))
            # 이미 있으면 더 나은 데이터(값이 있는)로 업데이트
            existing = fin.get(sym, {})
            fin[sym] = {
                "roe": roe if roe is not None else existing.get("roe"),
                "per": per if per is not None else existing.get("per"),
                "pbr": pbr if pbr is not None else existing.get("pbr"),
                "value_score": value_score if value_score is not None else existing.get("value_score"),
                "growth_score": growth_score if growth_score is not None else existing.get("growth_score"),
                "stability_score": stability_score if stability_score is not None else existing.get("stability_score"),
                "total_score": total_score if total_score is not None else existing.get("total_score"),
            }
            fin[sym.lstrip("0")] = fin[sym]
    return fin


def _is_undervalued_growth(sym: str, fin_map: dict[str, dict]) -> tuple[bool, str]:
    """
    저평가 성장주 판단:
    - ROE > 10% (수익성)
    - 가치점수 > 55 또는 PBR < 2.0
    - 성장점수 > 55 (있을 경우)
    반환: (해당 여부, 근거)
    """
    data = fin_map.get(sym) or fin_map.get(sym.lstrip("0")) or {}
    roe = data.get("roe")
    per = data.get("per")
    pbr = data.get("pbr")
    value_score = data.get("value_score")
    growth_score = data.get("growth_score")

    if not data:
        return False, ""

    reasons = []
    score = 0

    if roe is not None and roe > 10:
        reasons.append(f"ROE {roe:.1f}%")
        score += 2
    if roe is not None and roe > 15:
        score += 1  # 추가 가산

    if value_score is not None and value_score > 55:
        reasons.append(f"가치{value_score:.0f}점")
        score += 1
    elif pbr is not None and pbr < 2.0:
        reasons.append(f"PBR {pbr:.1f}")
        score += 1

    if growth_score is not None and growth_score > 55:
        reasons.append(f"성장{growth_score:.0f}점")
        score += 1

    if per is not None and per < 15:
        reasons.append(f"PER {per:.1f}")
        score += 1

    return score >= 2, " · ".join(reasons) if reasons else ""


# ══════════════════════════════════════════════
# A-3: 기관/외국인 순매수 신호
# ══════════════════════════════════════════════

def _load_supply_data() -> dict[str, dict[str, Any]]:
    """
    predictions.csv의 KIS 수급 데이터에서 종목별 최신 기관/외국인 순매수 로드.
    반환: {symbol: {inst5d, foreign5d, inst20d, foreign20d, signal}}
    """
    supply: dict[str, dict[str, Any]] = {}

    # predictions.csv — 종목별 가장 최신 행만 사용
    pred_path = ROOT / "predictions.csv"
    if not pred_path.exists():
        return supply

    latest_by_sym: dict[str, dict] = {}
    for row in _read_csv(pred_path):
        mkt = str(row.get("market", "")).lower()
        if "한국" not in mkt and mkt != "kr":
            continue
        sym = str(row.get("ticker") or row.get("symbol") or "").strip()
        if not sym:
            continue
        created = str(row.get("created_at", ""))
        existing = latest_by_sym.get(sym)
        if existing is None or created > str(existing.get("created_at", "")):
            latest_by_sym[sym] = row

    for sym, row in latest_by_sym.items():
        inst5d = _num(row.get("kis_institution_5d"))
        foreign5d = _num(row.get("kis_foreign_5d"))
        inst20d = _num(row.get("kis_institution_20d"))
        foreign20d = _num(row.get("kis_foreign_20d"))

        # 순매수 신호 판단
        signal = "NEUTRAL"
        signal_score = 0.0
        if inst5d is not None and inst5d > 0:
            signal_score += 1.0
        if inst20d is not None and inst20d > 0:
            signal_score += 1.0
        if foreign5d is not None and foreign5d > 0:
            signal_score += 1.0
        if foreign20d is not None and foreign20d > 0:
            signal_score += 0.5
        # 기관+외국인 동시 순매수
        if inst5d and inst5d > 0 and foreign5d and foreign5d > 0:
            signal = "STRONG_BUY"
            signal_score += 2.0
        elif inst5d and inst5d > 0:
            signal = "INST_BUY"
        elif foreign5d and foreign5d > 0:
            signal = "FOREIGN_BUY"
        elif inst5d and inst5d < 0 and foreign5d and foreign5d < 0:
            signal = "SELL_PRESSURE"
            signal_score -= 2.0

        supply[sym] = {
            "inst5d": inst5d, "foreign5d": foreign5d,
            "inst20d": inst20d, "foreign20d": foreign20d,
            "signal": signal, "signal_score": round(signal_score, 1),
        }
        supply[sym.lstrip("0")] = supply[sym]

    return supply


def _supply_score_adjust(sym: str, supply_map: dict) -> tuple[float, str]:
    """수급 신호 → 점수 가산/감점, 태그 반환"""
    data = supply_map.get(sym) or supply_map.get(sym.lstrip("0")) or {}
    if not data:
        return 0.0, ""
    signal = data.get("signal", "NEUTRAL")
    score = data.get("signal_score", 0.0)
    adjust = min(8.0, max(-8.0, score * 2.0))
    label = {
        "STRONG_BUY": "기관+외국인 동반매수",
        "INST_BUY": "기관 순매수",
        "FOREIGN_BUY": "외국인 순매수",
        "SELL_PRESSURE": "기관+외국인 순매도",
        "NEUTRAL": "",
    }.get(signal, "")
    return adjust, label


# ── 메인 생성 로직

def _load_ohlcv_all() -> dict[str, list[dict]]:
    """모든 KR OHLCV 파일 로드 → {symbol: rows}"""
    result: dict[str, list[dict]] = {}
    for path in sorted(OHLCV_DIR.glob("kr_*_daily.csv")):
        m = re.match(r"kr_(\w+)_daily\.csv", path.name)
        if not m:
            continue
        sym = m.group(1)
        rows = _read_csv(path)
        rows.sort(key=lambda r: str(r.get("date") or r.get("Date") or ""))
        if len(rows) >= MIN_OHLCV_ROWS:
            result[sym] = rows
    return print(f"  OHLCV 로드: {len(result)}종목") or result  # type: ignore[func-returns-value]


def _load_ohlcv_all_quiet() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for path in sorted(OHLCV_DIR.glob("kr_*_daily.csv")):
        m = re.match(r"kr_(\w+)_daily\.csv", path.name)
        if not m:
            continue
        sym = m.group(1)
        rows = _read_csv(path)
        rows.sort(key=lambda r: str(r.get("date") or r.get("Date") or ""))
        if len(rows) >= MIN_OHLCV_ROWS:
            result[sym] = rows
    return result


def generate_recommendations() -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] KR 추천 파일 생성 시작")

    ohlcv_all = _load_ohlcv_all_quiet()
    kis_prices = _load_kis_prices()
    name_map = _load_name_map()
    regime = _load_market_regime()
    news_sentiment = _load_news_sentiment()
    fin_data = _load_financial_data()
    supply_data = _load_supply_data()

    print(f"  OHLCV: {len(ohlcv_all)}종목, KIS 현재가: {len(kis_prices)}종목")
    print(f"  뉴스/공시 감성: {len(news_sentiment)}종목, 재무: {len(fin_data)//2}종목, 수급: {len(supply_data)//2}종목")
    print(f"  마켓 레짐: {regime['label']} ({regime['description']})")

    regime_adjust = regime.get("scoreAdjust", 0.0)
    regime_label = regime.get("label", "횡보장")
    regime_type = regime.get("regime", "SIDE")

    # 약세장: 보수형만 허용, 최소 점수 상향
    min_score_by_regime = {"BULL": 45.0, "SIDE": 50.0, "BEAR": 58.0}
    min_score_global = min_score_by_regime.get(regime_type, 50.0)

    # 전체 종목 스코어 계산
    all_scored: list[dict] = []
    for sym, rows in ohlcv_all.items():
        ind = indicators(rows)
        latest = ind.get("latest")
        if not latest or latest <= 0:
            continue
        current = kis_prices.get(sym) or kis_prices.get(sym.lstrip("0")) or latest
        ind["latest"] = current
        ma20 = ind.get("ma20")
        if ma20:
            ind["distanceToMa20"] = (current - ma20) / ma20 * 100
        # ROE 주입 (qualityScore 계산에 사용)
        fin = fin_data.get(sym) or fin_data.get(sym.lstrip("0")) or {}
        if fin.get("roe") is not None:
            ind["roe"] = fin["roe"]
        score_bal = _final_score(ind, "balanced", "swing")
        all_scored.append({
            "symbol": sym,
            "name": name_map.get(sym, sym),
            "current": current,
            "ind": ind,
            "score_base": score_bal,
            "price_source": "kis" if kis_prices.get(sym) or kis_prices.get(sym.lstrip("0")) else "ohlcv",
        })

    all_scored.sort(key=lambda x: x["score_base"], reverse=True)

    results: dict[str, int] = {}
    ev_filtered = 0
    regime_filtered = 0
    REPORTS.mkdir(parents=True, exist_ok=True)

    for mode in MODES:
        # 약세장에서는 공격형 비활성화
        if regime_type == "BEAR" and mode == "aggressive":
            # 빈 파일만 생성
            for horizon in HORIZONS:
                out_path = REPORTS / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"
                _write_csv(out_path, [])
                tv_path = REPORTS / f"mone_v36_final_trade_validation_kr_{mode}_{horizon}.csv"
                _write_csv(tv_path, [])
                results[f"{mode}_{horizon}"] = 0
            print(f"  [{mode:12s}] 약세장으로 비활성화")
            continue

        for horizon in HORIZONS:
            rows_out: list[dict] = []
            scored_combo: list[tuple[float, dict]] = []
            for c in all_scored:
                ind = c["ind"]
                base_score = _final_score(ind, mode, horizon)
                # 마켓 레짐 보정 (강세: +5, 약세: -8)
                adj_score = max(0.0, min(100.0, base_score + regime_adjust))
                scored_combo.append((adj_score, base_score, c))
            scored_combo.sort(key=lambda x: x[0], reverse=True)

            count = 0
            for adj_score, base_score, c in scored_combo:
                if count >= TOP_N:
                    break
                # 최소 점수 필터 (레짐별)
                if adj_score < min_score_global:
                    regime_filtered += 1
                    continue

                sym = c["symbol"]
                current = c["current"]
                ind = c["ind"]
                entry, stop, target, ev, decision = _price_band(adj_score, current, mode, horizon, ind)

                # EV 음수 필터링 (보수형은 엄격, 균형/공격은 경고만)
                if ev is not None and ev < 0:
                    if mode == "conservative":
                        ev_filtered += 1
                        continue
                    decision = "기다림"

                # 타이밍 상세
                _, timing_label, timing_reason = _decide_timing(adj_score, ind, mode, horizon, ev)

                # A-1: 뉴스/공시 감성 점수 반영
                news_penalty = news_sentiment.get(sym, news_sentiment.get(sym.lstrip("0"), 0.0))

                # A-3: 기관/외국인 수급 점수 반영
                supply_adjust, supply_label = _supply_score_adjust(sym, supply_data)

                # 최종 조정 점수 (뉴스 감점 + 수급 가산)
                adj_score_final = max(0.0, min(100.0, adj_score - news_penalty + supply_adjust))

                # A-2: 저평가 성장주 태그
                is_undervalued, fin_reason = _is_undervalued_growth(sym, fin_data)

                sub = _sub_scores(ind)
                tags_list = []
                if _ma_convergence(ind) and (not ind.get("rsi14") or ind["rsi14"] < 75):
                    tags_list.append("이격도수렴")
                d20 = ind.get("distanceToMa20")
                rsi = ind.get("rsi14")
                if d20 and -8 <= d20 <= 3 and (not rsi or rsi < 80):
                    tags_list.append("눌림목매수")
                if supply_label:
                    tags_list.append(supply_label)
                if is_undervalued:
                    tags_list.append("저평가성장주")
                vr = ind.get("volumeRatio20")
                if vr and vr >= 1.5:
                    tags_list.append("거래대금증가")
                mom5 = ind.get("recentMomentum5")
                mom20 = ind.get("recentMomentum20")
                if (mom5 and mom5 > 3) or (mom20 and mom20 > 8):
                    tags_list.append("모멘텀강세")
                if news_penalty >= 10.0:
                    tags_list.append("공시주의")
                if not tags_list:
                    tags_list.append("안정형")
                tags = " | ".join(tags_list)

                rr = round((target - entry) / max(entry - stop, 1), 2) if stop < entry else None
                rank_score = adj_score_final
                ev_negative = ev is not None and ev < 0
                ma_conv = _ma_convergence(ind)
                fin_info = fin_data.get(sym) or fin_data.get(sym.lstrip("0")) or {}
                supply_info = supply_data.get(sym) or supply_data.get(sym.lstrip("0")) or {}
                row = {
                    "market": "kr",
                    "mode": mode,
                    "modeLabel": MODE_LABELS[mode],
                    "horizon": horizon,
                    "horizonLabel": HORIZON_LABELS[horizon],
                    "symbol": sym,
                    "name": c["name"],
                    "decisionBucket": decision,
                    "timingLabel": timing_label,
                    "timingReason": timing_reason,
                    # 대기 관찰용 예상 진입가 (현재가보다 1~3% 낮은 수준)
                    "expectedEntryPrice": _fmt_krw(round(current * 0.98)) if decision == "대기 관찰" else "",
                    "newEntryDecision": "조건부 진입" if adj_score_final >= 55 and not ev_negative else "대기",
                    "holderDecision": "보유자는 목표가·손절가 대응",
                    "buyTiming": "조건부 매수 등록" if decision == "오늘 진입" else "기준가 도달 대기",
                    "sellTiming": "목표가 도달 시 분할익절 / 손절가 이탈 시 종료 / 보유기간 종료 시 재검토",
                    "entry": _fmt_krw(entry),
                    "stop":  _fmt_krw(stop),
                    "target": _fmt_krw(target),
                    "probability": f"{round(adj_score_final, 1)}%",
                    "expectedPrice": _fmt_krw(round(current * (1 + (adj_score_final/100 - 0.5) * 0.1))),
                    "opportunityScore": round(sub["upsideScore"] * 0.6 + sub["momentumScore"] * 0.4, 1),
                    "entryScore": round(sub["entryScore"], 1),
                    "riskScore": round(sub["riskScore"], 1),
                    "eventRiskScore": round(news_penalty, 1),
                    "newsReliabilityScore": round(50 - news_penalty, 1),
                    "newsRiskPenalty": round(news_penalty, 1),
                    "newsSentimentSource": "keyword" if news_sentiment.get(sym) is not None else "none",
                    "finalRankScore": round(adj_score_final, 1),
                    "finalScore": round(adj_score_final, 1),
                    "baseScore": round(base_score, 1),
                    "upsideScore": sub["upsideScore"],
                    "momentumScore": sub["momentumScore"],
                    "rrScore": sub["rrScore"],
                    "qualityScore": sub["qualityScore"],
                    "expectedValue": ev if ev is not None else "",
                    "evNegative": ev_negative,
                    "rrActual": rr if rr is not None else "",
                    "maConvergence": ma_conv,
                    # 재무 데이터
                    "roe": fin_info.get("roe", ""),
                    "per": fin_info.get("per", ""),
                    "pbr": fin_info.get("pbr", ""),
                    "finValueScore": fin_info.get("value_score", ""),
                    "finGrowthScore": fin_info.get("growth_score", ""),
                    "finStabilityScore": fin_info.get("stability_score", ""),
                    "isUndervaluedGrowth": is_undervalued,
                    "finReason": fin_reason,
                    # 수급 데이터
                    "instBuy5d": supply_info.get("inst5d", ""),
                    "foreignBuy5d": supply_info.get("foreign5d", ""),
                    "supplySignal": supply_info.get("signal", "NEUTRAL"),
                    "supplyScoreAdj": supply_adjust,
                    "surgeLabel": tags,
                    "eventBadges": " | ".join(filter(None, [
                        "EV음수" if ev_negative else "",
                        "이격도수렴" if ma_conv else "",
                        supply_label if supply_label else "",
                        "저평가성장주" if is_undervalued else "",
                        "공시주의" if news_penalty >= 10 else "",
                    ])),
                    "marketRegime": regime_label,
                    "marketRegimeAdjust": regime_adjust,
                    "executionStatus": "체결" if decision == "오늘 진입" else "대기",
                    "exitStatus": "",
                    "pnlText": "",
                    "excludedFromReturn": ev_negative,
                    "sourceBucket": "ohlcv_quant",
                    "dataStatus": "NORMAL" if c["price_source"] == "kis" else "PARTIAL",
                    "priceSource": c["price_source"],
                    "currentPrice": current,
                    "generatedAt": now,
                }
                rows_out.append(row)
                count += 1

            key = f"{mode}_{horizon}"
            out_path = REPORTS / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"
            _write_csv(out_path, rows_out)
            results[key] = len(rows_out)
            print(f"  [{mode:12s}/{horizon:5s}] {len(rows_out):2d}종목 → {out_path.name}")

            # trade_validation 파일도 생성
            tv_path = REPORTS / f"mone_v36_final_trade_validation_kr_{mode}_{horizon}.csv"
            tv_rows = [{**r, "validationStatus": "PENDING", "validationDate": ""} for r in rows_out]
            _write_csv(tv_path, tv_rows)

    # 상태 파일 업데이트
    status = {
        "generatedAt": now,
        "source": "ohlcv_quant_scanner",
        "symbols": len(ohlcv_all),
        "kisSymbols": len(kis_prices),
        "newsSentimentSymbols": len(news_sentiment),
        "financialSymbols": len(fin_data) // 2,
        "supplySymbols": len(supply_data) // 2,
        "marketRegime": regime,
        "evFiltered": ev_filtered,
        "regimeFiltered": regime_filtered,
        "results": results,
    }
    (REPORTS / "kr_recommendation_gen_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(results.values())
    print(f"[{now}] 완료: {total}건 생성 (EV음수 제외 {ev_filtered}건, 레짐필터 {regime_filtered}건)")
    return status


if __name__ == "__main__":
    generate_recommendations()
