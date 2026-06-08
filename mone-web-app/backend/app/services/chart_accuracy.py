from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from app.engine.chart_analysis_engine import build_chart_analysis, state_to_dict
from app.engine.quant_scanner import load_market_regime, load_ohlcv
from app.services import data_loader as data


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
