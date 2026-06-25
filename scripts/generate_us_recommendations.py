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

# 팩터 회귀 기반 필터 조정값 로드
def _load_factor_adjustments_us() -> dict:
    try:
        import json as _json
        p = ROOT / "reports" / "factor_based_filter_adjustments.json"
        if p.exists():
            doc = _json.loads(p.read_text(encoding="utf-8"))
            if doc.get("status") == "APPLIED":
                return doc.get("adjustments", {})
    except Exception:
        pass
    return {}

_FACTOR_ADJ_US = _load_factor_adjustments_us()

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


_ETF_SYMBOLS = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "GLD", "SLV",
    "SMH", "SOXX", "IBIT", "SOXL", "SOXS", "TQQQ", "SQQQ",
    "ARKK", "XLF", "XLE", "XLK", "XLV", "XLY",
    "SP500", "DRAM", "BTC-USD",
}


def _load_us_sector_map() -> dict[str, str]:
    sector: dict[str, str] = {}
    path = ROOT / "data" / "sector_map_us.csv"
    for row in _read_csv(path):
        sym = str(row.get("symbol") or "").strip().upper()
        sec = str(row.get("sector") or "").strip()
        if sym and sec:
            sector[sym] = sec
    return sector


def _load_us_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in [
        ROOT / "watchlist_us.csv",
        ROOT / "data" / "watchlist_us.csv",
        ROOT / "data" / "candidate_universe_us.csv",
        DATA_STOCKAPP / "price_collection_universe_us.csv",
        DATA_STOCKAPP / "kis_collection_targets_us.csv",
    ]:
        for row in _read_csv(path):
            sym = str(row.get("symbol") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if sym and name:
                names[sym] = name
    return names


def _load_us_candidate_symbols(limit: int = 160) -> list[str]:
    symbols: list[str] = []

    def add(value: Any, market: Any = "us") -> None:
        if market and str(market).strip().lower() not in {"", "us"}:
            return
        sym = str(value or "").strip().upper()
        if not sym:
            return
        if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", sym) and sym not in symbols:
            symbols.append(sym)

    for path in [
        DATA_STOCKAPP / "price_collection_universe_us.csv",
        DATA_STOCKAPP / "kis_collection_targets_us.csv",
        ROOT / "data" / "candidate_universe_us.csv",
        ROOT / "candidate_universe_us.csv",
        ROOT / "data" / "watchlist_us.csv",
        ROOT / "watchlist_us.csv",
    ]:
        for row in _read_csv(path):
            add(row.get("symbol") or row.get("ticker") or row.get("code"), row.get("market") or "us")

    return symbols[:limit]


def _download_us_ohlcv(symbols: list[str]) -> dict[str, list[dict]]:
    if not symbols:
        return {}
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        print(f"  yfinance import 실패: {exc}")
        return {}

    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    loaded: dict[str, list[dict]] = {}
    batch_size = 30
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start:start + batch_size]
        try:
            data = yf.download(
                tickers=" ".join(batch),
                period="9mo",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            print(f"  yfinance batch 실패 {batch[:3]}...: {exc}")
            continue

        for sym in batch:
            try:
                frame = data[sym] if len(batch) > 1 else data
            except Exception:
                continue
            if frame is None or getattr(frame, "empty", True):
                continue
            frame = frame.reset_index()
            rows: list[dict[str, Any]] = []
            for _, rec in frame.iterrows():
                close = _num(rec.get("Close"))
                if close is None or close <= 0:
                    continue
                rows.append({
                    "date": str(rec.get("Date") or rec.get("Datetime") or "")[:10],
                    "symbol": sym,
                    "name": sym,
                    "open": rec.get("Open", ""),
                    "high": rec.get("High", ""),
                    "low": rec.get("Low", ""),
                    "close": rec.get("Close", ""),
                    "volume": rec.get("Volume", ""),
                    "source": f"Yahoo Finance {sym}",
                })
            if len(rows) >= MIN_OHLCV_ROWS:
                _write_csv(OHLCV_DIR / f"us_{sym}_daily.csv", rows)
                loaded[sym] = rows
    return loaded


def _load_us_ohlcv() -> dict[str, list[dict]]:
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
    return ohlcv_all


def _nonempty_recommendation_count() -> int:
    count = 0
    for path in REPORTS.glob("mone_v36_final_recommendations_us_*.csv"):
        try:
            if len(_read_csv(path)) > 0:
                count += 1
        except Exception:
            pass
    return count


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

    # OHLCV 로드. Actions 러너에는 data/market/ohlcv가 .gitignore 때문에 없을 수 있어
    # 후보군을 기반으로 임시 OHLCV를 받아 생성한다.
    ohlcv_all = _load_us_ohlcv()
    if not ohlcv_all:
        candidates = _load_us_candidate_symbols()
        print(f"  로컬 US OHLCV 없음 → yfinance 수집 시도: {len(candidates)}종목")
        ohlcv_all = _download_us_ohlcv(candidates)

    prices = _load_us_prices()
    name_map = _load_us_name_map()
    sector_map_us = _load_us_sector_map()
    regime = _load_us_market_regime()

    print(f"  US OHLCV: {len(ohlcv_all)}종목, 현재가: {len(prices)}종목")
    print(f"  US 마켓 레짐: {regime['label']} ({regime['description']})")

    if not ohlcv_all:
        status = {
            "generatedAt": now,
            "source": "us_ohlcv_quant_scanner",
            "status": "NO_OHLCV",
            "symbols": 0,
            "liveSymbols": len(prices),
            "marketRegime": regime,
            "evFiltered": 0,
            "results": {},
            "preservedExistingRecommendationFiles": _nonempty_recommendation_count(),
            "message": "US OHLCV를 찾거나 수집하지 못해 기존 추천 파일을 보존했습니다.",
        }
        (REPORTS / "us_recommendation_gen_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("  US OHLCV 없음: 기존 추천 파일 보존")
        return status

    regime_adjust = regime.get("scoreAdjust", 0.0)
    regime_label = regime.get("label", "횡보장")
    regime_type = regime.get("regime", "SIDE")
    # 최소 점수 기준 — 7중 필터가 품질 보장하므로 레짐 기준 완화
    min_score_by_regime = {"BULL": 50.0, "SIDE": 55.0, "BEAR": 60.0}
    min_score_global = min_score_by_regime.get(regime_type, 55.0)

    # 전체 스코어 계산
    all_scored: list[dict] = []
    for sym, rows in ohlcv_all.items():
        if sym in _ETF_SYMBOLS or "-" in sym:
            continue
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
            "sector": sector_map_us.get(sym, "Unknown"),
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

            # 섹터 다양성
            _MAX_PER_SECTOR_US = {"conservative": 2, "balanced": 3, "aggressive": 4}.get(mode, 3)
            _sector_counts_us: dict[str, int] = {}

            count = 0
            for adj_score, base_score, c in scored_combo:
                if count >= TOP_N:
                    break
                if adj_score < min_score_global:
                    continue
                sym = c["symbol"]
                current = c["current"]
                ind = c["ind"]

                # ── 7중 필터 (v3: 정확도 최적화) ──────────────────────────
                _ma5 = ind.get("ma5"); _ma20 = ind.get("ma20"); _ma60 = ind.get("ma60")
                _rsi = ind.get("rsi14")
                _vr  = ind.get("volumeRatio20")
                _d20 = ind.get("distanceToMa20")
                _atr14 = ind.get("atr14")
                _bull5 = ind.get("bullRatio5", 0.0)

                # 필터 A: MA 추세 — 완전 정배열 OR 부분 정배열
                _ma_full_align = _ma5 and _ma20 and _ma60 and _ma5 > _ma20 > _ma60
                _ma_partial = (_ma5 and _ma20 and _ma5 > _ma20 and
                               _ma60 and _ma20 > _ma60 * 0.90)
                if not (_ma_full_align or _ma_partial):
                    continue

                # 필터 B: RSI — mode별 차등 (US 강세장 반영, 팩터 회귀 조정 적용)
                _rsi_lo = {"conservative": 38, "balanced": 35, "aggressive": 30}.get(mode, 35)
                _rsi_hi_default = {"conservative": 72, "balanced": 75, "aggressive": 78}.get(mode, 75)
                _rsi_hi = float(_FACTOR_ADJ_US.get(f"rsi_upper_{mode}", _rsi_hi_default))
                if _rsi is None or not (_rsi_lo <= _rsi <= _rsi_hi):
                    continue

                # 필터 C: 거래량 — mode별 최소 비율 (팩터 회귀 조정 적용)
                _min_vr_default = {"conservative": 0.7, "balanced": 0.5, "aggressive": 0.3}.get(mode, 0.5)
                _min_vr = float(_FACTOR_ADJ_US.get(f"min_vr_{mode}", _min_vr_default))
                if _vr is None or _vr < _min_vr:
                    continue

                # 필터 D: 이격도 — horizon별 허용 범위 (US는 더 넓게, 팩터 회귀 조정 적용)
                _d20_max_default = {"short": 12, "swing": 15, "mid": 20}.get(horizon, 15)
                _d20_max = float(_FACTOR_ADJ_US.get(f"d20_max_{horizon}", _d20_max_default))
                _d20_min = {"short": -12, "swing": -18, "mid": -25}.get(horizon, -18)
                if _d20 is None or _d20 > _d20_max or _d20 < _d20_min:
                    continue

                # 필터 E: 손익비 — horizon별 ATR 배수로 계산
                _stop_mult_e = {"short": 1.2, "swing": 1.5, "mid": 2.0}.get(horizon, 1.5)
                _tgt_mult_e  = {"short": 2.8, "swing": 4.5, "mid": 5.5}.get(horizon, 4.5)
                if _atr14 and _atr14 > 0 and current > 0:
                    if _tgt_mult_e / _stop_mult_e < 2.0:
                        continue

                # 필터 F: 양봉 품질
                _min_bull = {"conservative": 0.4, "balanced": 0.4, "aggressive": 0.2}.get(mode, 0.4)
                if _bull5 < _min_bull:
                    continue

                # 필터 G: 과도한 갭업 제거
                _gap = ind.get("gapUpPct")
                if _gap and _gap >= 12.0:
                    continue

                # 필터 H: 섹터 다양성
                _sec_us = c.get("sector", "Unknown") or "Unknown"
                if _sector_counts_us.get(_sec_us, 0) >= _MAX_PER_SECTOR_US:
                    continue
                # ─────────────────────────────────────────────────────────

                entry, stop, target, ev, decision, wr_prob, wr_samples = _price_band(adj_score, current, mode, horizon, ind)

                if ev is not None and ev < 0:
                    if mode == "conservative":
                        ev_filtered += 1
                        continue
                    decision = "기다림"

                _, timing_label, timing_reason = _decide_timing(adj_score, ind, mode, horizon, ev)
                ev_negative = ev is not None and ev < 0
                ma_conv = _ma_convergence(ind)

                # 자가보정 루프: 검증된 승률(wr_prob)을 표본수 가중치로 confidence에 자동 반영
                wr_weight = min(wr_samples / 100.0, 1.0)
                if wr_weight > 0:
                    wr_score_equiv = (wr_prob - 0.5) * 200.0  # 0.35~0.65 → -30~+30
                    adj_score = max(0.0, min(100.0, adj_score + wr_score_equiv * wr_weight * 0.3))

                # Self-Correction v2 적용 (7-F US)
                _corr_applied = False
                _corr_confidence = 0.0
                _corr_summary = ""
                _corr_version = 0
                try:
                    import sys as _sys, os as _os
                    _backend = _os.path.join(_os.path.dirname(__file__), "..", "mone-web-app", "backend")
                    if _backend not in _sys.path:
                        _sys.path.insert(0, _backend)
                    from app.engine.self_correction_v2 import apply_correction as _apply_corr
                    _sub = _sub_scores(ind)
                    _corr = _apply_corr(
                        {"upsideScore": _sub["upsideScore"], "momentumScore": _sub["momentumScore"],
                         "riskScore": _sub["riskScore"], "entryScore": _sub["entryScore"],
                         "rrScore": _sub["rrScore"], "qualityScore": _sub["qualityScore"]},
                        entry, target, stop, "us", mode, horizon
                    )
                    if _corr.get("correctionApplied"):
                        entry  = round(_corr["adjustedEntry"], 2)
                        target = round(_corr["adjustedTarget"], 2)
                        stop   = round(_corr["adjustedStop"], 2)
                        _corr_applied = True
                    _corr_confidence = _corr.get("correctionConfidence", 0.0)
                    _corr_summary = _corr.get("correctionSummary", "")
                    _corr_version = _corr.get("appliedCorrectionVersion", 0)
                except Exception:
                    pass

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
                    "correctionApplied": _corr_applied,
                    "correctionConfidence": _corr_confidence,
                    "correctionSummary": _corr_summary,
                    "appliedCorrectionVersion": _corr_version,
                    # 자가보정 루프: 검증된 승률(strategy_win_rates.json) → confidence 가중 반영
                    "verifiedWinRate": round(wr_prob * 100, 1),
                    "winRateSampleCount": wr_samples,
                    "winRateConfidenceWeight": round(wr_weight, 2),
                    # 팩터 귀속분석용 기술지표 (입력 시점 snapshot)
                    "rsi14": round(_rsi, 1) if _rsi is not None else "",
                    "volumeRatio20": round(_vr, 2) if _vr is not None else "",
                    "distanceToMa20": round(ind.get("distanceToMa20", 0) or 0, 2),
                    "atr14Pct": round(_atr14 / current * 100, 2) if (_atr14 and current) else "",
                    "maFullAlign": _ma_full_align,
                    "mdd20": round(ind.get("mdd20", 0) or 0, 2),
                    "recentMomentum5": round(ind.get("recentMomentum5", 0) or 0, 2),
                }
                _sector_counts_us[_sec_us] = _sector_counts_us.get(_sec_us, 0) + 1
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
