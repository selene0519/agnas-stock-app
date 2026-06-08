"""
MONE Phase 6 Chart Analysis Engine — Blueprint V4.5
Core Analysis (T) + Forward Projection (T+H) + FSM Signal Lifecycle

Architecture principles (from blueprint):
  - Core Analysis: all calculations use data up to time T only (no look-ahead bias)
  - Forward Projection: visualization coordinates for future area only
  - One-way flow: projection results cannot contaminate core analysis state
  - Conditional monitor: not a price predictor, a "conditional watchline generator"

Integration:
  - chart_signal_score (0~100) is injected into quant_scanner finalScore (+10% weight)
  - confirmed bullish → +12 pts / developing → +5 pts / invalidated → -8 pts
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


# ─── Constants ────────────────────────────────────────────────────────────────

FIBONACCI_LEVELS = [
    (0.236, "23.6%", False),
    (0.382, "38.2%", False),
    (0.500, "50.0%", False),
    (0.618, "61.8%", False),
    (0.786, "78.6%", False),
    (0.868, "86.8%", True),   # key level — overlaps with supply zones = strong signal
]

COMPLIANCE_NOTES = [
    "본 분석은 투자 권유가 아닌 조건부 감시 정보입니다.",
    "추세선은 '상단 저항 감시선' 및 '하단 지지 감시선'으로 활용하세요.",
    "되돌림 레벨은 '변곡 가능 감시 레벨' 및 '무효화 기준선'입니다.",
    "신호 박스는 '신호 유효 감시 구간'입니다. 투자 판단은 본인 책임입니다.",
]


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class Candle:
    index: int
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


@dataclass
class Pivot:
    index: int
    price: float
    pivot_type: Literal["H", "L"]
    date: str


@dataclass
class Trendline:
    slope: float        # price change per bar
    intercept: float    # price at index=0
    start_index: int
    end_index: int
    start_price: float
    end_price: float

    def price_at(self, index: int) -> float:
        return self.slope * index + self.intercept


@dataclass
class SupplyDemandZone:
    zone_id: str
    zone_type: Literal["supply", "demand"]
    top: float
    bottom: float
    strength_score: float
    is_mitigated: bool = False
    created_index: int = 0


@dataclass
class RetracementLevel:
    ratio: float
    price: float
    label: str
    is_key: bool


@dataclass
class OverlapSignal:
    price: float
    ratio: float
    is_key: bool
    zone_strength: float
    label: str


@dataclass
class EngineConfig:
    zigzag_threshold_pct: float = 0.05
    overlap_buffer_pct: float = 0.005
    confirmation_score_threshold: float = 80.0
    invalidation_score_threshold: float = 75.0
    debounce_bars: int = 2
    invalidation_bars: int = 2
    max_signal_age_bars: int = 10
    max_distance_pct_from_primary_level: float = 0.03
    max_reference_fraction: float = 0.03
    max_loss_fraction: float = 0.02


@dataclass
class ConfluenceComponents:
    overlap: float = 0.0       # retracement × zone overlap score
    momentum: float = 0.0      # trendline direction + ma alignment
    volume: float = 0.0        # recent volume vs 20-day avg
    market_condition: float = 0.0
    data_quality: float = 0.0
    penalty: float = 0.0       # RSI overbought / structure break


@dataclass
class ProjectionLine:
    from_index: int
    to_index: int
    from_price: float
    to_price: float
    kind: Literal["support", "resistance", "retracement"]
    source_status: str
    active: bool


@dataclass
class ProjectionZone:
    zone_id: str
    from_index: int
    to_index: int
    top: float
    bottom: float
    zone_type: Literal["supply", "demand"]
    active: bool


@dataclass
class ChartProjectionState:
    horizon_bars: int
    projected_trendlines: list[ProjectionLine] = field(default_factory=list)
    projected_zones: list[ProjectionZone] = field(default_factory=list)
    projected_retracements: list[ProjectionLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ChartAnalysisState:
    symbol: str
    market: str
    timeframe: str = "daily"

    # Core analysis outputs (T-only, no look-ahead)
    completed_pivots: list[Pivot] = field(default_factory=list)
    support_line: Optional[Trendline] = None
    resistance_line: Optional[Trendline] = None
    breakout_direction: Optional[str] = None
    breakout_status: str = "none"
    retracements: list[RetracementLevel] = field(default_factory=list)
    primary_retracement_level: Optional[float] = None
    zones: list[SupplyDemandZone] = field(default_factory=list)
    overlap_signals: list[OverlapSignal] = field(default_factory=list)

    # Confluence & FSM
    confluence_score: float = 0.0
    confluence_direction: str = "neutral"    # "bullish" | "bearish" | "neutral"
    signal_status: str = "none"             # FSM state
    confluence_components: ConfluenceComponents = field(default_factory=ConfluenceComponents)
    confluence_reasons: list[str] = field(default_factory=list)

    # Signal lifecycle
    confirmed_index: Optional[int] = None
    created_index: Optional[int] = None
    expires_at_index: Optional[int] = None
    invalidation_reason: Optional[str] = None
    consecutive_above_threshold: int = 0
    consecutive_below_invalidation: int = 0

    # Risk suggestion
    capped_fraction: float = 0.0   # always 0 unless confirmed
    risk_status: str = "none"

    # Forward projection
    projection: Optional[ChartProjectionState] = None

    # Integration score for quant_scanner (0~100)
    chart_signal_score: float = 0.0
    chart_signal_tag: str = "NO_SIGNAL"

    # Audit
    evaluated_at: float = 0.0
    input_candle_count: int = 0
    lookahead_safe: bool = True
    data_quality: str = "normal"   # "normal" | "stale" | "partial" | "error"
    warnings: list[str] = field(default_factory=list)


# ─── Helper functions ─────────────────────────────────────────────────────────

def _num(value: Any) -> Optional[float]:
    try:
        raw = str(value or "").replace(",", "").replace("$", "").replace("원", "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        v = float(raw)
        return None if math.isnan(v) else v
    except Exception:
        return None


def _rows_to_candles(rows: list[dict[str, Any]]) -> list[Candle]:
    candles: list[Candle] = []
    for i, row in enumerate(rows):
        date = str(row.get("date") or row.get("Date") or row.get("날짜") or "").strip()
        close = _num(row.get("close") or row.get("Close") or row.get("종가"))
        if not close or close <= 0:
            continue
        open_ = _num(row.get("open") or row.get("Open") or row.get("시가")) or close
        high = _num(row.get("high") or row.get("High") or row.get("고가")) or close
        low = _num(row.get("low") or row.get("Low") or row.get("저가")) or close
        volume = _num(row.get("volume") or row.get("Volume") or row.get("거래량")) or 0.0
        candles.append(Candle(
            index=i, date=date,
            open=open_, high=high, low=low, close=close,
            volume=volume, is_closed=True,
        ))
    return candles


# ─── Core Calculations ────────────────────────────────────────────────────────

def _calc_zigzag(
    candles: list[Candle],
    threshold: float = 0.05,
    win_size: int = 3,
) -> list[Pivot]:
    """ZigZag pivot detection with threshold filter. No look-ahead: uses only candles[0..T]."""
    if len(candles) < win_size * 2 + 2:
        return []

    # Step 1: local high/low candidates
    candidates: list[Pivot] = []
    for i in range(win_size, len(candles) - win_size):
        h = candles[i].high
        l = candles[i].low
        is_h = all(candles[j].high <= h for j in range(i - win_size, i + win_size + 1) if j != i)
        is_l = all(candles[j].low >= l for j in range(i - win_size, i + win_size + 1) if j != i)
        if is_h and not is_l:
            candidates.append(Pivot(i, h, "H", candles[i].date))
        elif is_l and not is_h:
            candidates.append(Pivot(i, l, "L", candles[i].date))

    # Step 2: threshold filter + merge consecutive same-direction
    filtered: list[Pivot] = []
    for p in candidates:
        if not filtered:
            filtered.append(p)
            continue
        last = filtered[-1]
        if last.pivot_type == p.pivot_type:
            # Merge: keep more extreme
            if (p.pivot_type == "H" and p.price > last.price) or \
               (p.pivot_type == "L" and p.price < last.price):
                filtered[-1] = p
        else:
            chg = abs(p.price - last.price) / last.price if last.price > 0 else 0
            if chg >= threshold:
                filtered.append(p)
            elif (p.pivot_type == "H" and p.price > last.price) or \
                 (p.pivot_type == "L" and p.price < last.price):
                filtered[-1] = p

    return filtered


def _calc_trendlines(
    candles: list[Candle],
    pivots: list[Pivot],
) -> tuple[Optional[Trendline], Optional[Trendline]]:
    """
    Support line: connect last 2 lows (up-slope trendline)
    Resistance line: connect last 2 highs (down-slope trendline)
    Returns (support, resistance).
    """
    lows = [p for p in pivots if p.pivot_type == "L"]
    highs = [p for p in pivots if p.pivot_type == "H"]
    n = len(candles)

    def make_line(p1: Pivot, p2: Pivot, kind: str) -> Optional[Trendline]:
        if p1.index >= p2.index:
            return None
        slope = (p2.price - p1.price) / (p2.index - p1.index)
        intercept = p1.price - slope * p1.index
        end_price = slope * (n - 1) + intercept
        # Defensive guard: extended price must be positive and within ±60% of current
        if end_price <= 0:
            return None
        current = candles[-1].close if candles else 0
        if current > 0 and abs(end_price - current) / current > 0.60:
            return None
        return Trendline(
            slope=slope, intercept=intercept,
            start_index=p1.index, end_index=n - 1,
            start_price=p1.price, end_price=end_price,
        )

    support = make_line(lows[-2], lows[-1], "support") if len(lows) >= 2 else None
    resistance = make_line(highs[-2], highs[-1], "resistance") if len(highs) >= 2 else None
    return support, resistance


def _calc_retracements(pivots: list[Pivot]) -> list[RetracementLevel]:
    """
    Fibonacci retracement from last confirmed swing (excludes developing tail).
    Uses only confirmed pivots (all but last which may be developing).
    """
    confirmed = pivots[:-1] if len(pivots) > 1 else pivots
    if len(confirmed) < 2:
        return []

    swing_end = confirmed[-1]
    swing_start = confirmed[-2]
    high = swing_end.price if swing_end.pivot_type == "H" else swing_start.price
    low = swing_end.price if swing_end.pivot_type == "L" else swing_start.price
    swing = high - low
    if swing <= 0:
        return []

    is_up_swing = swing_end.pivot_type == "H"
    result: list[RetracementLevel] = []
    for ratio, label, is_key in FIBONACCI_LEVELS:
        price = (high - ratio * swing) if is_up_swing else (low + ratio * swing)
        result.append(RetracementLevel(ratio=ratio, price=price, label=label, is_key=is_key))
    return result


def _calc_supply_zones(
    candles: list[Candle],
    top_n: int = 3,
) -> list[SupplyDemandZone]:
    """
    Volume-weighted price density histogram → supply/demand zones.
    60 bins across price range, merge adjacent hot bins (strength > 35%).
    """
    if len(candles) < 10:
        return []

    all_prices = [p for c in candles for p in (c.high, c.low)]
    min_p, max_p = min(all_prices), max(all_prices)
    if max_p <= min_p:
        return []

    bins = 60
    bin_size = (max_p - min_p) / bins
    buckets = [0.0] * bins
    total_vol = sum(c.volume for c in candles)
    use_vol = total_vol > 0

    for c in candles:
        lo = max(0, int((c.low - min_p) / bin_size))
        hi = min(bins, math.ceil((c.high - min_p) / bin_size))
        span = max(1, hi - lo)
        w = c.volume if use_vol else 1.0
        for b in range(lo, hi):
            buckets[b] += w / span

    max_vol = max(buckets) if buckets else 0
    if max_vol <= 0:
        return []

    hot = [(i, v / max_vol) for i, v in enumerate(buckets) if v / max_vol > 0.35]

    zones: list[dict] = []
    for idx, strength in hot:
        lower = min_p + idx * bin_size
        upper = lower + bin_size
        if zones and lower <= zones[-1]["upper"] + bin_size * 1.5:
            zones[-1]["upper"] = max(zones[-1]["upper"], upper)
            zones[-1]["center"] = (zones[-1]["lower"] + zones[-1]["upper"]) / 2
            zones[-1]["strength"] = max(zones[-1]["strength"], strength)
        else:
            zones.append({"lower": lower, "upper": upper,
                          "center": (lower + upper) / 2, "strength": strength})

    zones.sort(key=lambda z: z["strength"], reverse=True)
    current_price = candles[-1].close

    result: list[SupplyDemandZone] = []
    for i, z in enumerate(zones[:top_n]):
        zone_type: Literal["supply", "demand"] = "supply" if z["center"] > current_price else "demand"
        result.append(SupplyDemandZone(
            zone_id=f"zone_{i}",
            zone_type=zone_type,
            top=round(z["upper"], 4),
            bottom=round(z["lower"], 4),
            strength_score=round(z["strength"], 3),
            is_mitigated=False,
            created_index=len(candles) - 1,
        ))
    return result


def _find_overlap_signals(
    rets: list[RetracementLevel],
    zones: list[SupplyDemandZone],
    buffer_pct: float = 0.005,
) -> list[OverlapSignal]:
    """
    Find retracement levels that fall inside a supply/demand zone.
    Overlap = strong entry/exit signal (blueprint §3).
    """
    signals: list[OverlapSignal] = []
    for r in rets:
        for z in zones:
            tol = r.price * buffer_pct
            if z.bottom - tol <= r.price <= z.top + tol:
                signals.append(OverlapSignal(
                    price=r.price,
                    ratio=r.ratio,
                    is_key=r.is_key,
                    zone_strength=z.strength_score,
                    label=f"{'★' if r.is_key else ''}{r.label}+{'매물대' if z.zone_type == 'supply' else '지지대'}",
                ))
    return signals


def _detect_breakout(
    candles: list[Candle],
    support: Optional[Trendline],
    resistance: Optional[Trendline],
) -> tuple[Optional[str], str]:
    """
    Detect trendline breakout on closed candles.
    Returns (direction, status): direction = "UP"|"DOWN"|None, status = FSM status.
    """
    if not candles:
        return None, "none"
    last = candles[-1]

    if resistance and resistance.slope <= 0:  # downward resistance
        res_price = resistance.price_at(last.index)
        if res_price > 0 and last.close > res_price * 1.002:
            return "UP", "developing"

    if support and support.slope >= 0:  # upward support
        sup_price = support.price_at(last.index)
        if sup_price > 0 and last.close < sup_price * 0.998:
            return "DOWN", "developing"

    return None, "none"


# ─── Confluence Score ─────────────────────────────────────────────────────────

def _calc_confluence(
    candles: list[Candle],
    pivots: list[Pivot],
    support: Optional[Trendline],
    resistance: Optional[Trendline],
    zones: list[SupplyDemandZone],
    rets: list[RetracementLevel],
    overlaps: list[OverlapSignal],
    breakout_direction: Optional[str],
    market_regime_score: float = 50.0,
    data_quality: str = "normal",
) -> tuple[float, str, ConfluenceComponents, list[str]]:
    """
    Confluence score (0~100) combining all chart signals.
    Returns (score, direction, components, reasons).
    """
    components = ConfluenceComponents()
    reasons: list[str] = []

    if len(candles) < 20:
        return 0.0, "neutral", components, ["데이터 부족 (20봉 미만)"]

    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]

    # 1. Overlap score (retracement × zone confluence)
    if overlaps:
        key_overlaps = [o for o in overlaps if o.is_key]
        base_overlap = min(60.0, len(overlaps) * 15.0)
        key_bonus = min(20.0, len(key_overlaps) * 15.0)
        components.overlap = min(80.0, base_overlap + key_bonus)
        if key_overlaps:
            reasons.append(f"0.868 되돌림×매물대 겹침 {len(key_overlaps)}개 (강력 진입 구간)")
        else:
            reasons.append(f"피보나치×매물대 겹침 {len(overlaps)}개")
    else:
        components.overlap = 0.0

    # 2. Momentum score (trendline direction + MA alignment)
    momentum = 50.0
    if len(closes) >= 20:
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
        ma20 = sum(closes[-20:]) / 20
        current = closes[-1]
        if ma5 and ma20:
            if current > ma20 and ma5 > ma20:
                momentum += 20.0
                reasons.append("단기 정배열 (현재가 > MA20, MA5 > MA20)")
            elif current < ma20 and ma5 < ma20:
                momentum -= 20.0
                reasons.append("단기 역배열 (현재가 < MA20)")
    if breakout_direction == "UP":
        momentum += 15.0
        reasons.append("하락 추세선 상향 돌파 감지")
    elif breakout_direction == "DOWN":
        momentum -= 15.0
        reasons.append("상승 추세선 하향 이탈 감지")
    if support and support.slope > 0 and len(candles) >= 2:
        sup_cur = support.price_at(candles[-1].index)
        if candles[-1].close > sup_cur:
            momentum += 10.0
            reasons.append("상승 추세선 위 유지")
    components.momentum = max(0.0, min(100.0, momentum))

    # 3. Volume score
    vol_score = 50.0
    if len(volumes) >= 20 and sum(volumes) > 0:
        vol_avg20 = sum(volumes[-20:]) / 20
        vol_latest = volumes[-1]
        if vol_avg20 > 0:
            ratio = vol_latest / vol_avg20
            if ratio >= 2.0:
                vol_score = 85.0
                reasons.append(f"거래량 급증 ({ratio:.1f}x)")
            elif ratio >= 1.5:
                vol_score = 70.0
                reasons.append(f"거래량 증가 ({ratio:.1f}x)")
            elif ratio < 0.5:
                vol_score = 25.0
                reasons.append("거래량 감소 (신호 신뢰도 낮음)")
    components.volume = vol_score

    # 4. Market condition score (from regime)
    components.market_condition = market_regime_score

    # 5. Data quality
    if data_quality == "normal":
        components.data_quality = 100.0
    elif data_quality == "partial":
        components.data_quality = 60.0
        reasons.append("부분 데이터 — 점수 신뢰도 낮음")
    elif data_quality == "stale":
        components.data_quality = 30.0
        reasons.append("오래된 데이터 — 신호 불신뢰")
    else:
        components.data_quality = 0.0

    # 6. Penalty
    penalty = 0.0
    if len(closes) >= 14:
        # RSI
        gains = [max(closes[i] - closes[i-1], 0) for i in range(len(closes)-14, len(closes))]
        losses = [abs(min(closes[i] - closes[i-1], 0)) for i in range(len(closes)-14, len(closes))]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rsi = (100 - 100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100.0
        if rsi > 80:
            penalty = 20.0
            reasons.append(f"RSI 과열 ({rsi:.0f}) — 추격 진입 주의")
        elif rsi > 75:
            penalty = 10.0
    components.penalty = penalty

    # Weighted total
    # overlap×0.30 + momentum×0.25 + volume×0.20 + marketCondition×0.15 + dataQuality×0.10 − penalty
    dq_factor = components.data_quality / 100.0
    score = (
        components.overlap * 0.30
        + components.momentum * 0.25
        + components.volume * 0.20
        + components.market_condition * 0.15
        + components.data_quality * 0.10
        - components.penalty
    ) * dq_factor + (1 - dq_factor) * 30.0  # data quality degrades overall score

    score = max(0.0, min(100.0, round(score, 1)))

    # Direction
    direction = "neutral"
    if components.momentum >= 65:
        direction = "bullish"
    elif components.momentum <= 35:
        direction = "bearish"

    return score, direction, components, reasons


# ─── FSM State Transitions ────────────────────────────────────────────────────

def _update_fsm(
    current_status: str,
    score: float,
    direction: str,
    config: EngineConfig,
    consecutive_above: int,
    consecutive_below: int,
    current_index: int,
    confirmed_index: Optional[int],
    primary_level: Optional[float],
    current_price: float,
    zones_mitigated: bool = False,
) -> tuple[str, int, int, Optional[str]]:
    """
    FSM state transitions per blueprint §2.
    Returns (new_status, consecutive_above, consecutive_below, invalidation_reason).
    """
    invalidation_reason = None
    cfg = config

    # Structure break: mitigated zones → immediate invalidation
    if zones_mitigated and current_status in ("confirmed", "developing"):
        return "invalidated", 0, 0, "매물대 소멸 (구조 붕괴)"

    if current_status == "none":
        # none → developing: intraday signal observed
        if score >= 60:
            return "developing", 0, 0, None
        return "none", 0, 0, None

    elif current_status == "developing":
        if score >= cfg.confirmation_score_threshold:
            new_above = consecutive_above + 1
            if new_above >= cfg.debounce_bars:
                return "confirmed", new_above, 0, None
            return "developing", new_above, 0, None
        elif score < 60:
            return "invalidated", 0, 0, f"점수 급락 ({score:.0f}점 미만 60점)"
        return "developing", 0, 0, None

    elif current_status == "confirmed":
        # Score-based invalidation
        if score <= cfg.invalidation_score_threshold:
            new_below = consecutive_below + 1
            if new_below >= cfg.invalidation_bars:
                return "invalidated", 0, new_below, f"점수 하락 ({score:.0f}점 ≤ {cfg.invalidation_score_threshold:.0f}점) {new_below}봉 연속"
            return "confirmed", consecutive_above, new_below, None
        # Age expiry
        if confirmed_index is not None:
            age = current_index - confirmed_index
            if age > cfg.max_signal_age_bars:
                return "expired", 0, 0, f"신호 만료 ({age}봉 경과)"
        # Price distance expiry
        if primary_level and primary_level > 0 and current_price > 0:
            dist = abs(current_price - primary_level) / primary_level
            if dist > cfg.max_distance_pct_from_primary_level:
                return "expired", 0, 0, f"주가 이탈 ({dist*100:.1f}% > {cfg.max_distance_pct_from_primary_level*100:.0f}%)"
        return "confirmed", consecutive_above, 0, None

    # invalidated / expired: terminal
    return current_status, 0, 0, None


# ─── Forward Projection ───────────────────────────────────────────────────────

def _build_projection(
    candles: list[Candle],
    support: Optional[Trendline],
    resistance: Optional[Trendline],
    zones: list[SupplyDemandZone],
    rets: list[RetracementLevel],
    signal_status: str,
    confirmed_index: Optional[int],
    config: EngineConfig,
    horizon_bars: int = 50,
) -> ChartProjectionState:
    """
    Forward Projection layer — extends core signals into future (T+H).
    Does NOT modify any core analysis state (one-way flow).
    """
    T = len(candles) - 1
    to_index = T + horizon_bars
    current_price = candles[-1].close if candles else 0
    proj = ChartProjectionState(horizon_bars=horizon_bars, notes=list(COMPLIANCE_NOTES))

    # Extend trendlines
    if support:
        to_price = support.price_at(to_index)
        # Defensive rendering guard: ±50% divergence → active=False
        active = to_price > 0 and (abs(to_price - current_price) / current_price < 0.50 if current_price > 0 else False)
        proj.projected_trendlines.append(ProjectionLine(
            from_index=T, to_index=to_index,
            from_price=support.price_at(T), to_price=to_price,
            kind="support",
            source_status=signal_status,
            active=active,
        ))

    if resistance:
        to_price = resistance.price_at(to_index)
        active = to_price > 0 and (abs(to_price - current_price) / current_price < 0.50 if current_price > 0 else False)
        proj.projected_trendlines.append(ProjectionLine(
            from_index=T, to_index=to_index,
            from_price=resistance.price_at(T), to_price=to_price,
            kind="resistance",
            source_status=signal_status,
            active=active,
        ))

    # Extend zones
    for z in zones:
        proj.projected_zones.append(ProjectionZone(
            zone_id=z.zone_id,
            from_index=T, to_index=to_index,
            top=z.top, bottom=z.bottom,
            zone_type=z.zone_type,
            active=not z.is_mitigated,
        ))

    # Extend key retracement levels
    for r in rets:
        if r.is_key or r.ratio in (0.618, 0.786):
            to_price = r.price  # horizontal — same price
            active = abs(to_price - current_price) / current_price < 0.50 if current_price > 0 else False
            proj.projected_retracements.append(ProjectionLine(
                from_index=T, to_index=to_index,
                from_price=r.price, to_price=r.price,
                kind="retracement",
                source_status=signal_status,
                active=active,
            ))

    return proj


# ─── Chart Signal Score for Recommendation Integration ────────────────────────

def _calc_chart_signal_score(
    signal_status: str,
    direction: str,
    confluence_score: float,
    overlaps: list[OverlapSignal],
) -> tuple[float, str]:
    """
    Produces a 0~100 score for injection into quant_scanner finalScore.
    Also returns a tag string for display.
    """
    if signal_status == "confirmed":
        base = min(100.0, 50.0 + confluence_score * 0.5)
        overlap_bonus = min(20.0, len([o for o in overlaps if o.is_key]) * 10.0)
        score = min(100.0, base + overlap_bonus)
        if direction == "bullish":
            tag = "CHART_CONFIRMED_BULL"
        elif direction == "bearish":
            tag = "CHART_CONFIRMED_BEAR"
        else:
            tag = "CHART_CONFIRMED"
    elif signal_status == "developing":
        score = min(65.0, 30.0 + confluence_score * 0.35)
        tag = "CHART_DEVELOPING"
    elif signal_status == "invalidated":
        score = max(0.0, 20.0 - confluence_score * 0.1)
        tag = "CHART_INVALIDATED"
    elif signal_status == "expired":
        score = 30.0
        tag = "CHART_EXPIRED"
    else:
        score = max(0.0, confluence_score * 0.4)
        tag = "CHART_NEUTRAL" if score >= 30 else "NO_SIGNAL"

    return round(score, 1), tag


# ─── Main Engine Entry Point ───────────────────────────────────────────────────

def build_chart_analysis(
    rows: list[dict[str, Any]],
    symbol: str,
    market: str,
    market_regime_score: float = 50.0,
    prev_state: Optional[ChartAnalysisState] = None,
    config: Optional[EngineConfig] = None,
    horizon_bars: int = 50,
    freshness_reference_date: Optional[str] = None,
) -> ChartAnalysisState:
    """
    Main entry point. Builds complete ChartAnalysisState from OHLCV rows.
    Uses only data up to time T — no look-ahead bias.
    """
    cfg = config or EngineConfig()
    candles = _rows_to_candles(rows)

    state = ChartAnalysisState(symbol=symbol, market=market)
    state.evaluated_at = time.time()
    state.input_candle_count = len(candles)

    if len(candles) < 20:
        state.data_quality = "partial"
        state.warnings.append(f"봉 수 부족 ({len(candles)}개, 최소 20개 필요)")
        state.chart_signal_score, state.chart_signal_tag = 0.0, "NO_SIGNAL"
        return state

    # Data freshness check
    if candles:
        last_date = candles[-1].date
        if last_date:
            try:
                last_dt = datetime.strptime(last_date[:10], "%Y-%m-%d")
                reference_dt = datetime.now()
                if freshness_reference_date:
                    reference_dt = datetime.strptime(freshness_reference_date[:10], "%Y-%m-%d")
                days_old = (reference_dt - last_dt).days
                if days_old > 5:
                    state.data_quality = "stale"
                    state.warnings.append(f"OHLCV 오래됨 ({days_old}일 전)")
            except Exception:
                pass

    # ── Core Analysis (T only) ─────────────────────────────────────────────────
    pivots = _calc_zigzag(candles, cfg.zigzag_threshold_pct)
    state.completed_pivots = pivots

    support, resistance = _calc_trendlines(candles, pivots) if len(pivots) >= 4 else (None, None)
    state.support_line = support
    state.resistance_line = resistance

    rets = _calc_retracements(pivots) if len(pivots) >= 2 else []
    state.retracements = rets
    state.primary_retracement_level = next((r.price for r in rets if r.is_key), None)

    zones = _calc_supply_zones(candles)
    state.zones = zones

    overlaps = _find_overlap_signals(rets, zones, cfg.overlap_buffer_pct) if rets and zones else []
    state.overlap_signals = overlaps

    breakout_dir, _ = _detect_breakout(candles, support, resistance)
    state.breakout_direction = breakout_dir

    # Confluence
    score, direction, components, reasons = _calc_confluence(
        candles, pivots, support, resistance, zones, rets, overlaps,
        breakout_dir, market_regime_score, state.data_quality,
    )
    state.confluence_score = score
    state.confluence_direction = direction
    state.confluence_components = components
    state.confluence_reasons = reasons

    # FSM state transition
    prev_status = prev_state.signal_status if prev_state else "none"
    prev_above = prev_state.consecutive_above_threshold if prev_state else 0
    prev_below = prev_state.consecutive_below_invalidation if prev_state else 0
    prev_confirmed_idx = prev_state.confirmed_index if prev_state else None

    # Check if any zone is mitigated (price crossed through)
    current_price = candles[-1].close
    zones_mitigated = any(z.bottom <= current_price <= z.top for z in zones if z.zone_type == "supply")

    new_status, new_above, new_below, inv_reason = _update_fsm(
        prev_status, score, direction, cfg,
        prev_above, prev_below,
        len(candles) - 1, prev_confirmed_idx,
        state.primary_retracement_level, current_price,
        zones_mitigated,
    )

    state.signal_status = new_status
    state.consecutive_above_threshold = new_above
    state.consecutive_below_invalidation = new_below
    state.invalidation_reason = inv_reason

    if new_status == "confirmed" and prev_status != "confirmed":
        state.confirmed_index = len(candles) - 1
        state.created_index = prev_state.created_index if prev_state else len(candles) - 1
        state.expires_at_index = len(candles) - 1 + cfg.max_signal_age_bars
    elif prev_state:
        state.confirmed_index = prev_state.confirmed_index
        state.created_index = prev_state.created_index
        state.expires_at_index = prev_state.expires_at_index

    # Position sizing guardrail (blueprint §2)
    if new_status == "confirmed" and state.data_quality not in ("stale", "error"):
        state.capped_fraction = min(cfg.max_reference_fraction, score / 100.0 * cfg.max_reference_fraction)
        state.risk_status = "eligible"
    else:
        state.capped_fraction = 0.0  # hard lock when not confirmed
        state.risk_status = "none"

    # Chart signal score for recommendation integration
    state.chart_signal_score, state.chart_signal_tag = _calc_chart_signal_score(
        new_status, direction, score, overlaps,
    )

    # ── Forward Projection (T+H) ───────────────────────────────────────────────
    state.projection = _build_projection(
        candles, support, resistance, zones, rets,
        new_status, state.confirmed_index, cfg, horizon_bars,
    )

    return state


# ─── Serialization for API response ───────────────────────────────────────────

def state_to_dict(state: ChartAnalysisState) -> dict[str, Any]:
    """Convert ChartAnalysisState to JSON-serializable dict."""
    def pivot_d(p: Pivot) -> dict:
        return {"index": p.index, "price": p.price, "type": p.pivot_type, "date": p.date}

    def tl_d(t: Optional[Trendline]) -> Optional[dict]:
        if t is None:
            return None
        return {
            "slope": round(t.slope, 6), "intercept": round(t.intercept, 4),
            "startIndex": t.start_index, "endIndex": t.end_index,
            "startPrice": round(t.start_price, 4), "endPrice": round(t.end_price, 4),
        }

    def zone_d(z: SupplyDemandZone) -> dict:
        return {
            "id": z.zone_id, "zoneType": z.zone_type,
            "top": round(z.top, 4), "bottom": round(z.bottom, 4),
            "strengthScore": round(z.strength_score, 3),
            "isMitigated": z.is_mitigated,
        }

    def ret_d(r: RetracementLevel) -> dict:
        return {"ratio": r.ratio, "price": round(r.price, 4), "label": r.label, "isKey": r.is_key}

    def overlap_d(o: OverlapSignal) -> dict:
        return {"price": round(o.price, 4), "ratio": o.ratio, "isKey": o.is_key,
                "zoneStrength": round(o.zone_strength, 3), "label": o.label}

    def proj_line_d(p: ProjectionLine) -> dict:
        return {"fromIndex": p.from_index, "toIndex": p.to_index,
                "fromPrice": round(p.from_price, 4), "toPrice": round(p.to_price, 4),
                "kind": p.kind, "sourceStatus": p.source_status, "active": p.active}

    def proj_zone_d(p: ProjectionZone) -> dict:
        return {"zoneId": p.zone_id, "fromIndex": p.from_index, "toIndex": p.to_index,
                "top": round(p.top, 4), "bottom": round(p.bottom, 4),
                "zoneType": p.zone_type, "active": p.active}

    proj = state.projection
    projection_dict = None
    if proj:
        projection_dict = {
            "horizonBars": proj.horizon_bars,
            "projectedTrendlines": [proj_line_d(l) for l in proj.projected_trendlines],
            "projectedZones": [proj_zone_d(z) for z in proj.projected_zones],
            "projectedRetracements": [proj_line_d(r) for r in proj.projected_retracements],
            "notes": proj.notes,
        }

    comp = state.confluence_components
    return {
        "ok": state.data_quality != "error",
        "symbol": state.symbol,
        "market": state.market,
        "timeframe": state.timeframe,
        "evaluatedAt": round(state.evaluated_at, 3),
        "inputCandleCount": state.input_candle_count,
        "dataQuality": state.data_quality,
        "warnings": state.warnings,
        "lookaheadSafe": state.lookahead_safe,

        # Core analysis
        "completedPivots": [pivot_d(p) for p in state.completed_pivots[-20:]],  # last 20
        "supportLine": tl_d(state.support_line),
        "resistanceLine": tl_d(state.resistance_line),
        "breakoutDirection": state.breakout_direction,
        "breakoutStatus": state.breakout_status,
        "retracements": [ret_d(r) for r in state.retracements],
        "primaryRetracementLevel": state.primary_retracement_level,
        "zones": [zone_d(z) for z in state.zones],
        "overlapSignals": [overlap_d(o) for o in state.overlap_signals],

        # Confluence & FSM
        "confluenceScore": round(state.confluence_score, 1),
        "confluenceDirection": state.confluence_direction,
        "signalStatus": state.signal_status,
        "confluenceComponents": {
            "overlap": round(comp.overlap, 1),
            "momentum": round(comp.momentum, 1),
            "volume": round(comp.volume, 1),
            "marketCondition": round(comp.market_condition, 1),
            "dataQuality": round(comp.data_quality, 1),
            "penalty": round(comp.penalty, 1),
        },
        "confluenceReasons": state.confluence_reasons,

        # Signal lifecycle
        "confirmedIndex": state.confirmed_index,
        "createdIndex": state.created_index,
        "expiresAtIndex": state.expires_at_index,
        "invalidationReason": state.invalidation_reason,

        # Risk
        "cappedFraction": round(state.capped_fraction, 4),
        "riskStatus": state.risk_status,

        # Integration score
        "chartSignalScore": state.chart_signal_score,
        "chartSignalTag": state.chart_signal_tag,

        # Forward projection
        "projection": projection_dict,
    }
