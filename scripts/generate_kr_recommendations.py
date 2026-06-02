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


def _price_band(score: float, current: float, mode: str, horizon: str) -> tuple[float, float, float, float | None, str]:
    band = _HORIZON_BANDS[horizon]
    rf = _MODE_RISK[mode]; rwf = _MODE_REWARD[mode]
    entry = current
    stop = round(entry * (1.0 - (1.0 - band["stop"]) * rf))
    target = round(entry * (1.0 + (band["target"] - 1.0) * rwf))
    ev = None
    if entry > 0 and stop > 0 and target > entry:
        prob = score / 100.0
        rew = (target - entry) / entry * 100
        risk_pct = abs((entry - stop) / entry * 100)
        if risk_pct > 0:
            ev = round(prob * rew - (1 - prob) * risk_pct, 2)
    rr = round((target - entry) / max(entry - stop, 1), 2) if stop < entry else None
    decision = "오늘 진입" if score >= 55 else "기다림"
    return entry, stop, target, ev, decision


def _fmt_krw(v: float) -> str:
    return f"{int(v):,}원"


def _strategy_tags(ind: dict) -> str:
    tags = []
    rsi = ind.get("rsi14"); d20 = ind.get("distanceToMa20")
    vr = ind.get("volumeRatio20"); mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20"); mdd = ind.get("mdd20"); d60 = ind.get("distanceToMa60")
    bb_b = ind.get("bbPercentB"); cup = ind.get("consecutiveUpDays"); gap = ind.get("gapUpPct")
    d52 = ind.get("distanceTo52wHigh")
    if d20 and -8 <= d20 <= 3 and (not rsi or rsi < 80): tags.append("눌림목 매수")
    if vr and vr >= 1.5: tags.append("거래대금 증가")
    if (mom5 and mom5 > 3) or (mom20 and mom20 > 8): tags.append("모멘텀 강세")
    if mdd and mdd > -12 and (not d60 or d60 > -8): tags.append("안정형")
    if (rsi and rsi >= 80) or (bb_b and bb_b > 1) or (gap and gap >= 15) or (cup and cup >= 5 and vr and vr < 0.7):
        tags.append("주의")
    return " | ".join(tags) if tags else "판단 대기"


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

    print(f"  OHLCV: {len(ohlcv_all)}종목, KIS 현재가: {len(kis_prices)}종목")

    # 전체 종목 스코어 계산 (mode=balanced, horizon=swing 기준으로 1차 필터)
    all_scored: list[dict] = []
    for sym, rows in ohlcv_all.items():
        ind = indicators(rows)
        latest = ind.get("latest")
        if not latest or latest <= 0:
            continue
        # KIS 현재가 우선, 없으면 OHLCV 최신 close
        current = kis_prices.get(sym) or kis_prices.get(sym.lstrip("0")) or latest
        ind["latest"] = current  # 현재가 업데이트
        # distanceToMa20 재계산 (현재가 기준)
        ma20 = ind.get("ma20")
        if ma20:
            ind["distanceToMa20"] = (current - ma20) / ma20 * 100
        score_bal = _final_score(ind, "balanced", "swing")
        all_scored.append({
            "symbol": sym,
            "name": name_map.get(sym, sym),
            "current": current,
            "ind": ind,
            "score_base": score_bal,
            "price_source": "kis" if kis_prices.get(sym) or kis_prices.get(sym.lstrip("0")) else "ohlcv",
        })

    # 스코어 상위 TOP_N * 2 종목으로 후보 축소 (성능)
    all_scored.sort(key=lambda x: x["score_base"], reverse=True)
    candidates = all_scored[:min(len(all_scored), TOP_N * 3)]

    results: dict[str, int] = {}
    REPORTS.mkdir(parents=True, exist_ok=True)

    for mode in MODES:
        for horizon in HORIZONS:
            rows_out: list[dict] = []
            scored_combo: list[tuple[float, dict]] = []
            for c in all_scored:  # 전체에서 각 조합별 재스코어
                ind = c["ind"]
                score = _final_score(ind, mode, horizon)
                scored_combo.append((score, c))
            scored_combo.sort(key=lambda x: x[0], reverse=True)
            top = scored_combo[:TOP_N]

            for score, c in top:
                sym = c["symbol"]
                current = c["current"]
                ind = c["ind"]
                entry, stop, target, ev, decision = _price_band(score, current, mode, horizon)
                sub = _sub_scores(ind)
                tags = _strategy_tags(ind)
                rr = round((target - entry) / max(entry - stop, 1), 2) if stop < entry else None
                rank_score = sub["opportunityScore"] * 0.45 + sub["entryScore"] * 0.35 if "opportunityScore" in sub else score
                row = {
                    "market": "kr",
                    "mode": mode,
                    "modeLabel": MODE_LABELS[mode],
                    "horizon": horizon,
                    "horizonLabel": HORIZON_LABELS[horizon],
                    "symbol": sym,
                    "name": c["name"],
                    "decisionBucket": decision,
                    "newEntryDecision": "조건부 진입" if score >= 55 else "대기",
                    "holderDecision": "보유자는 목표가·손절가 대응",
                    "buyTiming": "조건부 매수 등록" if decision == "오늘 진입" else "기준가 도달 대기",
                    "sellTiming": "목표가 도달 시 분할익절 / 손절가 이탈 시 종료 / 보유기간 종료 시 재검토",
                    "entry": _fmt_krw(entry),
                    "stop":  _fmt_krw(stop),
                    "target": _fmt_krw(target),
                    "probability": f"{round(score, 1)}%",
                    "expectedPrice": _fmt_krw(round(current * (1 + (score/100 - 0.5) * 0.1))),
                    "opportunityScore": round(sub["upsideScore"] * 0.6 + sub["momentumScore"] * 0.4, 1),
                    "entryScore": round(sub["entryScore"], 1),
                    "riskScore": round(sub["riskScore"], 1),
                    "eventRiskScore": 0,
                    "newsReliabilityScore": 50,
                    "finalRankScore": round(score, 1),
                    "finalScore": round(score, 1),
                    "upsideScore": sub["upsideScore"],
                    "momentumScore": sub["momentumScore"],
                    "rrScore": sub["rrScore"],
                    "qualityScore": sub["qualityScore"],
                    "expectedValue": ev if ev is not None else "",
                    "rrActual": rr if rr is not None else "",
                    "surgeLabel": tags,
                    "eventBadges": "",
                    "executionStatus": "체결" if decision == "오늘 진입" else "대기",
                    "exitStatus": "",
                    "pnlText": "",
                    "excludedFromReturn": False,
                    "sourceBucket": "ohlcv_quant",
                    "dataStatus": "NORMAL" if c["price_source"] == "kis" else "PARTIAL",
                    "priceSource": c["price_source"],
                    "currentPrice": current,
                    "generatedAt": now,
                }
                rows_out.append(row)

            key = f"{mode}_{horizon}"
            out_path = REPORTS / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"
            _write_csv(out_path, rows_out)
            results[key] = len(rows_out)
            print(f"  [{mode:12s}/{horizon:5s}] {len(rows_out):2d}종목 → {out_path.name}")

            # trade_validation 파일도 생성 (동일 내용 기반)
            tv_path = REPORTS / f"mone_v36_final_trade_validation_kr_{mode}_{horizon}.csv"
            tv_rows = [{**r, "validationStatus": "PENDING", "validationDate": ""} for r in rows_out]
            _write_csv(tv_path, tv_rows)

    # 상태 파일 업데이트
    status = {
        "generatedAt": now,
        "source": "ohlcv_quant_scanner",
        "symbols": len(ohlcv_all),
        "kisSymbols": len(kis_prices),
        "results": results,
    }
    (REPORTS / "kr_recommendation_gen_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{now}] 완료: {sum(results.values())}건 생성")
    return status


if __name__ == "__main__":
    generate_recommendations()
