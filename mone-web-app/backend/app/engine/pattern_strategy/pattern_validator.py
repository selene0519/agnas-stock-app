"""
Pattern Strategy Engine v1 — Walk-Forward pattern validator.

Rules:
  • Only uses OHLCV rows with date < recommendationDate (no future leakage).
  • Evaluates each historical recommendation 1/5/20 days forward.
  • Reports per-pattern: sampleCount, winRate, avgReturn, stopRate, targetHitRate.
  • Reports blockedOutcomeStats for isBlocked=True symbols.
  • Returns patternCalibrationSuggestions for self-correction integration.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import indicators as ind_mod
from . import geometric_patterns as gp_mod
from .pattern_engine import analyze, load_params
from .types import DEFAULT_PARAMS, GEO_PATTERN_FAMILY


# ── Paths ─────────────────────────────────────────────────────────────────
_REPO_ROOT   = Path(__file__).resolve().parents[5]
_OHLCV_DIR   = _REPO_ROOT / "data" / "market" / "ohlcv"
_REPORTS_DIR = _REPO_ROOT / "reports"


# ── 9-Strategy configuration ───────────────────────────────────────────────
# 3 modes × 3 horizons = 9 strategy combinations

STRATEGIES = {
    "conservative": {"min_confidence": 65, "stop": -0.015, "target": 0.03},
    "balanced":     {"min_confidence": 55, "stop": -0.02,  "target": 0.04},
    "aggressive":   {"min_confidence": 45, "stop": -0.03,  "target": 0.05},
}
HORIZONS = {"short": 1, "swing": 5, "mid": 20}

# A bear-market long is never an "oversold" entry.  These are the existing
# geometric reversal structures whose confirmation stage has an explicit
# trigger and invalidation price.  Keep the universe deliberately small so a
# later result cannot quietly turn every bounce into a trade.
BEAR_REVERSAL_PATTERNS = {
    "DOUBLE_BOTTOM",
    "INVERSE_HEAD_AND_SHOULDERS",
    "FALLING_WEDGE_BREAKOUT",
    "RESISTANCE_FLIP_SUPPORT",
}
BEAR_REVERSAL_ENTRY_STAGE = "BUY_ZONE"
_BENCHMARK_SYMBOLS = {
    "KOSPI", "KOSDAQ", "KOSPI200", "USD_KRW", "USDKRW",
    "SPY", "QQQ", "DIA", "RSP", "IWM", "HYG", "LQD", "TLT",
    "XLY", "XLP", "VIX",
}

# These candidates are declared before inspecting the independent test period.
# They are intentionally chart-structure entries, not a disguised RSI dip-buy.
# Every candidate enters only after a BUY_ZONE confirmation and is tested with
# the same next-open, geometric-stop, 2R execution model.
REGIME_PATTERN_CANDIDATES = {
    "BULL": {
        "BULL_FLAG", "BULL_PENNANT", "ASCENDING_TRIANGLE", "CUP_AND_HANDLE",
        "FALLING_WEDGE_BREAKOUT", "RESISTANCE_FLIP_SUPPORT", "RISING_CHANNEL",
    },
    "BEAR": BEAR_REVERSAL_PATTERNS | {"V_REVERSAL"},
    "SIDE": {
        "DOUBLE_BOTTOM", "FALLING_WEDGE_BREAKOUT", "FAILED_BREAKDOWN", "V_REVERSAL",
        "RESISTANCE_FLIP_SUPPORT",
    },
}


def _indicator_stats_bucket() -> dict[str, Any]:
    return {
        "sampleCount": 0, "wins": 0, "losses": 0, "stops": 0, "targets": 0,
        "returns": [], "blocked_returns": [],
    }


def _strategy_bucket() -> dict[str, Any]:
    return {
        "sampleCount": 0, "wins": 0, "losses": 0, "stops": 0, "targets": 0,
        "returns": [], "byPattern": defaultdict(_indicator_stats_bucket),
    }


def _cs_bucket() -> dict[str, Any]:
    return {
        "sampleCount": 0, "wins": 0, "losses": 0, "stops": 0, "targets": 0,
        "returns": [],
        "confirmed_count": 0, "confirmed_wins": 0, "confirmed_returns": [],
        "unconfirmed_wins": 0, "unconfirmed_returns": [],
    }


def _geo_stats_bucket() -> dict[str, Any]:
    return {
        "sampleCount": 0, "wins": 0, "losses": 0, "long_wins": 0,
        "stops": 0, "targets": 0, "returns": [], "directional_returns": [],
        "directions": defaultdict(int),
    }


def _load_all_ohlcv(market: str) -> dict[str, list[dict]]:
    """Load all OHLCV CSV files for a market; returns {symbol: [row,...]}."""
    result: dict[str, list[dict]] = {}
    if not _OHLCV_DIR.exists():
        return result
    for path in _OHLCV_DIR.glob(f"{market}_*_daily.csv"):
        sym = path.stem.replace(f"{market}_", "").replace("_daily", "")
        rows = _read_ohlcv_csv(path)
        if rows:
            result[sym] = rows
    return result


def _read_ohlcv_csv(path: Path) -> list[dict]:
    import csv
    rows: list[dict] = []
    try:
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open(encoding=enc, newline="") as fh:
                    for r in csv.DictReader(fh):
                        rows.append(r)
                break
            except UnicodeDecodeError:
                continue
    except Exception:
        pass
    rows.sort(key=lambda r: str(r.get("date", "")))
    return rows


def _slice_before(rows: list[dict], cutoff_date: str) -> list[dict]:
    """Return rows strictly before cutoff_date — no future leakage."""
    return [r for r in rows if str(r.get("date", "")) < cutoff_date]


def _forward_return(rows: list[dict], from_date: str, days: int) -> float | None:
    """Calculate % return from from_date close, looking forward `days` rows."""
    future = [r for r in rows if str(r.get("date", "")) > from_date]
    if len(future) < days:
        return None
    # rows is oldest-first; walk backwards to find the most recent row at/before
    # from_date (the original forward iteration picked the OLDEST row in the
    # whole series instead, since its date is always <= from_date too).
    entry_row = next((r for r in reversed(rows) if str(r.get("date", "")) <= from_date), None)
    if not entry_row:
        return None
    entry_close = _f(entry_row.get("close"))
    exit_close  = _f(future[days - 1].get("close"))
    if not entry_close or not exit_close or entry_close <= 0:
        return None
    return (exit_close - entry_close) / entry_close


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _regime_for_index(rows: list[dict], cutoff_date: str) -> str:
    past = _slice_before(rows, cutoff_date)
    closes = [_f(r.get("close")) for r in past]
    closes = [c for c in closes if c is not None]
    if len(closes) < 25:
        return "SIDE"
    latest = closes[-1]
    ma20 = _ma(closes, 20)
    ma20_5ago = _ma(closes[:-5], 20) if len(closes) >= 25 else None
    if ma20 is None:
        return "SIDE"
    above_ma = latest > ma20
    ma_rising = ma20 > ma20_5ago if ma20_5ago is not None else True
    if above_ma and ma_rising:
        # Late-stage melt-up detection: MA20-based BULL persists right up to a
        # parabolic top. Index stretched ≥6% above its own MA20 while the
        # 60-day gain exceeds +30% = late-stage, crash-prone rally
        # (2026-02/03 −10.6%/−19.1% and 2026-05/06 +3.1%/−6.4% fwd-20d were
        # all flagged; early-stage rallies in 2026-04 were not).
        if len(closes) >= 61:
            disp   = latest / ma20
            gain60 = latest / closes[-61] - 1
            if disp >= 1.06 and gain60 >= 0.30:
                return "OVERHEATED"
        return "BULL"
    if not above_ma and not ma_rising:
        return "BEAR"
    return "SIDE"


def _market_regime_at_date(market: str, all_ohlcv: dict[str, list[dict]], cutoff_date: str) -> str:
    if market == "us":
        votes = [_regime_for_index(all_ohlcv.get(sym, []), cutoff_date) for sym in ("SPY", "QQQ", "DIA")]
        if votes.count("OVERHEATED") >= 2:
            return "OVERHEATED"
        # An OVERHEATED index is still a rising index for the BULL/BEAR vote
        if votes.count("BULL") + votes.count("OVERHEATED") >= 2:
            return "BULL"
        if votes.count("BEAR") >= 2:
            return "BEAR"
        return "SIDE"
    return _regime_for_index(all_ohlcv.get("KOSPI", []), cutoff_date)


_REGIME_CACHE: dict[tuple[str, str], str] = {}


def _index_mom60_at_date(market: str, all_ohlcv: dict[str, list[dict]], cutoff_date: str) -> float | None:
    """60-bar index momentum as of cutoff_date (KOSPI for KR, SPY for US)."""
    idx_sym = "SPY" if market == "us" else "KOSPI"
    hist = _slice_before(all_ohlcv.get(idx_sym, []), cutoff_date)
    closes = [c for r in hist if (c := _f(r.get("close"))) is not None]
    if len(closes) < 61 or closes[-61] <= 0:
        return None
    return (closes[-1] - closes[-61]) / closes[-61]


def current_index_momentum(market: str = "kr") -> float | None:
    """
    Latest 60-bar index momentum (KOSPI/SPY) for live relative-strength scoring.
    Pair with current_market_regime() when calling analyze() outside backtests.
    """
    market = str(market).lower()
    idx_sym = "SPY" if market == "us" else "KOSPI"
    path = _OHLCV_DIR / f"{market}_{idx_sym}_daily.csv"
    if not path.exists():
        return None
    rows = _read_ohlcv_csv(path)
    closes = [c for r in rows if (c := _f(r.get("close"))) is not None]
    if len(closes) < 61 or closes[-61] <= 0:
        return None
    return (closes[-1] - closes[-61]) / closes[-61]


def current_market_regime(market: str = "kr") -> str:
    """
    Index-level regime ("BULL"/"BEAR"/"SIDE"/"OVERHEATED") as of the latest
    available data. KR uses KOSPI; US uses a 2-of-3 vote across SPY/QQQ/DIA.
    Cached per calendar day — safe to call inside per-symbol loops.

    Live callers should pass this into analyze(..., market_regime=...) so the
    engine's regime-aware confidence adjustments apply outside of backtests.
    """
    market = str(market).lower()
    cache_key = (market, datetime.now().strftime("%Y-%m-%d"))
    if cache_key in _REGIME_CACHE:
        return _REGIME_CACHE[cache_key]

    index_syms = ("SPY", "QQQ", "DIA") if market == "us" else ("KOSPI",)
    ohlcv: dict[str, list[dict]] = {}
    for sym in index_syms:
        path = _OHLCV_DIR / f"{market}_{sym}_daily.csv"
        if path.exists():
            rows = _read_ohlcv_csv(path)
            if rows:
                ohlcv[sym] = rows
    regime = _market_regime_at_date(market, ohlcv, "9999-12-31") if ohlcv else "SIDE"
    _REGIME_CACHE.clear()   # keep only today's entries
    _REGIME_CACHE[cache_key] = regime
    return regime


def _date_range(from_str: str, to_str: str, step_days: int = 5) -> list[str]:
    """Generate evaluation dates between from_str and to_str."""
    try:
        start = datetime.strptime(from_str, "%Y-%m-%d")
        end   = datetime.strptime(to_str,   "%Y-%m-%d")
    except ValueError:
        return []
    dates: list[str] = []
    cur = start
    while cur <= end:
        # Skip weekends
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=step_days)
    return dates


# ── Core walk-forward loop ─────────────────────────────────────────────────

def run_walkforward(
    market: str = "kr",
    from_date: str | None = None,
    to_date: str | None = None,
    horizon_days: int = 5,
    min_score: float = 50.0,
    params: dict | None = None,
) -> dict[str, Any]:
    """
    Run pattern walk-forward validation.

    Returns a summary dict with per-pattern stats, blockedOutcomeStats,
    leakageCheck, and patternCalibrationSuggestions.
    """
    p = params or load_params()

    # Default date range: last 6 months
    if not to_date:
        to_date   = datetime.now().strftime("%Y-%m-%d")
    if not from_date:
        from_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    all_ohlcv = _load_all_ohlcv(market)
    if not all_ohlcv:
        return {
            "status":  "NO_DATA",
            "market":  market,
            "message": f"No OHLCV data found for market={market}",
        }

    eval_dates = _date_range(from_date, to_date, step_days=5)

    # per-pattern accumulators
    pattern_stats: dict[str, dict] = defaultdict(_indicator_stats_bucket)
    regime_pattern_stats: dict[str, dict] = defaultdict(_indicator_stats_bucket)
    # geometric (classic chart) pattern accumulators, keyed by "PATTERN:STAGE"
    geo_pattern_stats: dict[str, dict] = defaultdict(_geo_stats_bucket)
    regime_geo_pattern_stats: dict[str, dict] = defaultdict(_geo_stats_bucket)
    regime_counts: dict[str, int] = defaultdict(int)
    blocked_stats   = {"count": 0, "returns": [], "would_have_gained": 0}
    leakage_ok      = True

    for date_str in eval_dates:
        regime = _market_regime_at_date(market, all_ohlcv, date_str)
        idx_mom60 = _index_mom60_at_date(market, all_ohlcv, date_str)
        regime_counts[regime] += 1
        for sym, all_rows in all_ohlcv.items():
            # Strict cutoff — no future data
            hist_rows = _slice_before(all_rows, date_str)
            if len(hist_rows) < p.get("minOhlcvRows", 20):
                continue

            result = analyze(sym, market, hist_rows, p, market_regime=regime, index_mom60=idx_mom60)

            # Leakage check: the last row used must be < date_str
            last_used_date = str(hist_rows[-1].get("date", "")) if hist_rows else ""
            if last_used_date >= date_str:
                leakage_ok = False

            primary    = result.get("primaryPattern", "unknown")
            is_blocked = result.get("isBlocked", False)
            confidence = result.get("confidence", 0)

            fwd = _forward_return(all_rows, date_str, horizon_days)
            if fwd is None:
                continue

            # Assume 2% stop, 4% target (ATR-derived in future self-correction)
            stop_hit   = fwd < -0.02
            target_hit = fwd > 0.04
            win        = fwd > 0

            # Geometric pattern tracking is independent of the indicator-engine
            # confidence gate below — it has its own stage-based gating.
            geo_pattern = result.get("geometricPattern")
            geo_stage   = result.get("geometricPatternStage")
            if geo_pattern and geo_stage:
                geo_direction = str(result.get("geometricPatternDirection") or "NEUTRAL").upper()
                if geo_direction == "BEARISH":
                    geo_win = fwd < 0
                    geo_stop_hit = fwd > 0.02
                    geo_target_hit = fwd < -0.04
                    directional_return = -fwd
                elif geo_direction == "BULLISH":
                    geo_win = fwd > 0
                    geo_stop_hit = fwd < -0.02
                    geo_target_hit = fwd > 0.04
                    directional_return = fwd
                else:
                    geo_win = abs(fwd) <= 0.02
                    geo_stop_hit = abs(fwd) > 0.04
                    geo_target_hit = abs(fwd) <= 0.02
                    directional_return = -abs(fwd)
                gs = geo_pattern_stats[f"{geo_pattern}:{geo_stage}"]
                rgs = regime_geo_pattern_stats[f"{regime}|{geo_pattern}:{geo_stage}"]
                for bucket in (gs, rgs):
                    bucket["sampleCount"] += 1
                    bucket["returns"].append(fwd)
                    bucket["directional_returns"].append(directional_return)
                    bucket["directions"][geo_direction] += 1
                    if geo_win:        bucket["wins"]      += 1
                    else:              bucket["losses"]    += 1
                    if win:            bucket["long_wins"] += 1
                    if geo_stop_hit:   bucket["stops"]     += 1
                    if geo_target_hit: bucket["targets"]   += 1

            # Only validate indicator-driven pattern if confidence passes threshold
            if confidence < min_score:
                continue

            ps = pattern_stats[primary]
            rps = regime_pattern_stats[f"{regime}|{primary}"]
            for bucket in (ps, rps):
                bucket["sampleCount"] += 1
                bucket["returns"].append(fwd)
                if win:   bucket["wins"] += 1
                else:     bucket["losses"] += 1
                if stop_hit:   bucket["stops"]   += 1
                if target_hit: bucket["targets"] += 1

            if is_blocked:
                blocked_stats["count"] += 1
                blocked_stats["returns"].append(fwd)
                if fwd > 0.02:
                    blocked_stats["would_have_gained"] += 1

    # ── Summarise ──────────────────────────────────────────────────────────
    summary: dict[str, Any] = {}
    for pat, ps in pattern_stats.items():
        n = ps["sampleCount"]
        if n == 0:
            continue
        rets   = ps["returns"]
        avg_r  = sum(rets) / len(rets)
        win_r  = ps["wins"] / n
        stop_r = ps["stops"] / n
        tgt_r  = ps["targets"] / n
        summary[pat] = {
            "sampleCount":    n,
            "winRate":        round(win_r, 3),
            "avgReturn":      round(avg_r, 4),
            "medianReturn":   round(_median(rets), 4),
            "stopRate":       round(stop_r, 3),
            "targetHitRate":  round(tgt_r, 3),
        }

    geo_summary: dict[str, Any] = {}
    for key, gs in geo_pattern_stats.items():
        n = gs["sampleCount"]
        if n == 0:
            continue
        rets  = gs["returns"]
        directional_rets = gs["directional_returns"]
        direction = max(gs["directions"], key=gs["directions"].get) if gs["directions"] else "UNKNOWN"
        geo_summary[key] = {
            "sampleCount":      n,
            "expectedDirection": direction,
            "winRate":          round(gs["wins"] / n, 3),
            "directionalWinRate": round(gs["wins"] / n, 3),
            "longWinRate":      round(gs["long_wins"] / n, 3),
            "avgReturn":        round(sum(directional_rets) / len(directional_rets), 4),
            "avgForwardReturn": round(sum(rets) / len(rets), 4),
            "medianReturn":     round(_median(directional_rets), 4),
            "medianForwardReturn": round(_median(rets), 4),
            "stopRate":         round(gs["stops"] / n, 3),
            "targetHitRate":    round(gs["targets"] / n, 3),
        }

    regime_summary: dict[str, Any] = {}
    for key, ps in regime_pattern_stats.items():
        n = ps["sampleCount"]
        if n == 0:
            continue
        regime, _, pat = key.partition("|")
        rets = ps["returns"]
        regime_summary.setdefault(regime, {})[pat] = {
            "sampleCount":    n,
            "winRate":        round(ps["wins"] / n, 3),
            "avgReturn":      round(sum(rets) / len(rets), 4),
            "medianReturn":   round(_median(rets), 4),
            "stopRate":       round(ps["stops"] / n, 3),
            "targetHitRate":  round(ps["targets"] / n, 3),
        }

    geo_regime_summary: dict[str, Any] = {}
    for key, gs in regime_geo_pattern_stats.items():
        n = gs["sampleCount"]
        if n == 0:
            continue
        regime, _, pattern_key = key.partition("|")
        rets = gs["returns"]
        directional_rets = gs["directional_returns"]
        direction = max(gs["directions"], key=gs["directions"].get) if gs["directions"] else "UNKNOWN"
        geo_regime_summary.setdefault(regime, {})[pattern_key] = {
            "sampleCount":      n,
            "expectedDirection": direction,
            "winRate":          round(gs["wins"] / n, 3),
            "directionalWinRate": round(gs["wins"] / n, 3),
            "longWinRate":      round(gs["long_wins"] / n, 3),
            "avgReturn":        round(sum(directional_rets) / len(directional_rets), 4),
            "avgForwardReturn": round(sum(rets) / len(rets), 4),
            "medianReturn":     round(_median(directional_rets), 4),
            "medianForwardReturn": round(_median(rets), 4),
            "stopRate":         round(gs["stops"] / n, 3),
            "targetHitRate":    round(gs["targets"] / n, 3),
        }

    # ── Blocked outcome stats ──────────────────────────────────────────────
    bc = blocked_stats["count"]
    b_rets = blocked_stats["returns"]
    blocked_outcome = {
        "totalBlocked":         bc,
        "avgReturnIfAllowed":   round(sum(b_rets) / len(b_rets), 4) if b_rets else 0.0,
        "wouldHaveGainedCount": blocked_stats["would_have_gained"],
        "interpretation":       (
            "차단 로직이 손실을 효과적으로 방지함"
            if b_rets and sum(b_rets) / len(b_rets) < -0.005
            else "차단이 다소 보수적일 수 있음 — 기준 완화 검토"
        ) if b_rets else "데이터 부족",
    }

    # ── Calibration suggestions ────────────────────────────────────────────
    suggestions = _calibration_suggestions(summary, p)
    suggestions += _geometric_calibration_suggestions(geo_summary)

    result_doc = {
        "status":       "OK",
        "market":       market,
        "fromDate":     from_date,
        "toDate":       to_date,
        "horizonDays":  horizon_days,
        "evalDates":    len(eval_dates),
        "summary":      summary,
        "geometricPatternSummary":        geo_summary,
        "regimeCounts":                   dict(regime_counts),
        "regimeSummary":                  regime_summary,
        "geometricRegimeSummary":         geo_regime_summary,
        "blockedOutcomeStats":            blocked_outcome,
        "leakageCheck":                   {"status": "PASS" if leakage_ok else "FAIL"},
        "patternCalibrationSuggestions":  suggestions,
    }

    # Persist to reports/
    try:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _REPORTS_DIR / f"pattern_walkforward_{market}.json"
        out_path.write_text(json.dumps(result_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return result_doc


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# ── Bear reversal execution test ────────────────────────────────────────────

def _reversal_bucket() -> dict[str, Any]:
    return {
        "sampleCount": 0, "wins": 0, "stops": 0, "targets": 0,
        "netReturns": [], "grossReturns": [], "holdDays": [],
    }


def _bar_value(row: dict, key: str) -> float | None:
    return _f(row.get(key))


def _simulate_long_reversal(
    rows: list[dict],
    entry_index: int,
    stop: float,
    reward_r: float,
    max_holding_days: int,
    round_trip_cost: float,
) -> dict[str, Any] | None:
    """Simulate an end-of-day-confirmed long from the next session's open.

    OHLC data cannot establish whether a stop and target were hit first inside
    the same daily candle.  The deliberately conservative convention is that
    the stop was hit first.  A gap through the stop exits at the opening price,
    rather than pretending a stop-limit received its requested fill.
    """
    if entry_index >= len(rows):
        return None
    entry = _bar_value(rows[entry_index], "open")
    if entry is None or entry <= stop or stop <= 0:
        return None
    target = entry + reward_r * (entry - stop)
    last_index = min(len(rows) - 1, entry_index + max_holding_days - 1)
    exit_price: float | None = None
    exit_reason = "TIME_STOP"
    exit_index = last_index

    for idx in range(entry_index, last_index + 1):
        bar = rows[idx]
        opening = _bar_value(bar, "open")
        high = _bar_value(bar, "high")
        low = _bar_value(bar, "low")
        if opening is None or high is None or low is None:
            continue
        if opening <= stop:
            exit_price, exit_reason, exit_index = opening, "STOP_GAP", idx
            break
        if opening >= target:
            exit_price, exit_reason, exit_index = opening, "TARGET_GAP", idx
            break
        # Intraday ordering is unknowable in a daily bar: protect against
        # optimistic backtests by booking the stop whenever both were touched.
        if low <= stop:
            exit_price, exit_reason, exit_index = stop, "STOP", idx
            break
        if high >= target:
            exit_price, exit_reason, exit_index = target, "TARGET", idx
            break

    if exit_price is None:
        exit_price = _bar_value(rows[last_index], "close")
        if exit_price is None:
            return None

    gross = exit_price / entry - 1.0
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "grossReturn": gross,
        "netReturn": gross - round_trip_cost,
        "exitReason": exit_reason,
        "holdDays": exit_index - entry_index + 1,
        "exitIndex": exit_index,
    }


def _summarise_reversal_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    n = int(bucket["sampleCount"])
    net_returns = bucket["netReturns"]
    gross_returns = bucket["grossReturns"]
    if not n or not net_returns:
        return {
            "sampleCount": 0, "winRate": 0.0, "avgNetReturn": 0.0,
            "medianNetReturn": 0.0, "profitFactor": 0.0,
            "stopRate": 0.0, "targetRate": 0.0, "avgHoldDays": 0.0,
        }
    gains = sum(value for value in net_returns if value > 0)
    losses = -sum(value for value in net_returns if value < 0)
    profit_factor = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)
    return {
        "sampleCount": n,
        "winRate": round(bucket["wins"] / n, 4),
        "avgNetReturn": round(sum(net_returns) / n, 6),
        "avgGrossReturn": round(sum(gross_returns) / n, 6),
        "medianNetReturn": round(_median(net_returns), 6),
        "profitFactor": round(profit_factor, 3),
        "stopRate": round(bucket["stops"] / n, 4),
        "targetRate": round(bucket["targets"] / n, 4),
        "avgHoldDays": round(sum(bucket["holdDays"]) / n, 2),
    }


def _bear_reversal_qualification(train: dict[str, Any], oos: dict[str, Any]) -> tuple[bool, list[str]]:
    """Pre-declared promotion rule; never promote a single lucky period."""
    reasons: list[str] = []
    for label, stats in (("TRAIN", train), ("OUT_OF_SAMPLE", oos)):
        if int(stats.get("sampleCount") or 0) < 20:
            reasons.append(f"{label}_LOW_SAMPLE")
        if float(stats.get("avgNetReturn") or 0.0) <= 0:
            reasons.append(f"{label}_NON_POSITIVE_EXPECTANCY")
        if float(stats.get("profitFactor") or 0.0) <= 1.0:
            reasons.append(f"{label}_PROFIT_FACTOR_NOT_ABOVE_1")
    if float(oos.get("winRate") or 0.0) < 0.50:
        reasons.append("OUT_OF_SAMPLE_WIN_RATE_BELOW_50")
    return not reasons, reasons


def run_bear_reversal_walkforward(
    market: str = "kr",
    from_date: str | None = None,
    to_date: str | None = None,
    split_date: str = "2022-01-01",
    reward_r: float = 2.0,
    max_holding_days: int = 20,
    round_trip_cost_bps: float = 20.0,
) -> dict[str, Any]:
    """Test only confirmed bullish reversal structures while the index is BEAR.

    The signal is known at the close of date D.  Entry is the next available
    daily open, with the detector's own invalidation as stop and a fixed 2R
    target.  It intentionally does not test generic RSI/oversold bounces.
    """
    market = str(market).lower()
    all_ohlcv = _load_all_ohlcv(market)
    if not all_ohlcv:
        return {"status": "NO_DATA", "market": market}

    start = from_date or "2011-01-01"
    end = to_date or datetime.now().strftime("%Y-%m-%d")
    cost = max(0.0, float(round_trip_cost_bps)) / 10_000.0
    by_pattern: dict[str, dict[str, dict[str, Any]]] = {
        pattern: {"all": _reversal_bucket(), "train": _reversal_bucket(), "outOfSample": _reversal_bucket()}
        for pattern in sorted(BEAR_REVERSAL_PATTERNS)
    }
    regime_cache: dict[str, str] = {}
    rejected = defaultdict(int)
    trade_examples: list[dict[str, Any]] = []
    leakage_ok = True

    def regime_for(date_str: str) -> str:
        if date_str not in regime_cache:
            regime_cache[date_str] = _market_regime_at_date(market, all_ohlcv, date_str)
        return regime_cache[date_str]

    for symbol, rows in all_ohlcv.items():
        if symbol.upper() in _BENCHMARK_SYMBOLS or len(rows) < 65:
            continue
        # A position must be closed before the same symbol can produce another
        # signal.  That avoids counting one persistent breakout as many trades.
        next_eligible_index = 0
        previous_actionable: tuple[str, str] | None = None
        for signal_index in range(60, len(rows) - 1):
            signal_date = str(rows[signal_index].get("date", ""))
            if signal_date < start or signal_date > end:
                continue
            if signal_index < next_eligible_index:
                continue
            if regime_for(signal_date) != "BEAR":
                previous_actionable = None
                continue

            # Including D is valid: the signal is evaluated after D's close;
            # the simulated fill uses D+1's open.  No D+1 information reaches
            # the detector.
            # Both the geometric detector (120 bars) and indicators (60 bars)
            # are local-window calculations.  Keeping a 160-bar slice avoids
            # repeatedly copying an entire 10+ year series without changing
            # any information available at the decision point.
            history = rows[max(0, signal_index - 159):signal_index + 1]
            indicators = ind_mod.compute_all(history)
            atr20 = _f(indicators.get("atr20"))
            if atr20 is None or atr20 <= 0:
                continue
            geo = gp_mod.detect_all(history, atr20, _f(indicators.get("volumeRatio20")), market=market)
            if not geo:
                previous_actionable = None
                continue
            pattern = str(geo.get("pattern") or "")
            stage = str(geo.get("stage") or "")
            action_key = (pattern, stage)
            if (
                pattern not in BEAR_REVERSAL_PATTERNS
                or str(geo.get("direction") or "").upper() != "BULLISH"
                or stage != BEAR_REVERSAL_ENTRY_STAGE
            ):
                previous_actionable = None
                continue
            if previous_actionable == action_key:
                continue
            previous_actionable = action_key

            trigger = _f(geo.get("trigger"))
            stop = _f(geo.get("invalidation"))
            next_open = _bar_value(rows[signal_index + 1], "open")
            if trigger is None or stop is None or next_open is None or next_open <= stop:
                rejected["INVALID_OR_GAPPED_THROUGH_STOP"] += 1
                continue
            # The signal itself is limited to 1.2 ATR above its breakout.  Do
            # not convert a valid closing signal into a chase after an opening
            # gap: skip rather than silently worsening the entry.
            if next_open > trigger + 1.2 * atr20:
                rejected["CHASE_GAP"] += 1
                continue
            trade = _simulate_long_reversal(
                rows, signal_index + 1, stop, reward_r, max_holding_days, cost,
            )
            if not trade:
                rejected["UNSIMULATABLE"] += 1
                continue
            if str(rows[signal_index].get("date", "")) >= str(rows[signal_index + 1].get("date", "")):
                leakage_ok = False

            split_key = "train" if signal_date < split_date else "outOfSample"
            for bucket in (by_pattern[pattern]["all"], by_pattern[pattern][split_key]):
                bucket["sampleCount"] += 1
                bucket["netReturns"].append(trade["netReturn"])
                bucket["grossReturns"].append(trade["grossReturn"])
                bucket["holdDays"].append(trade["holdDays"])
                if trade["netReturn"] > 0:
                    bucket["wins"] += 1
                if str(trade["exitReason"]).startswith("STOP"):
                    bucket["stops"] += 1
                if str(trade["exitReason"]).startswith("TARGET"):
                    bucket["targets"] += 1
            next_eligible_index = signal_index + int(trade["holdDays"])
            if len(trade_examples) < 50:
                trade_examples.append({
                    "symbol": symbol, "signalDate": signal_date,
                    "entryDate": str(rows[signal_index + 1].get("date", "")),
                    "pattern": pattern, "entry": round(trade["entry"], 4),
                    "stop": round(trade["stop"], 4), "target": round(trade["target"], 4),
                    "exitReason": trade["exitReason"], "netReturn": round(trade["netReturn"], 6),
                })

    summary: dict[str, Any] = {}
    qualified: list[str] = []
    for pattern, buckets in by_pattern.items():
        all_stats = _summarise_reversal_bucket(buckets["all"])
        train_stats = _summarise_reversal_bucket(buckets["train"])
        oos_stats = _summarise_reversal_bucket(buckets["outOfSample"])
        is_qualified, reasons = _bear_reversal_qualification(train_stats, oos_stats)
        summary[pattern] = {
            "all": all_stats, "train": train_stats, "outOfSample": oos_stats,
            "qualified": is_qualified, "rejectionReasons": reasons,
        }
        if is_qualified:
            qualified.append(pattern)

    result_doc = {
        "status": "OK", "market": market, "fromDate": start, "toDate": end,
        "splitDate": split_date, "qualifiedPatterns": qualified,
        "entryStage": BEAR_REVERSAL_ENTRY_STAGE,
        "assumptions": {
            "signal": "D close confirmation; D+1 open entry only",
            "stop": "detector geometric invalidation",
            "targetR": reward_r, "maxHoldingDays": max_holding_days,
            "roundTripCostBps": round_trip_cost_bps,
            "intradayCollision": "stop first (conservative)",
            "entryGapRule": "skip if D+1 open is above trigger + 1.2 ATR",
        },
        "patternSummary": summary, "rejectedSignals": dict(rejected),
        "leakageCheck": {"status": "PASS" if leakage_ok else "FAIL"},
        "exampleTrades": trade_examples,
    }
    try:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (_REPORTS_DIR / f"bear_reversal_walkforward_{market}.json").write_text(
            json.dumps(result_doc, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception:
        pass
    return result_doc


def _regime_execution_qualification(
    train: dict[str, Any],
    train_early: dict[str, Any],
    train_late: dict[str, Any],
    out_of_sample: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Promotion rule fixed before the independent-period results are read."""
    approved, reasons = _bear_reversal_qualification(train, out_of_sample)
    # A fold is only used as a veto when it is large enough to be informative.
    # This catches a strategy that was profitable in aggregate but relied on
    # one isolated market episode inside the training interval.
    for label, stats in (("TRAIN_EARLY", train_early), ("TRAIN_LATE", train_late)):
        if int(stats.get("sampleCount") or 0) >= 12:
            if float(stats.get("avgNetReturn") or 0.0) <= 0:
                reasons.append(f"{label}_NON_POSITIVE_EXPECTANCY")
            if float(stats.get("profitFactor") or 0.0) <= 1.0:
                reasons.append(f"{label}_PROFIT_FACTOR_NOT_ABOVE_1")
    return approved and not reasons, reasons


def run_regime_pattern_execution_walkforward(
    market: str = "kr",
    from_date: str | None = None,
    to_date: str | None = None,
    split_date: str = "2022-01-01",
    train_fold_date: str = "2017-01-01",
    reward_r: float = 2.0,
    max_holding_days: int = 20,
    round_trip_cost_bps: float = 20.0,
) -> dict[str, Any]:
    """Execution-aware chart-pattern research for BULL, BEAR, and SIDE.

    This is the common proof engine for all three regimes.  It evaluates a
    signal only after that day's close, enters at the next session's open, and
    never lets the independent period choose a condition.  Two predeclared
    variants are tested for every candidate: BUY_ZONE and BUY_ZONE with a
    confirming candle.  A result is promotable only if it passes the fixed
    training and independent-period rules below.
    """
    market = str(market).lower()
    all_ohlcv = _load_all_ohlcv(market)
    if not all_ohlcv:
        return {"status": "NO_DATA", "market": market}
    start = from_date or "2011-01-01"
    end = to_date or datetime.now().strftime("%Y-%m-%d")
    cost = max(0.0, float(round_trip_cost_bps)) / 10_000.0

    buckets: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
        regime: {
            f"{pattern}:BUY_ZONE": {
                "all": _reversal_bucket(), "train": _reversal_bucket(),
                "trainEarly": _reversal_bucket(), "trainLate": _reversal_bucket(),
                "outOfSample": _reversal_bucket(),
            }
            for pattern in sorted(patterns)
            for _variant in (0,)
        }
        for regime, patterns in REGIME_PATTERN_CANDIDATES.items()
    }
    # Confirmed candle is a separate, predeclared condition rather than a
    # post-hoc boost.  It gets its own independent evidence.
    for regime, patterns in REGIME_PATTERN_CANDIDATES.items():
        for pattern in patterns:
            buckets[regime][f"{pattern}:BUY_ZONE:CONFIRMED_CANDLE"] = {
                "all": _reversal_bucket(), "train": _reversal_bucket(),
                "trainEarly": _reversal_bucket(), "trainLate": _reversal_bucket(),
                "outOfSample": _reversal_bucket(),
            }

    regime_cache: dict[str, str] = {}
    skipped = defaultdict(int)
    leakage_ok = True

    def regime_for(date_str: str) -> str:
        if date_str not in regime_cache:
            regime_cache[date_str] = _market_regime_at_date(market, all_ohlcv, date_str)
        return regime_cache[date_str]

    def record(bucket: dict[str, Any], trade: dict[str, Any]) -> None:
        bucket["sampleCount"] += 1
        bucket["netReturns"].append(trade["netReturn"])
        bucket["grossReturns"].append(trade["grossReturn"])
        bucket["holdDays"].append(trade["holdDays"])
        if trade["netReturn"] > 0:
            bucket["wins"] += 1
        if str(trade["exitReason"]).startswith("STOP"):
            bucket["stops"] += 1
        if str(trade["exitReason"]).startswith("TARGET"):
            bucket["targets"] += 1

    for symbol, rows in all_ohlcv.items():
        if symbol.upper() in _BENCHMARK_SYMBOLS or len(rows) < 65:
            continue
        next_eligible: dict[str, int] = defaultdict(int)
        active_pattern: dict[str, str | None] = defaultdict(lambda: None)
        for signal_index in range(60, len(rows) - 1):
            signal_date = str(rows[signal_index].get("date", ""))
            if signal_date < start or signal_date > end:
                continue
            regime = regime_for(signal_date)
            candidates = REGIME_PATTERN_CANDIDATES.get(regime)
            if not candidates:
                continue
            # The detector/indicators only consume recent history; see the
            # equivalent execution simulator above for why this is safe.
            history = rows[max(0, signal_index - 159):signal_index + 1]
            indicators = ind_mod.compute_all(history)
            atr20 = _f(indicators.get("atr20"))
            if atr20 is None or atr20 <= 0:
                continue
            geo = gp_mod.detect_all(history, atr20, _f(indicators.get("volumeRatio20")), market=market)
            if not geo:
                for key in active_pattern:
                    active_pattern[key] = None
                continue
            pattern = str(geo.get("pattern") or "")
            stage = str(geo.get("stage") or "")
            bullish = str(geo.get("direction") or "").upper() == "BULLISH"
            if pattern not in candidates or stage != BEAR_REVERSAL_ENTRY_STAGE or not bullish:
                for key in active_pattern:
                    active_pattern[key] = None
                continue

            variant_keys = [f"{pattern}:BUY_ZONE"]
            if geo.get("confirmed"):
                variant_keys.append(f"{pattern}:BUY_ZONE:CONFIRMED_CANDLE")
            trigger = _f(geo.get("trigger"))
            stop = _f(geo.get("invalidation"))
            next_open = _bar_value(rows[signal_index + 1], "open")
            if trigger is None or stop is None or next_open is None or next_open <= stop:
                skipped["INVALID_OR_GAPPED_THROUGH_STOP"] += 1
                continue
            if next_open > trigger + 1.2 * atr20:
                skipped["CHASE_GAP"] += 1
                continue
            if str(rows[signal_index].get("date", "")) >= str(rows[signal_index + 1].get("date", "")):
                leakage_ok = False

            for key in variant_keys:
                # One sustained pattern is one opportunity.  A transition from
                # unconfirmed to confirmed is deliberately a new opportunity
                # only for the confirmed-candle variant.
                if active_pattern[key] == pattern or signal_index < next_eligible[key]:
                    continue
                trade = _simulate_long_reversal(
                    rows, signal_index + 1, stop, reward_r, max_holding_days, cost,
                )
                if not trade:
                    skipped["UNSIMULATABLE"] += 1
                    continue
                active_pattern[key] = pattern
                next_eligible[key] = signal_index + int(trade["holdDays"])
                period_keys = ["all"]
                if signal_date < split_date:
                    period_keys.append("train")
                    period_keys.append("trainEarly" if signal_date < train_fold_date else "trainLate")
                else:
                    period_keys.append("outOfSample")
                for period_key in period_keys:
                    record(buckets[regime][key][period_key], trade)

    summaries: dict[str, Any] = {}
    qualified_by_regime: dict[str, list[str]] = {regime: [] for regime in REGIME_PATTERN_CANDIDATES}
    for regime, candidates in buckets.items():
        summaries[regime] = {}
        for key, raw in candidates.items():
            stats = {label: _summarise_reversal_bucket(bucket) for label, bucket in raw.items()}
            qualified, reasons = _regime_execution_qualification(
                stats["train"], stats["trainEarly"], stats["trainLate"], stats["outOfSample"],
            )
            summaries[regime][key] = {**stats, "qualified": qualified, "rejectionReasons": reasons}
            if qualified:
                qualified_by_regime[regime].append(key)

    result_doc = {
        "status": "OK", "market": market, "fromDate": start, "toDate": end,
        "splitDate": split_date, "trainFoldDate": train_fold_date,
        "entryStage": BEAR_REVERSAL_ENTRY_STAGE,
        "qualifiedByRegime": qualified_by_regime,
        "assumptions": {
            "signal": "D close confirmation; D+1 open entry only",
            "stop": "detector geometric invalidation", "targetR": reward_r,
            "maxHoldingDays": max_holding_days, "roundTripCostBps": round_trip_cost_bps,
            "intradayCollision": "stop first (conservative)",
            "entryGapRule": "skip if D+1 open is above trigger + 1.2 ATR",
            "promotion": "positive train/OOS expectancy and PF>1; OOS win >=50%; stable training folds when n>=12",
        },
        "regimePatternSummary": summaries, "skippedSignals": dict(skipped),
        "leakageCheck": {"status": "PASS" if leakage_ok else "FAIL"},
    }
    try:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (_REPORTS_DIR / f"regime_pattern_execution_{market}.json").write_text(
            json.dumps(result_doc, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception:
        pass
    return result_doc


def _calibration_suggestions(summary: dict, params: dict) -> list[dict]:
    """Generate human-readable calibration suggestions from walk-forward results."""
    suggestions: list[dict] = []
    pr = params.get("pullbackRisk", {})

    for pat, stats in summary.items():
        n      = stats["sampleCount"]
        if n < 10:
            suggestions.append({
                "pattern":    pat,
                "action":     "OBSERVE_ONLY",
                "reason":     f"표본 수 부족 ({n}개). 최소 10개 이상 쌓인 후 보정.",
            })
            continue

        win_r   = stats["winRate"]
        stop_r  = stats["stopRate"]
        avg_r   = stats["avgReturn"]

        if "pullback" in pat and stop_r > 0.35:
            suggestions.append({
                "pattern":    pat,
                "param":      "normalMaxDownAtr",
                "current":    pr.get("normalMaxDownAtr"),
                "suggestion": round(pr.get("normalMaxDownAtr", 1.2) - 0.1, 2),
                "action":     "TIGHTEN",
                "reason":     f"손절률 {stop_r:.0%} 초과 — 진입 허용 기준 강화 권장",
            })
        elif "pullback" in pat and stop_r < 0.10 and win_r < 0.45:
            suggestions.append({
                "pattern":    pat,
                "param":      "riskDownAtr",
                "current":    pr.get("riskDownAtr"),
                "suggestion": round(pr.get("riskDownAtr", 1.5) + 0.1, 2),
                "action":     "RELAX",
                "reason":     f"차단 후 많은 종목이 반등 ({win_r:.0%} 승률) — 기준 완화 검토",
            })

        if "breakout" in pat and win_r > 0.60:
            suggestions.append({
                "pattern":    pat,
                "param":      "confidence",
                "action":     "STRENGTHEN",
                "reason":     f"돌파 패턴 승률 {win_r:.0%} — 신뢰도 가중치 상향 권장",
            })

    return suggestions


def run_combined_walkforward(
    market: str = "kr",
    from_date: str | None = None,
    to_date: str | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    """
    Extended walk-forward validation covering all pattern types across 9 strategies.

    Tracks:
    - 9 strategy combinations (conservative/balanced/aggressive × short/swing/mid)
    - Candlestick pattern accuracy with confirmed vs unconfirmed split
    - Geometric pattern confirmed vs unconfirmed accuracy lift
    - Combo accuracy: both geo+cs confirmed together vs each alone
    - Market regime breakdown for all of the above

    Saves to reports/pattern_walkforward_combined_{market}.json
    """
    p = params or load_params()

    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d")
    if not from_date:
        from_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    all_ohlcv = _load_all_ohlcv(market)
    if not all_ohlcv:
        return {"status": "NO_DATA", "market": market,
                "message": f"No OHLCV data for market={market}"}

    eval_dates = _date_range(from_date, to_date, step_days=5)

    # Accumulators
    strategy_stats: dict[str, dict] = defaultdict(_strategy_bucket)
    cs_stats: dict[str, dict]       = defaultdict(_cs_bucket)
    confirmed_lift: dict[str, dict] = {
        "geo_confirmed":   _indicator_stats_bucket(),
        "geo_unconfirmed": _indicator_stats_bucket(),
        "cs_confirmed":    _indicator_stats_bucket(),
        "cs_unconfirmed":  _indicator_stats_bucket(),
        "both_confirmed":  _indicator_stats_bucket(),
        "neither":         _indicator_stats_bucket(),
    }
    # regime-keyed strategy stats: "{regime}|{mode}|{horizon}"
    regime_strategy_stats: dict[str, dict] = defaultdict(_strategy_bucket)
    regime_counts: dict[str, int]           = defaultdict(int)
    # geo family × confirmed → directional-win buckets ("{family}|confirmed")
    geo_family_lift: dict[str, dict] = defaultdict(_indicator_stats_bucket)
    leakage_ok = True

    for date_str in eval_dates:
        regime = _market_regime_at_date(market, all_ohlcv, date_str)
        idx_mom60 = _index_mom60_at_date(market, all_ohlcv, date_str)
        regime_counts[regime] += 1

        for sym, all_rows in all_ohlcv.items():
            hist_rows = _slice_before(all_rows, date_str)
            if len(hist_rows) < p.get("minOhlcvRows", 20):
                continue

            result = analyze(sym, market, hist_rows, p, market_regime=regime, index_mom60=idx_mom60)

            last_used = str(hist_rows[-1].get("date", "")) if hist_rows else ""
            if last_used >= date_str:
                leakage_ok = False

            primary     = result.get("primaryPattern", "unknown")
            confidence  = result.get("confidence", 0)
            is_blocked  = result.get("isBlocked", False)
            geo_pattern = result.get("geometricPattern")
            geo_conf    = result.get("geometricPatternConfirmed", False)
            cs_pattern  = result.get("candlestickPattern")
            cs_conf     = result.get("candlestickPatternConfirmed", False)
            geo_dir     = str(result.get("geometricPatternDirection") or "BULLISH").upper()
            cs_dir      = str(result.get("candlestickPatternDirection") or "BULLISH").upper()

            # Compute forward returns for all 3 horizons at once
            fwd_by_h: dict[str, float | None] = {
                h: _forward_return(all_rows, date_str, days)
                for h, days in HORIZONS.items()
            }
            fwd5 = fwd_by_h.get("swing")  # canonical for pattern-level tracking

            # ── 9-strategy tracking ───────────────────────────────────
            for mode, mode_cfg in STRATEGIES.items():
                # Blocked signals pass only for aggressive mode
                if is_blocked and mode != "aggressive":
                    continue
                if confidence < mode_cfg["min_confidence"]:
                    continue
                stop = mode_cfg["stop"]
                tgt  = mode_cfg["target"]
                for h_name, fwd in fwd_by_h.items():
                    if fwd is None:
                        continue
                    win = fwd > 0
                    for sb in (strategy_stats[f"{mode}|{h_name}"],
                                regime_strategy_stats[f"{regime}|{mode}|{h_name}"]):
                        sb["sampleCount"] += 1
                        sb["returns"].append(fwd)
                        if win:       sb["wins"]    += 1
                        else:         sb["losses"]  += 1
                        if fwd < stop: sb["stops"]   += 1
                        if fwd > tgt:  sb["targets"] += 1
                    # Per-pattern within strategy (global only, saves memory)
                    pb = strategy_stats[f"{mode}|{h_name}"]["byPattern"][primary]
                    pb["sampleCount"] += 1
                    pb["returns"].append(fwd)
                    if win: pb["wins"]   += 1
                    else:   pb["losses"] += 1

            if fwd5 is None:
                continue  # need fwd5 for candlestick + lift tracking

            win5    = fwd5 > 0
            stop5   = fwd5 < -0.02
            target5 = fwd5 > 0.04
            # Direction-adjusted wins (defined here, used in both cs and lift sections)
            geo_win5  = (fwd5 < 0) if geo_dir == "BEARISH" else (fwd5 > 0)
            cs_win5   = (fwd5 < 0) if cs_dir  == "BEARISH" else (fwd5 > 0)

            # ── Candlestick pattern accuracy (direction-adjusted) ─────
            if cs_pattern:
                csb = cs_stats[cs_pattern]
                csb["sampleCount"] += 1
                csb["returns"].append(fwd5)
                if cs_win5: csb["wins"]   += 1
                else:       csb["losses"] += 1
                if stop5:   csb["stops"]   += 1
                if target5: csb["targets"] += 1
                if cs_conf:
                    csb["confirmed_count"]   += 1
                    csb["confirmed_returns"].append(fwd5)
                    if cs_win5: csb["confirmed_wins"] += 1
                else:
                    csb["unconfirmed_returns"].append(fwd5)
                    if cs_win5: csb["unconfirmed_wins"] += 1

            # ── Confirmed-lift tracking (direction-adjusted wins) ─────
            # For "both" and "neither" we use cs direction as the canonical signal
            combo_win = cs_win5 if (geo_conf and cs_conf) else win5

            def _record_lift(key: str, directional_win: bool) -> None:
                bk = confirmed_lift[key]
                bk["sampleCount"] += 1
                bk["returns"].append(fwd5)
                if directional_win: bk["wins"]   += 1
                else:               bk["losses"] += 1
                if stop5:   bk["stops"]   += 1
                if target5: bk["targets"] += 1

            if geo_pattern:
                _record_lift("geo_confirmed" if geo_conf else "geo_unconfirmed", geo_win5)
                # Family-level confirmation lift — feeds the next calibration
                # round of the direction/family-aware confirm adjustments.
                fam = GEO_PATTERN_FAMILY.get(geo_pattern, "NEUTRAL")
                fb = geo_family_lift[f"{fam}|{'confirmed' if geo_conf else 'unconfirmed'}"]
                fb["sampleCount"] += 1
                fb["returns"].append(fwd5)
                if geo_win5: fb["wins"]   += 1
                else:        fb["losses"] += 1
            if cs_pattern:
                _record_lift("cs_confirmed" if cs_conf else "cs_unconfirmed", cs_win5)
            # True two-signal combo requires direction agreement — a bullish
            # geometry with a bearish confirmation candle is two signals
            # cancelling each other, not confirming.
            if geo_conf and cs_conf and geo_dir == cs_dir:
                _record_lift("both_confirmed", combo_win)
            elif not geo_pattern and not cs_pattern:
                _record_lift("neither", win5)

    # ── Summarize ──────────────────────────────────────────────────────────
    def _summarize_bucket(sb: dict, n: int, rets: list[float], stop_val: float | None = None) -> dict:
        d = {
            "sampleCount":   n,
            "winRate":       round(sb["wins"] / n, 3),
            "avgReturn":     round(sum(rets) / len(rets), 4),
            "medianReturn":  round(_median(rets), 4),
            "stopRate":      round(sb["stops"] / n, 3),
            "targetHitRate": round(sb["targets"] / n, 3),
        }
        return d

    strategy_summary: dict[str, Any] = {}
    for key, sb in strategy_stats.items():
        n = sb["sampleCount"]
        if n == 0:
            continue
        rets = sb["returns"]
        mode, _, h_name = key.partition("|")
        stop = STRATEGIES[mode]["stop"]
        tgt  = STRATEGIES[mode]["target"]
        by_pat: dict[str, Any] = {}
        for pat, pb in sb["byPattern"].items():
            pn = pb["sampleCount"]
            if pn == 0:
                continue
            pr = pb["returns"]
            by_pat[pat] = {
                "sampleCount": pn,
                "winRate":     round(pb["wins"] / pn, 3),
                "avgReturn":   round(sum(pr) / len(pr), 4),
                "medianReturn": round(_median(pr), 4),
            }
        strategy_summary[key] = {
            "sampleCount":   n,
            "winRate":       round(sb["wins"] / n, 3),
            "avgReturn":     round(sum(rets) / len(rets), 4),
            "medianReturn":  round(_median(rets), 4),
            "stopRate":      round(sb["stops"] / n, 3),
            "targetHitRate": round(sb["targets"] / n, 3),
            "stopThreshold": stop,
            "targetThreshold": tgt,
            "byPattern": by_pat,
        }

    # Regime-strategy summary (no byPattern for compactness)
    regime_strategy_summary: dict[str, Any] = {}
    for key, sb in regime_strategy_stats.items():
        n = sb["sampleCount"]
        if n == 0:
            continue
        rets = sb["returns"]
        regime, _, rest = key.partition("|")
        mode, _, h_name = rest.partition("|")
        stop = STRATEGIES.get(mode, {}).get("stop", -0.02)
        regime_strategy_summary.setdefault(regime, {})[rest] = {
            "sampleCount":   n,
            "winRate":       round(sb["wins"] / n, 3),
            "avgReturn":     round(sum(rets) / len(rets), 4),
            "medianReturn":  round(_median(rets), 4),
            "stopRate":      round(sb["stops"] / n, 3),
            "targetHitRate": round(sb["targets"] / n, 3),
        }

    cs_summary: dict[str, Any] = {}
    for pat, csb in cs_stats.items():
        n = csb["sampleCount"]
        if n == 0:
            continue
        rets = csb["returns"]
        nc   = csb["confirmed_count"]
        nu   = n - nc
        cr   = csb["confirmed_returns"]
        ucr  = csb["unconfirmed_returns"]
        cs_summary[pat] = {
            "sampleCount":          n,
            "winRate":              round(csb["wins"] / n, 3),
            "avgReturn":            round(sum(rets) / len(rets), 4),
            "medianReturn":         round(_median(rets), 4),
            "stopRate":             round(csb["stops"] / n, 3),
            "targetHitRate":        round(csb["targets"] / n, 3),
            "confirmedCount":       nc,
            "confirmedWinRate":     round(csb["confirmed_wins"] / nc, 3) if nc else None,
            "confirmedAvgReturn":   round(sum(cr) / len(cr), 4) if cr else None,
            "unconfirmedCount":     nu,
            "unconfirmedWinRate":   round(csb["unconfirmed_wins"] / nu, 3) if nu > 0 else None,
            "unconfirmedAvgReturn": round(sum(ucr) / len(ucr), 4) if ucr else None,
        }

    lift_summary: dict[str, Any] = {}
    for key, bk in confirmed_lift.items():
        n = bk["sampleCount"]
        if n == 0:
            continue
        rets = bk["returns"]
        lift_summary[key] = {
            "sampleCount":   n,
            "winRate":       round(bk["wins"] / n, 3),
            "avgReturn":     round(sum(rets) / len(rets), 4),
            "medianReturn":  round(_median(rets), 4),
            "stopRate":      round(bk["stops"] / n, 3),
            "targetHitRate": round(bk["targets"] / n, 3),
        }

    geo_family_summary: dict[str, Any] = {}
    for key, fb in geo_family_lift.items():
        n = fb["sampleCount"]
        if n == 0:
            continue
        rets = fb["returns"]
        geo_family_summary[key] = {
            "sampleCount":  n,
            "winRate":      round(fb["wins"] / n, 3),
            "avgReturn":    round(sum(rets) / len(rets), 4),
            "medianReturn": round(_median(rets), 4),
        }

    suggestions = _strategy_calibration_suggestions(strategy_summary)
    suggestions += _candlestick_calibration_suggestions(cs_summary)
    suggestions += _confirmation_lift_suggestions(lift_summary)
    # Family-level confirmation drift alerts: flag when a family's confirmed
    # win rate flips against the engine's current adjustment direction.
    for fam in ("REV_BULL", "CONT_BEAR"):
        c = geo_family_summary.get(f"{fam}|confirmed", {})
        u = geo_family_summary.get(f"{fam}|unconfirmed", {})
        if c.get("sampleCount", 0) >= 30 and u.get("sampleCount", 0) >= 30:
            lift = c["winRate"] - u["winRate"]
            if lift < 0:
                suggestions.append({
                    "pattern": fam,
                    "action":  "RECALIBRATE_CONFIRM",
                    "reason":  (
                        f"{fam} 확인봉 리프트가 음전환 ({lift*100:+.1f}p) — "
                        "엔진의 family-aware 확인 보정 재검토 필요"
                    ),
                })

    result_doc = {
        "status":    "OK",
        "market":    market,
        "fromDate":  from_date,
        "toDate":    to_date,
        "evalDates": len(eval_dates),
        "regimeCounts":              dict(regime_counts),
        "strategySummary":           strategy_summary,
        "regimeStrategySummary":     regime_strategy_summary,
        "candlestickSummary":        cs_summary,
        "confirmedLiftSummary":      lift_summary,
        "geoFamilyLiftSummary":      geo_family_summary,
        "leakageCheck":              {"status": "PASS" if leakage_ok else "FAIL"},
        "calibrationSuggestions":    suggestions,
        "strategiesConfig":          STRATEGIES,
        "horizonsConfig":            HORIZONS,
    }

    try:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _REPORTS_DIR / f"pattern_walkforward_combined_{market}.json"
        out_path.write_text(json.dumps(result_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return result_doc


def _strategy_calibration_suggestions(strategy_summary: dict) -> list[dict]:
    suggestions: list[dict] = []
    for key, stats in strategy_summary.items():
        n = stats["sampleCount"]
        mode, _, h_name = key.partition("|")
        if n < 10:
            suggestions.append({
                "strategy": key, "action": "OBSERVE_ONLY",
                "reason": f"표본 수 부족 ({n}개). 최소 10개 이상 쌓인 후 보정.",
            })
            continue
        win_r  = stats["winRate"]
        stop_r = stats["stopRate"]
        avg_r  = stats["avgReturn"]
        if win_r > 0.60:
            suggestions.append({
                "strategy": key, "action": "PROMOTE",
                "reason": (f"{mode}/{h_name} 전략 승률 {win_r:.0%}, "
                           f"평균수익률 {avg_r:+.1%} — 신호 우선도 높음"),
            })
        elif win_r < 0.40 or stop_r > 0.35:
            suggestions.append({
                "strategy": key, "action": "DEMOTE",
                "reason": (f"{mode}/{h_name} 전략 승률 {win_r:.0%}, "
                           f"손절률 {stop_r:.0%} — 필터 강화 검토"),
            })
    return suggestions


def _candlestick_calibration_suggestions(cs_summary: dict) -> list[dict]:
    suggestions: list[dict] = []
    for pat, stats in cs_summary.items():
        n = stats["sampleCount"]
        if n < 5:
            suggestions.append({
                "pattern": pat, "action": "OBSERVE_ONLY",
                "reason": f"캔들스틱 패턴 표본 부족 ({n}개).",
            })
            continue
        win_r    = stats["winRate"]
        conf_wr  = stats.get("confirmedWinRate")
        uconf_wr = stats.get("unconfirmedWinRate")
        if conf_wr is not None and uconf_wr is not None:
            lift = conf_wr - uconf_wr
            if lift > 0.10:
                suggestions.append({
                    "pattern": pat, "action": "CONFIRMATION_BONUS_JUSTIFIED",
                    "reason": (f"확인봉 있을 때 승률 {conf_wr:.0%} vs 없을 때 {uconf_wr:.0%} "
                               f"(+{lift:.0%}) — 두 신호 결합 가중치 유효"),
                })
            elif lift < -0.05:
                suggestions.append({
                    "pattern": pat, "action": "CONFIRMATION_BONUS_QUESTION",
                    "reason": (f"확인봉 있을 때 승률 {conf_wr:.0%}, 없을 때 {uconf_wr:.0%} "
                               f"— 확인봉 기준 재검토 권장"),
                })
        if win_r > 0.60:
            suggestions.append({
                "pattern": pat, "action": "STRENGTHEN",
                "reason": f"캔들스틱 패턴 승률 {win_r:.0%} — 컨텍스트 신호 강화 권장",
            })
        elif win_r < 0.35:
            suggestions.append({
                "pattern": pat, "action": "WEAKEN",
                "reason": f"캔들스틱 패턴 승률 {win_r:.0%} — 컨텍스트 필터 재검토 필요",
            })
    return suggestions


def _confirmation_lift_suggestions(lift_summary: dict) -> list[dict]:
    suggestions: list[dict] = []
    geo_c  = lift_summary.get("geo_confirmed", {})
    geo_u  = lift_summary.get("geo_unconfirmed", {})
    cs_c   = lift_summary.get("cs_confirmed", {})
    cs_u   = lift_summary.get("cs_unconfirmed", {})
    both   = lift_summary.get("both_confirmed", {})
    neither = lift_summary.get("neither", {})

    if geo_c and geo_u and geo_c.get("sampleCount", 0) >= 5:
        lift = (geo_c.get("winRate", 0) or 0) - (geo_u.get("winRate", 0) or 0)
        suggestions.append({
            "signal": "geometric_confirmation",
            "action": "CONFIRMATION_LIFT_VALID" if lift > 0.05 else "CONFIRMATION_LIFT_WEAK",
            "reason": (f"기하패턴 확인봉 있을 때 승률 {geo_c.get('winRate', 0):.0%} "
                       f"vs 없을 때 {geo_u.get('winRate', 0):.0%} (lift {lift:+.0%})"),
        })
    if cs_c and cs_u and cs_c.get("sampleCount", 0) >= 5:
        lift = (cs_c.get("winRate", 0) or 0) - (cs_u.get("winRate", 0) or 0)
        suggestions.append({
            "signal": "candlestick_confirmation",
            "action": "CONFIRMATION_LIFT_VALID" if lift > 0.05 else "CONFIRMATION_LIFT_WEAK",
            "reason": (f"캔들스틱 확인봉 있을 때 승률 {cs_c.get('winRate', 0):.0%} "
                       f"vs 없을 때 {cs_u.get('winRate', 0):.0%} (lift {lift:+.0%})"),
        })
    if both and neither and both.get("sampleCount", 0) >= 5:
        lift = (both.get("winRate", 0) or 0) - (neither.get("winRate", 0) or 0)
        suggestions.append({
            "signal": "both_confirmed_vs_neither",
            "action": "COMBO_SIGNAL_STRONG" if lift > 0.08 else "COMBO_SIGNAL_MODERATE",
            "reason": (f"기하+캔들 모두 확인됐을 때 승률 {both.get('winRate', 0):.0%} "
                       f"vs 신호 없음 {neither.get('winRate', 0):.0%} (lift {lift:+.0%}) "
                       f"— 두 신호 결합 전략 {'유효' if lift > 0.08 else '보통'}"),
        })
    return suggestions


def _geometric_calibration_suggestions(geo_summary: dict) -> list[dict]:
    """
    Human-readable calibration notes for classic chart patterns, keyed by
    "PATTERN:STAGE". Geometric patterns don't carry a numeric confidence yet
    (see geometric_patterns.py), so suggestions are observational — they flag
    which pattern+stage combinations are worth promoting/demoting once enough
    samples exist, ahead of wiring an actual per-pattern confidence weight.
    """
    suggestions: list[dict] = []
    for key, stats in geo_summary.items():
        n = stats["sampleCount"]
        if n < 10:
            suggestions.append({
                "pattern": key, "action": "OBSERVE_ONLY",
                "reason": f"표본 수 부족 ({n}개). 최소 10개 이상 쌓인 후 보정.",
            })
            continue

        win_r = stats.get("directionalWinRate", stats.get("winRate", 0))
        stop_r, avg_r = stats["stopRate"], stats["avgReturn"]
        pattern, _, stage = key.partition(":")
        direction = str(stats.get("expectedDirection") or "").upper()
        is_bearish_stage = direction == "BEARISH" or stage in ("AVOID", "BLOCKED", "RISK_WATCH")

        if is_bearish_stage:
            if win_r < 0.40:
                suggestions.append({
                    "pattern": key, "action": "WEAKEN",
                    "reason": f"하락 경계 단계인데 방향 확인율 {win_r:.0%}로 낮음 — 경계 기준 재검토 필요",
                })
            elif win_r > 0.65:
                suggestions.append({
                    "pattern": key, "action": "STRENGTHEN",
                    "reason": f"하락 확인율 {win_r:.0%}, 방향 기준 평균수익률 {avg_r:+.1%} — 경계 신호 신뢰도 높음",
                })
        else:
            if win_r > 0.60:
                suggestions.append({
                    "pattern": key, "action": "STRENGTHEN",
                    "reason": f"승률 {win_r:.0%}, 평균수익률 {avg_r:+.1%} — 우선순위 상향 후보",
                })
            elif win_r < 0.40 or stop_r > 0.35:
                suggestions.append({
                    "pattern": key, "action": "WEAKEN",
                    "reason": f"승률 {win_r:.0%}, 손절률 {stop_r:.0%} — 매수권 기준 강화 검토",
                })

    return suggestions
