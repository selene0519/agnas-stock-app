"""청산 신호 생성 서비스.

보유 종목에 대해 OHLCV 데이터를 읽어 청산 신호를 계산한다.
stop/target 단순 도달 체크를 넘어, 중간 청산 타이밍을 제공한다.

신호 레벨:
  SELL_STRONG  — RSI>75 & 목표가 5% 이내 or MA5 하향 이탈 (즉시 부분/전량 익절)
  SELL         — RSI>80 (과매수) or 목표가 2% 이내 (익절 타이밍)
  PARTIAL_EXIT — RSI 70~80 & 목표가 10% 이내 (부분 익절 고려)
  MONITOR      — 단기 패턴 약화 신호 (MA5 < MA10, 거래량 감소)
  HOLD         — 추세 유지, 보유 유지
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _ohlcv_path(market: str, symbol: str) -> Path:
    return _REPO_ROOT / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv"


def _read_ohlcv(market: str, symbol: str, rows: int = 60) -> list[dict]:
    path = _ohlcv_path(market, symbol)
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                data = list(csv.DictReader(f))
            return data[-rows:] if len(data) > rows else data
        except Exception:
            continue
    return []


def _num(v: Any) -> float | None:
    try:
        x = float(str(v).replace(",", "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _closes(data: list[dict]) -> list[float]:
    result = []
    for row in data:
        v = _num(row.get("close") or row.get("Close"))
        if v is not None:
            result.append(v)
    return result


def _volumes(data: list[dict]) -> list[float]:
    result = []
    for row in data:
        v = _num(row.get("volume") or row.get("Volume"))
        if v is not None:
            result.append(v)
    return result


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    # Wilder EMA
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _ma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _volume_ratio(volumes: list[float], period: int = 20) -> float | None:
    if len(volumes) < period + 1:
        return None
    avg = sum(volumes[-period - 1:-1]) / period
    if avg < 1:
        return None
    return round(volumes[-1] / avg, 2)


def _compute_indicators(market: str, symbol: str) -> dict[str, Any]:
    data = _read_ohlcv(market, symbol, rows=80)
    if not data:
        return {}

    closes  = _closes(data)
    volumes = _volumes(data)
    if len(closes) < 5:
        return {}

    current = closes[-1]
    rsi14   = _rsi(closes, 14)
    ma5     = _ma(closes, 5)
    ma10    = _ma(closes, 10)
    ma20    = _ma(closes, 20)
    vol_ratio = _volume_ratio(volumes, 20)

    # MA5가 MA10 아래로 크로스오버 (단기 약세 신호)
    ma5_below_ma10 = bool(ma5 and ma10 and ma5 < ma10)

    # 최근 3일 연속 하락
    consec_down = len(closes) >= 3 and closes[-1] < closes[-2] < closes[-3]

    return {
        "currentPrice": current,
        "rsi14":        rsi14,
        "ma5":          ma5,
        "ma10":         ma10,
        "ma20":         ma20,
        "volumeRatio":  vol_ratio,
        "ma5BelowMa10": ma5_below_ma10,
        "consecutiveDown": consec_down,
    }


def _exit_signal(
    holding: dict[str, Any],
    ind: dict[str, Any],
) -> dict[str, Any]:
    symbol = str(holding.get("symbol") or holding.get("ticker") or "")
    name   = str(holding.get("name") or symbol)
    market = str(holding.get("market") or "kr").lower()

    current = _num(ind.get("currentPrice"))
    rsi     = ind.get("rsi14")
    ma5_below = ind.get("ma5BelowMa10", False)
    consec_down = ind.get("consecutiveDown", False)
    vol_ratio = ind.get("volumeRatio")

    stop_price   = _num(holding.get("stopPrice")   or holding.get("stop_price")   or holding.get("stop"))
    target_price = _num(holding.get("targetPrice") or holding.get("target_price") or holding.get("target"))
    avg_price    = _num(holding.get("avgPrice")     or holding.get("avg_price"))

    reasons: list[str] = []
    signal = "HOLD"
    urgency = 0  # 높을수록 급함

    if current is None:
        return {
            "symbol": symbol, "name": name, "market": market,
            "signal": "NO_DATA", "urgency": -1, "reasons": ["현재가 없음"],
            "rsi14": None, "targetGapPct": None, "stopGapPct": None,
        }

    # 목표가/손절가 대비 현재 위치
    target_gap_pct: float | None = None
    stop_gap_pct:   float | None = None

    if target_price and target_price > current:
        target_gap_pct = round((target_price - current) / target_price * 100, 1)
    elif target_price and current >= target_price:
        target_gap_pct = 0.0

    if stop_price and stop_price < current:
        stop_gap_pct = round((current - stop_price) / current * 100, 1)
    elif stop_price and current <= stop_price:
        stop_gap_pct = 0.0

    # 수익률 (진입가 대비)
    pnl_pct: float | None = None
    if avg_price and avg_price > 0:
        pnl_pct = round((current - avg_price) / avg_price * 100, 1)

    # ── 신호 계산 ──────────────────────────────────────────────────────────
    # SELL_STRONG: RSI 과매수 + 목표 근접 (가장 강한 익절 신호)
    if rsi and rsi > 75 and target_gap_pct is not None and target_gap_pct <= 5:
        signal = "SELL_STRONG"
        urgency = 4
        reasons.append(f"RSI {rsi} 과매수 + 목표가 {target_gap_pct}% 이내")

    # SELL: 목표가 도달 or RSI 극과매수
    elif target_gap_pct is not None and target_gap_pct <= 1:
        signal = "SELL"
        urgency = 3
        reasons.append(f"목표가 {target_gap_pct}% 근접 — 익절 검토")
    elif rsi and rsi > 82:
        signal = "SELL"
        urgency = 3
        reasons.append(f"RSI {rsi} 극과매수 (82+) — 조정 가능성")

    # SELL: MA5 이탈 + 수익 구간
    elif ma5_below and pnl_pct is not None and pnl_pct > 3:
        signal = "SELL"
        urgency = 3
        reasons.append(f"MA5 < MA10 + 수익 {pnl_pct}% — 단기 추세 약화")

    # PARTIAL_EXIT: RSI 70~80 + 목표 10% 이내
    elif rsi and rsi > 70 and target_gap_pct is not None and target_gap_pct <= 10:
        signal = "PARTIAL_EXIT"
        urgency = 2
        reasons.append(f"RSI {rsi} 과열 + 목표가 {target_gap_pct}% — 부분 익절 고려")

    # MONITOR: 단기 패턴 약화
    elif ma5_below or consec_down or (vol_ratio is not None and vol_ratio < 0.5):
        signal = "MONITOR"
        urgency = 1
        if ma5_below:
            reasons.append("MA5 < MA10 단기 약세 전환")
        if consec_down:
            reasons.append("3일 연속 하락")
        if vol_ratio is not None and vol_ratio < 0.5:
            reasons.append(f"거래량 급감 (비율 {vol_ratio}x)")

    else:
        signal = "HOLD"
        urgency = 0
        reasons.append("추세 유지 — 보유 유지")

    return {
        "symbol":       symbol,
        "name":         name,
        "market":       market,
        "signal":       signal,
        "urgency":      urgency,
        "reasons":      reasons,
        "rsi14":        rsi,
        "ma5BelowMa10": ma5_below,
        "consecutiveDown": consec_down,
        "volumeRatio":  vol_ratio,
        "currentPrice": current,
        "targetGapPct": target_gap_pct,
        "stopGapPct":   stop_gap_pct,
        "pnlPct":       pnl_pct,
    }


def get_exit_signals(market: str = "all") -> dict[str, Any]:
    """보유 종목 전체에 청산 신호 계산."""
    from app.services import user_data

    markets = ("kr", "us") if market == "all" else (market,)
    results: list[dict[str, Any]] = []

    for mk in markets:
        holdings = user_data.get_holdings(mk)
        for h in holdings:
            symbol = str(h.get("symbol") or h.get("ticker") or "").strip()
            if not symbol:
                continue
            ind = _compute_indicators(mk, symbol)
            sig = _exit_signal({**h, "market": mk}, ind)
            results.append(sig)

    results.sort(key=lambda x: -x.get("urgency", 0))

    sell_count    = sum(1 for r in results if r["signal"] in ("SELL_STRONG", "SELL"))
    partial_count = sum(1 for r in results if r["signal"] == "PARTIAL_EXIT")
    monitor_count = sum(1 for r in results if r["signal"] == "MONITOR")

    return {
        "status":       "OK",
        "market":       market,
        "totalHoldings": len(results),
        "sellCount":    sell_count,
        "partialCount": partial_count,
        "monitorCount": monitor_count,
        "signals":      results,
    }
