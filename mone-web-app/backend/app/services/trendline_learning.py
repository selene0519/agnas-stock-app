from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.engine.chart_analysis_engine import _calc_atr_threshold, _calc_trendlines, _calc_zigzag, _rows_to_candles
from app.services import data_loader as data


ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT / "data"
TRENDLINE_ANCHOR_LEDGER_CSV = DATA_DIR / "trendline_anchor_ledger.csv"

ANCHOR_COLS = [
    "anchor_id", "market", "symbol", "asOfDate", "lineType",
    "anchor1Date", "anchor1Price", "anchor2Date", "anchor2Price",
    "slope", "intercept", "projected5d", "projected20d", "projected60d",
    "bandPct", "atrBand", "eventSpikeTag", "dataSourceType", "learningEligible",
    "createdAt", "outcome5d", "outcome20d", "outcome60d",
    "respectedTrendline", "brokenTrendline", "falseBreakout", "result",
]

BAND_RULES = {
    "short": (0.35, 0.008),
    "swing": (0.50, 0.012),
    "mid": (0.70, 0.018),
}


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        raw = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        parsed = float(raw)
        return parsed if math.isfinite(parsed) else None
    except Exception:
        return None


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TRENDLINE_ANCHOR_LEDGER_CSV.exists():
        with open(TRENDLINE_ANCHOR_LEDGER_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=ANCHOR_COLS).writeheader()


def _read_rows() -> list[dict[str, Any]]:
    _ensure()
    try:
        with open(TRENDLINE_ANCHOR_LEDGER_CSV, newline="", encoding="utf-8-sig") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except Exception:
        return []


def _write_rows(rows: list[dict[str, Any]]) -> None:
    _ensure()
    with open(TRENDLINE_ANCHOR_LEDGER_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ANCHOR_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _anchor_id(market: str, symbol: str, as_of: str, line_type: str, slope: float, anchor2_date: str) -> str:
    raw = f"{market}|{symbol}|{as_of}|{line_type}|{anchor2_date}|{slope:.8f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _date_at(rows: list[dict[str, Any]], index: int) -> str:
    if not rows:
        return ""
    idx = max(0, min(index, len(rows) - 1))
    return str(rows[idx].get("date") or rows[idx].get("Date") or "")[:10]


def _atr_value(rows: list[dict[str, Any]], period: int = 14) -> float:
    candles = _rows_to_candles(rows)
    if len(candles) < 2:
        return 0.0
    recent = candles[-min(len(candles), period + 1):]
    values: list[float] = []
    for idx in range(1, len(recent)):
        high, low, prev_close = recent[idx].high, recent[idx].low, recent[idx - 1].close
        values.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(values) / len(values) if values else 0.0


def band_width(rows: list[dict[str, Any]], horizon: str) -> tuple[float, float]:
    candles = _rows_to_candles(rows)
    if not candles:
        return 0.0, 0.0
    current = candles[-1].close
    atr = _atr_value(rows)
    mult, pct_cap = BAND_RULES.get(horizon, BAND_RULES["swing"])
    width = min(atr * mult, current * pct_cap) if current > 0 and atr > 0 else 0.0
    pct = (width / current * 100) if current > 0 else 0.0
    return width, pct


def _line_from_chart(chart: dict[str, Any], line_type: str) -> dict[str, Any] | None:
    key = "supportLine" if line_type == "support" else "resistanceLine"
    value = chart.get(key)
    return value if isinstance(value, dict) else None


def _line_price(line: dict[str, Any], index: int) -> float | None:
    slope = _num(line.get("slope"))
    intercept = _num(line.get("intercept"))
    if slope is None or intercept is None:
        return None
    value = slope * index + intercept
    return value if value > 0 else None


def _line_outcome(line: Any, future_rows: list[dict[str, Any]], line_type: str, width: float) -> dict[str, Any]:
    outcomes = {"outcome5d": "PENDING", "outcome20d": "PENDING", "outcome60d": "PENDING"}
    respected = True
    broken = False
    false_breakout = False
    first_break_idx: int | None = None
    for idx, row in enumerate(future_rows[:60], start=1):
        high = _num(row.get("high") or row.get("High") or row.get("close"))
        low = _num(row.get("low") or row.get("Low") or row.get("close"))
        line_price = line.price_at(line.end_index + idx) if hasattr(line, "price_at") else None
        if line_price is None:
            continue
        if line_type == "support":
            day_broken = bool(low is not None and low < line_price - width)
            day_respected = not day_broken
        else:
            day_broken = bool(high is not None and high > line_price + width)
            day_respected = not day_broken
        if day_broken and first_break_idx is None:
            first_break_idx = idx
            broken = True
            respected = False
        if first_break_idx is not None and idx <= first_break_idx + 3:
            close = _num(row.get("close") or row.get("Close"))
            if close is not None:
                recovered = close >= line_price if line_type == "support" else close <= line_price
                false_breakout = bool(false_breakout or recovered)
        if idx in (5, 20, 60):
            outcomes[f"outcome{idx}d"] = "RESPECTED" if day_respected else "BROKEN"
    result = "WIN_RESPECTED" if respected else ("WATCH_FALSE_BREAKOUT" if false_breakout else "LOSS_BROKEN")
    return {
        **outcomes,
        "respectedTrendline": respected,
        "brokenTrendline": broken,
        "falseBreakout": false_breakout,
        "result": result,
    }


def _historical_samples(rows: list[dict[str, Any]], market: str, symbol: str, data_source_type: str) -> list[dict[str, Any]]:
    if data_source_type != "actual_ohlcv" or len(rows) < 80:
        return []
    cutoffs: list[int] = []
    latest_cutoff = len(rows) - 21
    for offset in (0, 10, 20, 30, 40, 50):
        cutoff = latest_cutoff - offset
        if cutoff >= 55:
            cutoffs.append(cutoff)
    samples: list[dict[str, Any]] = []
    for cutoff in sorted(set(cutoffs)):
        history = rows[:cutoff + 1]
        future = rows[cutoff + 1:cutoff + 61]
        candles = _rows_to_candles(history)
        if len(candles) < 80 or len(future) < 5:
            continue
        pivots = _calc_zigzag(candles, threshold=_calc_atr_threshold(candles), win_size=3)
        support, resistance = _calc_trendlines(candles, pivots) if len(pivots) >= 4 else (None, None)
        for line_type, line in (("support", support), ("resistance", resistance)):
            if line is None:
                continue
            width, pct = band_width(history, "swing")
            as_of = _date_at(history, len(history) - 1)
            anchor2_date = _date_at(history, line.anchor2_index)
            sample = {
                "anchor_id": _anchor_id(market, symbol, as_of, line_type, float(line.slope), anchor2_date),
                "market": market,
                "symbol": symbol,
                "asOfDate": as_of,
                "lineType": line_type,
                "anchor1Date": _date_at(history, line.start_index),
                "anchor1Price": round(float(line.start_price), 4),
                "anchor2Date": anchor2_date,
                "anchor2Price": round(float(line.anchor2_price), 4),
                "slope": round(float(line.slope), 8),
                "intercept": round(float(line.intercept), 4),
                "projected5d": round(float(line.price_at(line.end_index + 5)), 4),
                "projected20d": round(float(line.price_at(line.end_index + 20)), 4),
                "projected60d": round(float(line.price_at(line.end_index + 60)), 4),
                "bandPct": round(pct, 4),
                "atrBand": round(width, 4),
                "eventSpikeTag": line.event_spike_tag,
                "dataSourceType": data_source_type,
                "learningEligible": data_source_type == "actual_ohlcv",
                "createdAt": datetime.now().isoformat(timespec="seconds"),
                **_line_outcome(line, future, line_type, width),
            }
            samples.append(sample)
    return samples


def _upsert_ledger(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    existing = _read_rows()
    merged = {str(row.get("anchor_id")): row for row in existing if row.get("anchor_id")}
    for row in rows:
        merged[str(row.get("anchor_id"))] = {key: row.get(key, "") for key in ANCHOR_COLS}
    _write_rows(list(merged.values()))


def _stats(market: str, symbol: str, line_type: str, event_tag: str) -> dict[str, Any]:
    rows = [
        row for row in _read_rows()
        if row.get("market") == market
        and row.get("symbol") == symbol
        and row.get("lineType") == line_type
        and str(row.get("learningEligible")).lower() in {"true", "1"}
        and str(row.get("result") or "") not in {"", "PENDING"}
    ]
    same_event = [row for row in rows if row.get("eventSpikeTag") == event_tag]
    basis = same_event if len(same_event) >= 3 else rows
    wins = [row for row in basis if str(row.get("result", "")).startswith("WIN")]
    rate = round(len(wins) / len(basis) * 100, 2) if basis else None
    return {
        "sampleCount": len(basis),
        "historicalWinRate": rate,
        "basis": "same_event" if basis is same_event and len(same_event) >= 3 else "symbol_line_type",
    }


def analyze(
    market: str,
    symbol: str,
    rows: list[dict[str, Any]],
    chart: dict[str, Any],
    horizon: str,
    data_source_type: str,
) -> dict[str, Any]:
    """Return learned trendline projection and record anchor samples."""
    learning_eligible = data_source_type == "actual_ohlcv"
    samples = _historical_samples(rows, market, symbol, data_source_type)
    _upsert_ledger(samples)

    candidates: list[tuple[str, dict[str, Any]]] = []
    for line_type in ("support", "resistance"):
        line = _line_from_chart(chart, line_type)
        if line:
            candidates.append((line_type, line))
    if not candidates or not rows:
        return _empty_result(data_source_type, learning_eligible, "NO_TRENDLINE")

    current_index = len(rows) - 1
    current_close = _num(rows[-1].get("close")) or 0.0
    ranked: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
    for line_type, line in candidates:
        line_price = _line_price(line, current_index)
        if line_price is None or current_close <= 0:
            continue
        distance = abs(current_close - line_price) / current_close
        event_tag = str(line.get("eventSpikeTag") or "none")
        stat = _stats(market, symbol, line_type, event_tag)
        historical = float(stat["historicalWinRate"] or 50.0)
        anchor_score = float(_num(line.get("anchorScore")) or 0.0)
        event_penalty = 8.0 if event_tag not in {"", "none"} and stat["sampleCount"] < 3 else 0.0
        total = anchor_score * 0.55 + historical * 0.35 + max(0.0, 15.0 - distance * 100.0) - event_penalty
        ranked.append((total, line_type, line, stat))
    if not ranked:
        return _empty_result(data_source_type, learning_eligible, "NO_ACTIVE_TRENDLINE")

    ranked.sort(key=lambda item: item[0], reverse=True)
    total_score, line_type, line, stat = ranked[0]
    width, pct = band_width(rows, horizon)
    band_allowed = pct <= (BAND_RULES.get(horizon, BAND_RULES["swing"])[1] * 100.0 + 1e-9)
    projected = {
        "trendlineProjected5d": round(float(_line_price(line, current_index + 5) or 0), 4),
        "trendlineProjected20d": round(float(_line_price(line, current_index + 20) or 0), 4),
        "trendlineProjected60d": round(float(_line_price(line, current_index + 60) or 0), 4),
    }
    current_line_price = float(_line_price(line, current_index) or 0.0)
    sample_count = int(stat.get("sampleCount") or 0)
    win_rate = stat.get("historicalWinRate")
    if not learning_eligible:
        status = "LOW_CONFIDENCE_FALLBACK"
    elif sample_count < 3:
        status = "INSUFFICIENT_SAMPLE"
    elif win_rate is not None and float(win_rate) >= 60.0 and band_allowed:
        status = "VERIFIED"
    elif win_rate is not None and float(win_rate) < 45.0:
        status = "FAILED_ANCHOR_HISTORY"
    else:
        status = "WATCH_ONLY"

    as_of = _date_at(rows, current_index)
    anchor2_date = _date_at(rows, int(line.get("anchor2Index") or line.get("endIndex") or current_index))
    current_record = {
        "anchor_id": _anchor_id(market, symbol, as_of, line_type, float(_num(line.get("slope")) or 0.0), anchor2_date),
        "market": market,
        "symbol": symbol,
        "asOfDate": as_of,
        "lineType": line_type,
        "anchor1Date": _date_at(rows, int(line.get("startIndex") or 0)),
        "anchor1Price": line.get("startPrice"),
        "anchor2Date": anchor2_date,
        "anchor2Price": line.get("anchor2Price") or line.get("endPrice"),
        "slope": line.get("slope"),
        "intercept": line.get("intercept"),
        "projected5d": projected["trendlineProjected5d"],
        "projected20d": projected["trendlineProjected20d"],
        "projected60d": projected["trendlineProjected60d"],
        "bandPct": round(pct, 4),
        "atrBand": round(width, 4),
        "eventSpikeTag": line.get("eventSpikeTag") or "none",
        "dataSourceType": data_source_type,
        "learningEligible": learning_eligible,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "outcome5d": "PENDING",
        "outcome20d": "PENDING",
        "outcome60d": "PENDING",
        "respectedTrendline": "",
        "brokenTrendline": "",
        "falseBreakout": "",
        "result": "PENDING",
    }
    _upsert_ledger([current_record])

    return {
        **projected,
        "trendlineBandUpper": round(current_line_price + width, 4),
        "trendlineBandLower": round(max(0.0, current_line_price - width), 4),
        "trendlineAnchorScore": round(total_score, 2),
        "trendlineHistoricalWinRate": win_rate,
        "trendlineLearningStatus": status,
        "trendlineDataSourceType": data_source_type,
        "trendlineLearningEligible": learning_eligible,
        "trendlineLineType": line_type,
        "trendlineEventSpikeTag": line.get("eventSpikeTag") or "none",
        "trendlineBandPct": round(pct, 4),
        "trendlineBandAllowed": band_allowed,
        "trendlineAnchorId": current_record["anchor_id"],
        "trendlineSampleCount": sample_count,
        "trendlineLedgerPath": str(TRENDLINE_ANCHOR_LEDGER_CSV),
    }


def _empty_result(data_source_type: str, learning_eligible: bool, status: str) -> dict[str, Any]:
    return {
        "trendlineProjected5d": None,
        "trendlineProjected20d": None,
        "trendlineProjected60d": None,
        "trendlineBandUpper": None,
        "trendlineBandLower": None,
        "trendlineAnchorScore": 0.0,
        "trendlineHistoricalWinRate": None,
        "trendlineLearningStatus": status,
        "trendlineDataSourceType": data_source_type,
        "trendlineLearningEligible": learning_eligible,
        "trendlineLineType": "",
        "trendlineEventSpikeTag": "none",
        "trendlineBandPct": 0.0,
        "trendlineBandAllowed": False,
        "trendlineAnchorId": "",
        "trendlineSampleCount": 0,
        "trendlineLedgerPath": str(TRENDLINE_ANCHOR_LEDGER_CSV),
    }


def learning_report(market: str = "all", symbol: str = "", limit: int = 200) -> dict[str, Any]:
    rows = _read_rows()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if market not in {"", "all"} and row.get("market") != market:
            continue
        if symbol and row.get("symbol") != symbol:
            continue
        filtered.append(row)
    eligible = [row for row in filtered if str(row.get("learningEligible")).lower() in {"true", "1"}]
    completed = [row for row in eligible if str(row.get("result") or "") not in {"", "PENDING"}]
    wins = [row for row in completed if str(row.get("result", "")).startswith("WIN")]
    return {
        "status": "OK" if filtered else "NO_DATA",
        "market": market,
        "symbol": symbol,
        "count": len(filtered[:limit]),
        "totalCount": len(filtered),
        "learningEligibleCount": len(eligible),
        "completedCount": len(completed),
        "winRate": round(len(wins) / len(completed) * 100, 2) if completed else None,
        "source": str(TRENDLINE_ANCHOR_LEDGER_CSV),
        "items": filtered[:limit],
    }
