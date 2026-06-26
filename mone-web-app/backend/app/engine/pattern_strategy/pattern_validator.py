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
from .pattern_engine import analyze, load_params
from .types import DEFAULT_PARAMS


# ── Paths ─────────────────────────────────────────────────────────────────
_REPO_ROOT   = Path(__file__).resolve().parents[5]
_OHLCV_DIR   = _REPO_ROOT / "data" / "market" / "ohlcv"
_REPORTS_DIR = _REPO_ROOT / "reports"


def _indicator_stats_bucket() -> dict[str, Any]:
    return {
        "sampleCount": 0, "wins": 0, "losses": 0, "stops": 0, "targets": 0,
        "returns": [], "blocked_returns": [],
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
        return "BULL"
    if not above_ma and not ma_rising:
        return "BEAR"
    return "SIDE"


def _market_regime_at_date(market: str, all_ohlcv: dict[str, list[dict]], cutoff_date: str) -> str:
    if market == "us":
        votes = [_regime_for_index(all_ohlcv.get(sym, []), cutoff_date) for sym in ("SPY", "QQQ", "DIA")]
        if votes.count("BULL") >= 2:
            return "BULL"
        if votes.count("BEAR") >= 2:
            return "BEAR"
        return "SIDE"
    return _regime_for_index(all_ohlcv.get("KOSPI", []), cutoff_date)


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
        regime_counts[regime] += 1
        for sym, all_rows in all_ohlcv.items():
            # Strict cutoff — no future data
            hist_rows = _slice_before(all_rows, date_str)
            if len(hist_rows) < p.get("minOhlcvRows", 20):
                continue

            result = analyze(sym, market, hist_rows, p)

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
