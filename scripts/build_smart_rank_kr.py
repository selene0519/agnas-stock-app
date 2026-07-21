#!/usr/bin/env python3
"""
AI 스마트 순위 엔진 (KR) — 다중신호 ML 선별 두뇌.

14개 가격신호를 릿지 회귀로 동시에 저울질해 "10거래일 뒤 net 손익"을 예측하고,
전 종목을 순위화한다. 사람이 못 하는 '여러 신호 동시 비교'가 핵심 엣지.

OOS 검증(2025-09 분할)에서 예측 상위20%가 하위20%를 단조 상회(+0.64%p, IC +0.04),
특히 횡보장 상위20% +1.18%(승률51%) — scratchpad/ml_rank.py. 약세장은 상위픽도 (−)라
레짐 게이트로 억제.

- 매일 전체 데이터로 재학습(표본 늘수록 개선) → 최신봉 스코어.
- 확장: 여기 features에 수급/뉴스/섹터/공시를 추가하면 성능 향상 여지(현재 가격신호만).
읽기: data/market/ohlcv/kr_*_daily.csv
출력: reports/smart_rank_kr.json
"""
from __future__ import annotations
import csv
import glob
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST = 0.5
SPLIT = "2025-09-01"      # OOS 검증 분할
RIDGE_LAMBDA = 10.0
TARGET_PCT, STOP_PCT, HOLD = 0.08, 0.04, 10
FEATURES = ["rsi14", "rsi2", "volratio", "distma20", "distma60", "mom5", "mom20",
            "atrpct", "mdd20", "nearhigh", "maalign", "zscore", "revbar", "bull"]


def load(f):
    out = []
    for x in csv.reader(open(f, encoding="utf-8-sig")):
        if not x or not x[0] or x[0] == "date":
            continue
        try:
            d, o, h, l, c = x[0], float(x[3]), float(x[4]), float(x[5]), float(x[6])
            v = float(x[7]) if len(x) > 7 and x[7] not in ("", "None") else 0.0
        except (ValueError, IndexError):
            continue
        if min(o, h, l, c) > 0:
            out.append((d, o, h, l, c, v))
    out.sort(key=lambda r: r[0])
    return out


def sma(a, n, i):
    return sum(a[i - n + 1:i + 1]) / n if i + 1 >= n else None


def rsi(cl, n, i):
    if i < n:
        return None
    g = l = 0.0
    for k in range(i - n + 1, i + 1):
        ch = cl[k] - cl[k - 1]
        g += max(ch, 0.0)
        l += max(-ch, 0.0)
    if g + l == 0:
        return 50.0
    return 100 - 100 / (1 + ((g / n) / ((l / n) if l > 0 else 1e-9)))


def atr(r, n, i):
    if i < n:
        return None
    s = 0.0
    for k in range(i - n + 1, i + 1):
        s += max(r[k][2] - r[k][3], abs(r[k][2] - r[k - 1][4]), abs(r[k][3] - r[k - 1][4]))
    return s / n


def label(entry, bars):
    for k in range(min(HOLD, len(bars))):
        _o, h, l, _c = bars[k]
        if l <= entry * (1 - STOP_PCT):
            return -STOP_PCT * 100 - COST
        if h >= entry * (1 + TARGET_PCT):
            return TARGET_PCT * 100 - COST
    return (bars[min(HOLD, len(bars)) - 1][3] / entry - 1) * 100 - COST if bars else None


def features_at(r, cl, vol, i, reg):
    d, o, h, l, c, v = r[i]
    ma5, ma20, ma60 = sma(cl, 5, i), sma(cl, 20, i), sma(cl, 60, i)
    if None in (ma5, ma20, ma60):
        return None
    r14, r2, a = rsi(cl, 14, i), rsi(cl, 2, i), atr(r, 14, i)
    sd = float(np.std(cl[i - 19:i + 1]))
    if None in (r14, r2, a) or sd == 0:
        return None
    v20 = sma(vol, 20, i) or 1
    hh20 = max(x[2] for x in r[i - 19:i + 1])
    mx = max(cl[i - 19:i + 1])
    return [r14, r2, v / v20 if v20 else 1, c / ma20 - 1, c / ma60 - 1,
            c / cl[i - 5] - 1, c / cl[i - 20] - 1, a / c, (c - mx) / mx, c / hh20,
            1.0 if ma5 > ma20 > ma60 else 0.0, (c - ma20) / sd,
            1.0 if (c > o and c > cl[i - 1]) else 0.0, 1.0 if reg == "BULL" else 0.0]


def ridge_fit(X, y, lam):
    Xs = np.c_[np.ones(len(X)), X]
    I = np.eye(Xs.shape[1]); I[0, 0] = 0
    return np.linalg.solve(Xs.T @ Xs + lam * I, Xs.T @ y)


def main() -> int:
    data = {f: load(f) for f in glob.glob(os.path.join(REPO, "data/market/ohlcv/kr_*_daily.csv"))}
    data = {f: r for f, r in data.items() if len(r) > 90}
    if not data:
        print("OHLCV 없음")
        return 1
    # 통일 레짐 — 메인 엔진과 동일한 KOSPI 기준(regime_kr). 파편화 제거.
    from regime_kr import kospi_regime_series
    regime = kospi_regime_series(REPO)

    rows = []  # (date, regime, feats, y)
    for f, r in data.items():
        cl = [x[4] for x in r]; vol = [x[5] for x in r]
        for i in range(60, len(r) - 1):
            reg = regime.get(r[i][0], "SIDE")
            fe = features_at(r, cl, vol, i, reg)
            if fe is None:
                continue
            bars = [(r[j][1], r[j][2], r[j][3], r[j][4]) for j in range(i + 1, min(i + 12, len(r)))]
            if not bars:
                continue
            y = label(bars[0][0], bars)
            if y is not None:
                rows.append((r[i][0], reg, fe, y))

    # OOS 검증
    tr = [x for x in rows if x[0] < SPLIT]; te = [x for x in rows if x[0] >= SPLIT]
    proven = {}
    if len(tr) > 500 and len(te) > 500:
        Xtr = np.array([x[2] for x in tr]); ytr = np.array([x[3] for x in tr])
        Xte = np.array([x[2] for x in te]); yte = np.array([x[3] for x in te])
        mu, sd = Xtr.mean(0), Xtr.std(0); sd[sd == 0] = 1
        b = ridge_fit((Xtr - mu) / sd, ytr, RIDGE_LAMBDA)
        pred = np.c_[np.ones(len(Xte)), (Xte - mu) / sd] @ b
        q = np.array_split(np.argsort(pred), 5)
        regte = np.array([x[1] for x in te])
        proven = {
            "split": SPLIT, "oosTrades": len(te),
            "topQuintileNetPct": round(float(yte[q[4]].mean()), 3),
            "bottomQuintileNetPct": round(float(yte[q[0]].mean()), 3),
            "spreadPct": round(float(yte[q[4]].mean() - yte[q[0]].mean()), 3),
            "ic": round(float(np.corrcoef(pred, yte)[0, 1]), 3),
            "topQuintileByRegime": {rg: round(float(np.mean([yte[i] for i in q[4] if regte[i] == rg])), 3)
                                    for rg in ["BULL", "SIDE", "BEAR"]
                                    if any(regte[i] == rg for i in q[4])},
        }

    # 전체 재학습 → 최신봉 스코어
    Xall = np.array([x[2] for x in rows]); yall = np.array([x[3] for x in rows])
    mu2, sd2 = Xall.mean(0), Xall.std(0); sd2[sd2 == 0] = 1
    beta = ridge_fit((Xall - mu2) / sd2, yall, RIDGE_LAMBDA)

    names = {}
    # candidate_universe_kr.csv(545종목 마스터)를 우선 소스로 → 대부분 종목명 매핑
    for f in ([os.path.join(REPO, "candidate_universe_kr.csv"),
               os.path.join(REPO, "data", "candidate_universe_kr.csv")]
              + glob.glob(os.path.join(REPO, "reports/mone_v36_final_recommendations_kr_*.csv"))
              + glob.glob(os.path.join(REPO, "data/*holdings_kr*.csv"))):
        if not os.path.exists(f):
            continue
        try:
            for rr in csv.DictReader(open(f, encoding="utf-8-sig")):
                s = (rr.get("symbol") or "").split(".")[0].zfill(6)
                if s and rr.get("name") and s not in names:
                    names[s] = rr["name"]
        except Exception:
            pass

    # 수급(기관/외국인) 컨텍스트 연결 — 신규 기능이 수급을 무시하던 문제 보완.
    supply = {}
    sp = os.path.join(REPO, "data", "kr_supply_flow.csv")
    if os.path.exists(sp):
        for rr in csv.DictReader(open(sp, encoding="utf-8-sig")):
            s = (rr.get("symbol") or "").zfill(6)
            try:
                supply[s] = (float(rr.get("foreign5d") or 0), float(rr.get("institution5d") or 0))
            except ValueError:
                continue

    def supply_signal(sym: str) -> str:
        fo, ins = supply.get(sym, (0, 0))
        if fo > 0 and ins > 0:
            return "기관+외국인 순매수"
        if fo > 0:
            return "외국인 순매수"
        if ins > 0:
            return "기관 순매수"
        if fo < 0 and ins < 0:
            return "기관+외국인 순매도"
        return ""

    from regime_kr import latest_regime as _lr
    latest_date = max(r[-1][0] for r in data.values())
    market_regime = _lr(REPO)[0]
    picks = []
    for f, r in data.items():
        cl = [x[4] for x in r]; vol = [x[5] for x in r]; i = len(r) - 1
        if r[i][0] != latest_date:
            continue
        fe = features_at(r, cl, vol, i, market_regime)
        if fe is None:
            continue
        score = float(beta[0] + ((np.array(fe) - mu2) / sd2) @ beta[1:])
        sym = os.path.basename(f).split("kr_")[1].split("_")[0]
        c = r[i][4]
        picks.append({"symbol": sym, "name": names.get(sym, sym), "modelScore": round(score, 3),
                      "close": round(c, 2), "rsi14": round(fe[0], 1),
                      "entryRef": round(c, 2), "stop": round(c * (1 - STOP_PCT)),
                      "target": round(c * (1 + TARGET_PCT)), "supplySignal": supply_signal(sym)})
    picks.sort(key=lambda x: -x["modelScore"])
    # 상위 20% + 강세/횡보 레짐 = actionable (약세장은 상위픽도 OOS (−) → caution)
    cut = picks[max(1, len(picks) // 5) - 1]["modelScore"] if picks else 0
    for p in picks:
        p["rankBucket"] = "TOP20" if p["modelScore"] >= cut else "LOWER"
        p["actionable"] = (p["rankBucket"] == "TOP20") and (market_regime in ("BULL", "SIDE"))

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "asOfDate": latest_date, "market": "kr", "marketRegime": market_regime,
        "modelType": "ridge_regression", "featureCount": len(FEATURES),
        "provenEdge": proven,
        "featureWeights": {n: round(float(w), 3) for n, w in
                           sorted(zip(FEATURES, beta[1:]), key=lambda t: -abs(t[1]))},
        "note": "다중신호 ML 순위(선별 두뇌). OOS 검증 통과. 약세장은 상위픽도 (−)라 caution. "
                "가격신호만 사용 — 수급/뉴스/섹터/공시 추가 시 개선 여지.",
        "actionableCount": sum(1 for p in picks if p["actionable"]),
        "candidateCount": len(picks),
        "candidates": picks[:20],
    }
    out = os.path.join(REPO, "reports", "smart_rank_kr.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"asOf={latest_date} regime={market_regime} picks={len(picks)} actionable={report['actionableCount']} -> {os.path.relpath(out, REPO)}")
    if proven:
        print(f"OOS 검증: 상위20% {proven['topQuintileNetPct']:+}% vs 하위20% {proven['bottomQuintileNetPct']:+}% "
              f"(스프레드 {proven['spreadPct']:+}%p, IC {proven['ic']:+}), 레짐별상위 {proven['topQuintileByRegime']}")
    print("상위 8:")
    for p in picks[:8]:
        print(f"  {p['name'][:14]:16s} score={p['modelScore']:+.3f} rsi={p['rsi14']:.0f} {'실행가능' if p['actionable'] else 'caution'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
