"""Research only: conservative walk-forward tests for bear/range long setups.

This script deliberately does not change recommendation scores.  It uses the
current local universe (therefore still has survivorship bias) and writes a
report that makes this limitation explicit.  A setup is merely a research
candidate when it is profitable *after* round-trip costs in both the pre-2022
and 2022+ partitions.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OHLCV = ROOT / "data" / "market" / "ohlcv"
REPORTS = ROOT / "reports"
ROUND_TRIP_COST_PCT = 0.20
HOLD_DAYS = 5
MIN_SPLIT_SAMPLES = 30
BENCHMARKS = {
    "kr": {"KOSPI", "KOSDAQ", "KOSPI200"},
    "us": {"SPY", "QQQ", "SP500", "DIA", "IWM", "RSP", "HYG", "LQD", "TLT", "XLY", "XLP", "VIX", "XLE", "XLF", "GLD", "SCHD", "SMH", "SOXX", "SOXL"},
}


def _num(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _date(value: Any) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else ""


def _read(path: Path) -> list[dict[str, Any]]:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                rows = []
                for raw in csv.DictReader(handle):
                    date = _date(raw.get("date") or raw.get("Date"))
                    open_ = _num(raw.get("open") or raw.get("Open"))
                    high = _num(raw.get("high") or raw.get("High"))
                    low = _num(raw.get("low") or raw.get("Low"))
                    close = _num(raw.get("close") or raw.get("Close"))
                    if date and all(value is not None for value in (open_, high, low, close)):
                        rows.append({"date": date, "open": open_, "high": high, "low": low, "close": close})
                return sorted(rows, key=lambda row: row["date"])
        except Exception:
            continue
    return []


def _sma(values: list[float], period: int) -> float | None:
    return statistics.fmean(values[-period:]) if len(values) >= period else None


def _std(values: list[float], period: int) -> float | None:
    return statistics.pstdev(values[-period:]) if len(values) >= period else None


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    deltas = [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]
    gains = sum(max(value, 0.0) for value in deltas) / period
    losses = sum(max(-value, 0.0) for value in deltas) / period
    if losses == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + gains / losses))


def _regime_by_date(index_rows: list[dict[str, Any]]) -> dict[str, str]:
    """Calculate the index regime once, before looping through constituents."""
    closes = [row["close"] for row in index_rows]
    result: dict[str, str] = {}
    for index, row in enumerate(index_rows):
        if index < 60:
            continue
        ma60 = statistics.fmean(closes[index - 59:index + 1])
        ret20 = (closes[index] / closes[index - 20] - 1.0) * 100.0
        if closes[index] < ma60 and ret20 <= -3.0:
            result[row["date"]] = "BEAR"
        elif closes[index] > ma60 and ret20 >= 3.0:
            result[row["date"]] = "BULL"
        else:
            result[row["date"]] = "RANGE"
    return result


def _signal(strategy: str, closes: list[float]) -> bool:
    if len(closes) < 21:
        return False
    rsi = _rsi(closes)
    ret5 = (closes[-1] / closes[-6] - 1.0) * 100.0
    mean20, std20 = _sma(closes, 20), _std(closes, 20)
    if rsi is None or mean20 is None or std20 is None:
        return False
    if strategy == "RANGE_MEAN_REVERSION":
        return rsi <= 35 and ret5 <= -3.0 and closes[-1] <= mean20 - std20
    if strategy == "BEAR_OVERSOLD_SCALP":
        return rsi <= 28 and ret5 <= -7.0 and closes[-1] <= mean20 - 1.25 * std20
    return False


def _outcome(rows: list[dict[str, Any]], signal_index: int, target_pct: float, stop_pct: float) -> dict[str, Any] | None:
    if signal_index + HOLD_DAYS >= len(rows):
        return None
    entry = rows[signal_index + 1]["open"]
    if entry <= 0:
        return None
    target, stop = entry * (1 + target_pct / 100), entry * (1 - stop_pct / 100)
    future = rows[signal_index + 1: signal_index + HOLD_DAYS + 1]
    exit_price, exit_reason = future[-1]["close"], "TIME_EXIT"
    for bar in future:
        # Intraday path is unknown: when both prices occur, count the stop first.
        if bar["low"] <= stop:
            exit_price, exit_reason = stop, "STOP_FIRST"
            break
        if bar["high"] >= target:
            exit_price, exit_reason = target, "TARGET"
            break
    gross = (exit_price / entry - 1.0) * 100.0
    return {"entryDate": future[0]["date"], "exitDate": future[-1]["date"], "netReturnPct": round(gross - ROUND_TRIP_COST_PCT, 4), "exitReason": exit_reason}


def _stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(row["netReturnPct"]) for row in trades]
    count = len(returns)
    if not count:
        return {"sampleCount": 0, "winRatePct": None, "averageNetReturnPct": None, "medianNetReturnPct": None, "targetRatePct": None, "stopRatePct": None}
    return {
        "sampleCount": count,
        "winRatePct": round(sum(value > 0 for value in returns) / count * 100, 2),
        "averageNetReturnPct": round(statistics.fmean(returns), 4),
        "medianNetReturnPct": round(statistics.median(returns), 4),
        "targetRatePct": round(sum(row["exitReason"] == "TARGET" for row in trades) / count * 100, 2),
        "stopRatePct": round(sum(row["exitReason"] == "STOP_FIRST" for row in trades) / count * 100, 2),
    }


def research_market(market: str) -> dict[str, Any]:
    market = market.lower()
    index_symbol = "KOSPI" if market == "kr" else "SPY"
    index_rows = _read(OHLCV / f"{market}_{index_symbol}_daily.csv")
    regimes = _regime_by_date(index_rows)
    universe = {
        path.name[len(market) + 1:-len("_daily.csv")]: _read(path)
        for path in OHLCV.glob(f"{market}_*_daily.csv")
        if path.name[len(market) + 1:-len("_daily.csv")] not in BENCHMARKS[market]
    }
    strategies = {
        "RANGE_MEAN_REVERSION": {"regime": "RANGE", "targetPct": 3.0, "stopPct": 2.5},
        "BEAR_OVERSOLD_SCALP": {"regime": "BEAR", "targetPct": 4.0, "stopPct": 3.0},
    }
    results: dict[str, Any] = {}
    for name, config in strategies.items():
        trades: list[dict[str, Any]] = []
        for symbol, rows in universe.items():
            closes: list[float] = []
            for index, row in enumerate(rows):
                closes.append(row["close"])
                if index % 5 != 0 or len(closes) < 61:
                    continue
                if regimes.get(row["date"]) != config["regime"] or not _signal(name, closes):
                    continue
                outcome = _outcome(rows, index, config["targetPct"], config["stopPct"])
                if outcome:
                    trades.append({"symbol": symbol, "signalDate": row["date"], **outcome})
        train = [trade for trade in trades if trade["signalDate"] < "2022-01-01"]
        oos = [trade for trade in trades if trade["signalDate"] >= "2022-01-01"]
        train_stats, oos_stats = _stats(train), _stats(oos)
        qualifies = (
            train_stats["sampleCount"] >= MIN_SPLIT_SAMPLES and oos_stats["sampleCount"] >= MIN_SPLIT_SAMPLES
            and (train_stats["averageNetReturnPct"] or 0) > 0 and (oos_stats["averageNetReturnPct"] or 0) > 0
        )
        results[name] = {"definition": config, "all": _stats(trades), "pre2022": train_stats, "from2022": oos_stats, "researchCandidate": qualifies, "trades": trades}
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"), "market": market,
        "dataRange": f"{index_rows[0]['date']} ~ {index_rows[-1]['date']}" if index_rows else "",
        "universeCount": len(universe), "costAssumptionRoundTripPct": ROUND_TRIP_COST_PCT,
        "sameBarPolicy": "stop_first_when_target_and_stop_both_touch", "survivorshipBias": True,
        "operationalPolicy": "research_only; no result may alter recommendations without an independent review and point-in-time universe validation",
        "strategies": results,
    }


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    for market in ("kr", "us"):
        report = research_market(market)
        path = REPORTS / f"regime_edge_research_{market}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        candidates = [name for name, result in report["strategies"].items() if result["researchCandidate"]]
        print(f"{market}: universe={report['universeCount']}, candidates={candidates or 'none'} -> {path}")


if __name__ == "__main__":
    main()
