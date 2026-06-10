from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from app.engine.dsg_signal_engine import (
        infer_kr_sector,
        get_theme_names,
        detect_leader_mode,
        get_pullback_state_from_ohlcv,
        sector_label_kr,
    )
    _DSG_AVAILABLE = True
except ImportError:
    _DSG_AVAILABLE = False

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

# ── 마켓 레짐 상수
REGIME_BULL   = "BULL"    # KOSPI 20일선 위, 최근 5일 상승
REGIME_BEAR   = "BEAR"    # KOSPI 20일선 아래, 최근 5일 하락
REGIME_SIDE   = "SIDE"    # 횡보 (나머지)


@dataclass(frozen=True)
class QuantContext:
    market: str
    mode: str
    horizon: str
    min_ohlcv_rows: int = 30


def normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODES else "balanced"


def normalize_horizon(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "long":
        return "mid"
    return text if text in HORIZONS else "swing"


def make_context(market: Any, mode: Any, horizon: Any) -> QuantContext:
    market_key = str(market or "kr").strip().lower()
    if market_key not in {"kr", "us"}:
        market_key = "kr"
    return QuantContext(market=market_key, mode=normalize_mode(mode), horizon=normalize_horizon(horizon))


def _num(value: Any) -> float | None:
    try:
        raw = str(value if value is not None else "").replace(",", "").replace("$", "").replace("원", "").replace("%", "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        value_float = float(raw)
        return None if math.isnan(value_float) else value_float
    except Exception:
        return None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size <= 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except Exception:
            continue
    return []


def load_ohlcv(repo_root: "Path | str", market: str, symbol: str) -> list[dict[str, Any]]:
    repo_root = Path(repo_root)
    candidates = [
        repo_root / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv",
        repo_root / "data" / "stockapp" / f"{market}_{symbol}_daily.csv",
        repo_root / "reports" / f"{market}_{symbol}_daily.csv",
    ]
    rows: list[dict[str, Any]] = []
    for path in candidates:
        rows = _read_csv(path)
        if rows:
            break
    rows.sort(key=lambda row: str(row.get("date") or row.get("Date") or row.get("날짜") or ""))
    return rows


def _series(rows: list[dict[str, Any]], key: str) -> list[float]:
    aliases = {
        "open": ["open", "Open", "시가"],
        "close": ["close", "Close", "종가"],
        "high": ["high", "High", "고가"],
        "low": ["low", "Low", "저가"],
        "volume": ["volume", "Volume", "거래량"],
    }[key]
    out: list[float] = []
    for row in rows:
        value = None
        for alias in aliases:
            value = _num(row.get(alias))
            if value is not None:
                break
        if value is not None:
            out.append(value)
    return out


def _ma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _momentum(values: list[float], period: int) -> float | None:
    if len(values) <= period or values[-period - 1] == 0:
        return None
    return (values[-1] - values[-period - 1]) / values[-period - 1] * 100


def _rsi(values: list[float], period: int = 14) -> float | None:
    """Wilder's Smoothed RSI — 업계 표준 (EMA 방식)"""
    if len(values) < period + 1:
        return None
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    # 초기 평균 (첫 period개)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # Wilder's smoothing (나머지 구간)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _atr(high: list[float], low: list[float], close: list[float], period: int = 14) -> float | None:
    if len(high) <= period or len(low) <= period or len(close) <= period:
        return None
    ranges: list[float] = []
    start = len(close) - period
    for idx in range(start, len(close)):
        previous_close = close[idx - 1]
        ranges.append(max(high[idx] - low[idx], abs(high[idx] - previous_close), abs(low[idx] - previous_close)))
    return sum(ranges) / period


def _mdd(values: list[float], period: int = 20) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    peak = window[0]
    worst = 0.0
    for value in window:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak * 100)
    return worst


def _stddev(values: list[float]) -> float | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _consecutive_up(values: list[float]) -> int:
    if len(values) < 2:
        return 0
    count = 0
    for idx in range(len(values) - 1, 0, -1):
        if values[idx] > values[idx - 1]:
            count += 1
        else:
            break
    return count


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  차트 패턴 인식 엔진
#  참고: 실전 주식 투자 차트 패턴 가이드북 (기술적 분석)
#  빅터 3대 원칙: ①종가 안착 ②거래량 컨플루언스(1.5×) ③손익비 우선(≥1:2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _find_local_minima(values: list[float], window: int = 3) -> list[int]:
    """window 내 최솟값 인덱스 반환"""
    result = []
    for i in range(window, len(values) - window):
        if values[i] == min(values[i - window:i + window + 1]):
            result.append(i)
    return result


def _find_local_maxima(values: list[float], window: int = 3) -> list[int]:
    """window 내 최댓값 인덱스 반환"""
    result = []
    for i in range(window, len(values) - window):
        if values[i] == max(values[i - window:i + window + 1]):
            result.append(i)
    return result


def detect_chart_patterns(rows: list[dict[str, Any]]) -> list[dict]:
    """
    PDF 가이드북 5개 차트 패턴 감지.
    반환: [{"pattern": str, "confidence": 0~100, "entry": float, "stop": float, "target": float, "desc": str}]
    빅터 원칙①: 종가(close) 기준만 사용
    빅터 원칙②: 돌파 거래량 20일평균 1.5배 이상 확인
    빅터 원칙③: 손익비(target-entry)/(entry-stop) >= 2.0
    """
    if not rows or len(rows) < 20:
        return []

    closes = _series(rows, "close")
    highs  = _series(rows, "high")
    lows   = _series(rows, "low")
    vols   = _series(rows, "volume")
    opens  = _series(rows, "open")
    if not closes or len(closes) < 20:
        return []

    current   = closes[-1]
    vol_ma20  = _ma(vols, min(20, len(vols))) or 1.0
    atr14     = _atr(highs, lows, closes, min(14, len(closes) - 1)) or (current * 0.02)
    patterns: list[dict] = []

    # ────────────────────────────────────────────────────
    # 패턴 1: 쌍바닥 (Double Bottom) — 상승 반전
    # 조건: 두 저점이 ±3% 내, 2번째 거래량 < 1번째, 중간 고점 돌파
    # ────────────────────────────────────────────────────
    if len(closes) >= 30:
        mins_idx = _find_local_minima(closes, window=3)
        if len(mins_idx) >= 2:
            # 최근 두 저점
            b1_i, b2_i = mins_idx[-2], mins_idx[-1]
            b1_price = closes[b1_i]
            b2_price = closes[b2_i]
            price_diff_pct = abs(b1_price - b2_price) / b1_price * 100
            # 중간 고점 (두 저점 사이)
            mid_highs = highs[b1_i:b2_i + 1] if b2_i > b1_i else []
            mid_peak  = max(mid_highs) if mid_highs else None
            # 두 번째 저점 이후 현재가
            b2_vol = vols[b2_i] if b2_i < len(vols) else 0
            b1_vol = vols[b1_i] if b1_i < len(vols) else 1
            vol_decrease = b2_vol < b1_vol * 1.1  # 2번째 저점 거래량 감소
            # 현재가가 중간 고점 근처 또는 이미 돌파 (빅터 원칙①: 종가 기준)
            if (mid_peak and price_diff_pct <= 4.0 and vol_decrease
                    and b2_i >= len(closes) - 25  # 최근 25봉 이내
                    and current >= mid_peak * 0.98):  # 종가 돌파 확인
                # 빅터 원칙②: 돌파 거래량 확인
                breakout_vol = vols[-1]
                vol_ok = breakout_vol >= vol_ma20 * 1.3
                stop   = b2_price * 0.985  # 두번째 저점 바로 아래
                target = mid_peak + (mid_peak - b2_price)  # 높이만큼 상향 투영
                rr = (target - current) / (current - stop) if current > stop else 0
                conf = 60
                if vol_ok:   conf += 20
                if rr >= 2:  conf += 15
                if price_diff_pct <= 2: conf += 5
                patterns.append({
                    "pattern": "DOUBLE_BOTTOM",
                    "confidence": min(conf, 100),
                    "entry": round(current, 0),
                    "stop":  round(stop, 0),
                    "target": round(target, 0),
                    "rr": round(rr, 2),
                    "desc": f"쌍바닥: 두 저점 ±{price_diff_pct:.1f}% | 중간 고점 종가 돌파",
                })

    # ────────────────────────────────────────────────────
    # 패턴 2: 역헤드앤숄더 (Inverse Head & Shoulders) — 상승 반전
    # 조건: 3개 저점 중 가운데(머리)가 가장 낮음, 양쪽 어깨 유사
    # ────────────────────────────────────────────────────
    if len(closes) >= 40:
        mins_idx = _find_local_minima(closes, window=4)
        if len(mins_idx) >= 3:
            ls_i, head_i, rs_i = mins_idx[-3], mins_idx[-2], mins_idx[-1]
            ls_p   = closes[ls_i]
            head_p = closes[head_i]
            rs_p   = closes[rs_i]
            shoulder_diff = abs(ls_p - rs_p) / ls_p * 100
            head_lower = head_p < ls_p and head_p < rs_p
            # 넥라인: 두 어깨 사이 고점들의 평균
            neck_highs = highs[ls_i:rs_i + 1] if rs_i > ls_i else []
            if neck_highs:
                neckline = sum(sorted(neck_highs)[-3:]) / 3  # 상위 3개 평균
            else:
                neckline = ls_p * 1.05
            # 오른쪽 어깨 이후 넥라인 돌파 여부 (빅터 원칙①: 종가 기준)
            if (head_lower and shoulder_diff <= 5.0
                    and rs_i >= len(closes) - 20
                    and current >= neckline * 0.99):
                breakout_vol = vols[-1]
                vol_ok = breakout_vol >= vol_ma20 * 1.4
                head_height = neckline - head_p
                target = neckline + head_height
                stop   = rs_p * 0.985
                rr = (target - current) / (current - stop) if current > stop else 0
                conf = 55
                if vol_ok:   conf += 20
                if rr >= 2:  conf += 15
                if shoulder_diff <= 3: conf += 10
                patterns.append({
                    "pattern": "INV_HEAD_SHOULDERS",
                    "confidence": min(conf, 100),
                    "entry": round(current, 0),
                    "stop":  round(stop, 0),
                    "target": round(target, 0),
                    "rr": round(rr, 2),
                    "desc": f"역헤드앤숄더: 어깨 대칭 {shoulder_diff:.1f}% | 넥라인 {neckline:,.0f} 돌파",
                })

    # ────────────────────────────────────────────────────
    # 패턴 3: 깃발형/페너트형 (Bull Flag / Pennant) — 상승 지속
    # 조건: 3봉+ 장대양봉 폴(극강 거래량) → 좁은 조정(거래량 급감) → 채널 상단 돌파
    # ────────────────────────────────────────────────────
    if len(closes) >= 20:
        # 폴 탐색: 최근 5~20봉 내 장대양봉(2%+) + 고거래량
        pole_i = None
        for i in range(max(0, len(closes) - 20), len(closes) - 5):
            candle_pct = (closes[i] - opens[i]) / opens[i] * 100 if opens[i] > 0 else 0
            if candle_pct >= 2.5 and vols[i] >= vol_ma20 * 1.8:
                pole_i = i
        if pole_i is not None:
            pole_height = closes[pole_i] - opens[pole_i]
            # 폴 이후 조정 구간
            consol = closes[pole_i + 1:]
            consol_vols = vols[pole_i + 1:]
            if len(consol) >= 3:
                consol_high = max(consol)
                consol_low  = min(consol)
                consol_range_pct = (consol_high - consol_low) / pole_height * 100 if pole_height > 0 else 999
                consol_vol_avg = sum(consol_vols) / len(consol_vols) if consol_vols else vol_ma20
                # 조정 구간: 폴 크기의 50% 이내 + 거래량 급감
                flag_ok = consol_range_pct <= 60 and consol_vol_avg < vol_ma20 * 0.85
                # 현재가 채널 상단 돌파 (빅터 원칙①: 종가 기준)
                breakout = current >= consol_high * 0.99
                if flag_ok and breakout:
                    vol_ok = vols[-1] >= vol_ma20 * 1.5  # 빅터 원칙②
                    target = consol_high + pole_height
                    stop   = consol_low * 0.99
                    rr = (target - current) / (current - stop) if current > stop else 0
                    conf = 60
                    if vol_ok:   conf += 20
                    if rr >= 2:  conf += 15
                    if consol_range_pct <= 30: conf += 5
                    patterns.append({
                        "pattern": "BULL_FLAG",
                        "confidence": min(conf, 100),
                        "entry": round(current, 0),
                        "stop":  round(stop, 0),
                        "target": round(target, 0),
                        "rr": round(rr, 2),
                        "desc": f"깃발형: 폴 +{pole_height/closes[pole_i]*100:.1f}% | 조정 {consol_range_pct:.0f}% | 채널 돌파",
                    })

    # ────────────────────────────────────────────────────
    # 패턴 4: 대칭삼각형 상향돌파 (Symmetrical Triangle Breakout) — 중립→상승
    # 조건: 고점 하강 + 저점 상승 수렴 → 70~80% 완성 시 거래량+돌파
    # ────────────────────────────────────────────────────
    if len(closes) >= 30:
        maxs_idx = _find_local_maxima(closes, window=3)
        mins_idx = _find_local_minima(closes, window=3)
        if len(maxs_idx) >= 2 and len(mins_idx) >= 2:
            # 최근 고점 하강 추세
            h1_i, h2_i = maxs_idx[-2], maxs_idx[-1]
            l1_i, l2_i = mins_idx[-2], mins_idx[-1]
            descend_highs = closes[h2_i] < closes[h1_i]
            ascend_lows   = closes[l2_i] > closes[l1_i]
            # 삼각형 시작 넓이와 현재 수렴률
            base_high = closes[h1_i]
            base_low  = closes[l1_i]
            base_width = base_high - base_low
            curr_width = max(current, closes[h2_i]) - min(current, closes[l2_i])
            converge_pct = curr_width / base_width if base_width > 0 else 1.0
            # 70~80% 수렴 구간 (빅터: 꼭짓점에 너무 근접 전 돌파)
            in_breakout_zone = 0.15 <= converge_pct <= 0.45
            # 상향 돌파: 현재가가 직전 하강 고점 위로 종가 안착
            upper_break = current > closes[h2_i] * 0.99
            if descend_highs and ascend_lows and in_breakout_zone and upper_break:
                vol_ok = vols[-1] >= vol_ma20 * 1.5  # 빅터 원칙②: 1.5배
                target = current + base_width  # 베이스 높이만큼 상방 투영
                stop   = closes[l2_i] * 0.985
                rr = (target - current) / (current - stop) if current > stop else 0
                conf = 50
                if vol_ok:   conf += 25
                if rr >= 2:  conf += 15
                if converge_pct <= 0.30: conf += 10
                patterns.append({
                    "pattern": "SYMM_TRIANGLE_UP",
                    "confidence": min(conf, 100),
                    "entry": round(current, 0),
                    "stop":  round(stop, 0),
                    "target": round(target, 0),
                    "rr": round(rr, 2),
                    "desc": f"대칭삼각형 상향돌파: 수렴 {converge_pct*100:.0f}% | 베이스 {base_width:,.0f}",
                })

    # ────────────────────────────────────────────────────
    # 빅터 원칙③ 최종 필터: 손익비 2.0 미만 패턴 제거
    # ────────────────────────────────────────────────────
    patterns = [p for p in patterns if p.get("rr", 0) >= 2.0]

    # 신뢰도 내림차순 정렬
    patterns.sort(key=lambda x: x["confidence"], reverse=True)
    return patterns


def indicators(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    open_prices = _series(rows, "open")
    close = _series(rows, "close")
    high = _series(rows, "high")
    low = _series(rows, "low")
    volume = _series(rows, "volume")
    latest = close[-1] if close else None
    ma20 = _ma(close, 20)
    ma60 = _ma(close, 60)
    ma20_prev = sum(close[-21:-1]) / 20 if len(close) >= 21 else None
    volume_ma20 = _ma(volume, 20)
    high52w = max(high[-252:]) if high else None
    bb_mid = ma20
    bb_std = _stddev(close[-20:]) if len(close) >= 20 else None
    bb_upper = (bb_mid + bb_std * 2) if bb_mid is not None and bb_std is not None else None
    bb_lower = (bb_mid - bb_std * 2) if bb_mid is not None and bb_std is not None else None
    bb_width = ((bb_upper - bb_lower) / bb_mid * 100) if bb_upper is not None and bb_lower is not None and bb_mid else None
    bb_percent_b = ((latest - bb_lower) / (bb_upper - bb_lower)) if latest is not None and bb_upper is not None and bb_lower is not None and bb_upper != bb_lower else None
    gap_up_pct = None
    if len(open_prices) >= 1 and len(close) >= 2 and close[-2] > 0:
        gap_up_pct = (open_prices[-1] - close[-2]) / close[-2] * 100

    # 볼린저 스퀴즈: 현재 bbWidth가 최근 20일 중 최저 수준
    bb_squeeze = False
    if bb_width is not None and len(close) >= 40:
        past_widths: list[float] = []
        for i in range(2, 22):
            if len(close) >= 20 + i:
                past_close = close[-(20 + i):-i]
                pmid = sum(past_close) / 20
                pstd_sq = sum((c - pmid) ** 2 for c in past_close) / 20
                pstd = pstd_sq ** 0.5
                pw = (pmid + pstd * 2 - (pmid - pstd * 2)) / pmid * 100 if pmid else 0
                past_widths.append(pw)
        if past_widths and bb_width <= min(past_widths) * 1.15:
            bb_squeeze = True

    ma5      = _ma(close, 5)
    ma5_prev = sum(close[-6:-1]) / 5  if len(close) >= 6  else None
    ma60_prev = sum(close[-61:-1]) / 60 if len(close) >= 61 else None
    atr14    = _atr(high, low, close)

    # 골든크로스/데드크로스: 오늘 ma5 vs ma20 / 어제 ma5_prev vs ma20_prev
    golden_cross = bool(
        ma5 is not None and ma20 is not None and
        ma5_prev is not None and ma20_prev is not None and
        ma5 > ma20 and ma5_prev <= ma20_prev
    )
    death_cross = bool(
        ma5 is not None and ma20 is not None and
        ma5_prev is not None and ma20_prev is not None and
        ma5 < ma20 and ma5_prev >= ma20_prev
    )
    mid_golden_cross = bool(
        ma20 is not None and ma60 is not None and
        ma20_prev is not None and ma60_prev is not None and
        ma20 > ma60 and ma20_prev <= ma60_prev
    )
    mid_death_cross = bool(
        ma20 is not None and ma60 is not None and
        ma20_prev is not None and ma60_prev is not None and
        ma20 < ma60 and ma20_prev >= ma60_prev
    )

    # 트레일링 스탑: 20일 최고가 − ATR×2
    recent_high20 = max(high[-20:]) if len(high) >= 20 else (max(high) if high else None)
    trailing_stop = None
    trailing_stop_pct = None
    if recent_high20 and atr14 and latest:
        trailing_stop = recent_high20 - atr14 * 2
        trailing_stop_pct = (latest - trailing_stop) / latest * 100 if trailing_stop > 0 else None

    return {
        "latest": latest,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": _ma(close, 120),
        "ma5Prev": ma5_prev,
        "ma20Prev": ma20_prev,
        "ma60Prev": ma60_prev,
        "rsi14": _rsi(close),
        "atr14": atr14,
        "mdd20": _mdd(close),
        "volumeValue": (latest * volume[-1]) if latest is not None and volume else None,
        "volumeRatio20": (volume[-1] / volume_ma20) if volume and volume_ma20 else None,
        "distanceToMa20": ((latest - ma20) / ma20 * 100) if latest is not None and ma20 else None,
        "distanceToMa60": ((latest - ma60) / ma60 * 100) if latest is not None and ma60 else None,
        "ma20Slope": ((ma20 - ma20_prev) / ma20_prev * 100) if ma20 is not None and ma20_prev else None,
        "recentMomentum5": _momentum(close, 5),
        "recentMomentum20": _momentum(close, 20),
        "high52w": high52w,
        "recentHigh20": recent_high20,
        "distanceTo52wHigh": ((latest - high52w) / high52w * 100) if latest is not None and high52w else None,
        "bbWidth20": bb_width,
        "bbPercentB": bb_percent_b,
        "bbSqueeze": bb_squeeze,
        "consecutiveUpDays": float(_consecutive_up(close)),
        "gapUpPct": gap_up_pct,
        "atr14Pct": (atr14 / latest * 100) if latest and atr14 else None,
        # v10.3 크로스 + 트레일링 스탑
        "goldenCross": golden_cross,
        "deathCross": death_cross,
        "midGoldenCross": mid_golden_cross,
        "midDeathCross": mid_death_cross,
        "trailingStop": trailing_stop,
        "trailingStopPct": trailing_stop_pct,
    }


def load_market_regime(repo_root: Path, market: str = "kr") -> dict[str, Any]:
    """
    benchmark_daily.csv에서 KOSPI/KOSDAQ 최근 데이터를 읽어 마켓 레짐을 판단.

    Returns:
        {
            "regime": "BULL" | "BEAR" | "SIDE",
            "label": "강세장" | "약세장" | "횡보장",
            "kospiLatest": float,
            "kospiMa20": float,
            "distanceToMa20Pct": float,   # 현재가/20일선 이격도 (%)
            "momentum5d": float,           # 최근 5일 수익률 (%)
            "scoreAdjust": float,          # 추천 점수 가산/감점 기준값
            "description": str,
        }
    """
    benchmark_key = "KOSPI" if market == "kr" else "NASDAQ"
    path = repo_root / "data" / "market" / "benchmark_daily.csv"
    rows: list[dict[str, Any]] = []
    if path.is_file():
        rows = _read_csv(path)

    # 해당 벤치마크 데이터만 필터 후 날짜 정렬
    filtered = [r for r in rows if str(r.get("benchmark", "")).upper() == benchmark_key]
    filtered.sort(key=lambda r: str(r.get("date", "")))

    closes = [_num(r.get("close")) for r in filtered]
    closes = [c for c in closes if c is not None]

    default = {
        "regime": REGIME_SIDE, "label": "횡보장", "kospiLatest": None,
        "kospiMa20": None, "distanceToMa20Pct": None, "momentum5d": None,
        "scoreAdjust": 0.0, "description": "벤치마크 데이터 부족 — 레짐 미적용",
    }
    if len(closes) < 20:
        return default

    latest = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    dist = (latest - ma20) / ma20 * 100 if ma20 else 0.0
    mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0

    # 레짐 판단: 20일선 위 + 최근 5일 양봉 → BULL
    if dist > 2.0 and mom5 > 1.0:
        regime, label, adjust = REGIME_BULL, "강세장", +8.0
        desc = f"{benchmark_key} 20일선 {dist:+.1f}%, 5일 수익 {mom5:+.1f}% → 강세 (공격/균형 우선)"
    elif dist > 0 and mom5 > 0:
        regime, label, adjust = REGIME_BULL, "약한 강세장", +3.0
        desc = f"{benchmark_key} 20일선 {dist:+.1f}%, 5일 수익 {mom5:+.1f}% → 완만한 강세"
    elif mom5 < -5.0 or dist < -5.0:
        regime, label, adjust = REGIME_BEAR, "급락장", -30.0
        desc = f"{benchmark_key} 20일선 {dist:+.1f}%, 5일 수익 {mom5:+.1f}% → 급락 이벤트 (신호 강력 억제)"
    elif dist < -2.0 or mom5 < -2.0:
        regime, label, adjust = REGIME_BEAR, "약세장", -18.0
        desc = f"{benchmark_key} 20일선 {dist:+.1f}%, 5일 수익 {mom5:+.1f}% → 약세 (보수 우선, 추천 축소)"
    else:
        regime, label, adjust = REGIME_SIDE, "횡보장", 0.0
        desc = f"{benchmark_key} 20일선 {dist:+.1f}%, 5일 수익 {mom5:+.1f}% → 횡보 (스윙 중심)"

    return {
        "regime": regime, "label": label, "kospiLatest": round(latest, 2),
        "kospiMa20": round(ma20, 2), "distanceToMa20Pct": round(dist, 2),
        "momentum5d": round(mom5, 2), "scoreAdjust": adjust, "description": desc,
    }


def _compute_sub_scores(ind: dict[str, float | None]) -> dict[str, float]:
    """
    7개 세부 점수를 0~100으로 계산.
    데이터 없으면 50(중립)으로 처리.
    """
    rsi = ind.get("rsi14")
    atr = ind.get("atr14")
    mdd = ind.get("mdd20")
    d20 = ind.get("distanceToMa20")
    d60 = ind.get("distanceToMa60")
    mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20")
    volume_ratio = ind.get("volumeRatio20")
    bb_percent_b = ind.get("bbPercentB")
    consecutive_up = ind.get("consecutiveUpDays")
    distance_52w = ind.get("distanceTo52wHigh")

    # ── upsideScore: 상승 여력 (0~100)
    # mom5/mom20 양수일수록, d20/d60 정배열일수록 높음
    upside = 50.0
    if mom5 is not None:
        upside += max(-15.0, min(20.0, mom5 * 1.5))
    if mom20 is not None:
        upside += max(-10.0, min(15.0, mom20 * 0.8))
    if d60 is not None and d60 > 0:
        upside += min(8.0, d60 * 0.4)
    if distance_52w is not None and -2.0 <= distance_52w <= 0:
        upside += 8.0
    upsideScore = max(0.0, min(100.0, upside))

    # ── riskScore: 리스크 안정성 (0~100, 높을수록 안전)
    # MDD 작을수록, ATR 적을수록, RSI 과열 아닐수록 높음
    risk = 60.0
    if mdd is not None:
        # mdd는 음수 (예: -8.5%)
        risk += max(-20.0, min(15.0, 15.0 + mdd * 1.2))
    if rsi is not None:
        if rsi > 80:
            risk -= 20.0
        elif rsi > 70:
            risk -= 10.0
        elif 40 <= rsi <= 65:
            risk += 8.0
    if bb_percent_b is not None and bb_percent_b > 1.0:
        risk -= 10.0
    if consecutive_up is not None and consecutive_up >= 5:
        risk -= 8.0
    riskScore = max(0.0, min(100.0, risk))

    # ── momentumScore: 추세/거래량 (0~100)
    momentum = 50.0
    if mom5 is not None:
        momentum += max(-12.0, min(18.0, mom5 * 1.2))
    if mom20 is not None:
        momentum += max(-8.0, min(12.0, mom20 * 0.6))
    if d20 is not None and d20 > 0:
        momentum += min(10.0, d20 * 0.5)
    if volume_ratio is not None and volume_ratio >= 2.0:
        momentum += 10.0
    momentumScore = max(0.0, min(100.0, momentum))

    # ── entryScore: 진입가 접근성 (0~100)
    # 20일선 이격도 -2%~+3% 구간이 최적 (눌림목 진입)
    entry = 50.0
    if d20 is not None:
        if -5.0 <= d20 <= 3.0:
            entry += 25.0   # 최적 눌림목 구간
        elif -8.0 <= d20 < -5.0:
            entry += 15.0   # 깊은 눌림, 아직 ok
        elif 3.0 < d20 <= 8.0:
            entry += 5.0    # 약간 오른 상태
        elif d20 > 8.0:
            entry -= 15.0   # 추격 위험
        elif d20 < -10.0:
            entry -= 10.0   # 너무 빠짐
    entryScore = max(0.0, min(100.0, entry))

    # ── rrScore: 손익비 점수 (0~100)
    # ATR 기반 예상 손익비 계산: 목표(1.5~2.5×ATR) / 손절(1~2×ATR)
    # ATR 없으면 MA 이격도 기반으로 추정
    rr = 50.0
    atr = ind.get("atr14")
    latest_px = ind.get("latest") or ind.get("ma5")
    if atr and latest_px and latest_px > 0 and atr > 0:
        # 기간별 예상 RR: 단기(1.5) / 스윙(2.0) / 중기(2.5)
        # 보수/균형/공격은 _score() 레벨에서 조정
        atr_pct = atr / latest_px * 100
        # ATR이 작을수록(안정) 더 유리한 RR 설정 가능
        if atr_pct < 1.0:    rr = 75.0   # 변동성 낮음 → RR 좋음
        elif atr_pct < 2.0:  rr = 65.0
        elif atr_pct < 3.5:  rr = 55.0
        elif atr_pct < 5.0:  rr = 45.0
        else:                rr = 35.0   # 변동성 너무 큼 → RR 불리
        # MA 이격도로 추가 보정: 60일선까지의 잠재 수익
        if d20 is not None and d60 is not None:
            potential = d60 - d20
            if potential > 5:  rr += min(15.0, potential * 0.8)
            elif potential < 0: rr -= min(15.0, abs(potential) * 0.6)
    else:
        # Fallback: MA 기반 추정
        if d20 is not None and d60 is not None:
            potential_reward = d60 - d20
            if potential_reward > 5:   rr += min(20.0, potential_reward * 1.0)
            elif potential_reward < 0: rr -= min(20.0, abs(potential_reward) * 0.8)
    rrScore = max(0.0, min(100.0, rr))

    # ── qualityScore: 기업 안정성 (0~100)
    # 재무 데이터(ROE) 있으면 우선 사용, 없으면 기술 지표 대리
    # ROE: 자기자본이익률 — 수익 창출 능력의 핵심 지표
    roe = ind.get("roe")  # 외부에서 주입된 재무 데이터 (있으면 사용)
    quality = 50.0
    if roe is not None:
        # ROE 기반 품질 점수
        if roe >= 20:    quality = 85.0
        elif roe >= 15:  quality = 75.0
        elif roe >= 10:  quality = 65.0
        elif roe >= 5:   quality = 55.0
        elif roe >= 0:   quality = 45.0
        else:            quality = 30.0  # 적자
    else:
        # Fallback: 기술 지표 대리 (MDD + MA 위치)
        if mdd is not None and mdd > -15.0:
            quality += 15.0
        if d60 is not None and d60 > -5.0:
            quality += 15.0
        if rsi is not None and 30 <= rsi <= 70:
            quality += 10.0
    qualityScore = max(0.0, min(100.0, quality))

    # ── newsRiskPenalty: 뉴스/공시 리스크 감점 (0~20)
    # 현재는 RSI 과열로 대리 측정 (뉴스 데이터 연결 전 임시)
    newsRisk = 0.0
    if rsi is not None and rsi > 80:
        newsRisk = 15.0  # 과열 = 호재 선반영 가능성
    elif rsi is not None and rsi > 75:
        newsRisk = 8.0

    return {
        "upsideScore": round(upsideScore, 1),
        "riskScore": round(riskScore, 1),
        "momentumScore": round(momentumScore, 1),
        "entryScore": round(entryScore, 1),
        "rrScore": round(rrScore, 1),
        "qualityScore": round(qualityScore, 1),
        "newsRiskPenalty": round(newsRisk, 1),
    }


# ── 레짐×전략별 동적 가중치
# 강세장(BULL): 상승여력·모멘텀 강조 / 약세장(BEAR): 리스크·품질 강조 / 횡보(SIDE): 균형
_REGIME_MODE_WEIGHTS: dict[str, dict[str, dict[str, float]]] = {
    "BULL": {
        "conservative": {
            "riskScore":       0.28,
            "momentumScore":   0.22,
            "upsideScore":     0.18,
            "entryScore":      0.15,
            "rrScore":         0.12,
            "qualityScore":    0.00,
            "newsRiskPenalty": 0.05,
        },
        "balanced": {
            "upsideScore":     0.30,
            "momentumScore":   0.22,
            "riskScore":       0.20,
            "rrScore":         0.15,
            "entryScore":      0.08,
            "qualityScore":    0.00,
            "newsRiskPenalty": 0.05,
        },
        "aggressive": {
            "upsideScore":     0.40,
            "momentumScore":   0.28,
            "rrScore":         0.14,
            "entryScore":      0.08,
            "riskScore":       0.05,
            "qualityScore":    0.00,
            "newsRiskPenalty": 0.05,
        },
    },
    "BEAR": {
        "conservative": {
            "riskScore":       0.45,
            "qualityScore":    0.20,
            "entryScore":      0.15,
            "rrScore":         0.10,
            "momentumScore":   0.05,
            "upsideScore":     0.00,
            "newsRiskPenalty": 0.05,
        },
        "balanced": {
            "riskScore":       0.35,
            "qualityScore":    0.18,
            "entryScore":      0.18,
            "rrScore":         0.15,
            "upsideScore":     0.09,
            "momentumScore":   0.00,
            "newsRiskPenalty": 0.05,
        },
        "aggressive": {
            "upsideScore":     0.28,
            "riskScore":       0.25,
            "rrScore":         0.18,
            "entryScore":      0.12,
            "momentumScore":   0.07,
            "qualityScore":    0.05,
            "newsRiskPenalty": 0.05,
        },
    },
    "SIDE": {
        "conservative": {
            "riskScore":       0.35,
            "entryScore":      0.20,
            "rrScore":         0.15,
            "momentumScore":   0.15,
            "qualityScore":    0.10,
            "upsideScore":     0.00,
            "newsRiskPenalty": 0.05,
        },
        "balanced": {
            "upsideScore":     0.25,
            "riskScore":       0.25,
            "rrScore":         0.20,
            "momentumScore":   0.15,
            "entryScore":      0.10,
            "qualityScore":    0.00,
            "newsRiskPenalty": 0.05,
        },
        "aggressive": {
            "upsideScore":     0.35,
            "momentumScore":   0.25,
            "rrScore":         0.15,
            "entryScore":      0.10,
            "riskScore":       0.10,
            "qualityScore":    0.00,
            "newsRiskPenalty": 0.05,
        },
    },
}
# 하위 호환 (기존 코드가 참조 시 SIDE 기본값 사용)
_MODE_WEIGHTS = _REGIME_MODE_WEIGHTS["SIDE"]

# ── 기간별 필터 기준 (정량)
_HORIZON_PRICE_BANDS: dict[str, dict[str, tuple[float, float]]] = {
    "short": {
        "entry_distance_pct":  (-5.0,  5.0),   # 현재가 대비 진입가 거리
        "stop_pct":            (-5.0, -2.5),    # 손절폭
        "target_pct":           (4.0,  8.0),    # 목표수익
        "min_rr":               1.5,
    },
    "swing": {
        "entry_distance_pct": (-10.0, 10.0),
        "stop_pct":            (-8.0, -5.0),
        "target_pct":           (8.0, 18.0),
        "min_rr":               1.8,
    },
    "mid": {
        "entry_distance_pct": (-15.0, 15.0),
        "stop_pct":           (-12.0, -7.0),
        "target_pct":          (15.0, 30.0),
        "min_rr":               2.0,
    },
}


def _score(
    ind: dict[str, float | None],
    context: QuantContext,
    regime: str = "SIDE",
) -> tuple[float, str]:
    """
    레짐×전략 동적 가중치 기반 finalScore 계산.
    BULL: 상승여력·모멘텀 강조 / BEAR: 리스크·품질 강조 / SIDE: 균형
    """
    sub = _compute_sub_scores(ind)
    regime_key = regime if regime in _REGIME_MODE_WEIGHTS else "SIDE"
    weights = _REGIME_MODE_WEIGHTS[regime_key].get(context.mode, _REGIME_MODE_WEIGHTS["SIDE"]["balanced"])
    notes: list[str] = []

    # 가중합 계산 (newsRiskPenalty는 감점)
    final = 0.0
    for key, w in weights.items():
        if key == "newsRiskPenalty":
            final -= sub[key] * w
        else:
            final += sub.get(key, 50.0) * w

    # 기간별 추가 보정
    rsi = ind.get("rsi14")
    d20 = ind.get("distanceToMa20")
    mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20")
    d60 = ind.get("distanceToMa60")
    mdd = ind.get("mdd20")
    volume_ratio = ind.get("volumeRatio20")
    bb_percent_b = ind.get("bbPercentB")
    bb_squeeze = ind.get("bbSqueeze")
    consecutive_up = ind.get("consecutiveUpDays")
    gap_up_pct = ind.get("gapUpPct")
    distance_52w = ind.get("distanceTo52wHigh")

    # ── 52주 신고가 돌파 가산 (이미 높지만 위가 열린 구간)
    if distance_52w is not None and -3.0 <= distance_52w <= 0 and volume_ratio is not None:
        if volume_ratio >= 2.0:
            final += 10.0
            notes.append("52주 신고가 돌파 + 거래량 급증")
        elif volume_ratio >= 1.5:
            final += 6.0
            notes.append("52주 신고가 근접")

    # ── 볼린저 스퀴즈 가산 (방향 폭발 임박)
    if bb_squeeze and bb_percent_b is not None:
        if bb_percent_b > 0.7:   # 상단 방향
            final += 8.0
            notes.append("볼린저 스퀴즈 상단 돌파")
        elif bb_percent_b > 0.5:  # 중립 이상
            final += 4.0
            notes.append("볼린저 스퀴즈 발산 중")

    # ── MA수렴 가산 (5·20·60일선 밀집 → 방향 폭발 임박)
    # 단독 수렴: 기간별 차등 / 스퀴즈 동반: 추가 가산
    _convergence = _ma_convergence(ind)
    if _convergence and (rsi is None or rsi < 75):
        if bb_squeeze:
            final += 10.0   # 스퀴즈 + 수렴 = 고확률 폭발
            notes.append("MA수렴 + 볼린저스퀴즈 = 폭발 임박")
        elif context.horizon == "swing":
            final += 7.0
            notes.append("3선 수렴 → 스윙 진입 준비")
        elif context.horizon == "mid":
            final += 6.0
            notes.append("3선 수렴 → 중기 추세 전환 준비")
        elif context.horizon == "short":
            final += 4.0
            notes.append("3선 수렴 확인")

    # ── 레짐 보정: BEAR 장에서 모멘텀 추격 억제
    if regime_key == "BEAR":
        if mom5 is not None and mom5 > 10.0:
            final -= 8.0
            notes.append("약세장 급등 추격 주의")
        if distance_52w is not None and distance_52w >= 0:
            final -= 5.0  # 약세장 신고가는 신뢰도 낮음
    elif regime_key == "BULL":
        if mom20 is not None and mom20 > 5.0 and (rsi is None or rsi < 75):
            final += 3.0   # 강세장 추세 동승 보너스

    if context.horizon == "short":
        # 단기: 진입가 접근성 + 단기 모멘텀 중요
        if d20 is not None and abs(d20) > 5.0:
            final -= 5.0
            notes.append("진입가 괴리 큼")
        if mom5 is not None and mom5 > 0:
            final += min(5.0, mom5 * 0.5)
        if rsi is not None and rsi > 80:
            final -= 8.0
            notes.append("RSI 과열")

    elif context.horizon == "swing":
        # 스윙: 눌림목 + 추세 유지
        if d20 is not None and -15.0 <= d20 <= -3.0:
            final += 5.0  # 눌림목 구간 가점
        if d60 is not None and d60 > -10.0:
            final += 3.0  # 60일선 위 유지

    elif context.horizon == "mid":
        # 중기: 방향성 + 재무 안정
        if d60 is not None and d60 > -5.0:
            final += 6.0
        if mdd is not None and mdd > -15.0:
            final += 4.0

    # 공격형 특별 차단 조건
    if context.mode == "aggressive":
        if rsi is not None and rsi > 80:
            final -= 12.0
            notes.append("공격형 과열 차단")
        if mom5 is not None and mom5 > 15.0:
            final -= 8.0
            notes.append("단기 급등 추격 주의")

    if consecutive_up is not None and consecutive_up >= 5 and volume_ratio is not None and volume_ratio < 0.7:
        final -= 12.0
        notes.append("5일 연속 상승 후 거래량 감소")
    if rsi is not None and rsi > 80 and bb_percent_b is not None and bb_percent_b > 1.0:
        final -= 15.0
        notes.append("RSI 과열 + 볼린저 상단 돌파")
    if gap_up_pct is not None and gap_up_pct >= 15.0:
        final -= 15.0
        notes.append("공시/이벤트성 갭상승 추격 금지")
    if distance_52w is not None and -2.0 <= distance_52w <= 0 and volume_ratio is not None and volume_ratio >= 2.0:
        final += 6.0
        notes.append("52주 고점 돌파 임박 + 거래량 확인")

    # 보수형 특별 가산 조건
    if context.mode == "conservative":
        if rsi is not None and 40 <= rsi <= 60:
            final += 5.0
        if d20 is not None and -3.0 <= d20 <= 2.0:
            final += 4.0  # 안정적 진입 구간

    score = max(0.0, min(100.0, round(final, 1)))
    return score, "; ".join(notes)


TAG_LABELS = {
    "BREAKOUT_52W": "52주 신고가 돌파",    # 실제 돌파 (d52>=0 + 거래량)
    "NEAR_52W_HIGH": "신고가 근접",        # 3% 이내 접근
    "BB_SQUEEZE": "볼린저 스퀴즈",         # 변동성 압축 → 방향 폭발 임박
    "PULLBACK_BUY": "눌림목 매수",
    "MA_CONVERGENCE": "이격도 수렴",
    "UNDERVALUED_GROWTH": "저평가 성장주",
    "VOLUME_BREAKOUT": "거래대금 증가",
    "MOMENTUM": "모멘텀 강세",
    "STABLE_LOW_RISK": "안정형",
    "CAUTION": "주의",
    "EV_NEGATIVE": "EV음수",
    # v10.3 신규 크로스 + 트레일링 스탑
    "GOLDEN_CROSS": "골든크로스",           # MA5 > MA20 단기 골든크로스
    "DEATH_CROSS": "데드크로스",            # MA5 < MA20 단기 데드크로스 (주의)
    "MID_GOLDEN_CROSS": "중기 골든크로스",  # MA20 > MA60 중기 골든크로스
    "MID_DEATH_CROSS": "중기 데드크로스",   # MA20 < MA60 중기 데드크로스 (주의)
    "TRAILING_STOP_ALERT": "트레일링 손절", # 20일 고점 ATR×2 이탈 근접
    # 차트 패턴 (PDF 가이드북)
    "DOUBLE_BOTTOM":      "쌍바닥 패턴",        # 상승 반전 — 두 저점 + 중간 고점 돌파
    "INV_HEAD_SHOULDERS": "역헤드앤숄더",        # 상승 반전 — 3저점 중 가운데 최저
    "BULL_FLAG":          "깃발형 돌파",         # 상승 지속 — 폴+조정+채널 상단 돌파
    "SYMM_TRIANGLE_UP":   "대칭삼각형 상향돌파", # 방향 확정 — 수렴 후 거래량 돌파
}


def _ma_convergence(ind: dict[str, float | None]) -> bool:
    """
    5/20/60일선 이격도가 동시 수렴 구간에 있을 때 True.
    세 이격도 모두 -3% ~ +3% 이내이면서 방향이 같은 경우.
    """
    d20 = ind.get("distanceToMa20")
    d60 = ind.get("distanceToMa60")
    ma5 = ind.get("ma5")
    ma20 = ind.get("ma20")
    latest = ind.get("distanceToMa20")  # 현재가 기준

    if d20 is None or d60 is None:
        return False
    # 5일/20일/60일 이격도 모두 -4% ~ +4% 이내 → 수렴
    d5 = None
    if ma5 is not None and ma20 is not None and ma20 > 0:
        # d5 계산: ma5 vs ma20 비율로 근사
        d5 = (ma5 - ma20) / ma20 * 100

    within_band = abs(d20) <= 4.0 and abs(d60) <= 6.0
    if d5 is not None:
        within_band = within_band and abs(d5) <= 3.0

    # 세 이격도 간 최대 차이가 5% 이내 → 밀집 구간
    vals = [v for v in [d5, d20, d60] if v is not None]
    spread = max(vals) - min(vals) if len(vals) >= 2 else 999
    return within_band and spread <= 5.0


def infer_supply_signal(ohlcv_rows: list[dict[str, Any]]) -> tuple[str | None, str]:
    """
    거래량 패턴으로 수급 신호 추론.
    실제 기관/외국인 데이터 없이 OHLCV만으로 근사.

    Returns
    -------
    (signal, reason)
    signal: "STRONG_BUY" | "INST_ACCUMULATE" | "SELL_PRESSURE" | "DISTRIBUTION" | None
    """
    if not ohlcv_rows or len(ohlcv_rows) < 10:
        return None, ""

    closes = _series(ohlcv_rows, "close")
    volumes = _series(ohlcv_rows, "volume")
    if len(closes) < 10 or len(volumes) < 10:
        return None, ""

    latest_close  = closes[-1]
    prev_close    = closes[-2]
    latest_vol    = volumes[-1]
    vol_ma20      = _ma(volumes, min(20, len(volumes))) or 1.0
    vol_ma5       = _ma(volumes, min(5,  len(volumes))) or 1.0
    price_chg_pct = (latest_close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

    vol_ratio_20 = latest_vol / vol_ma20 if vol_ma20 > 0 else 1.0
    vol_ratio_5  = latest_vol / vol_ma5  if vol_ma5  > 0 else 1.0

    # 3일 연속 거래량 증가 여부
    vol_trend_up = (
        len(volumes) >= 3
        and volumes[-1] > volumes[-2] > volumes[-3]
    )

    # ── 신호 판정
    # 1. 강한 매수세: 거래량 2.5배+ + 가격 상승
    if vol_ratio_20 >= 2.5 and price_chg_pct > 1.0:
        return "STRONG_BUY", f"거래량 {vol_ratio_20:.1f}배 + 가격 +{price_chg_pct:.1f}%"

    # 2. 기관 매집 추정: 3일 거래량 증가 + 가격 상승세
    if vol_trend_up and vol_ratio_5 >= 1.5 and price_chg_pct > 0:
        return "INST_BUY", f"3일 연속 거래량 증가 + 가격 상승"

    # 3. 매도 압력: 거래량 2배+ + 가격 하락
    if vol_ratio_20 >= 2.0 and price_chg_pct < -1.5:
        return "SELL_PRESSURE", f"거래량 {vol_ratio_20:.1f}배 + 가격 {price_chg_pct:.1f}%"

    # 4. 분산 매도: 3일 거래량 증가 + 가격 하락
    if vol_trend_up and vol_ratio_5 >= 1.3 and price_chg_pct < -0.5:
        return "DISTRIBUTION", "3일 거래량 증가 + 가격 하락 → 분산 매도 의심"

    return None, ""


def _compute_decision_bucket(
    score: float,
    ev: float | None,
    rsi: float | None,
    d20: float | None,
    rr_actual: float | None,
    mode: str,
    risk_flags: list[str],
) -> tuple[str, str]:
    """
    퀀트 지표 기반 진입/대기 결정 버킷.

    Returns (decisionBucket, decisionReason)
    ──────────────────────────────────────
    "오늘 진입"  : 즉시 진입 조건 완전 충족
    "대기 관찰"  : 진입 임박, 조건 일부 미충족
    "관찰"       : 중기 모니터링 단계
    "매수금지"   : 진입 절대 불가
    """
    # ── 매수금지 (최우선)
    block_flags = {"RSI_OVERHEATED", "GAP_UP_15PCT", "EV_NEGATIVE",
                   "BOLLINGER_UPPER_BREAK", "FIVE_DAY_UP_STREAK", "NEWS_DISCLOSURE_RISK"}
    if risk_flags and any(f in block_flags for f in risk_flags):
        bad = next(f for f in risk_flags if f in block_flags)
        labels = {
            "RSI_OVERHEATED": "RSI 80+ 과열",
            "GAP_UP_15PCT": "갭상승 15%+ 추격금지",
            "EV_NEGATIVE": "기댓값 음수",
            "BOLLINGER_UPPER_BREAK": "볼린저 상단 이탈",
            "FIVE_DAY_UP_STREAK": "5일 연속 상승 후 거래량 감소",
            "NEWS_DISCLOSURE_RISK": "공시/뉴스 리스크",
        }
        return "매수금지", labels.get(bad, bad)

    if rsi is not None and rsi > 85:
        return "매수금지", f"RSI {rsi:.0f} 극과열"
    if ev is not None and ev < -5.0:
        return "매수금지", f"기댓값 {ev:.1f}% 심각 음수"

    # ── 모드별 점수 기준
    thresholds = {
        "conservative": (70, 60),   # (진입최소, 대기최소)
        "balanced":     (62, 52),
        "aggressive":   (52, 42),
    }
    t_enter, t_watch = thresholds.get(mode, (62, 52))

    # ── 오늘 진입
    if (score >= t_enter
            and (ev is None or ev >= 1.0)
            and (rsi is None or rsi <= 78)
            and (d20 is None or -10.0 <= d20 <= 5.0)
            and (rr_actual is None or rr_actual >= 1.5)):
        ev_str = f", EV {ev:.1f}%" if ev is not None else ""
        return "오늘 진입", f"종합점수 {score:.0f}{ev_str}"

    # ── 대기 관찰
    if score >= t_watch and (ev is None or ev >= -1.0):
        if d20 is not None and d20 > 5.0:
            return "대기 관찰", f"진입가까지 약 {d20:.1f}% 남음"
        if ev is not None and ev < 1.0:
            return "대기 관찰", f"EV {ev:.1f}% (조건 보완 대기)"
        return "대기 관찰", f"점수 {score:.0f} (진입 조건 보완 중)"

    # ── 관찰
    ev_str = f", EV {ev:.1f}%" if ev is not None else ""
    return "관찰", f"점수 {score:.0f}{ev_str}"


def _strategy_tags(ind: dict[str, float | None], status: str) -> tuple[list[str], str, str]:
    tags: list[str] = []
    rsi = ind.get("rsi14")
    d20 = ind.get("distanceToMa20")
    d60 = ind.get("distanceToMa60")
    mom5 = ind.get("recentMomentum5")
    mom20 = ind.get("recentMomentum20")
    atr = ind.get("atr14")
    mdd = ind.get("mdd20")
    volume_value = ind.get("volumeValue")
    volume_ratio = ind.get("volumeRatio20")
    bb_percent_b = ind.get("bbPercentB")
    consecutive_up = ind.get("consecutiveUpDays")
    gap_up_pct = ind.get("gapUpPct")
    distance_52w = ind.get("distanceTo52wHigh")
    bb_squeeze = ind.get("bbSqueeze")
    # v10.3 크로스 + 트레일링 스탑 시그널
    golden_cross     = bool(ind.get("goldenCross", False))
    death_cross      = bool(ind.get("deathCross", False))
    mid_golden_cross = bool(ind.get("midGoldenCross", False))
    mid_death_cross  = bool(ind.get("midDeathCross", False))
    trailing_stop_pct = ind.get("trailingStopPct")

    if status in {"PRICE_PENDING", "DATA_PENDING"}:
        tags.append("CAUTION")

    # ── 골든크로스 (MA5 > MA20 교차)
    if golden_cross and (rsi is None or rsi < 75):
        tags.append("GOLDEN_CROSS")
    # ── 중기 골든크로스 (MA20 > MA60 교차)
    if mid_golden_cross and not death_cross:
        tags.append("MID_GOLDEN_CROSS")
    # ── 데드크로스 (MA5 < MA20 교차, 하락 전환)
    if death_cross:
        tags.append("DEATH_CROSS")
    # ── 중기 데드크로스 (MA20 < MA60 교차)
    if mid_death_cross:
        tags.append("MID_DEATH_CROSS")
    # ── 트레일링 스탑 근접 경보 (5% 이내)
    if trailing_stop_pct is not None and 0 < trailing_stop_pct <= 5.0:
        tags.append("TRAILING_STOP_ALERT")

    # ── 52주 신고가 돌파 (실제 신고가 이상 + 거래량)
    if distance_52w is not None and distance_52w >= 0 and volume_ratio is not None and volume_ratio >= 1.5:
        tags.append("BREAKOUT_52W")
    # 52주 신고가 근접 (3% 이내) — 돌파와 구분
    elif distance_52w is not None and -3.0 <= distance_52w < 0 and volume_ratio is not None and volume_ratio >= 1.3:
        tags.append("NEAR_52W_HIGH")

    # ── 볼린저 스퀴즈 (변동성 압축 → 방향 폭발 임박)
    if bb_squeeze and bb_percent_b is not None and bb_percent_b > 0.5:
        tags.append("BB_SQUEEZE")

    # ── 이격도 수렴 신호
    if _ma_convergence(ind) and (rsi is None or rsi < 75):
        tags.append("MA_CONVERGENCE")

    if d20 is not None and -8 <= d20 <= 3 and (rsi is None or rsi < 80):
        tags.append("PULLBACK_BUY")
    if volume_ratio is not None and volume_ratio >= 1.5:
        tags.append("VOLUME_BREAKOUT")
    if (mom5 is not None and mom5 > 3) or (mom20 is not None and mom20 > 8):
        tags.append("MOMENTUM")
    if atr is not None and mdd is not None and mdd > -12 and (d60 is None or d60 > -8):
        tags.append("STABLE_LOW_RISK")
    if distance_52w is not None and -2 <= distance_52w <= 0 and volume_ratio is not None and volume_ratio >= 2:
        tags.append("MOMENTUM")
        tags.append("VOLUME_BREAKOUT")
    if (
        (rsi is not None and rsi >= 80)
        or (bb_percent_b is not None and bb_percent_b > 1)
        or (gap_up_pct is not None and gap_up_pct >= 15)
        or (consecutive_up is not None and consecutive_up >= 5 and volume_ratio is not None and volume_ratio < 0.7)
        or death_cross      # 데드크로스 → 주의
        or mid_death_cross  # 중기 데드크로스 → 주의
    ):
        tags.append("CAUTION")

    unique = []
    for tag in tags or ["CAUTION"]:
        if tag not in unique:
            unique.append(tag)
    primary = unique[0]
    return unique, primary, TAG_LABELS.get(primary, primary)


def score_candidate(
    row: dict[str, Any],
    ohlcv_rows: list[dict[str, Any]],
    context: QuantContext,
    regime: str = "SIDE",
) -> dict[str, Any]:
    symbol = row.get("symbol") or row.get("ticker") or row.get("code")

    # 현재가: row에 없으면 OHLCV 최신 close로 fallback
    current = _num(row.get("currentPrice") or row.get("current_price") or row.get("currentPriceText"))
    current_source = "live"
    if current is None and ohlcv_rows:
        closes = [_num(r.get("close") or r.get("Close") or r.get("종가")) for r in ohlcv_rows]
        closes = [c for c in closes if c is not None]
        if closes:
            current = closes[-1]
            current_source = "ohlcv_close"

    if current is None:
        return {
            "symbol": symbol, "market": context.market, "mode": context.mode,
            "horizon": context.horizon, "score": None,
            "dataStatus": "PRICE_PENDING", "reason": "현재가 수집 대기",
        }
    if len(ohlcv_rows or []) < context.min_ohlcv_rows:
        return {
            "symbol": symbol, "market": context.market, "mode": context.mode,
            "horizon": context.horizon, "score": None,
            "dataStatus": "DATA_PENDING", "reason": f"OHLCV {context.min_ohlcv_rows}거래일 미만",
        }

    ind = indicators(ohlcv_rows)
    score, note = _score(ind, context, regime=regime)
    sub = _compute_sub_scores(ind)
    status = "NORMAL" if all(ind.get(key) is not None for key in ("ma5", "ma20", "rsi14", "atr14")) else "PARTIAL"
    if current_source == "ohlcv_close":
        status = "PARTIAL"  # 현재가가 live가 아님을 표시

    # ── Phase 6: 뉴스/공시 감성 신호 통합 (차트 분석 앞에 실행) ────────────────
    news_sentiment_tag = "NEUTRAL"
    news_sentiment_reasons: list = []
    _news_penalty_for_chart = 0.0
    try:
        from app.engine.news_sentiment_engine import score_news_sentiment, load_sentiment_cache
        _name = str(row.get("name") or row.get("종목명") or "")
        if not hasattr(score_candidate, "_sentiment_cache"):
            score_candidate._sentiment_cache = {}  # type: ignore[attr-defined]
        _mkt = context.market
        if _mkt not in score_candidate._sentiment_cache:  # type: ignore[attr-defined]
            score_candidate._sentiment_cache[_mkt] = load_sentiment_cache(_mkt)  # type: ignore[attr-defined]
        _sent = score_news_sentiment(
            _mkt, str(symbol or ""), _name,
            cache=score_candidate._sentiment_cache[_mkt],  # type: ignore[attr-defined]
        )
        _news_penalty_for_chart = float(_sent.get("penalty", 0.0))
        news_sentiment_tag = str(_sent.get("tag", "NEUTRAL"))
        news_sentiment_reasons = list(_sent.get("reasons", []))

        if _sent.get("disclosureHits", 0) > 0 or abs(_sent.get("newsAdj", 0.0)) > 0.5:
            sub["newsRiskPenalty"] = _news_penalty_for_chart

        if news_sentiment_tag == "HIGH_RISK":
            score = max(0.0, round(score - 8.0, 1))
            reasons_str = ", ".join(news_sentiment_reasons[:2])
            note = (note + f"; 공시 리스크({reasons_str})").lstrip("; ")
        elif news_sentiment_tag == "POSITIVE" and _news_penalty_for_chart <= 0:
            score = min(100.0, round(score + 3.0, 1))
            reasons_str = ", ".join(news_sentiment_reasons[:2])
            if reasons_str:
                note = (note + f"; 긍정 공시({reasons_str})").lstrip("; ")
    except Exception:
        pass

    # ── Phase 6: 차트 분석 신호 통합 (뉴스 패널티 반영) ──────────────────────
    chart_signal_score = 0.0
    chart_signal_tag = "NO_SIGNAL"
    chart_signal_status = "none"
    chart_signal_direction = "neutral"
    chart_confluence_score = 0.0
    chart_overlap_signals: list = []
    try:
        from app.engine.chart_analysis_engine import build_chart_analysis
        _regime_score_map = {"BULL": 70.0, "BEAR": 30.0, "SIDE": 50.0}
        _chart_state = build_chart_analysis(
            rows=ohlcv_rows,
            symbol=str(symbol or ""),
            market=context.market,
            market_regime_score=_regime_score_map.get(regime, 50.0),
            news_penalty=_news_penalty_for_chart,
        )
        chart_signal_score = _chart_state.chart_signal_score
        chart_signal_tag = _chart_state.chart_signal_tag
        chart_signal_status = _chart_state.signal_status
        chart_signal_direction = _chart_state.confluence_direction
        chart_confluence_score = _chart_state.confluence_score
        chart_overlap_signals = [
            {"price": o.price, "ratio": o.ratio, "isKey": o.is_key, "label": o.label}
            for o in _chart_state.overlap_signals
        ]
        if chart_signal_status == "confirmed":
            if chart_signal_direction == "bullish":
                score = min(100.0, round(score + 12.0, 1))
                if "차트 확정 매수 신호" not in note:
                    note = (note + "; 차트 확정 매수 신호 (Phase 6)").lstrip("; ")
            elif chart_signal_direction == "bearish":
                score = max(0.0, round(score - 10.0, 1))
                note = (note + "; 차트 확정 매도 신호 (Phase 6 — 진입 주의)").lstrip("; ")
        elif chart_signal_status == "developing" and chart_signal_direction == "bullish":
            score = min(100.0, round(score + 5.0, 1))
            note = (note + "; 차트 신호 발달 중 (Phase 6)").lstrip("; ")
        elif chart_signal_status == "invalidated":
            score = max(0.0, round(score - 8.0, 1))
            note = (note + "; 차트 신호 무효화 (Phase 6 — 진입 보류)").lstrip("; ")
    except Exception:
        pass

    # 기간별 price band 기준
    band = _HORIZON_PRICE_BANDS.get(context.horizon, _HORIZON_PRICE_BANDS["swing"])

    # 진입가: 원본 있으면 사용, 없으면 현재가 기준 이격도로 산출
    entry_raw = _num(row.get("entry") or row.get("entryPrice") or row.get("entry_price"))
    stop_raw = _num(row.get("stop") or row.get("stopLoss") or row.get("stop_loss"))
    target_raw = _num(row.get("target") or row.get("targetPrice") or row.get("target_price"))

    # 진입가가 현재가와 괴리가 너무 크면 (15% 이상) 현재가 기준으로 재산출
    entry_recomputed = False
    if entry_raw and current and current > 0:
        gap_pct = abs(entry_raw - current) / current * 100.0
        if gap_pct > 15.0:
            # 현재가 기준 재산출 (기간별 band 중간값 사용)
            band_entry_max = band["entry_distance_pct"][1]  # 최대 허용 괴리
            entry_raw = current * (1.0 + min(band_entry_max / 100.0, 0.05))
            stop_raw = None  # 재산출 필요
            target_raw = None
            entry_recomputed = True

    if not entry_raw and current:
        entry_raw = current
        entry_recomputed = True

    # 손절/목표 재산출 (없거나 재계산 필요할 때)
    _mode_risk = {"conservative": 0.85, "balanced": 1.0, "aggressive": 1.20}
    _mode_reward = {"conservative": 0.80, "balanced": 1.0, "aggressive": 1.30}
    _horizon_mid = {
        "short": {"stop": 0.961, "target": 1.060},
        "swing": {"stop": 0.935, "target": 1.130},
        "mid":   {"stop": 0.905, "target": 1.220},
    }
    hmid = _horizon_mid.get(context.horizon, _horizon_mid["swing"])
    rf = _mode_risk.get(context.mode, 1.0)
    rwf = _mode_reward.get(context.mode, 1.0)

    if entry_raw and (not stop_raw or stop_raw <= 0):
        raw_stop_pct = 1.0 - hmid["stop"]
        stop_raw = entry_raw * (1.0 - raw_stop_pct * rf)
    if entry_raw and (not target_raw or target_raw <= 0):
        raw_target_pct = hmid["target"] - 1.0
        target_raw = entry_raw * (1.0 + raw_target_pct * rwf)

    # EV (기댓값) 계산
    # ── 승률 보정: score는 기술적 품질 점수이지 승률이 아님
    # 실증 연구 기준: 기술적 전략 승률 범위 ≈ 45%~58%
    # score 50 → 50%, score 100 → 57.5% (선형 보정)
    # 기간별 베이스 조정: 단기(더 불확실) < 스윙 < 중기
    _HORIZON_BASE_WIN = {"short": 0.485, "swing": 0.505, "mid": 0.515}
    _HORIZON_SCALE   = {"short": 0.12,  "swing": 0.14,  "mid":  0.15}
    horizon_base = _HORIZON_BASE_WIN.get(context.horizon, 0.505)
    horizon_scale = _HORIZON_SCALE.get(context.horizon, 0.14)
    # prob = base + (score-50)/50 * scale → [base-scale, base+scale]
    calibrated_prob = horizon_base + ((score - 50.0) / 50.0) * horizon_scale
    calibrated_prob = max(0.35, min(0.65, calibrated_prob))   # 35~65% 하드 클램프

    ev = None
    rr_actual = None
    min_rr = {"short": 1.5, "swing": 1.8, "mid": 2.0}.get(context.horizon, 1.5)
    rr_ok = False

    if entry_raw and stop_raw and target_raw and entry_raw > 0 and stop_raw > 0 and target_raw > entry_raw:
        reward_pct = (target_raw - entry_raw) / entry_raw * 100.0
        risk_pct = abs((entry_raw - stop_raw) / entry_raw * 100.0)
        if risk_pct > 0:
            rr_actual = round(reward_pct / risk_pct, 2)
            rr_ok = rr_actual >= min_rr
            ev = round(calibrated_prob * reward_pct - (1 - calibrated_prob) * risk_pct, 2)

    risk_flags: list[str] = []
    technical_signals: list[str] = []
    if ind.get("bbWidth20") is not None:
        technical_signals.append("BOLLINGER_READY")
    if ind.get("bbPercentB") is not None and ind["bbPercentB"] > 1:
        risk_flags.append("BOLLINGER_UPPER_BREAK")
    # 52주 신고가: 근접과 돌파 구분
    d52w = ind.get("distanceTo52wHigh")
    if d52w is not None:
        if d52w >= 0:
            technical_signals.append("BREAKOUT_52W")      # 실제 돌파
        elif d52w >= -3.0:
            technical_signals.append("NEAR_52W_HIGH")     # 근접
    # 최소 RR 미달 경고
    if not rr_ok and rr_actual is not None:
        risk_flags.append(f"RR_BELOW_MIN_{min_rr}")
    if ind.get("volumeRatio20") is not None and ind["volumeRatio20"] >= 2:
        technical_signals.append("VOLUME_2X")
    if ind.get("consecutiveUpDays") is not None and ind["consecutiveUpDays"] >= 5:
        risk_flags.append("FIVE_DAY_UP_STREAK")
    if ind.get("gapUpPct") is not None and ind["gapUpPct"] >= 15:
        risk_flags.append("GAP_UP_15PCT")
    if ind.get("rsi14") is not None and ind["rsi14"] >= 80:
        risk_flags.append("RSI_OVERHEATED")
    # 이격도 수렴 신호
    if _ma_convergence(ind):
        technical_signals.append("MA_CONVERGENCE")
    # EV 음수 플래그
    ev_negative = ev is not None and ev < 0

    if ev_negative:
        risk_flags.append("EV_NEGATIVE")

    return {
        "symbol": symbol,
        "market": context.market,
        "mode": context.mode,
        "horizon": context.horizon,
        "score": score,
        "finalScore": score,
        "upsideScore": sub["upsideScore"],
        "riskScore": sub["riskScore"],
        "momentumScore": sub["momentumScore"],
        "entryScore": sub["entryScore"],
        "rrScore": sub["rrScore"],
        "qualityScore": sub["qualityScore"],
        "newsRiskPenalty": sub["newsRiskPenalty"],
        "expectedValue": ev,
        "evNegative": ev_negative,
        "rrActual": rr_actual,
        "currentPriceUsed": current,
        "currentPriceSource": current_source,
        "entryRecomputed": entry_recomputed,
        "entryUsed": round(entry_raw) if entry_raw else None,
        "stopUsed": round(stop_raw) if stop_raw else None,
        "targetUsed": round(target_raw) if target_raw else None,
        "priceBand": band,
        "dataStatus": status,
        "reason": note,
        "riskFlags": risk_flags,
        "technicalSignals": technical_signals,
        "indicators": ind,
        "maConvergence": _ma_convergence(ind),
        "regime": regime,
        # Phase 6 차트 분석 신호
        "chartSignalScore": chart_signal_score,
        "chartSignalTag": chart_signal_tag,
        "chartSignalStatus": chart_signal_status,
        "chartSignalDirection": chart_signal_direction,
        "chartConfluenceScore": chart_confluence_score,
        "chartOverlapSignals": chart_overlap_signals,
        # Phase 6 뉴스/공시 감성 신호
        "newsSentimentTag": news_sentiment_tag,
        "newsSentimentReasons": news_sentiment_reasons,
        # 수급 신호 (거래량 패턴 기반 추론)
        **dict(zip(
            ("supplySignal", "supplySignalReason"),
            infer_supply_signal(ohlcv_rows),
        )),
    }


def apply_quant_overlay(item: dict[str, Any], repo_root: Path, mode: str, horizon: str) -> dict[str, Any]:  # noqa: C901
    market = str(item.get("market") or "kr").lower()
    symbol = str(item.get("symbol") or "").upper()
    context = make_context(market, mode, horizon)
    _ohlcv = load_ohlcv(repo_root, market, symbol)
    # 마켓 레짐 로드 (점수 가중치 결정)
    try:
        _regime_data = load_market_regime(repo_root, market)
        _regime = _regime_data.get("regime", "SIDE")
    except Exception:
        _regime = "SIDE"
    result = score_candidate(item, _ohlcv, context, regime=_regime)
    computed = list(item.get("computedFields") or [])
    computed.append("quant_scanner_v2")

    out = {
        **item,
        # 전략별 finalScore 및 세부 점수
        "quantScore": result.get("score"),
        "finalScore": result.get("finalScore"),
        "upsideScore": result.get("upsideScore"),
        "riskScore": result.get("riskScore"),
        "momentumScore": result.get("momentumScore"),
        "entryScore": result.get("entryScore"),
        "rrScore": result.get("rrScore"),
        "qualityScore": result.get("qualityScore"),
        "newsRiskPenalty": result.get("newsRiskPenalty"),
        # EV 및 실제 손익비
        "expectedValue": result.get("expectedValue"),
        "rrActual": result.get("rrActual"),
        # 기간별 price band 기준
        "priceBand": result.get("priceBand"),
        "quantDataStatus": result.get("dataStatus"),
        "quantReason": result.get("reason", ""),
        "riskFlags": result.get("riskFlags", []),
        "technicalSignals": result.get("technicalSignals", []),
        "maConvergence": result.get("maConvergence", False),
        "evNegative": result.get("evNegative", False),
        "indicators": result.get("indicators", {}),
        "regime": _regime,
        "supplySignal": result.get("supplySignal"),
        "supplySignalReason": result.get("supplySignalReason", ""),
        "computedFields": computed,
    }
    # 뉴스/공시 감성 — CSV 파일에서 실데이터 우선, 없으면 텍스트 키워드 fallback
    real_news_penalty = _num(item.get("newsRiskPenalty") or item.get("eventRiskScore"))
    if real_news_penalty is not None and real_news_penalty > 0:
        # generate_kr_recommendations.py에서 이미 계산된 실제 감성 점수 사용
        out["newsRiskPenalty"] = real_news_penalty
        out["newsSentimentSource"] = item.get("newsSentimentSource", "csv")
        if real_news_penalty >= 10.0:
            out.setdefault("riskFlags", []).append("NEWS_DISCLOSURE_RISK")
    else:
        # Fallback: 텍스트 키워드 스캔
        event_text = " ".join(
            str(item.get(key) or "")
            for key in ("warning_reason", "warningReason", "newsSummary", "disclosureTitle", "eventBadgesText", "riskReason", "surgeLabel")
        )
        _RISK_KW = ("공시주의", "유상증자", "감자", "소송", "관리종목", "상장폐지", "횡령", "배임", "전환사채")
        if any(kw in event_text for kw in _RISK_KW):
            penalty = 12.0
            out["newsRiskPenalty"] = min(20.0, float(out.get("newsRiskPenalty") or 0) + penalty)
            if isinstance(out.get("finalScore"), (int, float)):
                out["finalScore"] = max(0.0, round(float(out["finalScore"]) - penalty * 0.3, 1))
                out["quantScore"] = out["finalScore"]
            out.setdefault("riskFlags", []).append("NEWS_DISCLOSURE_RISK")
            out.setdefault("computedFields", []).append("news_keyword_risk_penalty")

    # 현재가 fallback 반영 (OHLCV close 사용 시)
    current_source = result.get("currentPriceSource", "live")
    if current_source == "ohlcv_close":
        used_price = result.get("currentPriceUsed")
        if used_price and not out.get("currentPrice"):
            out["currentPrice"] = used_price
            out["currentPriceText"] = f"{int(used_price):,}원" if market == "kr" else f"${used_price:,.2f}"
            out.setdefault("computedFields", []).append("current_price_from_ohlcv")
        computed.append("current_price_from_ohlcv")

    # 진입가 재산출 시 item에 반영
    if result.get("entryRecomputed") and result.get("entryUsed"):
        entry_used = result["entryUsed"]
        stop_used = result.get("stopUsed")
        target_used = result.get("targetUsed")
        # 원본보다 재산출값이 더 신뢰할 때만 덮어씀
        if entry_used and entry_used > 0:
            out["entry"] = entry_used
            out["entryText"] = f"{entry_used:,}원" if market == "kr" else f"${entry_used:,.2f}"
        if stop_used and stop_used > 0:
            out["stop"] = stop_used
            out["stopText"] = f"{stop_used:,}원" if market == "kr" else f"${stop_used:,.2f}"
        if target_used and target_used > 0:
            out["target"] = target_used
            out["targetText"] = f"{target_used:,}원" if market == "kr" else f"${target_used:,.2f}"
        computed.append("entry_recomputed_from_current")

    if result.get("score") is not None:
        base_prob = _num(out.get("probability")) or 0
        # 세부 점수 기반 확률 보정 (기존보다 정교화)
        score_val = float(result["score"])
        adjustment = (score_val - 50.0) * 0.15  # 기존 0.12 → 0.15로 민감도 높임
        probability = max(35.0, min(80.0, round(base_prob + adjustment, 1)))
        out["probability"] = probability
        out["probabilityText"] = f"{probability:.1f}%"
        # 가격 데이터 상태: 두 소스 중 더 좋은 것을 반영
        # PRICE_PENDING > PARTIAL > NORMAL 순으로 품질
        prior_status = out.get("dataStatus", "PARTIAL")
        quant_status = result.get("dataStatus", "PARTIAL")
        if prior_status == "PRICE_PENDING" or quant_status == "PRICE_PENDING":
            out["dataStatus"] = "PRICE_PENDING"
        elif prior_status == "NORMAL" or quant_status == "NORMAL":
            out["dataStatus"] = "NORMAL"  # 어느 하나라도 NORMAL이면 NORMAL
        else:
            out["dataStatus"] = "PARTIAL"

        # EV 기반 추천 적합성 등급
        ev = result.get("expectedValue")
        if ev is not None:
            if ev >= 3.0:
                out["evGrade"] = "우수"
            elif ev >= 1.0:
                out["evGrade"] = "양호"
            elif ev >= 0:
                out["evGrade"] = "보통"
            else:
                out["evGrade"] = "주의"
            out["expectedValueText"] = f"{ev:+.1f}%"

    # 기간별 price band 범위 내인지 검증
    band = result.get("priceBand")
    entry = _num(out.get("entry"))
    stop = _num(out.get("stop"))
    target = _num(out.get("target"))
    band_warnings: list[str] = []

    if band and entry and entry > 0:
        if stop and stop > 0:
            stop_pct = (stop - entry) / entry * 100.0
            stop_min, stop_max = band["stop_pct"]
            if not (stop_min <= stop_pct <= stop_max):
                band_warnings.append(f"손절폭 {stop_pct:.1f}% (권장 {stop_min}~{stop_max}%)")
        if target and target > 0:
            target_pct = (target - entry) / entry * 100.0
            target_min, target_max = band["target_pct"]
            if not (target_min <= target_pct <= target_max):
                band_warnings.append(f"목표수익 {target_pct:.1f}% (권장 {target_min}~{target_max}%)")

    out["priceBandWarnings"] = band_warnings

    tags, primary, label = _strategy_tags(out.get("indicators", {}), str(out.get("quantDataStatus") or out.get("dataStatus") or ""))
    financial_keys = (
        "eps", "per", "pbr", "roe", "revenue", "operatingProfit", "netIncome",
        "epsGrowth", "revenueGrowth", "operatingProfitGrowth", "peg", "debtRatio",
        "operatingCashFlow", "interestCoverage",
    )
    financial_values = {key: _num(out.get(key)) for key in financial_keys}
    has_financial = any(value is not None and value != 0 for value in financial_values.values())
    out["financialDataStatus"] = "NORMAL" if has_financial else "DATA_PENDING"
    if has_financial:
        per = financial_values.get("per")
        pbr = financial_values.get("pbr")
        roe = financial_values.get("roe")
        revenue = financial_values.get("revenue")
        operating_profit = financial_values.get("operatingProfit")
        net_income = financial_values.get("netIncome")
        eps_growth = financial_values.get("epsGrowth")
        revenue_growth = financial_values.get("revenueGrowth")
        operating_profit_growth = financial_values.get("operatingProfitGrowth")
        peg = financial_values.get("peg")
        debt_ratio = financial_values.get("debtRatio")
        operating_cash_flow = financial_values.get("operatingCashFlow")
        interest_coverage = financial_values.get("interestCoverage")
        value_ok = (per is not None and 0 < per <= 18) or (pbr is not None and 0 < pbr <= 2.5)
        if peg is None and per is not None and eps_growth is not None and eps_growth > 0:
            peg = per / eps_growth
            out["peg"] = round(peg, 3)
            out.setdefault("computedFields", []).append("peg_from_per_eps_growth")
        if peg is not None:
            value_ok = value_ok or (0 < peg < 1.5)
        growth_ok = (roe is not None and roe >= 5) or (
            revenue is not None and revenue > 0 and (operating_profit or 0) > 0 and (net_income or 0) > 0
        )
        growth_ok = growth_ok or (eps_growth is not None and eps_growth > 15) or (revenue_growth is not None and revenue_growth > 10) or (operating_profit_growth is not None and operating_profit_growth > 15)
        stable_finance = (
            (debt_ratio is None or debt_ratio < 150)
            and (operating_cash_flow is None or operating_cash_flow > 0)
            and (interest_coverage is None or interest_coverage > 3)
        )
        out["financialScreening"] = {
            "valueOk": bool(value_ok),
            "growthOk": bool(growth_ok),
            "stableFinance": bool(stable_finance),
        }
        if value_ok and growth_ok and stable_finance and "UNDERVALUED_GROWTH" not in tags:
            tags.insert(0, "UNDERVALUED_GROWTH")
    else:
        out["financialDataMessage"] = "재무 데이터 보강 필요"
    # PRICE_PENDING/DATA_PENDING만 CAUTION 추가 (PARTIAL은 KIS 미연결 종목일 뿐, 과도한 CAUTION 방지)
    if out.get("dataStatus") in {"PRICE_PENDING", "DATA_PENDING"}:
        if "CAUTION" not in tags:
            tags.append("CAUTION")

    # EV < 0이면 CAUTION 추가 (EV < -1% 종목은 stabilizer에서 완전 제외됨)
    if result.get("expectedValue") is not None and result["expectedValue"] < 0:
        if "CAUTION" not in tags:
            tags.append("CAUTION")

    deduped_tags: list[str] = []
    for tag in tags or ["CAUTION"]:
        if tag not in deduped_tags:
            deduped_tags.append(tag)
    tags = deduped_tags
    primary = tags[0]
    label = TAG_LABELS.get(primary, primary)

    # ── 차트 패턴 인식 (PDF 가이드북 4개 매수 패턴)
    chart_patterns = detect_chart_patterns(_ohlcv)
    if chart_patterns:
        best_pattern = chart_patterns[0]
        pattern_tag  = best_pattern["pattern"]
        # 패턴 태그를 strategyTags 앞에 추가
        if pattern_tag not in tags:
            tags.insert(0, pattern_tag)
        primary = tags[0]
        label   = TAG_LABELS.get(primary, primary)
        # 패턴 신뢰도로 finalScore 보너스 (+0~+10)
        pconf = best_pattern.get("confidence", 0)
        if isinstance(out.get("finalScore"), (int, float)) and pconf >= 70:
            bonus = round((pconf - 70) / 30 * 10, 1)  # 70→0점, 100→10점
            out["finalScore"] = min(100.0, round(float(out["finalScore"]) + bonus, 1))
            out["quantScore"]  = out["finalScore"]
        # 패턴이 더 나은 entry/stop/target 제시하면 덮어씌우기
        p_entry  = best_pattern.get("entry")
        p_stop   = best_pattern.get("stop")
        p_target = best_pattern.get("target")
        cur_entry  = _num(out.get("entry"))
        if p_entry and p_stop and p_target and cur_entry:
            p_rr = (p_target - p_entry) / (p_entry - p_stop) if p_entry > p_stop else 0
            cur_rr = ((_num(out.get("target")) or 0) - cur_entry) / (cur_entry - (_num(out.get("stop")) or 0)) if cur_entry > (_num(out.get("stop")) or 0) else 0
            if p_rr > cur_rr + 0.5:  # 패턴이 0.5 이상 더 좋은 RR이면 대체
                out["entry"]  = p_entry
                out["stop"]   = p_stop
                out["target"] = p_target
                out["rrActual"] = round(p_rr, 2)
                market_ = str(out.get("market") or "kr").lower()
                sfx = "원" if market_ == "kr" else "$"
                out["entryText"]  = f"{p_entry:,}{sfx}"
                out["stopText"]   = f"{p_stop:,}{sfx}"
                out["targetText"] = f"{p_target:,}{sfx}"
                out.setdefault("computedFields", []).append("entry_from_chart_pattern")
    out["chartPatterns"] = chart_patterns
    out["chartPatternCount"] = len(chart_patterns)

    out["strategyTags"] = tags
    out["strategyTagLabels"] = [TAG_LABELS.get(tag, tag) for tag in tags]
    out["primaryStrategyTag"] = primary
    out["candidateType"] = primary
    out["candidateTypeLabel"] = label

    # tradeBlockStatus: 실제 매수 주의가 필요한 조건만 (재무데이터 부족은 정보 표시용, 매수차단 아님)
    block_reasons = []
    info_reasons = []
    if "CAUTION" in tags:
        block_reasons.append("과열·데이터 조건 확인 필요")
    if out.get("quantDataStatus") in {"PRICE_PENDING", "DATA_PENDING"}:
        block_reasons.append(str(out.get("quantReason") or out.get("quantDataStatus")))
    if out.get("riskFlags"):
        risk_flag_labels = {
            "RSI_OVERHEATED": "RSI 과열(80+)",
            "BOLLINGER_UPPER_BREAK": "볼린저 상단 돌파",
            "FIVE_DAY_UP_STREAK": "5일 연속 상승 후 거래량 감소",
            "GAP_UP_15PCT": "갭상승 15%+ 추격금지",
            "EV_NEGATIVE": "EV(기댓값) 음수",
        }
        for flag in out.get("riskFlags", []):
            block_reasons.append(risk_flag_labels.get(str(flag), str(flag)))
    # 가격 밴드 경고는 참고용 (매수 차단 아님, 전략별 조정으로 인한 정상 범위 이탈)
    if band_warnings:
        info_reasons.extend(band_warnings)
    # 재무 데이터 부족은 정보 표시용 (매수 차단 아님)
    if out.get("financialDataStatus") == "DATA_PENDING":
        info_reasons.append(str(out.get("financialDataMessage") or "재무 데이터 보강 필요"))
    out["cautionReasons"] = block_reasons
    out["infoReasons"] = info_reasons
    out["tradeBlockStatus"] = "CAUTION" if block_reasons else "OK"

    # ── decisionBucket: 진입/대기 결정 (백엔드에서 확정)
    _score_val   = float(out.get("finalScore") or out.get("quantScore") or 0)
    _ev_val      = _num(out.get("expectedValue"))
    _rsi_val     = _num((result.get("indicators") or {}).get("rsi14"))
    _d20_val     = _num((result.get("indicators") or {}).get("distanceToMa20"))
    _rr_val      = _num(out.get("rrActual"))
    _risk_flags  = out.get("riskFlags") or []
    _decision, _decision_reason = _compute_decision_bucket(
        score=_score_val, ev=_ev_val, rsi=_rsi_val,
        d20=_d20_val, rr_actual=_rr_val,
        mode=mode, risk_flags=_risk_flags,
    )
    # 기존 decisionBucket이 있으면 더 엄격한 쪽 채택
    _existing_bucket = str(out.get("decisionBucket") or "")
    _priority = {"매수금지": 0, "관찰": 1, "대기 관찰": 2, "오늘 진입": 3}
    if _priority.get(_decision, 2) < _priority.get(_existing_bucket, 2):
        out["decisionBucket"] = _decision
        out["decisionReason"] = _decision_reason
    elif not _existing_bucket:
        out["decisionBucket"] = _decision
        out["decisionReason"] = _decision_reason

    # ── DSG 섹터 추론 + 주도주 + 눌림목 (KR 전용)  # noqa: E501
    if _DSG_AVAILABLE and market == "kr":  # type: ignore[name-defined]
        _name_kr = str(item.get("name") or item.get("nameKr") or item.get("stockName") or "")
        _existing_sec = str(out.get("sector") or "").strip()
        if not _existing_sec or _existing_sec in ("Unknown", "Other", ""):
            out["sector"] = infer_kr_sector(symbol, _name_kr)  # type: ignore[name-defined]
        out["sectorLabel"] = sector_label_kr(str(out.get("sector") or "Other"))  # type: ignore[name-defined]
        if not out.get("themeNames"):
            out["themeNames"] = get_theme_names(symbol)  # type: ignore[name-defined]

        _ind = result.get("indicators", {})

        def _fi(_k: str, _d: float = 0.0) -> float:
            _v = _ind.get(_k)
            try:
                return float(_v) if _v is not None else _d
            except Exception:
                return _d

        _close_px = float(result.get("currentPriceUsed") or _fi("ma20"))
        _ma20 = _fi("ma20", _close_px)
        _ma60 = _fi("ma60", _close_px)
        _ret20 = _fi("recentMomentum20", 0.0)
        _ret60 = _fi("distanceToMa60", 0.0)
        _vol_r = _fi("volumeRatio20", 1.0)
        _score = float(result.get("score") or 50)
        # 종목 섹터의 실제 강도 점수 조회 (없으면 upsideScore로 fallback)
        try:
            from app.engine.dsg_signal_engine import sector_strength as _ss  # type: ignore[name-defined]
            _sec_map = {r["sector"]: r["sector_score"] for r in _ss(market, period=5)}
            _sec_s = float(_sec_map.get(str(out.get("sector") or ""), 0) or result.get("upsideScore") or 50)
        except Exception:
            _sec_s = float(result.get("upsideScore") or 50)
        if _close_px > _ma20 > 0 and _ret20 > 0:
            _regime = "BULL"
        elif _close_px < _ma20 and _ret20 < -3:
            _regime = "BEAR"
        else:
            _regime = "SIDE"
        _is_leader, _lr = detect_leader_mode(  # type: ignore[name-defined]
            score=_score, sector_score=_sec_s, market_regime=_regime,
            close=_close_px, ma20=_ma20, ma60=_ma60,
            ret20=_ret20, ret60=_ret60,
            vol=_vol_r, vol_ma20=1.0, news_score=5.0,
        )
        out["isLeader"] = _is_leader
        out["leaderReason"] = _lr
        _entry_v = float(_num(out.get("entry")) or 0)
        _ind2 = {**_ind, "rrActual": result.get("rrActual") or 2.0}
        _ps, _pr = get_pullback_state_from_ohlcv(_ohlcv, _ind2, _entry_v, _is_leader)  # type: ignore[name-defined]
        out["pullbackState"] = _ps
        out["pullbackReason"] = _pr

    # ── v10.3 크로스 + 트레일링 스탑 (모든 종목)
    _ind3 = result.get("indicators", {})
    out["goldenCross"]    = bool(_ind3.get("goldenCross", False))
    out["deathCross"]     = bool(_ind3.get("deathCross", False))
    out["midGoldenCross"] = bool(_ind3.get("midGoldenCross", False))
    out["midDeathCross"]  = bool(_ind3.get("midDeathCross", False))
    _ts = _ind3.get("trailingStop")
    _tsp = _ind3.get("trailingStopPct")
    out["trailingStop"]    = round(_ts, 2)  if _ts  is not None else None
    out["trailingStopPct"] = round(_tsp, 2) if _tsp is not None else None
    out["recentHigh20"]    = _ind3.get("recentHigh20")

    return out
