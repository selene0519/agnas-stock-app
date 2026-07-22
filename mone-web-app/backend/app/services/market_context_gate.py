"""Evidence-labelled market breadth, macro proxy, and exposure guardrails.

The app does not have a licensed all-exchange breadth feed or real-time credit
data.  This module therefore measures only the locally collected universe and
labels every result accordingly.  It is a position-sizing constraint, never a
price or return forecast.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
MIN_BREADTH_SYMBOLS = 20


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                result = [dict(row) for row in csv.DictReader(handle)]
            return sorted(result, key=lambda row: str(row.get("date") or row.get("Date") or ""))
        except Exception:
            continue
    return []


def _closes(rows: list[dict[str, str]]) -> tuple[list[str], list[float]]:
    dates: list[str] = []
    closes: list[float] = []
    for row in rows:
        close = _number(row.get("close") or row.get("Close"))
        raw_date = str(row.get("date") or row.get("Date") or "").strip()
        digits = "".join(char for char in raw_date if char.isdigit())
        date = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else raw_date[:10]
        if close is not None and close > 0 and date:
            dates.append(date[:10])
            closes.append(close)
    return dates, closes


def _ma(values: list[float], days: int) -> float | None:
    return sum(values[-days:]) / days if len(values) >= days else None


def _pct_change(values: list[float], days: int) -> float | None:
    if len(values) <= days or values[-days - 1] <= 0:
        return None
    return (values[-1] / values[-days - 1] - 1.0) * 100.0


def _read_symbol(market: str, symbol: str) -> tuple[list[str], list[float]]:
    return _closes(_rows(OHLCV_DIR / f"{market}_{symbol}_daily.csv"))


def market_breadth(market: str, *, directory: Path | None = None) -> dict[str, Any]:
    """Calculate breadth for the *locally tracked* universe, not an exchange."""
    market = str(market or "").lower()
    folder = directory or OHLCV_DIR
    prefix = f"{market}_"
    universe: list[tuple[str, list[str], list[float]]] = []
    for path in sorted(folder.glob(f"{prefix}*_daily.csv")):
        symbol = path.name[len(prefix):-len("_daily.csv")]
        # Indices, FX and ETFs are market context inputs, not constituents.
        if symbol.upper() in {"KOSPI", "KOSDAQ", "SPY", "QQQ", "DIA", "IWM", "TLT", "XLE", "XLF", "SMH", "SOXX", "GLD", "SCHD", "SOXL", "BTC-USD", "USD/ KRW", "USDKRW"}:
            continue
        dates, closes = _closes(_rows(path))
        if len(closes) >= 51:
            universe.append((symbol, dates, closes))

    eligible = len(universe)
    as_of = max((dates[-1] for _, dates, _ in universe if dates), default="")
    above20 = above50 = positive20 = 0
    completed = 0
    for _, dates, closes in universe:
        # A stale constituent is excluded rather than treated as a decline.
        if not dates or dates[-1] != as_of:
            continue
        ma20, ma50, ret20 = _ma(closes, 20), _ma(closes, 50), _pct_change(closes, 20)
        if ma20 is None or ma50 is None or ret20 is None:
            continue
        completed += 1
        above20 += int(closes[-1] > ma20)
        above50 += int(closes[-1] > ma50)
        positive20 += int(ret20 > 0)
    if completed < MIN_BREADTH_SYMBOLS:
        return {
            "status": "INSUFFICIENT_LOCAL_UNIVERSE", "asOf": as_of, "sampleCount": completed,
            "eligibleSymbols": eligible, "minimumSamples": MIN_BREADTH_SYMBOLS,
            "basis": "local_tracked_universe_only", "score": None, "zone": "UNKNOWN",
        }
    pct20, pct50, pct_return = (above20 / completed * 100, above50 / completed * 100, positive20 / completed * 100)
    score = round(pct20 * 0.40 + pct50 * 0.35 + pct_return * 0.25, 1)
    if score >= 80:
        zone, exposure = "STRONG", 1.0
    elif score >= 60:
        zone, exposure = "HEALTHY", 0.85
    elif score >= 40:
        zone, exposure = "NEUTRAL", 0.65
    elif score >= 20:
        zone, exposure = "WEAKENING", 0.40
    else:
        zone, exposure = "CRITICAL", 0.25
    return {
        "status": "OK", "asOf": as_of, "sampleCount": completed, "eligibleSymbols": eligible,
        "basis": "local_tracked_universe_only", "score": score, "zone": zone,
        "recommendedExposureMultiplier": exposure,
        "components": {"aboveMa20Pct": round(pct20, 1), "aboveMa50Pct": round(pct50, 1), "positiveReturn20dPct": round(pct_return, 1)},
    }


def _ratio_momentum(numerator: list[float], denominator: list[float], days: int = 63) -> float | None:
    common = min(len(numerator), len(denominator))
    if common <= days:
        return None
    ratios = [numerator[-common + i] / denominator[-common + i] for i in range(common) if denominator[-common + i] > 0]
    return _pct_change(ratios, days)


def macro_proxy(market: str) -> dict[str, Any]:
    """Use available local cross-asset proxies; missing components stay missing."""
    market = str(market or "").lower()
    if market == "us":
        symbols = {key: _read_symbol("us", key) for key in ("SPY", "QQQ", "RSP", "IWM", "HYG", "LQD", "TLT", "XLY", "XLP")}
        as_of = min((dates[-1] for dates, values in symbols.values() if dates and values), default="")
        spy = symbols["SPY"][1]
        components = {
            "concentrationQqqSpy63dPct": _ratio_momentum(symbols["QQQ"][1], spy),
            "breadthRspSpy63dPct": _ratio_momentum(symbols["RSP"][1], spy),
            "sizeIwmSpy63dPct": _ratio_momentum(symbols["IWM"][1], spy),
            "creditHygLqd63dPct": _ratio_momentum(symbols["HYG"][1], symbols["LQD"][1]),
            "equityBondSpyTlt63dPct": _ratio_momentum(spy, symbols["TLT"][1]),
            "cyclicalDefensiveXlyXlp63dPct": _ratio_momentum(symbols["XLY"][1], symbols["XLP"][1]),
        }
        available = [value for value in components.values() if value is not None]
        if len(available) < 5:
            return {"status": "INSUFFICIENT_LOCAL_PROXIES", "asOf": as_of, "basis": "local_cross_asset_proxy_partial", "classification": "UNKNOWN", "components": components}
        contraction = (components["sizeIwmSpy63dPct"] or 0) < -3 and (components["creditHygLqd63dPct"] or 0) < -1
        broadening = (components["breadthRspSpy63dPct"] or 0) > 2 and (components["sizeIwmSpy63dPct"] or 0) > 2
        concentration = (components["breadthRspSpy63dPct"] or 0) < -2 and (components["concentrationQqqSpy63dPct"] or 0) > 0
        classification = "CONTRACTION" if contraction else "BROADENING" if broadening else "CONCENTRATION" if concentration else "TRANSITIONAL"
        return {"status": "PARTIAL_PROXY", "asOf": as_of, "basis": "local_cross_asset_proxy_no_yield_curve", "classification": classification, "components": {key: None if value is None else round(value, 2) for key, value in components.items()}}
    if market == "kr":
        kospi_dates, kospi = _read_symbol("kr", "KOSPI")
        kosdaq_dates, kosdaq = _read_symbol("kr", "KOSDAQ")
        fx_dates, fx = _read_symbol("fx", "USDKRW")
        components = {"kosdaqKospi63dPct": _ratio_momentum(kosdaq, kospi), "usdKrw63dPct": _pct_change(fx, 63)}
        if any(value is None for value in components.values()):
            return {"status": "INSUFFICIENT_LOCAL_PROXIES", "asOf": min((x[-1] for x in (kospi_dates, kosdaq_dates, fx_dates) if x), default=""), "basis": "local_kr_proxy_partial", "classification": "UNKNOWN", "components": components}
        classification = "CONTRACTION" if components["usdKrw63dPct"] > 5 and components["kosdaqKospi63dPct"] < -3 else "BROADENING" if components["kosdaqKospi63dPct"] > 2 else "TRANSITIONAL"
        return {"status": "PARTIAL_PROXY", "asOf": min(kospi_dates[-1], kosdaq_dates[-1], fx_dates[-1]), "basis": "local_kr_proxy_partial_no_credit_or_yield_curve", "classification": classification, "components": {key: round(value, 2) for key, value in components.items()}}
    return {"status": "UNSUPPORTED_MARKET", "classification": "UNKNOWN", "components": {}}


def build_market_context(market: str) -> dict[str, Any]:
    breadth = market_breadth(market)
    macro = macro_proxy(market)
    exposure = breadth.get("recommendedExposureMultiplier")
    if exposure is None:
        exposure = 0.0
        status = "CASH_UNTIL_BREADTH_AVAILABLE"
    else:
        status = "OK"
    # The CONTRACTION exposure throttle (cap at 0.35) was removed: a 2011-2026
    # walk-forward on KOSPI showed the KR CONTRACTION signal (fx63>5 &
    # kosdaqKospi63<-3) actually *preceded* better outcomes on both return and
    # risk (fwd-20d +6.99% vs +0.57%; avg max drawdown -1.33% vs -2.93%). It
    # throttled exposure right before rebounds, i.e. an unjustified cash bias.
    # The classification is still surfaced below for transparency, but no longer
    # forces a smaller position size.
    return {
        "version": "market-context-v2", "market": str(market or "").lower(), "status": status,
        "breadth": breadth, "macro": macro, "recommendedExposureMultiplier": round(float(exposure), 2),
        "manualReviewRequired": True,
        "note": "Breadth uses only the local tracked universe; macro is surfaced for context and does not throttle exposure (CONTRACTION throttle removed on walk-forward evidence); not a return forecast.",
    }


def pre_trade_gate(item: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable checklist verdict; unknown data never grants approval."""
    reasons: list[str] = []
    if context.get("status") != "OK":
        reasons.append("MARKET_BREADTH_UNAVAILABLE")
    if str((context.get("breadth") or {}).get("zone") or "") == "CRITICAL":
        reasons.append("CRITICAL_LOCAL_BREADTH")
    if bool(item.get("isTradeBlocked")) or bool(item.get("isRegimePerformanceBlocked")):
        reasons.append("PERFORMANCE_GATE_BLOCKED")
    plan = item.get("tradePlan") if isinstance(item.get("tradePlan"), dict) else {}
    if plan and plan.get("status") != "READY":
        reasons.append("REGIME_TRADE_PLAN_NOT_READY")
    return {
        "version": "pre-trade-gate-v1", "status": "NO_TRADE" if reasons else "REVIEW_READY",
        "isTradeBlocked": bool(reasons), "reasonCodes": reasons,
        "maxExposureMultiplier": context.get("recommendedExposureMultiplier"),
        "manualReviewRequired": True,
    }
