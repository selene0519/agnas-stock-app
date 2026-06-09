from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from app.engine.chart_analysis_engine import (
    _calc_atr_threshold,
    _calc_trendlines,
    _calc_zigzag,
    _rows_to_candles,
    build_chart_analysis,
    state_to_dict,
)
from app.engine.quant_scanner import load_market_regime, load_ohlcv
from app.services import data_loader as data

TRENDLINE_VERIFIED_TARGET_PCT = 90.0
TRENDLINE_VERIFIED_MIN_SAMPLES = 3


def _load_benchmark_closes(market: str) -> list[tuple[str, float]]:
    """Load (date, close) pairs from benchmark_daily.csv for the given market."""
    import csv
    key = "KOSPI" if market == "kr" else "NASDAQ"
    path = data.REPO_ROOT / "data" / "market" / "benchmark_daily.csv"
    rows: list[tuple[str, float]] = []
    if not path.is_file():
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if str(r.get("benchmark", "")).upper() != key:
                continue
            try:
                rows.append((str(r["date"]).strip(), float(str(r.get("close") or 0).replace(",", ""))))
            except Exception:
                pass
    rows.sort(key=lambda x: x[0])
    return rows


def _historical_regime_score(benchmark: list[tuple[str, float]], as_of_date: str) -> float:
    """Compute market regime score using only benchmark data up to as_of_date."""
    closes = [c for d, c in benchmark if d <= as_of_date and c > 0]
    if len(closes) < 20:
        return 50.0
    ma20 = sum(closes[-20:]) / 20
    latest = closes[-1]
    dist = (latest - ma20) / ma20 * 100 if ma20 else 0.0
    mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
    if dist > 2.0 and mom5 > 1.0:
        adjust = +8.0
    elif dist > 0 and mom5 > 0:
        adjust = +3.0
    elif mom5 < -5.0 or dist < -5.0:
        adjust = -30.0
    elif dist < -2.0 or mom5 < -2.0:
        adjust = -18.0
    else:
        adjust = 0.0
    return max(0.0, min(100.0, 50.0 + adjust))


DEFAULT_SYMBOLS = {
    "kr": ["005930", "000660", "005380", "035420", "035720", "051910", "068270", "207940"],
    "us": ["NVDA", "AAPL", "MSFT", "AMZN", "AMD", "TSLA", "AVGO", "META"],
}


def _num(value: Any) -> float | None:
    try:
        raw = str(value or "").replace(",", "").replace("$", "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        parsed = float(raw)
        return None if math.isnan(parsed) else parsed
    except Exception:
        return None


def _date(row: dict[str, Any]) -> str:
    return str(row.get("date") or row.get("Date") or row.get("날짜") or "").strip()


def _close(row: dict[str, Any]) -> float | None:
    return _num(row.get("close") or row.get("Close") or row.get("종가") or row.get("stck_clpr"))


def _high(row: dict[str, Any]) -> float | None:
    return _num(row.get("high") or row.get("High") or row.get("고가") or row.get("stck_hgpr")) or _close(row)


def _low(row: dict[str, Any]) -> float | None:
    return _num(row.get("low") or row.get("Low") or row.get("저가") or row.get("stck_lwpr")) or _close(row)


def _ohlcv_files(market: str) -> list[str]:
    base = data.REPO_ROOT / "data" / "market" / "ohlcv"
    if not base.is_dir():
        return []
    prefix = f"{market}_"
    suffix = "_daily.csv"
    symbols: list[str] = []
    for path in sorted(base.glob(f"{prefix}*{suffix}")):
        name = path.name
        symbols.append(name[len(prefix):-len(suffix)])
    return symbols


def _symbol_universe(market: str, limit: int) -> list[str]:
    preferred = [symbol for symbol in DEFAULT_SYMBOLS.get(market, []) if load_ohlcv(data.REPO_ROOT, market, symbol)]
    seen = set(preferred)
    for symbol in _ohlcv_files(market):
        if symbol not in seen:
            preferred.append(symbol)
            seen.add(symbol)
        if len(preferred) >= limit:
            break
    return preferred[:limit]


def _cutoff_indexes(row_count: int, future_bars: int, min_history: int, max_cutoffs: int) -> list[int]:
    last_cutoff = row_count - future_bars - 1
    if last_cutoff < min_history:
        return []
    step = max(10, future_bars)
    indexes = [last_cutoff - step * idx for idx in range(max_cutoffs)]
    return [idx for idx in indexes if idx >= min_history]


def _future_stats(current: float, future_rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_close(row) for row in future_rows]
    closes = [value for value in closes if value is not None and value > 0]
    if not closes or current <= 0:
        return {"futureReturnPct": None, "maxReturnPct": None, "minReturnPct": None}
    returns = [((value - current) / current) * 100 for value in closes]
    return {
        "futureReturnPct": round(returns[-1], 2),
        "maxReturnPct": round(max(returns), 2),
        "minReturnPct": round(min(returns), 2),
    }


def _line_outcome(line: Any, future_rows: list[dict[str, Any]], kind: str, tolerance_pct: float = 0.015) -> dict[str, Any]:
    broken = False
    broken_at = ""
    worst_break_pct = 0.0
    for offset, row in enumerate(future_rows, start=1):
        future_index = int(line.end_index) + offset
        line_price = float(line.price_at(future_index))
        if line_price <= 0:
            continue
        if kind == "support":
            observed = _low(row)
            if observed is None:
                continue
            break_pct = (line_price - observed) / line_price
        else:
            observed = _high(row)
            if observed is None:
                continue
            break_pct = (observed - line_price) / line_price
        if break_pct > worst_break_pct:
            worst_break_pct = break_pct
        if break_pct > tolerance_pct and not broken:
            broken = True
            broken_at = _date(row)
    return {
        "respected": not broken,
        "broken": broken,
        "brokenAt": broken_at,
        "worstBreakPct": round(worst_break_pct * 100, 2),
    }


def _news_sentiment(market: str, symbol: str, as_of_date: str) -> dict[str, Any]:
    try:
        from app.engine.news_sentiment_engine import score_news_sentiment
        return score_news_sentiment(market, symbol, symbol, as_of_date=as_of_date)
    except Exception:
        return {"penalty": 0.0, "tag": "NEUTRAL", "reasons": []}


def _apply_verified_trendline_gate(records: list[dict[str, Any]], target_pct: float = TRENDLINE_VERIFIED_TARGET_PCT) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in records:
        groups.setdefault((str(row["market"]), str(row["symbol"]), str(row["kind"])), []).append(row)

    for row in records:
        group = groups.get((str(row["market"]), str(row["symbol"]), str(row["kind"])), [])
        group_rate = None
        if len(group) >= TRENDLINE_VERIFIED_MIN_SAMPLES:
            group_rate = round(sum(1 for item in group if item["respected"]) / len(group) * 100, 1)
        news_penalty = float(row.get("newsRiskPenalty") or 0.0)
        news_allowed = news_penalty < 6.0
        verified = (
            group_rate is not None
            and group_rate >= target_pct
            and bool(row.get("structurallyValid"))
            and news_allowed
        )
        row["calibratedRespectRatePct"] = group_rate
        row["calibrationSampleCount"] = len(group)
        row["newsAllowed"] = news_allowed
        row["verified90"] = verified
        row["confidenceLabel"] = "VERIFIED_90" if verified else ("NEWS_BLOCKED" if not news_allowed else "WATCH_ONLY")
    return records


def trendline_accuracy(
    market: str = "all",
    future_bars: int = 20,
    symbol_limit: int = 12,
    max_cutoffs: int = 6,
    min_history: int = 80,
    include_items: bool = True,
) -> dict[str, Any]:
    markets = ["kr", "us"] if market == "all" else [market]
    records: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    symbol_count = 0

    for mk in markets:
        for symbol in _symbol_universe(mk, symbol_limit):
            rows = load_ohlcv(data.REPO_ROOT, mk, symbol)
            if not rows:
                continue
            symbol_count += 1
            for cutoff in _cutoff_indexes(len(rows), future_bars, min_history, max_cutoffs):
                future_rows = rows[cutoff + 1:cutoff + 1 + future_bars]
                if len(future_rows) < future_bars:
                    continue
                candles = _rows_to_candles(rows[:cutoff + 1])
                if len(candles) < min_history:
                    continue
                threshold = _calc_atr_threshold(candles)
                pivots = _calc_zigzag(candles, threshold=threshold, win_size=3)
                support, resistance = _calc_trendlines(candles, pivots) if len(pivots) >= 4 else (None, None)
                cutoff_date = _date(rows[cutoff])

                for kind, line in (("support", support), ("resistance", resistance)):
                    if line is None:
                        continue
                    outcome = _line_outcome(line, future_rows, kind)
                    sentiment = _news_sentiment(mk, symbol, cutoff_date)
                    record = {
                        "market": mk,
                        "symbol": symbol,
                        "asOf": cutoff_date,
                        "futureEnd": _date(future_rows[-1]),
                        "kind": kind,
                        "lineDirection": line.line_direction,
                        "structurallyValid": bool(line.is_structurally_valid),
                        "touchCount": int(line.touch_count),
                        "slopePctPerBar": line.slope_pct_per_bar,
                        "linePriceAtT": round(float(line.end_price), 4),
                        "newsRiskPenalty": float(sentiment.get("penalty") or 0.0),
                        "newsSentimentTag": sentiment.get("tag", "NEUTRAL"),
                        "newsSentimentReasons": sentiment.get("reasons", [])[:3],
                        **outcome,
                    }
                    records.append(record)
                    if len(examples) < 10:
                        examples.append({
                            **record,
                            "chart": _chart_rows(rows, cutoff, future_bars),
                        })

    records = _apply_verified_trendline_gate(records)
    high_confidence = [r for r in records if r["structurallyValid"] and int(r["touchCount"]) >= 3]
    verified_90 = [r for r in records if r.get("verified90")]
    news_blocked = [r for r in records if not r.get("newsAllowed", True)]
    support_rows = [r for r in records if r["kind"] == "support"]
    resistance_rows = [r for r in records if r["kind"] == "resistance"]

    def respect_rate(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        return round(sum(1 for row in rows if row["respected"]) / len(rows) * 100, 1)

    payload = {
        "status": "OK" if records else "NO_DATA",
        "market": market,
        "policy": "Trendline snapshot backtest: draw support/resistance using OHLCV only through asOf, then check whether the next futureBars candles violate the projected line by more than 1.5%.",
        "verifiedPolicy": "VERIFIED_90 is shown only when the same symbol/direction has at least 3 historical samples, calibrated respect rate is >= 90%, structure is valid, and news/disclosure risk penalty is below 6.",
        "targetRespectRatePct": TRENDLINE_VERIFIED_TARGET_PCT,
        "futureBars": future_bars,
        "symbolCount": symbol_count,
        "sampleCount": len(records),
        "supportCount": len(support_rows),
        "resistanceCount": len(resistance_rows),
        "highConfidenceCount": len(high_confidence),
        "verified90Count": len(verified_90),
        "newsBlockedCount": len(news_blocked),
        "respectRatePct": respect_rate(records),
        "supportRespectRatePct": respect_rate(support_rows),
        "resistanceRespectRatePct": respect_rate(resistance_rows),
        "highConfidenceRespectRatePct": respect_rate(high_confidence),
        "verified90RespectRatePct": respect_rate(verified_90),
    }
    if include_items:
        payload["items"] = records
        payload["examples"] = examples
    return payload


def _chart_rows(rows: list[dict[str, Any]], cutoff: int, future_bars: int, history_bars: int = 80) -> dict[str, Any]:
    history = rows[max(0, cutoff - history_bars + 1):cutoff + 1]
    future = rows[cutoff + 1:cutoff + 1 + future_bars]

    def point(row: dict[str, Any]) -> dict[str, Any]:
        return {"date": _date(row), "close": _close(row)}

    return {
        "history": [point(row) for row in history],
        "future": [point(row) for row in future],
    }


def chart_analysis_accuracy(
    market: str = "all",
    future_bars: int = 20,
    symbol_limit: int = 8,
    max_cutoffs: int = 4,
    min_history: int = 80,
) -> dict[str, Any]:
    markets = ["kr", "us"] if market == "all" else [market]
    records: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    symbol_count = 0

    for mk in markets:
        benchmark = _load_benchmark_closes(mk)
        for symbol in _symbol_universe(mk, symbol_limit):
            rows = load_ohlcv(data.REPO_ROOT, mk, symbol)
            if not rows:
                continue
            symbol_count += 1
            for cutoff in _cutoff_indexes(len(rows), future_bars, min_history, max_cutoffs):
                current = _close(rows[cutoff])
                future_rows = rows[cutoff + 1:cutoff + 1 + future_bars]
                if current is None or current <= 0 or len(future_rows) < future_bars:
                    continue

                # Use historical regime and benchmark closes at the cutoff date
                cutoff_date = _date(rows[cutoff])
                regime_score = _historical_regime_score(benchmark, cutoff_date)
                bench_closes = [c for d, c in benchmark if d <= cutoff_date]
                state = build_chart_analysis(
                    rows=rows[:cutoff + 1],
                    symbol=symbol,
                    market=mk,
                    market_regime_score=regime_score,
                    benchmark_closes=bench_closes,
                    horizon_bars=future_bars,
                    freshness_reference_date=_date(rows[cutoff]),
                )
                payload = state_to_dict(state)
                direction = str(payload.get("confluenceDirection") or "neutral")
                score = float(payload.get("confluenceScore") or 0)
                status = str(payload.get("signalStatus") or "none")
                # confirmed signals: score >= 65 (FSM validated, sustained above threshold)
                # developing signals: score >= 70 (higher bar — not yet FSM-confirmed)
                actionable = direction in {"bullish", "bearish"} and (
                    (status == "confirmed" and score >= 65) or
                    (status == "developing" and score >= 70)
                )
                stats = _future_stats(current, future_rows)
                future_return = stats["futureReturnPct"]
                directional_hit = None
                if actionable and future_return is not None:
                    directional_hit = future_return > 0 if direction == "bullish" else future_return < 0

                record = {
                    "market": mk,
                    "symbol": symbol,
                    "asOf": _date(rows[cutoff]),
                    "futureEnd": _date(future_rows[-1]),
                    "currentClose": current,
                    "direction": direction,
                    "signalStatus": status,
                    "confluenceScore": round(score, 1),
                    "chartSignalScore": payload.get("chartSignalScore"),
                    "chartSignalTag": payload.get("chartSignalTag"),
                    "actionable": actionable,
                    "directionalHit": directional_hit,
                    **stats,
                    "reasons": payload.get("confluenceReasons", [])[:5],
                }
                records.append(record)

                if actionable and len(examples) < 8:
                    examples.append({
                        **record,
                        "levels": {
                            "supportLine": payload.get("supportLine"),
                            "resistanceLine": payload.get("resistanceLine"),
                            "primaryRetracementLevel": payload.get("primaryRetracementLevel"),
                            "overlapSignals": payload.get("overlapSignals", [])[:4],
                        },
                        "chart": _chart_rows(rows, cutoff, future_bars),
                    })

    actionable_records = [row for row in records if row["actionable"] and row["directionalHit"] is not None]
    hits = sum(1 for row in actionable_records if row["directionalHit"])
    bullish = [row for row in actionable_records if row["direction"] == "bullish"]
    bearish = [row for row in actionable_records if row["direction"] == "bearish"]

    def hit_rate(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        return round(sum(1 for row in rows if row["directionalHit"]) / len(rows) * 100, 1)

    avg_future_return = None
    if actionable_records:
        avg_future_return = round(
            sum(float(row["futureReturnPct"]) for row in actionable_records if row["futureReturnPct"] is not None)
            / len(actionable_records),
            2,
        )

    return {
        "status": "OK" if records else "NO_DATA",
        "market": market,
        "policy": "Snapshot backtest: each analysis uses OHLCV only through asOf, then checks the next futureBars closes.",
        "futureBars": future_bars,
        "symbolCount": symbol_count,
        "sampleCount": len(records),
        "actionableCount": len(actionable_records),
        "neutralOrLowScoreCount": len(records) - len(actionable_records),
        "directionalHitRatePct": hit_rate(actionable_records),
        "bullishHitRatePct": hit_rate(bullish),
        "bearishHitRatePct": hit_rate(bearish),
        "avgFutureReturnPct": avg_future_return,
        "items": records,
        "examples": examples,
    }
