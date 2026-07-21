#!/usr/bin/env python3
"""
Regime-adaptive lens screener (KR).

레짐 적응형 매수 후보 스크리너. 백테스트(scratchpad/mr_backtest.py, 2024-06~2026-07,
110종목, 비용 왕복 0.5% 반영, 룩어헤드 없음)로 검증된 두 셋업을 매일 최신봉에 적용한다:

  - BOTTOM_CATCH (하락장 저점반등): c<MA60 + RSI14<32 + 반등봉(c>o & c>전일)
      → 약세장(BEAR)에서 net +0.62%/거래, PF 1.24 (검증)
  - BREAKOUT (강세/횡보 돌파): c>MA20>MA60 + 20일 신고가 -2% 이내 + RSI14>60
      → 전 레짐 net +0.25~0.53%/거래, 손익비 1.8 (검증, 가장 견고)

시장 레짐 = breadth(MA60 위 종목 비율): >=0.6 BULL / <=0.4 BEAR / else SIDE.
레짐 라우팅: BEAR -> BOTTOM_CATCH, SIDE/BULL -> BREAKOUT. (activeLens)

⚠️ 생존편향: universe = 현재 상장 종목 glob뿐(상폐/추락 부재)이라 백테스트가 낙관.
이 스크리너는 '후보 제시'까지만. 실사이징은 VTJ forward 검증(Step 3) 통과 후.

읽기전용: data/market/ohlcv/*.csv 만 읽고 reports/regime_lens_candidates_kr.json 을 쓴다.
"""
from __future__ import annotations
import csv
import glob
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- 파라미터 (백테스트와 동일) ---
MA_TREND = 60
MA_MID = 20
RSI_N = 14
BOTTOM_RSI_MAX = 32.0
BREAKOUT_RSI_MIN = 60.0
BOTTOM_TARGET, BOTTOM_STOP = 0.08, 0.05
BREAKOUT_TARGET, BREAKOUT_STOP = 0.08, 0.04
NEAR_HIGH_PCT = 0.02  # 20일 고가 -2% 이내


def load_ohlcv(path: str) -> list[tuple[str, float, float, float, float]]:
    out: list[tuple[str, float, float, float, float]] = []
    with open(path, encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if not row or not row[0] or row[0] == "date":
                continue
            try:
                d = row[0]
                o, h, l, c = float(row[3]), float(row[4]), float(row[5]), float(row[6])
            except (ValueError, IndexError):
                continue
            if min(o, h, l, c) > 0:
                out.append((d, o, h, l, c))
    out.sort(key=lambda r: r[0])
    return out


def sma(xs: list[float], n: int, i: int) -> float | None:
    return sum(xs[i - n + 1 : i + 1]) / n if i + 1 >= n else None


def rsi(cl: list[float], n: int, i: int) -> float | None:
    if i < n:
        return None
    gain = loss = 0.0
    for k in range(i - n + 1, i + 1):
        ch = cl[k] - cl[k - 1]
        gain += max(ch, 0.0)
        loss += max(-ch, 0.0)
    if gain + loss == 0:
        return 50.0
    rs = (gain / n) / ((loss / n) if loss > 0 else 1e-9)
    return 100 - 100 / (1 + rs)


def load_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    patterns = [
        os.path.join(REPO, "candidate_universe_kr.csv"),
        os.path.join(REPO, "data", "candidate_universe_kr.csv"),
        os.path.join(REPO, "reports", "mone_v36_final_recommendations_kr_*.csv"),
        os.path.join(REPO, "data", "*holdings_kr*.csv"),
    ]
    for pat in patterns:
        for f in glob.glob(pat):
            try:
                for r in csv.DictReader(open(f, encoding="utf-8-sig")):
                    sym = (r.get("symbol") or "").split(".")[0].zfill(6)
                    nm = r.get("name")
                    if sym and nm and sym not in names:
                        names[sym] = nm
            except Exception:
                continue
    return names


def main() -> int:
    files = glob.glob(os.path.join(REPO, "data", "market", "ohlcv", "kr_*_daily.csv"))
    series: dict[str, list] = {}
    for f in files:
        r = load_ohlcv(f)
        if len(r) > MA_TREND + 15:
            sym = os.path.basename(f).split("kr_")[1].split("_")[0]
            series[sym] = r
    if not series:
        print("no OHLCV data found", file=sys.stderr)
        return 1

    # 시장 레짐 = 최신 공통일의 breadth(MA60 위 비율)
    latest_date = max(r[-1][0] for r in series.values())
    above = total = 0
    for r in series.values():
        cl = [x[4] for x in r]
        i = len(r) - 1
        if r[i][0] != latest_date:
            continue
        m = sma(cl, MA_TREND, i)
        if m is None:
            continue
        total += 1
        if cl[i] > m:
            above += 1
    breadth = (above / total) if total else 0.0
    market_regime = "BULL" if breadth >= 0.6 else ("BEAR" if breadth <= 0.4 else "SIDE")

    # 자가보정 읽기 (Step 3 산출물). 없으면 정적 폴백.
    calib_path = os.path.join(REPO, "reports", "lens_calibration_kr.json")
    calib = {}
    routing = {}
    live_samples_total = 0
    if os.path.exists(calib_path):
        try:
            cj = json.load(open(calib_path, encoding="utf-8"))
            calib = cj.get("calibration", {})
            routing = cj.get("activeSetupByRegime", {})
            live_samples_total = int(cj.get("liveSamplesTotal", 0) or 0)
        except Exception:
            pass
    active_for_regime = routing.get(market_regime)
    if active_for_regime:  # 실측 자가보정 우선
        active_lens = active_for_regime[0]
    else:  # 폴백(정적 라우팅)
        active_lens = "BOTTOM_CATCH" if market_regime == "BEAR" else "BREAKOUT"

    def setup_gate(setup: str) -> tuple[str, float]:
        c = calib.get(f"{setup}|{market_regime}")
        if not c:
            return ("UNCALIBRATED", 0.5)
        return (c.get("gate", "UNCALIBRATED"), float(c.get("sizeMultiplier", 0.0)))

    names = load_name_map()
    candidates: list[dict] = []
    for sym, r in series.items():
        cl = [x[4] for x in r]
        i = len(r) - 1
        d, o, h, l, c = r[i]
        ma60 = sma(cl, MA_TREND, i)
        ma20 = sma(cl, MA_MID, i)
        rsi14 = rsi(cl, RSI_N, i)
        if None in (ma60, ma20, rsi14):
            continue
        prev_c = cl[i - 1]
        dist_ma20 = (c / ma20 - 1) * 100
        setup = None
        if c < ma60 and rsi14 < BOTTOM_RSI_MAX and c > o and c > prev_c:
            setup = "BOTTOM_CATCH"
            stop = round(l * 0.985)
            target = round(c * (1 + BOTTOM_TARGET))
        else:
            hh20 = max(x[2] for x in r[i - 19 : i + 1])
            if c > ma20 > ma60 and c >= hh20 * (1 - NEAR_HIGH_PCT) and rsi14 > BREAKOUT_RSI_MIN:
                setup = "BREAKOUT"
                stop = round(c * (1 - BREAKOUT_STOP))
                target = round(c * (1 + BREAKOUT_TARGET))
        if not setup:
            continue
        risk = c - stop
        reward = target - c
        gate, size_mult = setup_gate(setup)
        candidates.append(
            {
                "symbol": sym,
                "name": names.get(sym, sym),
                "setup": setup,
                "asOfDate": d,
                "close": round(c, 2),
                "entryRef": round(c, 2),
                "stop": stop,
                "target": target,
                "rrRatio": round(reward / risk, 2) if risk > 0 else None,
                "rsi14": round(rsi14, 1),
                "distMa20Pct": round(dist_ma20, 1),
                "calibrationGate": gate,       # ACTIVE 만 실측 자가보정 통과
                "sizeMultiplier": size_mult,   # 엣지 세기 → 사이즈 배율(실측 기반)
                "actionable": gate == "ACTIVE",
            }
        )

    # 정렬: 자가보정 통과(actionable) 먼저, 그다음 사이즈배율/RR 높은순
    candidates.sort(
        key=lambda x: (
            0 if x["actionable"] else 1,
            -(x["sizeMultiplier"] or 0),
            x["rsi14"] if x["setup"] == "BOTTOM_CATCH" else -(x["rrRatio"] or 0),
        )
    )

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "asOfDate": latest_date,
        "market": "kr",
        "marketRegime": market_regime,
        "breadthAboveMa60": round(breadth, 3),
        "activeLens": active_lens,
        "activeSetupByRegime": routing or None,
        "selfCalibrated": bool(calib),
        "liveSamplesTotal": live_samples_total,
        "universeSize": len(series),
        "candidateCount": len(candidates),
        "actionableCount": sum(1 for x in candidates if x["actionable"]),
        "disclaimer": "생존편향(현상장 glob만)로 백테스트 낙관. actionable(ACTIVE)만 자가보정 통과 — 실사이징은 라이브 VTJ forward 검증 후.",
        "candidates": candidates,
    }
    out_path = os.path.join(REPO, "reports", "regime_lens_candidates_kr.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    act = sum(1 for x in candidates if x["actionable"])
    print(f"asOf={latest_date}  regime={market_regime}(breadth={breadth:.2f})  activeLens={active_lens}  selfCalibrated={bool(calib)}")
    print(f"universe={len(series)}  candidates={len(candidates)}  actionable(자가보정통과)={act}  -> {os.path.relpath(out_path, REPO)}")
    print(f"\n{'종목':16s}{'셋업':13s}{'RSI':>5s}{'기준가':>9s}{'손절':>9s}{'목표':>9s}{'RR':>5s}{'MA20':>7s}{'게이트':>20s}{'size':>6s}")
    for x in candidates[:20]:
        print(
            f"{x['name'][:14]:16s}{x['setup']:13s}{x['rsi14']:5.0f}{x['entryRef']:9.0f}"
            f"{x['stop']:9.0f}{x['target']:9.0f}{(x['rrRatio'] or 0):5.1f}{x['distMa20Pct']:+6.1f}%"
            f"{x['calibrationGate']:>20s}{x['sizeMultiplier']:6.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
