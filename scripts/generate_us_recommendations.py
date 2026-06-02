"""
US OHLCV + KIS/Finnhub 현재가 기반으로 US 추천 파일 18개 직접 생성.
generate_kr_recommendations.py의 미장 버전.

출력: reports/mone_v36_final_recommendations_us_{mode}_{horizon}.csv  (9개)
      reports/mone_v36_final_trade_validation_us_{mode}_{horizon}.csv (9개)
"""
from __future__ import annotations

import sys
from pathlib import Path

# KR 스크립트의 모든 로직 재사용, 파라미터만 미장으로 변경
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# generate_kr_recommendations의 핵심 함수들을 import
from scripts.generate_kr_recommendations import (
    _read_csv, _write_csv, _num, _series, indicators,
    _sub_scores, _final_score, _ma_convergence,
    _ma_convergence as _ma_conv,
    _price_band, _decide_timing, _strategy_tags, _fmt_krw,
    _HORIZON_BANDS, _MODE_WEIGHTS, _MODE_RISK, _MODE_REWARD,
    MODE_LABELS, HORIZON_LABELS, MODES, HORIZONS,
    _load_news_sentiment, _load_financial_data,
    MIN_OHLCV_ROWS, TOP_N,
)
import csv, json, math, os, re
from datetime import datetime
from typing import Any

OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
REPORTS = ROOT / "reports"
DATA_STOCKAPP = ROOT / "data" / "stockapp"


def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


def _load_us_prices() -> dict[str, float]:
    prices: dict[str, float] = {}
    for p in [
        REPORTS / "kis_current_price_us.csv",
        DATA_STOCKAPP / "kis_current_price_us.csv",
        REPORTS / "intraday_realtime_snapshot_us.csv",
    ]:
        for row in _read_csv(p):
            sym = str(row.get("symbol", "")).strip().upper()
            price = _num(row.get("currentPrice") or row.get("current_price") or row.get("last_price"))
            ok = str(row.get("ok", "")).lower() in {"true", "1", "yes"}
            if price and price > 0 and ok:
                prices[sym] = price
    return prices


def _load_us_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in [ROOT / "watchlist_us.csv", ROOT / "data" / "watchlist_us.csv"]:
        for row in _read_csv(path):
            sym = str(row.get("symbol") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if sym and name:
                names[sym] = name
    return names


def _load_us_market_regime() -> dict[str, Any]:
    path = ROOT / "data" / "market" / "benchmark_daily.csv"
    rows = [r for r in _read_csv(path) if str(r.get("benchmark", "")).upper() in ("NASDAQ", "SP500", "SPY")]
    if not rows:
        rows = [r for r in _read_csv(path) if str(r.get("benchmark", "")).upper() not in ("KOSPI", "KOSDAQ")]
    rows.sort(key=lambda r: str(r.get("date", "")))
    closes = [_num(r.get("close")) for r in rows]
    closes = [c for c in closes if c is not None]
    if len(closes) < 20:
        return {"regime": "SIDE", "label": "횡보장", "scoreAdjust": 0.0, "description": "US 벤치마크 데이터 부족"}
    latest = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    dist = (latest - ma20) / ma20 * 100
    mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
    if dist > 0 and mom5 > 0:
        return {"regime": "BULL", "label": "강세장", "scoreAdjust": +5.0,
                "description": f"US 시장 MA20 {dist:+.1f}%, 5일 {mom5:+.1f}%"}
    elif dist < -2.0 or mom5 < -2.0:
        return {"regime": "BEAR", "label": "약세장", "scoreAdjust": -8.0,
                "description": f"US 시장 MA20 {dist:+.1f}%, 5일 {mom5:+.1f}%"}
    return {"regime": "SIDE", "label": "횡보장", "scoreAdjust": 0.0,
            "description": f"US 시장 MA20 {dist:+.1f}%, 5일 {mom5:+.1f}%"}


def generate_us_recommendations() -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] US 추천 파일 생성 시작")

    # OHLCV 로드
    ohlcv_all: dict[str, list[dict]] = {}
    for path in sorted(OHLCV_DIR.glob("us_*_daily.csv")):
        m = re.match(r"us_(.+)_daily\.csv", path.name)
        if not m:
            continue
        sym = m.group(1).upper()
        rows = _read_csv(path)
        rows.sort(key=lambda r: str(r.get("date") or r.get("Date") or ""))
        if len(rows) >= MIN_OHLCV_ROWS:
            ohlcv_all[sym] = rows

    prices = _load_us_prices()
    name_map = _load_us_name_map()
    regime = _load_us_market_regime()

    print(f"  US OHLCV: {len(ohlcv_all)}종목, 현재가: {len(prices)}종목")
    print(f"  US 마켓 레짐: {regime['label']} ({regime['description']})")

    regime_adjust = regime.get("scoreAdjust", 0.0)
    regime_label = regime.get("label", "횡보장")
    regime_type = regime.get("regime", "SIDE")
    min_score_by_regime = {"BULL": 45.0, "SIDE": 50.0, "BEAR": 58.0}
    min_score_global = min_score_by_regime.get(regime_type, 50.0)

    # 전체 스코어 계산
    all_scored: list[dict] = []
    for sym, rows in ohlcv_all.items():
        ind = indicators(rows)
        latest = ind.get("latest")
        if not latest or latest <= 0:
            continue
        current = prices.get(sym) or latest
        ind["latest"] = current
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
            "price_source": "live" if prices.get(sym) else "ohlcv",
        })

    all_scored.sort(key=lambda x: x["score_base"], reverse=True)

    results: dict[str, int] = {}
    ev_filtered = 0
    REPORTS.mkdir(parents=True, exist_ok=True)

    for mode in MODES:
        if regime_type == "BEAR" and mode == "aggressive":
            for horizon in HORIZONS:
                _write_csv(REPORTS / f"mone_v36_final_recommendations_us_{mode}_{horizon}.csv", [])
                _write_csv(REPORTS / f"mone_v36_final_trade_validation_us_{mode}_{horizon}.csv", [])
                results[f"{mode}_{horizon}"] = 0
            print(f"  [US {mode:12s}] 약세장으로 비활성화")
            continue

        for horizon in HORIZONS:
            rows_out: list[dict] = []
            scored_combo: list[tuple[float, float, dict]] = []
            for c in all_scored:
                base = _final_score(c["ind"], mode, horizon)
                adj = max(0.0, min(100.0, base + regime_adjust))
                scored_combo.append((adj, base, c))
            scored_combo.sort(key=lambda x: x[0], reverse=True)

            count = 0
            for adj_score, base_score, c in scored_combo:
                if count >= TOP_N:
                    break
                if adj_score < min_score_global:
                    continue
                sym = c["symbol"]
                current = c["current"]
                ind = c["ind"]

                entry, stop, target, ev, decision = _price_band(adj_score, current, mode, horizon, ind)

                if ev is not None and ev < 0:
                    if mode == "conservative":
                        ev_filtered += 1
                        continue
                    decision = "기다림"

                _, timing_label, timing_reason = _decide_timing(adj_score, ind, mode, horizon, ev)
                ev_negative = ev is not None and ev < 0
                ma_conv = _ma_convergence(ind)
                rr = round((target - entry) / max(entry - stop, 1), 2) if stop < entry else None

                # 전략 태그 (US 버전)
                tags_list = []
                d52 = ind.get("distanceTo52wHigh")
                vr = ind.get("volumeRatio20")
                if d52 and -3.0 <= d52 <= 0 and vr and vr >= 1.5:
                    tags_list.append("52주신고가돌파")
                if ind.get("bbSqueeze") and ind.get("bbPercentB", 0) > 0.5:
                    tags_list.append("볼린저스퀴즈")
                if ma_conv and (not ind.get("rsi14") or ind["rsi14"] < 75):
                    tags_list.append("이격도수렴")
                d20 = ind.get("distanceToMa20")
                if d20 and -8 <= d20 <= 3 and (not ind.get("rsi14") or ind["rsi14"] < 80):
                    tags_list.append("눌림목매수")
                if vr and vr >= 1.5:
                    tags_list.append("거래량증가")
                mom5 = ind.get("recentMomentum5")
                mom20 = ind.get("recentMomentum20")
                if (mom5 and mom5 > 3) or (mom20 and mom20 > 8):
                    tags_list.append("모멘텀강세")
                if not tags_list:
                    tags_list.append("안정형")
                tags = " | ".join(tags_list)

                row = {
                    "market": "us",
                    "mode": mode,
                    "modeLabel": MODE_LABELS[mode],
                    "horizon": horizon,
                    "horizonLabel": HORIZON_LABELS[horizon],
                    "symbol": sym,
                    "name": c["name"],
                    "decisionBucket": decision,
                    "timingLabel": timing_label,
                    "timingReason": timing_reason,
                    "expectedEntryPrice": _fmt_usd(current * 0.98) if decision == "대기 관찰" else "",
                    "newEntryDecision": "조건부 진입" if adj_score >= 55 and not ev_negative else "대기",
                    "holderDecision": "보유자는 목표가·손절가 대응",
                    "buyTiming": "조건부 매수 등록" if decision == "오늘 진입" else "기준가 도달 대기",
                    "sellTiming": "목표가 도달 시 분할익절 / 손절가 이탈 시 종료",
                    "entry": _fmt_usd(entry),
                    "stop": _fmt_usd(stop),
                    "target": _fmt_usd(target),
                    "probability": f"{round(adj_score, 1)}%",
                    "expectedPrice": _fmt_usd(round(current * (1 + (adj_score/100 - 0.5) * 0.1), 2)),
                    "opportunityScore": round(_sub_scores(ind)["upsideScore"] * 0.6 + _sub_scores(ind)["momentumScore"] * 0.4, 1),
                    "entryScore": round(_sub_scores(ind)["entryScore"], 1),
                    "riskScore": round(_sub_scores(ind)["riskScore"], 1),
                    "eventRiskScore": 0,
                    "newsReliabilityScore": 50,
                    "newsRiskPenalty": 0,
                    "finalRankScore": round(adj_score, 1),
                    "finalScore": round(adj_score, 1),
                    "baseScore": round(base_score, 1),
                    "upsideScore": _sub_scores(ind)["upsideScore"],
                    "momentumScore": _sub_scores(ind)["momentumScore"],
                    "rrScore": _sub_scores(ind)["rrScore"],
                    "qualityScore": _sub_scores(ind)["qualityScore"],
                    "expectedValue": ev if ev is not None else "",
                    "evNegative": ev_negative,
                    "rrActual": rr if rr is not None else "",
                    "maConvergence": ma_conv,
                    "supplySignal": "NEUTRAL",
                    "surgeLabel": tags,
                    "eventBadges": " | ".join(filter(None, [
                        "EV음수" if ev_negative else "",
                        "이격도수렴" if ma_conv else "",
                        "52주돌파" if (d52 and -3 <= d52 <= 0 and vr and vr >= 1.5) else "",
                    ])),
                    "marketRegime": regime_label,
                    "marketRegimeAdjust": regime_adjust,
                    "executionStatus": "체결" if decision == "오늘 진입" else "대기",
                    "exitStatus": "",
                    "pnlText": "",
                    "excludedFromReturn": ev_negative,
                    "sourceBucket": "ohlcv_quant",
                    "dataStatus": "NORMAL" if c["price_source"] == "live" else "PARTIAL",
                    "priceSource": c["price_source"],
                    "currentPrice": current,
                    "generatedAt": now,
                }
                rows_out.append(row)
                count += 1

            key = f"{mode}_{horizon}"
            out_path = REPORTS / f"mone_v36_final_recommendations_us_{mode}_{horizon}.csv"
            _write_csv(out_path, rows_out)
            results[key] = len(rows_out)
            print(f"  [US {mode:12s}/{horizon:5s}] {len(rows_out):2d}종목 → {out_path.name}")

            tv_path = REPORTS / f"mone_v36_final_trade_validation_us_{mode}_{horizon}.csv"
            _write_csv(tv_path, [{**r, "validationStatus": "PENDING", "validationDate": ""} for r in rows_out])

    status = {
        "generatedAt": now,
        "source": "us_ohlcv_quant_scanner",
        "symbols": len(ohlcv_all),
        "liveSymbols": len(prices),
        "marketRegime": regime,
        "evFiltered": ev_filtered,
        "results": results,
    }
    (REPORTS / "us_recommendation_gen_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(results.values())
    print(f"[{now}] US 완료: {total}건 생성")
    return status


if __name__ == "__main__":
    generate_us_recommendations()
