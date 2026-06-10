from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.engine.chart_analysis_engine import build_chart_analysis, state_to_dict
from app.services import data_loader as data
from app.services import runtime_limits
from app.services import trendline_learning
from app.services import event_context as _ec
from app.services import adaptive_weights as _aw

MARKETS = ("kr", "us")
MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

MODE_LABELS = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
HORIZON_LABELS = {"short": "단기", "swing": "스윙", "mid": "중기"}
HORIZON_DAYS = {"short": 1, "swing": 5, "mid": 20}
HORIZON_PROB_FIELD = {"short": "prob1d", "swing": "prob5d", "mid": "prob20d"}
HORIZON_PRICE_FIELD = {"short": "expectedPrice1dText", "swing": "expectedPrice5dText", "mid": "expectedPrice20dText"}

MODE_RULES = {
    "conservative": {"min_opportunity": 68, "min_entry": 64, "max_risk": 38, "max_gap": 0.035, "max_items": 5, "risk_mult": 0.82},
    "balanced": {"min_opportunity": 58, "min_entry": 54, "max_risk": 56, "max_gap": 0.075, "max_items": 8, "risk_mult": 1.0},
    "aggressive": {"min_opportunity": 48, "min_entry": 42, "max_risk": 74, "max_gap": 0.13, "max_items": 12, "risk_mult": 1.25},
}

EVENT_KEYWORDS = {
    "macro": ("FOMC", "CPI", "PPI", "PCE", "고용", "금리", "파월", "환율", "국채", "yield"),
    "earnings": ("실적", "earnings", "분기", "컨센서스", "EPS", "guidance", "가이던스"),
    "disclosure_good": ("수주", "공급계약", "계약", "자사주", "배당", "흑자", "승인", "FDA", "임상 성공"),
    "disclosure_risk": ("증자", "CB", "전환사채", "BW", "관리종목", "상장폐지", "감사의견", "소송", "유상증자"),
    "theme": ("테마", "급등", "상한가", "IPO", "상장", "보호예수", "락업", "신규상장"),
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(value: Any) -> float | None:
    return data._safe_float(value)  # type: ignore[attr-defined]


def _pct(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("%", "").replace(",", "").strip()
    n = _num(value)
    if n is None:
        return None
    if 0 <= n <= 1:
        return n * 100
    return n


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    return str(value).strip()


def _has(text: str, words: Iterable[str]) -> bool:
    lower = text.lower()
    return any(word.lower() in lower for word in words)


def _symbol(item: dict[str, Any], market: str) -> str:
    return data.normalize_symbol(item.get("symbol") or data.first_value(item.get("raw", item), data.SYMBOL_ALIASES, ""), market)


def _raw(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("raw")
    return dict(raw) if isinstance(raw, dict) else dict(item)


def _latest_ohlcv(symbol: str, market: str) -> tuple[pd.DataFrame, str]:
    try:
        return data._load_ohlcv(symbol, market)  # type: ignore[attr-defined]
    except Exception:
        return pd.DataFrame(), ""


def _chart_data_source_type(df: pd.DataFrame, source: str, normalized: dict[str, Any] | None = None) -> str:
    source_text = _as_text(source).lower()
    row_source = _as_text((normalized or {}).get("sourceType")).lower()
    price_source = _as_text((normalized or {}).get("priceSourceType")).lower()
    if "mock" in source_text or "mock" in row_source or "mock" in price_source:
        return "mock"
    if df.empty:
        if row_source in {"stockapp_snapshot", "github_actions", "local_fallback", "stale"}:
            return "csv"
        if row_source in {"placeholder", "fallback"}:
            return "placeholder"
        return "unavailable"
    if "close-history fallback" in source_text:
        return "close_history_fallback"
    if "api" in source_text or any(token in source_text for token in ("kis", "finnhub", "yfinance", "yahoo")):
        return "api"
    if source_text.endswith(".csv") or ".csv" in source_text:
        return "actual_ohlcv"
    if row_source in {"stockapp_snapshot", "github_actions", "local_fallback", "stale"}:
        return "csv"
    return "actual_ohlcv"


def _line_price(line: dict[str, Any] | None, index: int) -> float | None:
    if not line:
        return None
    slope = _num(line.get("slope"))
    intercept = _num(line.get("intercept"))
    if slope is None or intercept is None:
        return None
    price = slope * index + intercept
    return price if price > 0 else None


def _distance_pct(price: float | None, reference: float | None) -> float | None:
    if price is None or reference is None or reference <= 0:
        return None
    return (price - reference) / reference * 100


def _basis_label(value: float | None, support: float | None, resistance: float | None, atr: float | None, fallback: str) -> str:
    if value is None:
        return "unavailable"
    matches: list[str] = []
    tolerance = max((atr or 0) * 0.75, value * 0.015)
    if support is not None and abs(value - support) <= tolerance:
        matches.append("support")
    if resistance is not None and abs(value - resistance) <= tolerance:
        matches.append("resistance")
    if atr and atr > 0:
        matches.append("atr")
    return "+".join(matches) if matches else fallback


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float | None:
    if df.empty or len(df) < 2:
        return None
    work = df.tail(period + 1).copy()
    for col in ("high", "low", "close"):
        if col not in work:
            return None
        work[col] = pd.to_numeric(work[col], errors="coerce")
    prev_close = work["close"].shift(1)
    tr = pd.concat([
        work["high"] - work["low"],
        (work["high"] - prev_close).abs(),
        (work["low"] - prev_close).abs(),
    ], axis=1).max(axis=1).dropna()
    if tr.empty:
        return None
    atr = float(tr.tail(period).mean())
    return atr if np.isfinite(atr) and atr > 0 else None


def _chart_signal_overlay(symbol: str, market: str, normalized: dict[str, Any], mode: str, horizon: str) -> dict[str, Any]:
    df, source = _latest_ohlcv(symbol, market)
    data_source_type = _chart_data_source_type(df, source, normalized)
    base = {
        "chartSignalUsed": False,
        "lineSignalUsed": False,
        "supportResistanceUsed": False,
        "trendlineUsed": False,
        "supportUsed": False,
        "resistanceUsed": False,
        "volumeZoneUsed": False,
        "fakeBreakoutRiskUsed": False,
        "dataSourceType": data_source_type,
        "chartSignalSummary": {
            "status": "unavailable",
            "recommendedIntegration": "chart display only / recommendation not used",
            "displayOnly": ["ZigZag", "retracement", "fakeBreakout"],
            "usedSignals": [],
            "badges": ["fallback 데이터" if data_source_type != "actual_ohlcv" else "실측 데이터"],
            "source": source,
            "notes": [],
        },
        "chartSignalBadges": ["fallback 데이터" if data_source_type != "actual_ohlcv" else "실측 데이터"],
        "entryBasis": "unavailable",
        "targetBasis": "unavailable",
        "stopBasis": "unavailable",
        "supportDistancePct": None,
        "resistanceDistancePct": None,
        "trendlineDistancePct": None,
        "riskRewardRatio": None,
        "chartScoreAdjustment": 0.0,
        "trendlineProjected5d": None,
        "trendlineProjected20d": None,
        "trendlineProjected60d": None,
        "trendlineBandUpper": None,
        "trendlineBandLower": None,
        "trendlineAnchorScore": 0.0,
        "trendlineHistoricalWinRate": None,
        "trendlineLearningStatus": "NO_DATA",
        "trendlineDataSourceType": data_source_type,
        "trendlineLearningEligible": data_source_type == "actual_ohlcv",
        "trendlineBandPct": 0.0,
        "trendlineBandAllowed": False,
    }
    if df.empty or len(df) < 20:
        base["chartSignalSummary"]["notes"].append("OHLCV unavailable or insufficient; chart signals not applied")
        if data_source_type in {"unavailable", "placeholder"}:
            base["chartScoreAdjustment"] = -8.0
        elif data_source_type != "actual_ohlcv":
            base["chartScoreAdjustment"] = -4.0
        return base

    rows = df.tail(180).replace({np.nan: None}).to_dict(orient="records")
    horizon_bars = {"short": 5, "swing": 20, "mid": 60}.get(horizon, 20)
    try:
        state = build_chart_analysis(rows, symbol=symbol, market=market, horizon_bars=horizon_bars)
        chart = state_to_dict(state)
    except Exception as exc:
        base["chartSignalSummary"]["status"] = "error"
        base["chartSignalSummary"]["notes"].append(f"chart analysis failed: {exc}")
        return base
    trendline_overlay = trendline_learning.analyze(
        market=market,
        symbol=symbol,
        rows=rows,
        chart=chart,
        horizon=horizon,
        data_source_type=data_source_type,
    )

    current = _num(normalized.get("currentPrice")) or _num(df["close"].iloc[-1] if "close" in df and len(df) else None)
    entry = _num(normalized.get("entry"))
    target = _num(normalized.get("target"))
    stop = _num(normalized.get("stop"))
    support = _line_price(chart.get("supportLine"), len(rows) - 1)
    resistance = _line_price(chart.get("resistanceLine"), len(rows) - 1)
    atr = _compute_atr(df)
    zones = chart.get("zones") if isinstance(chart.get("zones"), list) else []
    overlap_signals = chart.get("overlapSignals") if isinstance(chart.get("overlapSignals"), list) else []
    direction = _as_text(chart.get("confluenceDirection"))
    signal_status = _as_text(chart.get("signalStatus"))
    breakout = _as_text(chart.get("breakoutDirection"))
    support_dist = _distance_pct(current, support)
    resistance_dist = _distance_pct(current, resistance)
    trend_dist_candidates = [abs(v) for v in (support_dist, resistance_dist) if v is not None]
    trend_dist = min(trend_dist_candidates) if trend_dist_candidates else None
    rr = None
    if entry and stop and target and entry > 0 and target > entry and stop < entry:
        rr = (target - entry) / max(entry - stop, 1e-9)

    used: list[str] = []
    display_only = ["ZigZag", "retracement", "fakeBreakout"]
    badges = ["실측 데이터" if data_source_type == "actual_ohlcv" else "fallback 데이터"]
    adjustment = 0.0

    support_used = support is not None and support_dist is not None and 0 <= support_dist <= 3.0
    resistance_break = resistance is not None and current is not None and resistance * 1.002 < current <= resistance * 1.06
    resistance_near = resistance is not None and resistance_dist is not None and -4.0 <= resistance_dist <= 0.8
    trendline_hold = (
        support is not None
        and current is not None
        and direction == "bullish"
        and current >= support
        and support_dist is not None
        and 0 <= support_dist <= 6.0
    )
    resistance_line = chart.get("resistanceLine") if isinstance(chart.get("resistanceLine"), dict) else {}
    falling_resistance_break = resistance_break and resistance_line.get("lineDirection") in {"descending_resistance", "falling_resistance"}
    trendline_status = _as_text(trendline_overlay.get("trendlineLearningStatus"))
    trendline_verified = trendline_status == "VERIFIED" and bool(trendline_overlay.get("trendlineLearningEligible")) and bool(trendline_overlay.get("trendlineBandAllowed"))
    trendline_failed_history = trendline_status == "FAILED_ANCHOR_HISTORY"
    learned_line_type = _as_text(trendline_overlay.get("trendlineLineType"))
    trendline_hold = bool(trendline_hold and trendline_verified and learned_line_type == "support")
    falling_resistance_break = bool(falling_resistance_break and trendline_verified and learned_line_type == "resistance")
    fake_breakout_risk = False
    if breakout == "UP" and resistance is not None and current is not None and current < resistance * 1.012:
        fake_breakout_risk = True
    supply_near = False
    for zone in zones:
        if not isinstance(zone, dict) or zone.get("zoneType") != "supply" or current is None:
            continue
        top = _num(zone.get("top"))
        bottom = _num(zone.get("bottom"))
        if top and bottom and bottom <= current <= top * 1.015:
            supply_near = True
            break

    if support_used:
        adjustment += 4.0
        used.append("support_near")
        badges.append("지지선 근접")
    if resistance_break:
        adjustment += 4.0
        used.append("resistance_break")
        badges.append("저항 돌파")
    if trendline_hold:
        adjustment += 3.0
        used.append("trendline_hold")
        badges.append("빗각 유지")
    if falling_resistance_break:
        adjustment += 4.0
        used.append("falling_trendline_break")
    if trendline_failed_history:
        adjustment -= 4.0
        used.append("failed_anchor_history")
    if fake_breakout_risk:
        adjustment -= 6.0
        used.append("fake_breakout_risk")
        badges.append("가짜돌파 주의")
    if supply_near or resistance_near:
        adjustment -= 4.0
        used.append("volume_or_resistance_overhead")
    if data_source_type in {"close_history_fallback", "csv", "api"} and data_source_type != "actual_ohlcv":
        adjustment -= 3.0
    if data_source_type in {"unavailable", "placeholder", "mock"}:
        adjustment -= 8.0

    adjustment = float(data._clamp(adjustment, -12, 12))  # type: ignore[attr-defined]
    chart_used = bool(used) or data_source_type != "actual_ohlcv"
    if chart_used:
        badges.append("chart_signal_used")
        badges.append("recommendation_reflected")
    else:
        badges.append("chart_display_only")
    trendline_recommendation_used = bool(trendline_hold or falling_resistance_break)
    if trendline_verified:
        badges.append("verified_trendline")
    if trendline_recommendation_used:
        badges.append("trendline_recommendation_used")
    else:
        badges.append("trendline_chart_display_only")
    if trendline_status == "INSUFFICIENT_SAMPLE":
        badges.append("insufficient_trendline_samples")
    badges.append("actual_ohlcv_based" if data_source_type == "actual_ohlcv" else "fallback_based")

    return {
        **base,
        **trendline_overlay,
        "chartSignalUsed": chart_used,
        "lineSignalUsed": bool(support_used or resistance_break or trendline_hold or falling_resistance_break),
        "supportResistanceUsed": bool(support_used or resistance_break or resistance_near),
        "trendlineUsed": bool(trendline_hold or falling_resistance_break),
        "supportUsed": bool(support_used),
        "resistanceUsed": bool(resistance_break or resistance_near),
        "volumeZoneUsed": bool(supply_near),
        "fakeBreakoutRiskUsed": bool(fake_breakout_risk),
        "entryBasis": _basis_label(entry, support, resistance, atr, "recommendation_level"),
        "targetBasis": _basis_label(target, support, resistance, atr, "recommendation_level"),
        "stopBasis": _basis_label(stop, support, resistance, atr, "recommendation_level"),
        "supportDistancePct": round(support_dist, 3) if support_dist is not None else None,
        "resistanceDistancePct": round(resistance_dist, 3) if resistance_dist is not None else None,
        "trendlineDistancePct": round(trend_dist, 3) if trend_dist is not None else None,
        "riskRewardRatio": round(rr, 3) if rr is not None else None,
        "chartScoreAdjustment": round(adjustment, 2),
        "chartSignalBadges": list(dict.fromkeys(badges)),
        "chartSignalSummary": {
            "status": signal_status or "none",
            "direction": direction or "neutral",
            "chartSignalScore": chart.get("chartSignalScore"),
            "chartSignalTag": chart.get("chartSignalTag"),
            "confluenceScore": chart.get("confluenceScore"),
            "breakoutDirection": breakout or "",
            "recommendedIntegration": "recommendation reflected" if chart_used else "chart display only / recommendation not used",
            "displayOnly": display_only,
            "usedSignals": used,
            "badges": list(dict.fromkeys(badges)),
            "trendlineLearning": trendline_overlay,
            "source": source,
            "dataQuality": chart.get("dataQuality"),
            "supportLine": chart.get("supportLine"),
            "resistanceLine": chart.get("resistanceLine"),
            "supportPrice": round(support, 4) if support is not None else None,
            "resistancePrice": round(resistance, 4) if resistance is not None else None,
            "nearestSupplyZone": next((z for z in zones if isinstance(z, dict) and z.get("zoneType") == "supply"), None),
            "overlapSignalCount": len(overlap_signals),
            "notes": chart.get("warnings", []),
        },
    }


OPERATIONAL_VERSION = "v3.6.1-operational-stable"


FINAL_PRICE_OVERLAY_FIELDS = (
    "currentPrice",
    "currentPriceText",
    "priceTime",
    "priceSource",
    "priceSourceType",
    "priceSourceFile",
    "priceSourceDate",
    "priceDataStatus",
    "priceBasis",
    "priceSession",
)


def _final_price_overlay_score(item: dict[str, Any]) -> tuple[int, str]:
    """Rank already-normalized report prices for final recommendation cards.

    final_recommendations can start from older prediction rows.  Those rows may
    still contain a usable score/entry/target, but their current-price layer can
    point to an old predictions.csv value.  The report/intraday API has already
    resolved the current session price source (KIS snapshot, OHLCV close, or
    StockApp post-close snapshot), so final cards should reuse that price layer.
    """
    price = _num(item.get("currentPrice"))
    if price is None or price <= 0:
        return (-1, "")
    status = _as_text(item.get("priceDataStatus")).upper()
    source_type = _as_text(item.get("priceSourceType")).lower()
    source_file = _as_text(item.get("priceSourceFile") or item.get("sourceFile"))
    if status in {"", "STALE", "NO_PRICE", "ERROR", "MISSING"}:
        return (-1, "")
    if source_type in {"", "local", "local_fallback", "row", "existing"}:
        return (-1, "")
    try:
        if data._is_legacy_quote_source(source_file, _as_text(item.get("market"))):  # type: ignore[attr-defined]
            return (-1, "")
    except Exception:
        pass

    source_rank = {
        "kis_snapshot": 120,
        "kis": 115,
        "ohlcv": 100,
        "github": 95,
        "stockapp_snapshot": 90,
        "quote_cache": 80,
        "yfinance_fallback": 70,
        "finnhub_fallback": 70,
    }.get(source_type, 50)
    status_rank = {
        "INTRADAY": 40,
        "AFTER_CLOSE": 35,
        "PREMARKET_SNAPSHOT": 30,
        "PREVIOUS_CLOSE": 25,
        "NORMAL": 20,
    }.get(status, 10)
    return (source_rank + status_rank, _as_text(item.get("priceSourceDate") or item.get("priceTime")))


def _final_price_overlay_map(market: str) -> dict[str, dict[str, Any]]:
    """Build symbol -> clean price layer from the already-normalized report API."""
    try:
        payload = data.intraday_report(market)
    except Exception:
        return {}
    best: dict[str, dict[str, Any]] = {}
    best_score: dict[str, tuple[int, str]] = {}
    for item in payload.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        sym = data.normalize_symbol(item.get("symbol"), market)
        if not sym:
            continue
        score = _final_price_overlay_score(item)
        if score[0] < 0:
            continue
        if sym not in best_score or score > best_score[sym]:
            best_score[sym] = score
            best[sym] = {field: item.get(field) for field in FINAL_PRICE_OVERLAY_FIELDS if field in item}
    return best


def _apply_final_price_overlay(item: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    """Replace only the price layer, preserving recommendation scores and reasons."""
    if not overlay:
        return item
    patched = dict(item)
    for field in FINAL_PRICE_OVERLAY_FIELDS:
        if field in overlay and overlay.get(field) not in (None, ""):
            patched[field] = overlay[field]
    # Keep lowercase/current aliases aligned for helper functions that still look
    # at current_price rather than currentPrice.
    if "currentPrice" in patched:
        patched["current_price"] = patched["currentPrice"]
        patched["last_price"] = patched["currentPrice"]
    statuses = patched.get("statuses")
    if isinstance(statuses, dict):
        statuses = dict(statuses)
        if patched.get("priceDataStatus"):
            statuses["price"] = patched.get("priceDataStatus")
        patched["statuses"] = statuses
    patched["finalPriceOverlayApplied"] = True
    return patched


def _to_ts(value: Any) -> pd.Timestamp | None:
    """Parse a date/time value safely. Returns None if parsing fails."""
    text = _as_text(value)
    if not text:
        return None
    # Common KST strings contain extra labels; keep the date/time-looking prefix.
    text = text.replace("KST", "").replace("kst", "").strip()
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        # Try YYYYMMDD embedded in filenames/fields.
        m = re.search(r"(20\d{6})", text)
        if m:
            ts = pd.to_datetime(m.group(1), format="%Y%m%d", errors="coerce")
    if pd.isna(ts):
        return None
    return ts.normalize()


def _prediction_date(row: dict[str, Any]) -> pd.Timestamp | None:
    for key in ("prediction_date", "created_at", "run_time_kst", "prediction_at", "target_date", "actual_date", "date", "날짜"):
        ts = _to_ts(row.get(key))
        if ts is not None:
            return ts
    return None


def _ohlcv_with_dates(symbol: str, market: str) -> tuple[pd.DataFrame, str]:
    df, source = _latest_ohlcv(symbol, market)
    if df.empty:
        return df, source
    work = df.copy()
    work["_date_ts"] = pd.to_datetime(work.get("date"), errors="coerce").dt.normalize()
    work = work.dropna(subset=["_date_ts"]).sort_values("_date_ts").reset_index(drop=True)
    return work, source


def _actual_close_after(symbol: str, market: str, base_date: pd.Timestamp | None, trading_day_offset: int) -> tuple[float | None, str, str]:
    """Return close at Nth trading day after base_date from stored OHLCV."""
    if base_date is None:
        return None, "", "예측일 부족"
    df, source = _ohlcv_with_dates(symbol, market)
    if df.empty:
        return None, source, "OHLCV 없음"
    future = df[df["_date_ts"] > base_date]
    if len(future) < trading_day_offset:
        return None, source, f"D+{trading_day_offset} 거래일 미도래"
    row = future.iloc[trading_day_offset - 1]
    close = _num(row.get("close"))
    date_text = _as_text(row.get("date"))
    return close, source, date_text


def _prediction_market(row: pd.Series, fallback: str | None = None) -> str:
    text = _as_text(row.get("market")).lower()
    if "us" in text or "미국" in text or "nasdaq" in text or "nyse" in text:
        return "us"
    if "kr" in text or "한국" in text or "국장" in text or "kospi" in text or "kosdaq" in text:
        return "kr"
    return fallback if fallback in MARKETS else "kr"


def _fill_prediction_accuracy_actuals(df: pd.DataFrame, requested_market: str | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fill missing prediction actuals from stored OHLCV for read-time accuracy stats."""
    if df.empty:
        return df, {"matchedRows": 0, "latestOhlcvDate": "", "source": "predictions.csv"}
    work = df.copy()
    cache: dict[tuple[str, str], tuple[pd.DataFrame, str]] = {}
    matched = 0
    latest_ohlcv_date = ""

    for idx, row in work.iterrows():
        if _as_text(row.get("actual_close")):
            latest_ohlcv_date = max(latest_ohlcv_date, _as_text(row.get("actual_date"))[:10])
            continue
        mk = _prediction_market(row, requested_market)
        if requested_market in MARKETS and mk != requested_market:
            continue
        raw = row.to_dict()
        symbol = data.normalize_symbol(data.first_value(raw, data.SYMBOL_ALIASES + ["ticker", "stock_code"], ""), mk)
        target_date = _to_ts(row.get("target_date") or row.get("actual_date") or row.get("created_at"))
        if not symbol or target_date is None:
            continue
        key = (mk, symbol)
        if key not in cache:
            cache[key] = _ohlcv_with_dates(symbol, mk)
        ohlcv, source = cache[key]
        if ohlcv.empty:
            continue
        future = ohlcv[ohlcv["_date_ts"] >= target_date]
        if future.empty:
            continue
        actual = future.iloc[0]
        actual_date = _row_date_text(actual)[:10]
        actual_open = _num(actual.get("open"))
        actual_high = _num(actual.get("high"))
        actual_low = _num(actual.get("low"))
        actual_close = _num(actual.get("close"))
        if actual_close is None:
            continue

        pred_open_low = data.first_number(raw, ["pred_open_low", "open_low"])
        pred_open_high = data.first_number(raw, ["pred_open_high", "open_high"])
        pred_close_low = data.first_number(raw, ["pred_close_low", "close_low"])
        pred_close_high = data.first_number(raw, ["pred_close_high", "close_high"])
        pred_close_mid = data.first_number(raw, ["pred_close_mid", "expected_price_1d", "take_profit1"])
        prev_close = data.first_number(raw, ["prev_close", "basis_close", "current_price_at_prediction"])
        entry = data.first_number(raw, ["preferred_entry", "entryPrice", "entry_price", "technical_entry", "conservative_entry"])
        stop = data.first_number(raw, ["stop_loss", "stopLoss"])
        tp1 = data.first_number(raw, ["take_profit1", "targetPrice", "target_price"])

        open_in_range = actual_open is not None and pred_open_low is not None and pred_open_high is not None and pred_open_low <= actual_open <= pred_open_high
        close_in_range = pred_close_low is not None and pred_close_high is not None and pred_close_low <= actual_close <= pred_close_high
        entry_touched = entry is not None and actual_low is not None and actual_low <= entry <= (actual_high or entry)
        stop_touched = stop is not None and actual_low is not None and actual_low <= stop
        tp1_touched = tp1 is not None and actual_high is not None and actual_high >= tp1
        direction_hit = False
        if prev_close not in (None, 0) and pred_close_mid is not None:
            direction_hit = (pred_close_mid - prev_close) * (actual_close - prev_close) >= 0

        virtual_return = None
        virtual_label = "미체결"
        exit_price = None
        if entry_touched and entry not in (None, 0):
            if stop_touched:
                exit_price = stop
                virtual_label = "손절"
            elif tp1_touched:
                exit_price = tp1
                virtual_label = "목표"
            else:
                exit_price = actual_close
                virtual_label = "종가청산"
            virtual_return = ((exit_price - entry) / entry) * 100 if exit_price is not None else None

        updates = {
            "actual_source": source or "OHLCV 자동 매칭",
            "actual_date": actual_date,
            "actual_open": actual_open,
            "actual_high": actual_high,
            "actual_low": actual_low,
            "actual_close": actual_close,
            "actual_volume": _num(actual.get("volume")),
            "actual_quality_flag": "OHLCV_AUTO",
            "actual_quality_note": "prediction_accuracy_stats read-time OHLCV match",
            "open_in_range": float(bool(open_in_range)),
            "close_in_range": float(bool(close_in_range)),
            "direction_hit": float(bool(direction_hit)),
            "entry_touched": bool(entry_touched),
            "stop_touched": bool(stop_touched),
            "tp1_touched": bool(tp1_touched),
            "virtual_entry_filled": float(bool(entry_touched)),
            "virtual_exit_price": exit_price if exit_price is not None else "",
            "virtual_result_label": virtual_label,
            "virtual_return_pct": virtual_return if virtual_return is not None else "",
        }
        for col, value in updates.items():
            if col not in work.columns:
                work[col] = ""
            work.at[idx, col] = value
        matched += 1
        latest_ohlcv_date = max(latest_ohlcv_date, actual_date)

    return work, {"matchedRows": matched, "latestOhlcvDate": latest_ohlcv_date, "source": "predictions.csv + OHLCV read-time match"}


@lru_cache(maxsize=256)
def _evaluation_window(symbol: str, market: str, horizon: str) -> tuple[pd.DataFrame, str]:
    df, source = _ohlcv_with_dates(symbol, market)
    if df.empty:
        return df, source
    # Use enough bars to evaluate fill and exit. Keep the window deterministic.
    days = max(1, HORIZON_DAYS.get(horizon, 5))
    return df.tail(days).reset_index(drop=True), source


def _row_date_text(row: pd.Series) -> str:
    return _as_text(row.get("date")) or _as_text(row.get("_date_ts"))


def _calendar_files() -> list[Path]:
    candidates: list[Path] = []
    for base in (data.DATA_DIR, data.REPORT_DIR, data.REPO_ROOT):
        for rel in (
            "calendar/macro_calendar.csv",
            "calendar/earnings_calendar.csv",
            "calendar/ipo_lockup_calendar.csv",
            "calendar/event_calendar.csv",
            "macro_calendar.csv",
            "earnings_calendar.csv",
            "ipo_lockup_calendar.csv",
            "event_calendar.csv",
        ):
            path = base / rel
            if path.exists():
                candidates.append(path)
    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        key = path.resolve().as_posix().lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _calendar_events(market: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    today = pd.Timestamp.today().normalize()
    for path in _calendar_files():
        df = data.read_csv(path)
        if df.empty:
            continue
        for raw in data.dataframe_records(df):
            row_market = _as_text(raw.get("market") or raw.get("시장") or raw.get("country"))
            if row_market and market == "kr" and row_market.lower() not in {"kr", "korea", "국장", "한국", "한국주식"}:
                continue
            if row_market and market == "us" and row_market.lower() not in {"us", "usa", "미장", "미국", "미국주식"}:
                continue
            date_ts = _to_ts(raw.get("date") or raw.get("event_date") or raw.get("발표일") or raw.get("일자"))
            dday = None if date_ts is None else int((date_ts - today).days)
            title = _as_text(raw.get("title") or raw.get("event") or raw.get("name") or raw.get("이벤트") or raw.get("지표"))
            if not title:
                continue
            risk = 12
            text = title + " " + _as_text(raw.get("description") or raw.get("memo") or raw.get("설명"))
            if _has(text, EVENT_KEYWORDS["macro"]):
                risk += 22
            if _has(text, EVENT_KEYWORDS["earnings"]):
                risk += 18
            if _has(text, EVENT_KEYWORDS["theme"]):
                risk += 12
            if dday is not None:
                if -1 <= dday <= 1:
                    risk += 28
                elif 2 <= dday <= 5:
                    risk += 15
                elif dday < -3:
                    risk = max(4, risk - 10)
            badge = "매크로 주의" if _has(text, EVENT_KEYWORDS["macro"]) else "이벤트 주의"
            rows.append({
                "market": market,
                "sourceType": "일정",
                "symbol": _as_text(raw.get("symbol") or raw.get("ticker") or raw.get("종목코드")),
                "name": _as_text(raw.get("name") or raw.get("종목명") or title),
                "date": date_ts.strftime("%Y-%m-%d") if date_ts is not None else _as_text(raw.get("date") or raw.get("event_date")),
                "dday": "" if dday is None else dday,
                "title": title,
                "badges": [badge],
                "badgeText": f"{badge}" + (f" D{dday:+d}" if dday is not None else ""),
                "riskScore": int(data._clamp(risk, 0, 100)),  # type: ignore[attr-defined]
                "action": "신규 진입 기준 강화" if risk >= 35 else "근거 확인 후 유지",
                "source": data.source_label(path),
            })
    return rows


def _mtime_age_hours(path: Path) -> float | None:
    try:
        if not path.exists():
            return None
        return max(0.0, (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600)
    except Exception:
        return None


def _critical_file_status(path: Path, max_age_hours: float | None = None) -> dict[str, Any]:
    exists = path.exists()
    age = _mtime_age_hours(path)
    status = "OK" if exists else "MISSING"
    if exists and max_age_hours is not None and age is not None and age > max_age_hours:
        status = "STALE"
    return {
        "path": data.source_label(path),
        "exists": exists,
        "status": status,
        "ageHours": round(age, 2) if age is not None else "",
        "updatedAt": data.file_mtime(path) if exists else "",
    }


def _fresh_report_source(path: Path, max_age_hours: float = 48) -> str:
    status = _critical_file_status(path, max_age_hours=max_age_hours)
    if status["status"] == "OK" and data.rows_for(path) > 0:
        return data.source_label(path)
    return ""


@lru_cache(maxsize=256)
def _news_context(market: str) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        rows = data.news_rows(market).get("items", [])
    except Exception:
        rows = []
    for row in rows:
        sym = data.normalize_symbol(row.get("symbol", ""), market)
        if sym:
            by_symbol[sym].append(row)
    return by_symbol


@lru_cache(maxsize=256)
def _disclosure_context(market: str) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        rows = data.disclosure_rows(market).get("items", [])
    except Exception:
        rows = []
    for row in rows:
        sym = data.normalize_symbol(row.get("symbol", ""), market)
        if sym:
            by_symbol[sym].append(row)
    return by_symbol


@lru_cache(maxsize=256)
def _candidate_universe(market: str) -> tuple[list[dict[str, Any]], list[str]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    sources: list[str] = []
    preferred = data.preferred_source_type(market)
    prediction_rows, prediction_source, _ = data.read_primary_predictions(market)

    def add_prediction_rows() -> None:
        if not prediction_rows:
            return
        if prediction_source and prediction_source not in sources:
            sources.append(prediction_source)
        for row in prediction_rows:
            sym = _symbol(row, market)
            if not sym:
                continue
            key = f"{market}|{sym}"
            if key in seen:
                continue
            enriched = dict(row)
            enriched["baseBucket"] = "stockapp_predictions" if enriched.get("sourceType") == "stockapp_snapshot" else "github_predictions"
            enriched.setdefault("sourceType", "github_actions")
            enriched.setdefault("sourceFile", prediction_source)
            enriched.setdefault("isFallback", False)
            seen.add(key)
            items.append(enriched)

    def add_candidate_rows() -> int:
        added = 0
        for kind in ("action", "pullback", "flow", "risk"):
            payload = data.candidate_rows(market, kind)
            src = payload.get("source", "")
            if src and src not in sources:
                sources.append(src)
            for item in payload.get("items", []):
                sym = _symbol(item, market)
                if not sym:
                    continue
                key = f"{market}|{sym}"
                enriched = dict(item)
                enriched["baseBucket"] = kind
                if key in seen:
                    continue
                seen.add(key)
                items.append(enriched)
                added += 1
        return added

    if preferred == "stockapp_snapshot":
        if add_candidate_rows() == 0:
            add_prediction_rows()
    else:
        add_prediction_rows()
        add_candidate_rows()
    # Add broader symbol snapshot as discovery fallback so the app is not limited to current watch/action cards.
    try:
        symbol_payload = data.symbols(market)
        if symbol_payload.get("source") and symbol_payload.get("source") not in sources:
            sources.append(symbol_payload.get("source"))
        for item in symbol_payload.get("items", [])[:250]:
            sym = _symbol(item, market)
            key = f"{market}|{sym}"
            if sym and key not in seen:
                seen.add(key)
                enriched = dict(item)
                enriched["baseBucket"] = "discovery"
                items.append(enriched)
    except Exception:
        pass
    return items, sources


def _report_source_date(path: Path, rows: list[dict[str, Any]]) -> str:
    mtime_date = data.file_mtime(path)[:10]
    row_dates = [
        data._normalize_date_text(data.first_value(row, ["sourceDate", "target_date", "targetDate", "actual_date", "data_date", "date", "updated_at", "업데이트시각"], ""))
        for row in rows[:20]
    ]
    row_dates = [date[:10] for date in row_dates if len(date) >= 10]
    return max([mtime_date] + row_dates) if mtime_date or row_dates else ""


def _confidence_card_rows(path: Path, market: str) -> list[dict[str, Any]]:
    rows = data.dataframe_records(data.read_csv(path))
    if not rows:
        return []
    source = data.source_label(path)
    source_date = _report_source_date(path, rows)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not data._market_matches(row, market):  # type: ignore[attr-defined]
            continue
        symbol = data.normalize_symbol(data.first_value(row, ["symbol", "ticker", "종목코드"], ""), market)
        if not symbol:
            continue
        mapped = dict(row)
        mapped["symbol"] = symbol
        mapped.setdefault("name", data.first_value(row, ["name", "companyName", "종목명"], symbol))
        current = data.first_number(row, ["currentPrice", "current_price", "price", "close", "현재가", "last_price"])
        confidence = data.first_number(row, ["confidence", "confidenceScore", "score", "신뢰도점수"])
        entry = data.first_number(row, ["entryPrice", "entry_price", "buyPrice"])
        target = data.first_number(row, ["targetPrice", "target_price"])
        stop = data.first_number(row, ["stopLoss", "stop_loss"])
        if current is not None:
            mapped["current_price"] = current
        if confidence is not None:
            mapped["confidenceScore"] = confidence
            mapped["confidence_score"] = confidence
            mapped["risk_confidence_score"] = confidence
        if entry is not None:
            mapped["entry_price"] = entry
        if target is not None:
            mapped["target_price"] = target
        if stop is not None:
            mapped["stop_loss"] = stop
        mapped["reason"] = data.first_value(row, ["reason", "note", "summary", "핵심근거"], "")
        mapped["nextAction"] = data.first_value(row, ["nextAction", "다음행동"], "")
        mapped["sourceFile"] = source
        mapped["sourceType"] = "github_actions"
        mapped["sourceDate"] = source_date
        mapped["data_status"] = "NORMAL"
        mapped["dataStatus"] = "NORMAL"
        mapped["isFallback"] = False
        mapped["baseBucket"] = "us_confidence_cards"
        out.append(mapped)
    return out


def _rows_from_report_path(path: Path, market: str) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 0 or data.rows_for(path) <= 0:
        return []
    source = data.source_label(path)
    if path.name in {"v93_confidence_cards_us.csv", "v92_confidence_cards_us.csv"}:
        return _confidence_card_rows(path, market)
    rows = [row for row in data.dataframe_records(data.read_csv(path)) if data._market_matches(row, market)]  # type: ignore[attr-defined]
    source_date = _report_source_date(path, rows)
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = data.normalize_symbol(data.first_value(row, data.SYMBOL_ALIASES + ["ticker"], ""), market)
        if not symbol:
            continue
        mapped = dict(row)
        mapped["symbol"] = symbol
        mapped.setdefault("sourceFile", source)
        mapped.setdefault("sourceType", "github_actions")
        mapped.setdefault("sourceDate", source_date)
        mapped.setdefault("data_status", "NORMAL")
        mapped.setdefault("dataStatus", "NORMAL")
        mapped.setdefault("isFallback", False)
        mapped.setdefault("baseBucket", "us_report")
        out.append(mapped)
    return out


def _us_balanced_swing_universe() -> tuple[list[dict[str, Any]], list[str]]:
    mone_path = data.REPORT_DIR / "mone_v36_final_recommendations_us_balanced_swing.csv"
    newer_report_paths = [
        data.REPORT_DIR / "v93_confidence_cards_us.csv",
        data.REPORT_DIR / "v92_confidence_cards_us.csv",
        data.REPORT_DIR / "swing_candidates_us.csv",
    ]
    newest_report_time = max((data.file_mtime(path) for path in newer_report_paths if path.exists()), default="")
    paths = []
    if not newest_report_time or data.file_mtime(mone_path) >= newest_report_time:
        paths.append(mone_path)
    paths.extend(newer_report_paths)
    for path in paths:
        rows = _rows_from_report_path(path, "us")
        if rows:
            return rows, [data.source_label(path)]

    rows, source, _ = data.read_primary_predictions("us")
    return rows, ([source] if source else [])


def _event_badges(item: dict[str, Any], news_rows: list[dict[str, Any]], disclosure_rows: list[dict[str, Any]]) -> tuple[list[str], int, int, str]:
    texts = [
        _as_text(item.get("reason")),
        _as_text(item.get("warning")),
        _as_text(item.get("nextAction")),
        _as_text(item.get("dataStatus")),
        _as_text(_raw(item).get("event_label")),
        _as_text(_raw(item).get("earnings_event_timing")),
        _as_text(_raw(item).get("risk_warning_flags")),
        _as_text(_raw(item).get("disclosure_summary")),
        _as_text(_raw(item).get("sec_title")),
        _as_text(_raw(item).get("dart_report_nm")),
    ]
    texts.extend(_as_text(n.get("title")) + " " + _as_text(n.get("summary")) for n in news_rows[:5])
    texts.extend(_as_text(d.get("title")) for d in disclosure_rows[:5])
    joined = " | ".join(t for t in texts if t)

    badges: list[str] = []
    event_risk = 0
    news_reliability = 50
    if _has(joined, EVENT_KEYWORDS["macro"]):
        badges.append("매크로 주의")
        event_risk += 16
    if _has(joined, EVENT_KEYWORDS["earnings"]):
        badges.append("실적 이벤트")
        event_risk += 12
    if _has(joined, EVENT_KEYWORDS["disclosure_good"]):
        badges.append("신뢰도 높은 공시")
        news_reliability += 16
        event_risk = max(0, event_risk - 4)
    if _has(joined, EVENT_KEYWORDS["disclosure_risk"]):
        badges.append("공시 리스크")
        event_risk += 22
    if _has(joined, EVENT_KEYWORDS["theme"]):
        badges.append("재료 소멸 주의")
        event_risk += 14
    if news_rows:
        news_reliability += min(18, len(news_rows) * 3)
    if disclosure_rows:
        news_reliability += min(18, len(disclosure_rows) * 4)
    if not badges:
        badges.append("이벤트 특이사항 낮음")
    return badges[:4], int(data._clamp(event_risk, 0, 100)), int(data._clamp(news_reliability, 0, 100)), joined


def _surge_label(item: dict[str, Any], df: pd.DataFrame) -> tuple[str, str]:
    if df.empty or len(df) < 5:
        return "판단 대기", "차트/OHLCV 부족"
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < 5:
        return "판단 대기", "종가 데이터 부족"
    last = float(close.iloc[-1])
    prev5 = float(close.iloc[-5]) if close.iloc[-5] else last
    ret5 = (last / prev5 - 1) * 100 if prev5 else 0
    high20 = float(close.tail(20).max()) if len(close) >= 20 else float(close.max())
    near_high = high20 > 0 and last >= high20 * 0.97
    if ret5 >= 12 and near_high:
        return "과열 주의", f"5일 {ret5:.1f}% 상승 · 20일 고점권"
    if ret5 >= 6 and not near_high:
        return "추세 지속 후보", f"5일 {ret5:.1f}% 상승 · 고점 돌파 전"
    if ret5 < -4:
        return "눌림 대기 후보", f"5일 {ret5:.1f}% 조정"
    return "보유 유지 후보", f"5일 {ret5:.1f}% 흐름"


def _entry_gap(current: float | None, entry: float | None) -> float | None:
    if current is None or entry is None or entry <= 0:
        return None
    return (current - entry) / entry


def _mode_allowed(mode: str, horizon: str, scores: dict[str, Any], event_risk: int) -> bool:
    rule = MODE_RULES.get(mode, MODE_RULES["balanced"])
    opp = float(scores.get("opportunityScore") or 0)
    entry = float(scores.get("entryScore") or 0)
    risk = float(scores.get("riskScore") or 0) + event_risk * 0.35
    gap = scores.get("gap")
    if mode == "aggressive" and horizon == "short":
        return opp >= 45 and entry >= 38 and risk <= 82 and (gap is None or gap <= 0.16)
    if horizon == "mid":
        return opp >= rule["min_opportunity"] - 3 and risk <= rule["max_risk"] + 10
    return opp >= rule["min_opportunity"] and entry >= rule["min_entry"] and risk <= rule["max_risk"] and (gap is None or gap <= rule["max_gap"])


def _decision_bucket(mode: str, horizon: str, scores: dict[str, Any], event_risk: int, surge_label: str) -> tuple[str, str, str]:
    opp = float(scores.get("opportunityScore") or 0)
    entry = float(scores.get("entryScore") or 0)
    risk = float(scores.get("riskScore") or 0) + event_risk * 0.35
    gap = scores.get("gap")
    gap_text = "기준가 거리 없음" if gap is None else f"기준가 대비 {gap * 100:+.1f}%"
    if risk >= 70 or surge_label == "과열 주의":
        return "주의", "신규 진입 제한", f"위험 {risk:.1f} · {surge_label} · {gap_text}"
    if _mode_allowed(mode, horizon, scores, event_risk) and entry >= 66:
        return "오늘 진입", "조건부 매수 등록", f"기회 {opp:.1f} / 진입 {entry:.1f} / 위험 {risk:.1f} · {gap_text}"
    if opp >= 65 and risk < 62:
        return "기다림", "기준가 도달 대기", f"좋은 후보이나 {gap_text} · 체결 조건 확인 필요"
    if opp >= 65 and risk < 70:
        return "다음 진입", "다음 장전 재검토", f"기회는 있으나 진입점수 {entry:.1f}로 보수적 확인 필요"
    return "주의", "관망/제외", f"기회 {opp:.1f} / 위험 {risk:.1f}"


def _conditional_execution(item: dict[str, Any], mode: str, horizon: str, df: pd.DataFrame, source: str) -> dict[str, Any]:
    """Operational conditional trade validation.

    Recommended != bought. A trade is filled only when entry_price is touched by
    OHLCV low/high inside the evaluation window. Returns are calculated only for
    filled orders. If both target and stop are touched in the same daily bar, the
    mode setting decides whether to use the conservative stop-first rule.
    """
    settings = data.TRADE_MODE_SETTINGS.get(mode, data.TRADE_MODE_SETTINGS["balanced"])
    entry = _num(item.get("entry"))
    stop = _num(item.get("stop"))
    target = _num(item.get("target"))
    market = item.get("market", "kr")
    hold_days = HORIZON_DAYS[horizon]
    if entry is None or stop is None or target is None:
        return {
            "executionStatus": "검증 대기",
            "executionReason": "진입가/손절가/목표가 부족",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "수익률 제외",
            "ohlcvSource": source,
        }
    if df.empty:
        status = data._execution_status_for_plan(item.get("currentPrice"), entry, mode)  # type: ignore[attr-defined]
        return {
            "executionStatus": status if status != "체결 가능" else "체결 가능(현재가 기준)",
            "executionReason": "OHLCV 부족: 현재가와 기준가 거리만 표시",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "실제 체결 검증 대기",
            "ohlcvSource": source,
        }

    # If caller passed a raw dataframe, normalize dates/window again.
    work = df.copy()
    if "_date_ts" not in work.columns:
        work["_date_ts"] = pd.to_datetime(work.get("date"), errors="coerce").dt.normalize()
    work = work.dropna(subset=["_date_ts"]).sort_values("_date_ts").reset_index(drop=True)
    # 추천일 기준 이후 봉만 사용 (generatedAt 있을 때). 없으면 최신 N봉 fallback.
    _rec_date_str = str(item.get("generatedAt", ""))[:10]
    if _rec_date_str and len(_rec_date_str) == 10:
        try:
            _rec_ts = pd.Timestamp(_rec_date_str)
            work = work[work["_date_ts"] > _rec_ts].head(max(1, hold_days)).reset_index(drop=True)
        except Exception:
            work = work.tail(max(1, hold_days)).reset_index(drop=True)
    else:
        work = work.tail(max(1, hold_days)).reset_index(drop=True)
    if work.empty:
        return {
            "executionStatus": "검증 대기",
            "executionReason": "평가 구간 OHLCV 부족",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "수익률 제외",
            "ohlcvSource": source,
        }

    fill_idx: int | None = None
    fill_row: pd.Series | None = None
    for idx, row in work.iterrows():
        hi = _num(row.get("high")) or _num(row.get("close"))
        lo = _num(row.get("low")) or _num(row.get("close"))
        if hi is None or lo is None:
            continue
        if lo <= entry <= hi:
            fill_idx = int(idx)
            fill_row = row
            break

    latest = work.iloc[-1]
    day_high = _num(latest.get("high")) or _num(latest.get("close"))
    day_low = _num(latest.get("low")) or _num(latest.get("close"))
    if fill_idx is None or fill_row is None:
        return {
            "executionStatus": "미체결",
            "executionReason": f"평가 구간 {hold_days}거래일 내 진입가 미도달",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "미체결 · 수익률 제외",
            "dayHigh": data.format_price(day_high, market) if day_high is not None else "",
            "dayLow": data.format_price(day_low, market) if day_low is not None else "",
            "ohlcvDate": _row_date_text(latest),
            "ohlcvSource": source,
            "evaluationDays": hold_days,
        }

    exit_price = None
    outcome = "보유중"
    exit_date = ""
    target_first = bool(settings.get("target_first"))
    for idx in range(fill_idx, len(work)):
        row = work.iloc[idx]
        hi = _num(row.get("high")) or _num(row.get("close"))
        lo = _num(row.get("low")) or _num(row.get("close"))
        close = _num(row.get("close"))
        if hi is None or lo is None:
            continue
        target_hit = hi >= target
        stop_hit = lo <= stop
        if target_hit and stop_hit:
            exit_price = target if target_first else stop
            outcome = "목표/손절 동시 · 목표 우선" if target_first else "목표/손절 동시 · 보수적 손절 우선"
            exit_date = _row_date_text(row)
            break
        if target_hit:
            exit_price = target
            outcome = "목표 도달"
            exit_date = _row_date_text(row)
            break
        if stop_hit:
            exit_price = stop
            outcome = "손절 도달"
            exit_date = _row_date_text(row)
            break
        if idx == len(work) - 1:
            exit_price = close if close is not None else entry
            outcome = "기간종료" if len(work) >= hold_days else "보유중"
            exit_date = _row_date_text(row)

    if exit_price is None:
        exit_price = entry
    slip = float(settings.get("slippage_pct", 0.002))
    actual_entry = entry * (1 + slip)
    actual_exit = exit_price * (1 - slip)
    pnl = ((actual_exit - actual_entry) / actual_entry) * 100 if actual_entry else None
    return {
        "executionStatus": "체결",
        "executionReason": f"{_row_date_text(fill_row)} 진입가 도달 · {exit_date or _row_date_text(latest)} {outcome}",
        "filled": True,
        "excludedFromReturn": False,
        "entryFilledPrice": data.format_price(entry, market),
        "entryFilledDate": _row_date_text(fill_row),
        "exitStatus": outcome,
        "exitDate": exit_date,
        "exitPrice": data.format_price(exit_price, market),
        "pnlPct": round(pnl, 3) if pnl is not None else "",
        "pnlText": data.format_percent(pnl) if pnl is not None else "수익률 산출 대기",
        "dayHigh": data.format_price(day_high, market) if day_high is not None else "",
        "dayLow": data.format_price(day_low, market) if day_low is not None else "",
        "ohlcvDate": _row_date_text(latest),
        "ohlcvSource": source,
        "evaluationDays": hold_days,
        "rule": "진입가 도달 종목만 체결 · 체결 이후 목표/손절/기간종료 판정 · 미체결 수익률 제외",
    }


@lru_cache(maxsize=256)
def final_recommendations(market: str = "kr", mode: str = "balanced", horizon: str = "swing", limit: int | None = None) -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    mode = mode if mode in MODES else "balanced"
    horizon = horizon if horizon in HORIZONS else "swing"
    max_allowed = min(50, runtime_limits.recommendation_max_symbols())
    requested_limit = runtime_limits.clamp_limit(limit, 20, max_allowed)
    news_map = _news_context(market)
    disc_map = _disclosure_context(market)
    # ── 5차: adaptive weight table 로드 (루프 외부에서 1회) ──────────────────
    try:
        _adaptive_table = _aw.load_adaptive_weights()
    except Exception:
        _adaptive_table = {}
    if market == "us" and mode == "balanced" and horizon == "swing":
        universe, sources = _us_balanced_swing_universe()
    else:
        universe, sources = _candidate_universe(market)
    price_overlay_map = _final_price_overlay_map(market)
    rows: list[dict[str, Any]] = []
    for item in universe:
        sym = _symbol(item, market)
        if not sym:
            continue
        raw = _raw(item)
        merged = dict(raw)
        for key, value in item.items():
            if key not in merged and key != "raw":
                merged[key] = value
        price_overlay = price_overlay_map.get(sym)
        if price_overlay:
            merged = _apply_final_price_overlay(merged, price_overlay)
        scores = data._mone_classifier_scores(merged, market)  # type: ignore[attr-defined]
        normalized = data.normalize_security_row(merged, market)
        if price_overlay:
            normalized = _apply_final_price_overlay(normalized, price_overlay)
        for key, value in item.items():
            normalized.setdefault(key, value)
        chart_overlay = _chart_signal_overlay(sym, market, normalized, mode, horizon)
        normalized.update({
            "symbol": sym,
            "market": market,
            "mode": mode,
            "modeLabel": MODE_LABELS[mode],
            "horizon": horizon,
            "horizonLabel": HORIZON_LABELS[horizon],
            "opportunityScore": scores["opportunityScore"],
            "entryScore": scores["entryScore"],
            "riskScore": scores["riskScore"],
            "rr": round(float(scores.get("rr") or 0), 3),
            "riskReward": f"1:{float(scores.get('rr') or 0):.2f}" if scores.get("rr") else "손익비 없음",
        })
        n_rows = news_map.get(sym, [])
        d_rows = disc_map.get(sym, [])
        badges, event_risk, news_reliability, event_text = _event_badges(normalized, n_rows, d_rows)

        # ── 4차: 이벤트 컨텍스트 연동 ──────────────────────────────────────────
        try:
            evt_ctx = _ec.get_event_context(sym, market)
        except Exception:
            evt_ctx = {
                "newsEventTag": "unknown", "disclosureEventTag": "unknown",
                "earningsEventTag": "unknown", "macroEventTag": "unknown",
                "sectorEventTag": "unknown", "eventRiskScore": 0.0,
                "eventReliabilityScore": 0.0, "eventSummary": "",
                "eventDataSourceType": "unavailable", "eventLearningEligible": False,
            }

        # 이벤트 점수 반영 (eventLearningEligible=True 이고 actual_api/csv 소스일 때만)
        event_score_adj = 0.0
        if evt_ctx.get("eventLearningEligible") and evt_ctx.get("eventDataSourceType") in {"actual_api", "csv"}:
            _n_tag = evt_ctx.get("newsEventTag", "")
            _d_tag = evt_ctx.get("disclosureEventTag", "")
            _e_tag = evt_ctx.get("earningsEventTag", "")
            _m_tag = evt_ctx.get("macroEventTag", "")
            _s_tag = evt_ctx.get("sectorEventTag", "")
            # 음수 조정
            if _n_tag == "negative_news":
                event_score_adj -= 2.5
            if _d_tag == "negative_disclosure":
                event_score_adj -= 4.0
            if _e_tag == "earnings_miss":
                event_score_adj -= 5.0
            elif _e_tag == "guidance_down":
                event_score_adj -= 4.0
            if _m_tag in {"rate_risk", "fomc_risk"}:
                event_score_adj -= 2.5
            elif _m_tag in {"inflation_risk", "volatility_risk"}:
                event_score_adj -= 3.0
            if _s_tag == "sector_weak":
                event_score_adj -= 2.0
            # 양수 조정
            if _n_tag == "positive_news":
                event_score_adj += 1.5
            if _d_tag == "positive_disclosure":
                event_score_adj += 1.5
            if _e_tag == "earnings_beat":
                event_score_adj += 2.0
            elif _e_tag == "guidance_up":
                event_score_adj += 1.5
            if _s_tag == "sector_strong":
                event_score_adj += 1.0
        # 이벤트 하나만으로 추천 안 뒤집음: ±8 상한
        event_score_adj = float(data._clamp(event_score_adj, -8.0, 8.0))  # type: ignore[attr-defined]
        # ────────────────────────────────────────────────────────────────────

        df, ohlcv_source = _evaluation_window(sym, market, horizon)
        surge, surge_reason = _surge_label(normalized, df)
        bucket, buy_timing, decision_reason = _decision_bucket(mode, horizon, scores, event_risk, surge)
        allowed = _mode_allowed(mode, horizon, scores, event_risk)
        execution = _conditional_execution(normalized, mode, horizon, df, ohlcv_source)
        holding_decision = "보유 유지" if surge in {"추세 지속 후보", "보유 유지 후보"} and event_risk < 55 else "비중 축소/손절선 확인" if event_risk >= 55 else "보유자는 목표가·손절가 대응"
        sell_timing = "목표가 도달 시 분할익절 / 손절가 이탈 시 종료 / 보유기간 종료 시 재검토"
        base_rank = float(scores["opportunityScore"]) * 0.45 + float(scores["entryScore"]) * 0.35 - (float(scores["riskScore"]) + event_risk * 0.4) * 0.25 + news_reliability * 0.08
        if bucket == "오늘 진입":
            base_rank += 8
        chart_adj = float(chart_overlay.get("chartScoreAdjustment") or 0)
        base_rank += chart_adj
        base_rank += event_score_adj

        # ── 5차: adaptive score 보정 ─────────────────────────────────────────
        # chart_overlay에 usedSignals를 담아 넘길 수 있도록 임시 dict 구성
        _pre_row: dict[str, Any] = {
            **normalized,
            **chart_overlay,
            "newsEventTag": evt_ctx.get("newsEventTag", "unknown"),
            "disclosureEventTag": evt_ctx.get("disclosureEventTag", "unknown"),
            "earningsEventTag": evt_ctx.get("earningsEventTag", "unknown"),
            "macroEventTag": evt_ctx.get("macroEventTag", "unknown"),
            "sectorEventTag": evt_ctx.get("sectorEventTag", "unknown"),
        }
        try:
            _adaptive_row = _aw.apply_adaptive_adjustment(_pre_row, _adaptive_table)
        except Exception:
            _adaptive_row = {
                **_pre_row,
                "adaptiveScoreUsed": False,
                "adaptiveScoreAdjustment": 0.0,
                "adaptiveScoreSummary": "",
                "adaptiveSignalBreakdown": {},
                "adaptiveConfidence": 0.0,
                "adaptiveLearningStatus": "DISABLED",
            }
        adaptive_adj = float(_adaptive_row.get("adaptiveScoreAdjustment") or 0.0)
        rank_score = base_rank + adaptive_adj
        # ────────────────────────────────────────────────────────────────────

        row = {
            **_adaptive_row,
            "decisionBucket": bucket,
            "buyTiming": buy_timing,
            "sellTiming": sell_timing,
            "newEntryDecision": "조건부 진입" if bucket == "오늘 진입" else "대기" if bucket in {"기다림", "다음 진입"} else "신규 진입 제한",
            "holderDecision": holding_decision,
            "decisionReason": decision_reason,
            "eventBadges": badges,
            "eventBadgesText": " · ".join(badges),
            "eventRiskScore": event_risk,
            "newsReliabilityScore": news_reliability,
            "surgeLabel": surge,
            "surgeReason": surge_reason,
            "finalRankScore": round(data._clamp(rank_score, 0, 100), 1),  # type: ignore[attr-defined]
            "recommended": bool(allowed and bucket != "주의"),
            "probabilityText": normalized.get(HORIZON_PROB_FIELD[horizon], "확률 산출 필요"),
            "expectedPriceText": normalized.get(HORIZON_PRICE_FIELD[horizon], "예상가 산출 필요"),
            "execution": execution,
            "executionStatus": execution.get("executionStatus", "검증 대기"),
            "exitStatus": execution.get("exitStatus", ""),
            "pnlText": execution.get("pnlText", ""),
            "sourceBucket": item.get("baseBucket", item.get("category", "")),
            "newsCount": len(n_rows),
            "disclosureCount": len(d_rows),
            "eventContext": event_text[:300],
            # ── 4차 이벤트 필드 ──
            "eventContextUsed": evt_ctx.get("eventLearningEligible", False),
            "newsEventTag": evt_ctx.get("newsEventTag", "unknown"),
            "disclosureEventTag": evt_ctx.get("disclosureEventTag", "unknown"),
            "earningsEventTag": evt_ctx.get("earningsEventTag", "unknown"),
            "macroEventTag": evt_ctx.get("macroEventTag", "unknown"),
            "sectorEventTag": evt_ctx.get("sectorEventTag", "unknown"),
            "eventReliabilityScore": evt_ctx.get("eventReliabilityScore", 0.0),
            "eventSummary": evt_ctx.get("eventSummary", ""),
            "eventDataSourceType": evt_ctx.get("eventDataSourceType", "unavailable"),
            "eventScoreAdjustment": round(event_score_adj, 2),
        }
        # ── 4차: postmortem 저장 (실패 케이스) ──────────────────────────────
        try:
            if execution.get("filled"):
                from app.services import postmortem as _pm
                _pm.save_postmortem(row)
        except Exception:
            pass
        # ───────────────────────────────────────────────────────────────────
        rows.append(row)
    rows.sort(key=lambda r: (bool(r.get("recommended")), float(r.get("finalRankScore") or 0)), reverse=True)
    selected = rows[:requested_limit]

    # ── 이름 보정: name == symbol(숫자) 인 경우 sector_map에서 실제 이름 조회 ──
    try:
        import csv as _csv
        _sector_name_map: dict[str, str] = {}
        _sector_path = data.REPO_ROOT / "data" / f"sector_map_{market}.csv"
        if _sector_path.exists():
            with _sector_path.open("r", encoding="utf-8-sig") as _sf:
                for _sr in _csv.DictReader(_sf):
                    _sym = str(_sr.get("symbol", "")).strip()
                    _nm = str(_sr.get("name", "")).strip()
                    if _sym and _nm:
                        _sector_name_map[_sym] = _nm
        for _row in selected:
            _nm = str(_row.get("name", "")).strip()
            _sym = str(_row.get("symbol", "")).strip()
            # name이 심볼과 동일(숫자코드) 이거나 비어있는 경우만 보정
            if (_nm == _sym or not _nm) and _sym in _sector_name_map:
                _row["name"] = _sector_name_map[_sym]
    except Exception:
        pass

    limit_meta = runtime_limits.limit_meta(
        total_count=len(universe),
        processed_count=len(rows),
        limit=requested_limit,
        max_allowed=max_allowed,
        dataSourceType="mixed",
    )
    return {
        "status": "OK",
        "market": market,
        "mode": mode,
        "modeLabel": MODE_LABELS[mode],
        "horizon": horizon,
        "horizonLabel": HORIZON_LABELS[horizon],
        "count": len(selected),
        "universeCount": len(universe),
        **limit_meta,
        "sources": sources[:12],
        "rule": "국장/미장 후보군을 StockApp raw·MONE reports·CSV/OHLCV·뉴스·공시로 합친 뒤 MONE 점수로 재분류",
        "items": selected,
        "generatedAt": _now(),
    }


def _recommendation_detail_score(row: dict[str, Any]) -> float:
    for key in ("finalRankScore", "finalScore", "opportunityScore", "probability", "entryScore"):
        value = _num(row.get(key))
        if value is not None:
            return float(value)
    return 0.0


def _recommendation_detail_rows(market: str, symbol: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    target = data.normalize_symbol(symbol, market)
    if not target:
        return rows
    for mode in MODES:
        for horizon in HORIZONS:
            for kind in ("recommendations", "trade_validation"):
                path = data.REPORT_DIR / f"mone_v36_final_{kind}_{market}_{mode}_{horizon}.csv"
                if not path.exists() or path.stat().st_size <= 0:
                    continue
                for raw in data.dataframe_records(data.read_csv(path)):
                    row_symbol = data.normalize_symbol(data.first_value(raw, data.SYMBOL_ALIASES + ["ticker", "code", "stock_code"], ""), market)
                    if row_symbol != target:
                        continue
                    normalized = data.normalize_security_row(raw, market)
                    merged = {**normalized, **raw}
                    current_price = _num(merged.get("currentPrice") or merged.get("current_price") or merged.get("close"))
                    if current_price is not None and current_price > 0:
                        merged["basePrice"] = current_price
                        merged["base"] = current_price
                        merged["currentPrice"] = current_price
                        merged.setdefault("currentPriceText", data.format_price(current_price, market))
                    for key in ("entry", "stop", "target"):
                        value = _num(merged.get(key))
                        if value is not None and value > 0:
                            merged[key] = value
                    expected = _num(merged.get("expectedPrice") or merged.get("expected") or merged.get(HORIZON_PRICE_FIELD[horizon]))
                    if expected is not None and expected > 0:
                        merged["expectedPrice"] = expected
                        merged["expected"] = expected
                        merged.setdefault("expectedPriceText", data.format_price(expected, market))
                    merged.update({
                        "symbol": target,
                        "market": market,
                        "mode": mode,
                        "modeLabel": MODE_LABELS[mode],
                        "horizon": horizon,
                        "horizonLabel": HORIZON_LABELS[horizon],
                        "sourceFile": path.name,
                        "sourceKind": kind,
                        "detailScore": _recommendation_detail_score(merged),
                    })
                    rows.append(merged)
    for path_name in ("virtual_validation_results.csv", "virtual_prediction_ledger.csv"):
        path = data.REPORT_DIR / path_name
        if not path.exists() or path.stat().st_size <= 0:
            continue
        for raw in data.dataframe_records(data.read_csv(path)):
            row_market = "us" if str(raw.get("market", "")).lower() == "us" else "kr" if str(raw.get("market", "")).lower() == "kr" else ""
            if row_market != market:
                continue
            row_symbol = data.normalize_symbol(data.first_value(raw, data.SYMBOL_ALIASES + ["ticker", "code", "stock_code"], ""), market)
            if row_symbol != target:
                continue
            normalized = data.normalize_security_row(raw, market)
            merged = {**normalized, **raw}
            mode = str(merged.get("mode") or "balanced").lower()
            horizon = str(merged.get("horizon") or "swing").lower()
            if mode not in MODES:
                mode = "balanced"
            if horizon not in HORIZONS:
                horizon = "swing"
            for src_key, dst_key in (("entryPrice", "entry"), ("stopPrice", "stop"), ("targetPrice", "target"), ("expectedPrice", "expectedPrice")):
                value = _num(merged.get(src_key))
                if value is not None and value > 0:
                    merged.setdefault(dst_key, value)
            expected = _num(merged.get("expectedPrice") or merged.get("expected"))
            if expected is not None and expected > 0:
                merged.setdefault("expected", expected)
                merged.setdefault("expectedPriceText", data.format_price(expected, market))
            merged.update({
                "symbol": target,
                "market": market,
                "mode": mode,
                "modeLabel": MODE_LABELS[mode],
                "horizon": horizon,
                "horizonLabel": HORIZON_LABELS[horizon],
                "sourceFile": path.name,
                "sourceKind": "virtual_prediction",
                "detailScore": _recommendation_detail_score(merged) - 5,
            })
            rows.append(merged)
    rows.sort(key=lambda r: (float(r.get("detailScore") or 0), str(r.get("generatedAt") or "")), reverse=True)
    return rows


def recommendation_detail(market: str = "kr", symbol: str = "") -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    target = data.normalize_symbol(symbol, market)
    rows = _recommendation_detail_rows(market, target)
    if not rows:
        return {
            "status": "NO_DATA",
            "market": market,
            "symbol": target,
            "count": 0,
            "items": [],
            "item": None,
            "generatedAt": _now(),
        }
    best = rows[0]
    return {
        "status": "OK",
        "market": market,
        "symbol": target,
        "count": len(rows),
        "items": rows[:9],
        "item": best,
        "source": best.get("sourceFile", ""),
        "generatedAt": _now(),
    }


def conditional_execution_summary(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    payload = final_recommendations(market, mode, horizon, limit=int(MODE_RULES.get(mode, MODE_RULES["balanced"])["max_items"]))
    items = payload.get("items", [])
    filled = [r for r in items if r.get("execution", {}).get("filled")]
    unfilled = [r for r in items if not r.get("execution", {}).get("filled")]
    pnl_values = [_num(r.get("execution", {}).get("pnlPct")) for r in filled]
    pnl_values = [v for v in pnl_values if v is not None]
    avg = sum(pnl_values) / len(pnl_values) if pnl_values else None
    return {
        "status": "OK",
        "market": payload["market"],
        "mode": payload["mode"],
        "modeLabel": payload["modeLabel"],
        "horizon": payload["horizon"],
        "horizonLabel": payload["horizonLabel"],
        "conditionalOrders": len(items),
        "filledCount": len(filled),
        "unfilledCount": len(unfilled),
        "filledReturnAvgPct": round(avg, 3) if avg is not None else "",
        "filledReturnAvgText": data.format_percent(avg) if avg is not None else "체결 종목 수익률 없음",
        "rule": "추천됨 ≠ 매수됨 · 진입가가 당일 고가/저가 범위에 들어온 종목만 체결 · 미체결은 수익률 계산 제외",
        "items": items,
        "generatedAt": _now(),
    }


def _prediction_rows(market: str) -> list[dict[str, Any]]:
    rows, _, _ = data.read_primary_predictions(market)
    if rows:
        return rows
    rows = data.read_predictions_csv(market)
    if rows:
        return rows
    return data.dataframe_records(data.read_csv(data.REPO_ROOT / "predictions.csv"))


def prediction_validation(market: str = "kr", limit: int = 250) -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    rows = []
    for row in _prediction_rows(market):
        if not data._market_matches(row, market):  # type: ignore[attr-defined]
            continue
        sym = data.normalize_symbol(data.first_value(row, data.SYMBOL_ALIASES + ["ticker", "stock_code"], ""), market)
        if not sym:
            continue
        pred_date = _prediction_date(row)
        prev_close = data.first_number(row, ["prev_close", "basis_close", "current_price_at_prediction", "close_at_prediction"])
        if prev_close is None:
            df_for_prev, _ = _ohlcv_with_dates(sym, market)
            if pred_date is not None and not df_for_prev.empty:
                before = df_for_prev[df_for_prev["_date_ts"] <= pred_date]
                if not before.empty:
                    prev_close = _num(before.iloc[-1].get("close"))
        pred = {
            "D+1": data.first_number(row, ["pred_close_mid", "expected_price_1d", "predicted_price_1d", "target_price_1d", "1일예상가"]),
            "D+5": data.first_number(row, ["expected_price_5d", "predicted_price_5d", "target_price_5d", "take_profit1", "5일예상가"]),
            "D+20": data.first_number(row, ["expected_price_20d", "predicted_price_20d", "midterm_expected_price", "take_profit2", "20일예상가"]),
        }
        actual = {
            "D+1": data.first_number(row, ["actual_close", "actual_1d_close"]),
            "D+5": data.first_number(row, ["actual_5d_close"]),
            "D+20": data.first_number(row, ["actual_20d_close"]),
        }
        offsets = {"D+1": 1, "D+5": 5, "D+20": 20}
        actual_dates: dict[str, str] = {"D+1": "", "D+5": "", "D+20": ""}
        actual_sources: dict[str, str] = {"D+1": "", "D+5": "", "D+20": ""}
        for key, offset in offsets.items():
            if actual[key] is None:
                close, source, date_or_reason = _actual_close_after(sym, market, pred_date, offset)
                actual[key] = close
                actual_sources[key] = source
                actual_dates[key] = date_or_reason
            else:
                actual_sources[key] = "predictions.csv actual column"
                actual_dates[key] = data.first_value(row, ["actual_date", "target_date"], "")
        validations = {}
        for key in ("D+1", "D+5", "D+20"):
            pval = pred[key]
            aval = actual[key]
            error = ((aval - pval) / pval * 100) if pval and aval else None
            direction_hit = "검증 대기"
            if prev_close and pval and aval:
                direction_hit = "적중" if (pval - prev_close) * (aval - prev_close) >= 0 else "불일치"
            range_hit = "검증 대기"
            if error is not None:
                tolerance = 2.5 if key == "D+1" else 5.0 if key == "D+5" else 9.0
                range_hit = "허용범위 적중" if abs(error) <= tolerance else "허용범위 이탈"
            validations[key] = {
                "expectedPrice": data.format_price(pval, market) if pval else "예상가 없음",
                "actualClose": data.format_price(aval, market) if aval else "실제 종가 대기",
                "actualDate": actual_dates.get(key, ""),
                "actualSource": actual_sources.get(key, ""),
                "errorPct": round(error, 3) if error is not None else "",
                "errorText": data.format_percent(error) if error is not None else "오차율 대기",
                "directionHit": direction_hit,
                "rangeHit": range_hit,
            }
        rows.append({
            "market": market,
            "symbol": sym,
            "name": data.first_value(row, data.NAME_ALIASES + ["stock_name"], sym),
            "predictionDate": pred_date.strftime("%Y-%m-%d") if pred_date is not None else data.first_value(row, ["created_at", "run_time_kst", "prediction_at"], ""),
            "targetDate": data.first_value(row, ["target_date", "actual_date"], ""),
            "sessionLabel": data.first_value(row, ["session_label", "session_type"], ""),
            "D+1": validations["D+1"],
            "D+5": validations["D+5"],
            "D+20": validations["D+20"],
            "openErrorPct": data.first_value(row, ["open_error_pct"], ""),
            "closeErrorPct": data.first_value(row, ["close_error_pct"], ""),
            "predictionResult": data.first_value(row, ["prediction_result", "direction_hit"], "검증 대기"),
        })
    rows = sorted(rows, key=lambda r: str(r.get("predictionDate", "")), reverse=True)[:limit]
    ready = sum(1 for r in rows if r.get("D+1", {}).get("actualClose") != "실제 종가 대기")
    return {
        "status": "OK",
        "version": OPERATIONAL_VERSION,
        "market": market,
        "count": len(rows),
        "validatedD1Count": ready,
        "source": "predictions.csv + OHLCV 자동 매칭",
        "rule": "예측 검증은 예측일 이후 거래일 기준 D+1/D+5/D+20 종가를 OHLCV에서 자동 매칭해 오차·방향성을 검증",
        "items": rows,
    }


def trade_validation(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    summary = conditional_execution_summary(market, mode, horizon)
    items = []
    for row in summary.get("items", []):
        ex = row.get("execution", {})
        items.append({
            "market": row.get("market"),
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "mode": row.get("mode"),
            "horizon": row.get("horizon"),
            "entry": row.get("entryText"),
            "stop": row.get("stopText"),
            "target": row.get("targetText"),
            "executionStatus": ex.get("executionStatus", row.get("executionStatus")),
            "executionReason": ex.get("executionReason", ""),
            "exitStatus": ex.get("exitStatus", ""),
            "pnlText": ex.get("pnlText", ""),
            "excludedFromReturn": ex.get("excludedFromReturn", True),
            "ohlcvDate": ex.get("ohlcvDate", ""),
            "ohlcvSource": ex.get("ohlcvSource", ""),
        })
    return {**summary, "items": items, "rule": "가상운용 검증은 진입가 도달/체결/손절/목표/기간종료만 검증하며 예측 정확도와 분리"}


def macro_event_risk(market: str = "kr") -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    events: list[dict[str, Any]] = _calendar_events(market)
    for payload_name, getter in (("뉴스", data.news_rows), ("공시", data.disclosure_rows)):
        try:
            payload = getter(market)
            source = payload.get("source") or " · ".join(payload.get("sources", []))
            for row in payload.get("items", [])[:200]:
                text = f"{row.get('title','')} {row.get('summary','')} {row.get('status','')}"
                badges = []
                risk = 0
                if _has(text, EVENT_KEYWORDS["macro"]):
                    badges.append("매크로 주의")
                    risk += 20
                if _has(text, EVENT_KEYWORDS["earnings"]):
                    badges.append("실적 이벤트")
                    risk += 15
                if _has(text, EVENT_KEYWORDS["disclosure_risk"]):
                    badges.append("공시 리스크")
                    risk += 25
                if _has(text, EVENT_KEYWORDS["disclosure_good"]):
                    badges.append("신뢰도 높은 공시")
                    risk = max(0, risk - 8)
                if _has(text, EVENT_KEYWORDS["theme"]):
                    badges.append("재료 소멸 주의")
                    risk += 16
                if badges:
                    events.append({
                        "market": market,
                        "sourceType": payload_name,
                        "symbol": row.get("symbol", ""),
                        "name": row.get("name", ""),
                        "date": row.get("publishedAt") or row.get("date") or "",
                        "title": row.get("title", ""),
                        "badges": badges,
                        "badgeText": " · ".join(badges),
                        "riskScore": int(data._clamp(risk, 0, 100)),  # type: ignore[attr-defined]
                        "action": "신규 진입 기준 강화" if risk >= 20 else "근거 확인 후 유지",
                        "source": source,
                    })
        except Exception:
            continue
    if not events:
        events.append({
            "market": market,
            "sourceType": "시스템",
            "symbol": "",
            "name": "시장 이벤트",
            "date": "",
            "title": "저장된 뉴스/공시에서 FOMC·CPI·실적·IPO 등 이벤트 키워드가 감지되지 않음",
            "badges": ["일정 데이터 연결 대기"],
            "badgeText": "일정 데이터 연결 대기",
            "riskScore": 0,
            "action": "외부 일정 CSV/API 연결 시 자동 반영",
            "source": "news/disclosures fallback",
        })
    return {"status": "OK", "market": market, "version": OPERATIONAL_VERSION, "calendarFiles": [data.source_label(p) for p in _calendar_files()], "count": len(events), "items": sorted(events, key=lambda e: int(e.get("riskScore", 0)), reverse=True)[:80]}


def portfolio_risk(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    rec = final_recommendations(market, mode, horizon, limit=20)
    items = rec.get("items", [])
    sectors = Counter(_as_text(_raw(r).get("sector") or r.get("sector") or "섹터 미분류") or "섹터 미분류" for r in items)
    filled = [r for r in items if r.get("execution", {}).get("filled")]
    risk_scores = [_num(r.get("riskScore")) or 0 for r in items]
    event_scores = [_num(r.get("eventRiskScore")) or 0 for r in items]
    warnings = []
    if sectors:
        top_sector, top_count = sectors.most_common(1)[0]
        if len(items) and top_count / len(items) >= 0.45:
            warnings.append(f"{top_sector} 비중 과다: {top_count}/{len(items)}")
    if sum(1 for r in items if r.get("market") == "kr") and sum(1 for r in items if r.get("market") == "us"):
        market_mix = "국장/미장 혼합"
    else:
        market_mix = "국장 단일" if rec.get("market") == "kr" else "미장 단일"
    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0
    avg_event = sum(event_scores) / len(event_scores) if event_scores else 0
    if avg_risk >= 55:
        warnings.append("후보 평균 위험 점수 높음")
    if avg_event >= 25:
        warnings.append("이벤트/매크로 리스크 확인 필요")
    if not warnings:
        warnings.append("쏠림 경고 낮음")
    return {
        "status": "OK",
        "market": rec.get("market"),
        "mode": mode,
        "horizon": horizon,
        "candidateCount": len(items),
        "filledCount": len(filled),
        "sectorDistribution": dict(sectors),
        "topSector": sectors.most_common(1)[0][0] if sectors else "섹터 없음",
        "marketMix": market_mix,
        "averageRiskScore": round(avg_risk, 1),
        "averageEventRiskScore": round(avg_event, 1),
        "cashPolicy": "보수 3종목 / 균형 5종목 / 공격 8~12종목 이내, 동일 섹터 과다 시 진입 수 제한",
        "warnings": warnings,
        "items": [{"symbol": r.get("symbol"), "name": r.get("name"), "sector": _raw(r).get("sector", "섹터 미분류"), "riskScore": r.get("riskScore"), "eventRiskScore": r.get("eventRiskScore"), "decision": r.get("decisionBucket")} for r in items],
    }


def data_center(market: str = "kr") -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    status = data.data_source_status().get("items", [])
    github = data.github_actions_status()
    bridge = data.stockapp_bridge_status()
    files = data.status_files().get("items", [])
    critical_paths = [
        data.REPORT_DIR / f"mone_v36_final_recommendations_{market}_balanced_swing.csv",
        data.REPORT_DIR / f"mone_v36_final_trade_validation_{market}_balanced_swing.csv",
        data.REPORT_DIR / f"mone_v36_final_prediction_validation_{market}.csv",
        data.REPORT_DIR / f"mone_v36_final_macro_events_{market}.csv",
        data.REPORT_DIR / f"mone_v36_final_data_center_{market}.csv",
        data.REPO_ROOT / "predictions.csv",
    ]
    critical = [_critical_file_status(path, max_age_hours=48 if "final" in path.name else 96) for path in critical_paths]
    missing = [x for x in critical if x["status"] == "MISSING"]
    stale = [x for x in critical if x["status"] == "STALE"]
    def find_status(key: str) -> str:
        row = next((x for x in status if x.get("key") == key), {})
        return row.get("status", "MISSING")
    chart_status = "MISSING"
    try:
        for item in data.symbols(market).get("items", [])[:30]:
            sym = data.normalize_symbol(item.get("symbol", ""), market)
            if sym:
                chart_df, _ = data._load_ohlcv(sym, market)  # type: ignore[attr-defined]
                if not chart_df.empty:
                    chart_status = "OK"
                    break
    except Exception:
        chart_status = find_status("chart")
    disclosure_payload = data.disclosure_rows(market)
    disclosure_status = "OK" if disclosure_payload.get("count", 0) else "MISSING"
    company_payload = data.company_analysis(market)
    company_status = company_payload.get("status") or ("OK" if company_payload.get("count", 0) else "MISSING")
    company_quality = company_payload.get("financialCompleteness", {}) if isinstance(company_payload, dict) else {}
    report_sources: list[str] = []
    report_rows = 0
    for name in (
        "operational_readiness_{market}.csv",
        "operation_health_{market}.csv",
        "latest_{market}_performance_summary.csv",
        "prediction_integrity_status.csv",
    ):
        rows, src = data.stockapp_report_rows(market, name)
        if src:
            report_sources.append(src)
            report_rows += len(rows)
    if market == "us":
        for path in (
            data.REPORT_DIR / "v93_confidence_cards_us.csv",
            data.REPORT_DIR / "v93_operational_dashboard_us.csv",
            data.REPORT_DIR / "v92_confidence_cards_us.csv",
            data.REPORT_DIR / "v92_operational_dashboard_us.csv",
        ):
            src = _fresh_report_source(path)
            if src and src not in report_sources:
                report_sources.append(src)
                report_rows += data.rows_for(path)

    # Split the old one-word report state into the active report phase.
    # A report folder can contain rows while the active intraday/close/premarket
    # data for the current market phase is stale.
    try:
        phase = data._market_price_phase(market)  # type: ignore[attr-defined]
    except Exception:
        phase = {"phase": "unknown", "label": "가격 기준 확인"}
    try:
        premarket_payload = data.premarket_report(market)
    except Exception:
        premarket_payload = {"status": "MISSING", "count": 0, "missingReason": "장전 리포트 확인 실패"}
    try:
        intraday_payload = data.intraday_report(market)
    except Exception:
        intraday_payload = {"status": "MISSING", "count": 0, "missingReason": "장중 리포트 확인 실패"}
    try:
        closing_payload = data.closing_report(market)
        if not closing_payload.get("status"):
            closing_payload["status"] = "OK" if closing_payload.get("count", 0) else "MISSING"
    except Exception:
        closing_payload = {"status": "MISSING", "count": 0, "missingReason": "장마감 리포트 확인 실패"}

    phase_key = str(phase.get("phase", ""))
    if phase_key.endswith("intraday"):
        active_report_payload = intraday_payload
    elif phase_key.endswith("after_close"):
        active_report_payload = closing_payload
    else:
        active_report_payload = premarket_payload
    report_status = str(active_report_payload.get("status") or "MISSING").upper()
    if report_status not in {"OK", "STALE", "MISSING", "PARTIAL"}:
        report_status = "PARTIAL" if active_report_payload.get("count", 0) else "MISSING"
    latest_automation_run = github.get("latestScheduled") or github.get("latestWorkflowDispatch") or github.get("latestAutomationRun")
    github_schedule_status = "OK" if github.get("latestScheduled") else "SCHEDULE_MISSING"
    automation_mode = "github_schedule" if github.get("latestScheduled") else ("external_workflow_dispatch" if github.get("latestWorkflowDispatch") else github.get("automationMode", "unknown"))
    if latest_automation_run and latest_automation_run.get("conclusion") == "success":
        automation_status = "OK"
        automation_label = "자동 실행 정상"
    elif latest_automation_run:
        automation_status = "PARTIAL"
        automation_label = "자동 실행 확인 필요"
    else:
        automation_status = "MISSING"
        automation_label = "자동 실행 기록 없음"
    prediction_payload = data.predictions(market)
    prediction_items = prediction_payload.get("items", [])
    item_statuses = {str(item.get("dataStatus", "")) for item in prediction_items}
    if not prediction_items:
        data_status = "NO_DATA"
    elif "STALE" in item_statuses:
        data_status = "STALE"
    elif "NORMAL" in item_statuses:
        data_status = "NORMAL"
    else:
        data_status = "PARTIAL"
    ok_points = 0
    ok_points += 20 if automation_status == "OK" else 10
    ok_points += 20 if bridge.get("status") in {"OK", "NOT_FOUND"} else 0
    ok_points += 20 if chart_status == "OK" else 0
    ok_points += 15 if disclosure_status == "OK" else 0
    ok_points += 25 if report_status == "OK" else max(0, 25 - len(missing) * 8 - len(stale) * 5)
    readiness = int(data._clamp(ok_points, 0, 100))  # type: ignore[attr-defined]
    if readiness >= 85:
        readiness_label = "운영 가능"
    elif readiness >= 65:
        readiness_label = "부분 운영 가능"
    else:
        readiness_label = "점검 필요"
    warnings = []
    if missing:
        warnings.append(f"핵심 산출물 누락 {len(missing)}개")
    if stale:
        warnings.append(f"오래된 산출물 {len(stale)}개")
    if chart_status != "OK":
        warnings.append("차트/OHLCV 데이터 부족")
    if disclosure_status != "OK":
        warnings.append("공시 데이터 부족")
    if company_status != "OK":
        warnings.append("기업분석 데이터 부족")
    if automation_status != "OK":
        warnings.append("자동 실행 기록 확인 필요")
    if not warnings:
        warnings.append("핵심 데이터 상태 양호")
    return {
        "status": data_status,
        "version": OPERATIONAL_VERSION,
        "market": market,
        "updatedAt": data.latest_updated_at(),
        "readinessScore": readiness,
        "readinessLabel": readiness_label,
        "warnings": warnings,
        "todayDataSource": "StockApp snapshot" if data.preferred_source_type(market) == "stockapp_snapshot" else "GitHub Actions",
        "githubStatus": github.get("status", "UNKNOWN"),
        "githubScheduleStatus": github_schedule_status,
        "automationStatus": automation_status,
        "automationLabel": automation_label,
        "automationMode": automation_mode,
        "latestAutomationRunAt": (latest_automation_run or {}).get("updated_at") or (latest_automation_run or {}).get("created_at", ""),
        "latestAutomationEvent": (latest_automation_run or {}).get("event", ""),
        "latestAutomationConclusion": (latest_automation_run or {}).get("conclusion", ""),
        "stockAppBridgeStatus": bridge.get("status", "NOT_FOUND"),
        "chartData": chart_status,
        "flowData": find_status("flow"),
        "orderbookData": find_status("orderbook"),
        "disclosureData": disclosure_status,
        "reportData": report_status,
        "premarketData": premarket_payload.get("status", "MISSING"),
        "intradayData": intraday_payload.get("status", "MISSING"),
        "closingData": closing_payload.get("status", "MISSING"),
        "activeReportPhase": phase.get("phase", "unknown"),
        "activeReportLabel": phase.get("label", ""),
        "activeReportMissingReason": active_report_payload.get("missingReason", ""),
        "companyData": company_status,
        "companyQuality": company_quality,
        "criticalFiles": critical,
        "summary": [
            {"label": "운영 준비도", "value": f"{readiness}점 · {readiness_label}", "note": "핵심 파일/차트/공시/GitHub/StockApp 상태 종합"},
            {"label": "오늘 데이터 출처", "value": "StockApp snapshot" if data.preferred_source_type(market) == "stockapp_snapshot" else "GitHub Actions", "note": "handoff 기준 source policy 반영"},
            {"label": "자동 실행 상태", "value": automation_label, "note": f"mode={automation_mode} · event={(latest_automation_run or {}).get('event', '없음')}"},
            {"label": "마지막 업데이트", "value": data.latest_updated_at(), "note": "reports/data 기준"},
            {"label": "차트 데이터", "value": chart_status, "note": "OHLCV/기술지표/체결 검증"},
            {"label": "공시 데이터", "value": disclosure_status, "note": "DART/SEC CSV 감지"},
            {"label": "리포트 데이터", "value": report_status, "note": f"active={phase.get('phase', 'unknown')} · pre={premarket_payload.get('status', 'MISSING')} · intra={intraday_payload.get('status', 'MISSING')} · close={closing_payload.get('status', 'MISSING')}"},
            {"label": "기업분석 데이터", "value": company_status, "note": company_quality.get("note") or "필요 파일: kr_financial_metrics/kr_market_cap 또는 SEC/US financial"},
        ],
        "raw": {"dataSources": status, "github": github, "stockapp": bridge},
    }


def discovery(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    rec = final_recommendations(market, mode, horizon, limit=80)
    buckets = defaultdict(list)
    for r in rec.get("items", []):
        label = "저평가 성장" if "저평가" in _as_text(r.get("eventContext")) or "valuation" in _as_text(r.get("scores")) else None
        if not label and "수급" in _as_text(r.get("sourceBucket")) + _as_text(r.get("decisionReason")):
            label = "수급 포착"
        if not label and r.get("surgeLabel") in {"눌림 대기 후보", "추세 지속 후보"}:
            label = r.get("surgeLabel")
        if not label and r.get("decisionBucket") == "오늘 진입":
            label = "모멘텀 초기"
        if not label:
            label = "중기 관심 후보" if horizon == "mid" else "차트 회복 후보"
        row = {"symbol": r.get("symbol"), "name": r.get("name"), "label": label, "mode": r.get("modeLabel"), "horizon": r.get("horizonLabel"), "score": r.get("finalRankScore"), "decision": r.get("decisionBucket"), "buyTiming": r.get("buyTiming"), "eventBadges": r.get("eventBadgesText")}
        buckets[label].append(row)
    items = [{"bucket": k, "count": len(v), "items": v[:12]} for k, v in sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)]
    return {"status": "OK", "market": market, "mode": mode, "horizon": horizon, "count": sum(x["count"] for x in items), "items": items}




def _admin_records_from_recommendations(market: str, limit: int = 250) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode in MODES:
        for horizon in HORIZONS:
            rec = final_recommendations(market, mode, horizon, limit=80)
            for item in rec.get("items", []):
                rows.append({
                    "date": item.get("sourceDate") or item.get("priceSourceDate") or rec.get("generatedAt") or "",
                    "market": market,
                    "mode": MODE_LABELS.get(mode, mode),
                    "horizon": HORIZON_LABELS.get(horizon, horizon),
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "decision": item.get("decisionBucket") or item.get("newEntryDecision") or item.get("buyTiming"),
                    "price": item.get("currentPriceText"),
                    "priceStatus": item.get("priceDataStatus"),
                    "sourceFile": item.get("sourceFile"),
                    "dataStatus": item.get("dataStatus"),
                })
    return rows[:limit]


def admin_prediction_history(market: str | None = None, limit: int = 250) -> dict[str, Any]:
    markets = [market] if market in MARKETS else list(MARKETS)
    rows: list[dict[str, Any]] = []
    sources: list[str] = []
    for mk in markets:
        rec_rows = _admin_records_from_recommendations(mk, limit=limit)
        rows.extend(rec_rows)
        for row in rec_rows:
            src = _as_text(row.get("sourceFile"))
            if src and src not in sources:
                sources.append(src)
    rows = sorted(rows, key=lambda r: str(r.get("date", "")), reverse=True)[:limit]
    return {"status": "OK" if rows else "NO_DATA", "market": market or "all", "count": len(rows), "source": " · ".join(sources[:5]) or "final recommendations", "items": rows}


def admin_outcome_history(market: str | None = None, limit: int = 250) -> dict[str, Any]:
    markets = [market] if market in MARKETS else list(MARKETS)
    rows: list[dict[str, Any]] = []
    sources: list[str] = []
    for mk in markets:
        for mode in ("balanced",):
            for horizon in ("swing", "short", "mid"):
                trade = trade_validation(mk, mode, horizon)
                if trade.get("source") and trade.get("source") not in sources:
                    sources.append(str(trade.get("source")))
                for item in trade.get("items", [])[:80]:
                    rows.append({
                        "date": item.get("ohlcvDate") or item.get("sourceDate") or "",
                        "market": mk,
                        "mode": MODE_LABELS.get(mode, mode),
                        "horizon": HORIZON_LABELS.get(horizon, horizon),
                        "symbol": item.get("symbol"),
                        "name": item.get("name"),
                        "result": item.get("executionStatus"),
                        "exitStatus": item.get("exitStatus"),
                        "pnlText": item.get("pnlText"),
                        "reason": item.get("executionReason"),
                        "ohlcvSource": item.get("ohlcvSource"),
                    })
    rows = sorted(rows, key=lambda r: str(r.get("date", "")), reverse=True)[:limit]
    return {"status": "OK" if rows else "NO_DATA", "market": market or "all", "count": len(rows), "source": " · ".join(sources[:5]) or "trade validation", "items": rows}


def admin_prediction_insights(market: str = "kr") -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    pred_history = admin_prediction_history(market, limit=250)
    outcomes = admin_outcome_history(market, limit=250)
    pred_validation = prediction_validation(market, limit=250)
    validation_rows = pred_validation.get("items", [])
    outcome_rows = outcomes.get("items", [])
    success = 0
    fail = 0
    neutral = 0
    failures: list[dict[str, Any]] = []
    by_symbol: dict[str, dict[str, Any]] = {}
    by_period: dict[str, dict[str, Any]] = {}

    def mark(symbol: str, ok: bool | None, period: str, row: dict[str, Any]) -> None:
        nonlocal success, fail, neutral
        if ok is True:
            success += 1
        elif ok is False:
            fail += 1
            failures.append({
                "symbol": symbol,
                "name": row.get("name", ""),
                "period": period,
                "reason": row.get("reason") or row.get("result") or row.get("predictionResult") or "검증 불일치",
                "source": row.get("ohlcvSource") or row.get("source") or "",
            })
        else:
            neutral += 1
        bucket = by_symbol.setdefault(symbol or "UNKNOWN", {"symbol": symbol or "UNKNOWN", "success": 0, "fail": 0, "neutral": 0})
        pb = by_period.setdefault(period, {"period": period, "success": 0, "fail": 0, "neutral": 0})
        key = "success" if ok is True else "fail" if ok is False else "neutral"
        bucket[key] += 1
        pb[key] += 1

    for row in validation_rows:
        symbol = _as_text(row.get("symbol"))
        for period in ("D+1", "D+5", "D+20"):
            payload = row.get(period, {}) if isinstance(row.get(period), dict) else {}
            status_text = _as_text(payload.get("status") or payload.get("direction") or row.get("predictionResult"))
            if "성공" in status_text or "hit" in status_text.lower():
                mark(symbol, True, period, row)
            elif "실패" in status_text or "miss" in status_text.lower() or "불일치" in status_text:
                mark(symbol, False, period, row)
            else:
                mark(symbol, None, period, row)
    if not validation_rows:
        for row in outcome_rows:
            text = f"{row.get('result','')} {row.get('exitStatus','')} {row.get('reason','')}"
            ok = True if any(word in text for word in ("체결", "목표", "이익", "성공")) else False if any(word in text for word in ("손절", "불일치", "실패")) else None
            mark(_as_text(row.get("symbol")), ok, _as_text(row.get("horizon") or "검증"), row)
    total_checked = success + fail
    success_rate = f"{success / total_checked * 100:.1f}%" if total_checked else "검증 데이터 부족"
    coverage = f"{len(validation_rows) or len(outcome_rows)}/{pred_history.get('count', 0)}" if pred_history.get("count", 0) else "검증 데이터 부족"
    corrections = []
    if fail:
        corrections.append({"항목": "진입 기준", "제안": "실패/불일치 종목은 진입 점수 기준 상향", "근거": f"실패 {fail}건"})
    if neutral > success + fail:
        corrections.append({"항목": "검증 데이터", "제안": "장마감 OHLC/actual_close 연결 우선", "근거": f"중립/대기 {neutral}건"})
    diagnostics = [
        {"항목": "예측 source", "값": pred_history.get("source", "")},
        {"항목": "결과 source", "값": outcomes.get("source", "")},
        {"항목": "검증 기준", "값": "final recommendations + trade validation + OHLCV/actual close"},
    ]
    return {
        "market": market,
        "status": "OK" if (validation_rows or outcome_rows) else "NO_DATA",
        "summary": {
            "predictionRows": pred_history.get("count", 0),
            "historyRows": pred_history.get("count", 0),
            "outcomeRows": outcomes.get("count", 0),
            "validationRows": len(validation_rows),
            "success": success,
            "fail": fail,
            "neutral": neutral,
            "successRate": success_rate,
            "coverage": coverage,
        },
        "diagnostics": diagnostics,
        "bySymbol": list(by_symbol.values())[:120],
        "byPeriod": list(by_period.values()),
        "failures": failures[:120],
        "corrections": corrections,
        "sources": [pred_history.get("source", ""), outcomes.get("source", ""), pred_validation.get("source", "")],
    }


def prediction_accuracy_stats(market: str | None = None) -> dict[str, Any]:
    """predictions.csv 전체에서 실제 결과 기반 정확도 통계를 계산합니다."""
    pred_path = data.REPO_ROOT / "predictions.csv"
    if not pred_path.exists():
        return {"status": "NO_DATA", "message": "predictions.csv 없음"}

    df = data.read_csv(pred_path)
    if df.empty:
        return {"status": "NO_DATA", "message": "predictions.csv 비어 있음"}

    # 시장 필터
    if market in ("kr", "us"):
        mk_label = "한국주식" if market == "kr" else "미국주식"
        df = df[df["market"].astype(str).str.contains("한국" if market == "kr" else "미국", na=False)]

    df, ohlcv_match = _fill_prediction_accuracy_actuals(df, market)
    df_actual = df[df["actual_close"].astype(str).str.strip().ne("")]
    total = len(df_actual)
    if total == 0:
        return {"status": "NO_DATA", "message": "실제 결과 데이터 없음", "totalRows": len(df)}

    def hit_rate(col: str) -> float | None:
        if col not in df_actual.columns:
            return None
        hits = df_actual[col].astype(str).isin(["1", "1.0", "True", "true"]).sum()
        return round(hits / total * 100, 1)

    direction_hit = hit_rate("direction_hit")
    open_in_range = hit_rate("open_in_range")
    close_in_range = hit_rate("close_in_range")
    entry_touched = hit_rate("entry_touched")
    tp1_touched = hit_rate("tp1_touched")
    stop_touched = hit_rate("stop_touched")

    vr = pd.to_numeric(df_actual.get("virtual_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    avg_virtual_return = round(float(vr.mean()), 3) if len(vr) else None
    positive_rate = round(float((vr > 0).sum() / len(vr) * 100), 1) if len(vr) else None

    # 신뢰도 구간별 분석
    by_bucket: list[dict[str, Any]] = []
    if "confidence_score" in df_actual.columns and "direction_hit" in df_actual.columns:
        df_work = df_actual.copy()
        df_work["_conf"] = pd.to_numeric(df_work["confidence_score"], errors="coerce")
        df_work["_hit"] = df_work["direction_hit"].astype(str).isin(["1", "1.0", "True", "true"])
        bins = [(0, 50, "50미만"), (50, 65, "50~64"), (65, 80, "65~79"), (80, 101, "80이상")]
        for lo, hi, label in bins:
            subset = df_work[(df_work["_conf"] >= lo) & (df_work["_conf"] < hi)]
            if len(subset):
                by_bucket.append({
                    "bucket": label,
                    "count": int(len(subset)),
                    "directionHitRate": round(float(subset["_hit"].mean() * 100), 1),
                })

    # virtual_result_label 분포
    result_dist: dict[str, int] = {}
    if "virtual_result_label" in df_actual.columns:
        for label, cnt in df_actual["virtual_result_label"].value_counts().head(8).items():
            result_dist[str(label)] = int(cnt)

    # 날짜 범위
    date_min = str(df_actual["target_date"].min()) if "target_date" in df_actual.columns else ""
    date_max = str(df_actual["target_date"].max()) if "target_date" in df_actual.columns else ""

    # prediction_learning_summary.csv 에서 진입가 도달률 보강
    learning_path = data.REPORT_DIR / "prediction_learning_summary.csv"
    learning_rows: list[dict[str, Any]] = []
    if learning_path.exists():
        ldf = data.read_csv(learning_path)
        if not ldf.empty:
            for _, row in ldf.iterrows():
                mk_text = str(row.get("market", "")).strip()
                if market == "kr" and "미국" in mk_text:
                    continue
                if market == "us" and "한국" in mk_text:
                    continue
                learning_rows.append({
                    "market": mk_text,
                    "confidenceBucket": str(row.get("confidence_bucket", "")),
                    "sampleCount": data._safe_float(row.get("sample_count")),
                    "entryHitRate": data._safe_float(row.get("entry_hit_rate_pct")),
                    "tp1TouchRate": data._safe_float(row.get("tp1_touch_rate_pct")),
                    "stopTouchRate": data._safe_float(row.get("stop_touch_rate_pct")),
                })

    # 최신 validation_summary JSON
    import json, glob as _glob
    val_summaries = sorted(_glob.glob(str(data.REPORT_DIR / "validation_summary_*.json")))
    latest_validation: dict[str, Any] = {}
    if val_summaries:
        try:
            latest_validation = json.loads(Path(val_summaries[-1]).read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "status": "OK",
        "market": market or "all",
        "totalRows": len(df),
        "validatedRows": total,
        "dateRange": {"from": date_min, "to": date_max},
        "directionHitRate": direction_hit,
        "openInRangeRate": open_in_range,
        "closeInRangeRate": close_in_range,
        "entryTouchedRate": entry_touched,
        "tp1TouchedRate": tp1_touched,
        "stopTouchedRate": stop_touched,
        "avgVirtualReturn": avg_virtual_return,
        "positiveReturnRate": positive_rate,
        "byConfidenceBucket": by_bucket,
        "virtualResultDist": result_dist,
        "learningData": learning_rows,
        "latestValidationSummary": latest_validation,
        "actualSource": ohlcv_match.get("source"),
        "autoOhlcvMatchedRows": ohlcv_match.get("matchedRows", 0),
        "latestOhlcvDate": ohlcv_match.get("latestOhlcvDate", ""),
        "updatedAt": _now(),
    }


def admin_backtest(market: str = "kr") -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    items: list[dict[str, Any]] = []
    recent_trades: list[dict[str, Any]] = []
    recent_outcomes: list[dict[str, Any]] = []
    warnings: list[str] = []
    for mode in MODES:
        trade = trade_validation(market, mode, "swing")
        rows = trade.get("items", [])
        filled = [r for r in rows if "체결" in _as_text(r.get("executionStatus")) and not r.get("excludedFromReturn")]
        pnl_values = []
        for r in filled:
            m = re.search(r"([+-]?\\d+(?:\\.\\d+)?)%", _as_text(r.get("pnlText")))
            if m:
                pnl_values.append(float(m.group(1)))
        win = sum(1 for v in pnl_values if v > 0)
        trades = len(pnl_values)
        total_return = sum(pnl_values)
        win_rate = f"{win / trades * 100:.1f}%" if trades else "체결 수익률 없음"
        items.append({
            "strategy": MODE_LABELS.get(mode, mode),
            "status": "OK" if rows else "NO_DATA",
            "totalReturn": f"{total_return:+.2f}%" if trades else "검증 대기",
            "winRate": win_rate,
            "mdd": "실거래 누적 전용",
            "sharpe": "실거래 누적 전용",
            "trades": str(len(rows)),
            "recentResult": _as_text(rows[0].get("executionStatus")) if rows else "신호 없음",
        })
        recent_trades.extend(rows[:10])
        recent_outcomes.extend(rows[:10])
    pred_history = admin_prediction_history(market, 250)
    outcome_history = admin_outcome_history(market, 250)
    if not recent_trades:
        warnings.append("최신 추천/검증 데이터 부족")
    if any(_as_text(r.get("priceDataStatus")) == "STALE" for r in recent_trades):
        warnings.append("일부 가격 기준 STALE")
    return {
        "status": "OK" if items and any(i.get("status") == "OK" for i in items) else "NO_DATA",
        "market": market,
        "count": len(items),
        "items": items,
        "warnings": warnings or ["최신 final/trade validation 기준"],
        "predictionRows": pred_history.get("count", 0),
        "totalPredictionRows": pred_history.get("count", 0),
        "outcomeRows": outcome_history.get("count", 0),
        "recentOutcomes": recent_outcomes[:80],
        "recentTrades": recent_trades[:80],
        "diagnostics": [
            {"항목": "기준", "값": "latest final recommendations + trade validation"},
            {"항목": "예측 source", "값": pred_history.get("source", "")},
            {"항목": "결과 source", "값": outcome_history.get("source", "")},
        ],
        "ohlcv": {"files": "fallback 포함", "eligibleSymbols": len({r.get("symbol") for r in recent_trades if r.get("symbol")}), "minDaysRequired": 1, "predictionMatchedSymbols": len({r.get("symbol") for r in recent_outcomes if r.get("symbol")})},
    }



def operational_readiness() -> dict[str, Any]:
    """Fast operational readiness check for UI/GitHub.

    This intentionally avoids doing a second full market scan when reports already
    exist. It checks every market/mode/horizon output file and only computes a
    lightweight fallback when a file is missing.
    """
    markets = [data_center("kr"), data_center("us")]
    checks: list[dict[str, Any]] = []
    for market in MARKETS:
        for mode in MODES:
            for horizon in HORIZONS:
                rec_path = data.REPORT_DIR / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
                trade_path = data.REPORT_DIR / f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv"
                rec_df = data.read_csv(rec_path) if rec_path.exists() else pd.DataFrame()
                trade_df = data.read_csv(trade_path) if trade_path.exists() else pd.DataFrame()
                if rec_df.empty:
                    rec = final_recommendations(market, mode, horizon, limit=1)
                    rec_count = int(rec.get("count", 0))
                    universe_count = int(rec.get("universeCount", 0))
                else:
                    rec_count = int(len(rec_df))
                    universe_count = rec_count
                filled_count = 0
                avg_return = ""
                if not trade_df.empty:
                    status_col = next((c for c in trade_df.columns if c in {"executionStatus", "execution_status"}), None)
                    if status_col:
                        filled_count = int((trade_df[status_col].astype(str) == "체결").sum())
                    pnl_col = next((c for c in trade_df.columns if c in {"pnlText", "pnl_text"}), None)
                    if pnl_col and filled_count:
                        avg_return = "체결 기준 산출됨"
                checks.append({
                    "market": market,
                    "mode": mode,
                    "horizon": horizon,
                    "recommendations": rec_count,
                    "universeCount": universe_count,
                    "conditionalOrders": rec_count,
                    "filledCount": filled_count,
                    "avgReturn": avg_return,
                    "recommendationReport": data.source_label(rec_path),
                    "tradeValidationReport": data.source_label(trade_path),
                    "status": "OK" if rec_count > 0 else "NO_RECOMMENDATION",
                })
    pred = {}
    macro = {}
    for market in MARKETS:
        pred_payload = prediction_validation(market, limit=80)
        pred[market] = pred_payload.get("validatedD1Count", 0)
        macro[market] = macro_event_risk(market).get("count", 0)
    avg_readiness = sum(int(m.get("readinessScore", 0)) for m in markets) / len(markets)
    no_rec = [c for c in checks if c["status"] != "OK"]
    blocking = []
    if no_rec:
        blocking.append(f"추천 없음 조합 {len(no_rec)}개")
    if avg_readiness < 65:
        blocking.append("데이터 센터 준비도 낮음")
    label = "운영 안정" if not blocking and avg_readiness >= 75 else "부분 운영" if avg_readiness >= 55 else "운영 전 점검"
    return {
        "status": "OK" if label != "운영 전 점검" else "CHECK_REQUIRED",
        "version": OPERATIONAL_VERSION,
        "readinessAverage": round(avg_readiness, 1),
        "readinessLabel": label,
        "blockingIssues": blocking or ["차단 이슈 없음"],
        "markets": markets,
        "matrix": checks,
        "predictionValidatedD1Count": pred,
        "macroEventCount": macro,
        "generatedAt": _now(),
    }


def write_final_reports() -> dict[str, Any]:
    data.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for market in MARKETS:
        dc = data_center(market)
        pd.DataFrame(dc.get("summary", [])).to_csv(data.REPORT_DIR / f"mone_v36_final_data_center_{market}.csv", index=False, encoding="utf-8-sig")
        written.append({"path": f"reports/mone_v36_final_data_center_{market}.csv", "rows": len(dc.get("summary", []))})
        macro = macro_event_risk(market)
        pd.DataFrame(macro.get("items", [])).to_csv(data.REPORT_DIR / f"mone_v36_final_macro_events_{market}.csv", index=False, encoding="utf-8-sig")
        written.append({"path": f"reports/mone_v36_final_macro_events_{market}.csv", "rows": len(macro.get("items", []))})
        pred = prediction_validation(market)
        flat_pred = []
        for row in pred.get("items", []):
            base = {k: v for k, v in row.items() if k not in {"D+1", "D+5", "D+20"}}
            for h in ("D+1", "D+5", "D+20"):
                for kk, vv in row.get(h, {}).items():
                    base[f"{h}_{kk}"] = vv
            flat_pred.append(base)
        pd.DataFrame(flat_pred).to_csv(data.REPORT_DIR / f"mone_v36_final_prediction_validation_{market}.csv", index=False, encoding="utf-8-sig")
        written.append({"path": f"reports/mone_v36_final_prediction_validation_{market}.csv", "rows": len(flat_pred)})
        for mode in MODES:
            for horizon in HORIZONS:
                rec = final_recommendations(market, mode, horizon)
                flat = []
                for r in rec.get("items", []):
                    ex = r.get("execution", {})
                    flat.append({
                        "market": market,
                        "mode": mode,
                        "modeLabel": MODE_LABELS[mode],
                        "horizon": horizon,
                        "horizonLabel": HORIZON_LABELS[horizon],
                        "symbol": r.get("symbol"),
                        "name": r.get("name"),
                        "decisionBucket": r.get("decisionBucket"),
                        "newEntryDecision": r.get("newEntryDecision"),
                        "holderDecision": r.get("holderDecision"),
                        "buyTiming": r.get("buyTiming"),
                        "sellTiming": r.get("sellTiming"),
                        "entry": r.get("entryText"),
                        "stop": r.get("stopText"),
                        "target": r.get("targetText"),
                        "probability": r.get("probabilityText"),
                        "expectedPrice": r.get("expectedPriceText"),
                        "opportunityScore": r.get("opportunityScore"),
                        "entryScore": r.get("entryScore"),
                        "riskScore": r.get("riskScore"),
                        "eventRiskScore": r.get("eventRiskScore"),
                        "newsReliabilityScore": r.get("newsReliabilityScore"),
                        "finalRankScore": r.get("finalRankScore"),
                        "surgeLabel": r.get("surgeLabel"),
                        "eventBadges": r.get("eventBadgesText"),
                        "executionStatus": ex.get("executionStatus"),
                        "exitStatus": ex.get("exitStatus"),
                        "pnlText": ex.get("pnlText"),
                        "excludedFromReturn": ex.get("excludedFromReturn"),
                        "sourceBucket": r.get("sourceBucket"),
                    })
                path = data.REPORT_DIR / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
                pd.DataFrame(flat).to_csv(path, index=False, encoding="utf-8-sig")
                written.append({"path": f"reports/{path.name}", "rows": len(flat)})
                trade = trade_validation(market, mode, horizon)
                pd.DataFrame(trade.get("items", [])).to_csv(data.REPORT_DIR / f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv", index=False, encoding="utf-8-sig")
                written.append({"path": f"reports/mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv", "rows": len(trade.get("items", []))})
    readiness = operational_readiness()
    pd.DataFrame(readiness.get("matrix", [])).to_csv(data.REPORT_DIR / "mone_v36_operational_readiness_matrix.csv", index=False, encoding="utf-8-sig")
    written.append({"path": "reports/mone_v36_operational_readiness_matrix.csv", "rows": len(readiness.get("matrix", []))})
    data.write_json(data.REPORT_DIR / "mone_v36_operational_readiness.json", readiness)
    written.append({"path": "reports/mone_v36_operational_readiness.json", "rows": len(readiness.get("matrix", []))})
    manifest = {"version": OPERATIONAL_VERSION, "generatedAt": _now(), "readiness": readiness, "written": written}
    data.write_json(data.REPORT_DIR / "mone_v36_final_manifest.json", manifest)
    return manifest
