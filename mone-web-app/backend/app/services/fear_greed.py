"""
공포·탐욕 지수 서비스.

US: CNN Fear & Greed API 시도 후 실패 시 SPY OHLCV 기반 복합 지수
KR: KOSPI OHLCV 기반 복합 지수 (RSI·MA이격·ATR역수·MDD역수)

GET /api/market/fear-greed?market=kr|us|all
"""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

import requests

_CACHE: dict[str, Any] = {}
_CACHE_TTL = 1800  # 30분 캐시


def _cached(key: str) -> Any | None:
    item = _CACHE.get(key)
    if item and time.time() - item["ts"] < _CACHE_TTL:
        return item["data"]
    return None


def _set_cache(key: str, data: Any) -> None:
    _CACHE[key] = {"ts": time.time(), "data": data}


# ── RSI 계산 ─────────────────────────────────────────────────────────────

def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    # Wilder's smoothed average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _atr_pct(rows: list[dict], period: int = 14) -> float:
    """ATR을 현재가 대비 % 로 반환"""
    trs = []
    for i in range(1, len(rows)):
        high = float(rows[i].get("high") or rows[i].get("High") or 0)
        low = float(rows[i].get("low") or rows[i].get("Low") or 0)
        prev_close = float(rows[i - 1].get("close") or rows[i - 1].get("Close") or 0)
        if high > 0 and low > 0 and prev_close > 0:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
    if not trs:
        return 2.0
    atr = sum(trs[-period:]) / min(len(trs), period)
    current = float(rows[-1].get("close") or rows[-1].get("Close") or 1)
    return round(atr / current * 100, 2) if current > 0 else 2.0


def _score_label(score: float) -> str:
    if score < 20:
        return "극단적 공포"
    if score < 40:
        return "공포"
    if score < 60:
        return "중립"
    if score < 80:
        return "탐욕"
    return "극단적 탐욕"


def _score_color(score: float) -> str:
    if score < 20:
        return "#ef4444"   # red-500
    if score < 40:
        return "#f97316"   # orange-500
    if score < 60:
        return "#eab308"   # yellow-500
    if score < 80:
        return "#84cc16"   # lime-500
    return "#22c55e"       # green-500


# ── CNN Fear & Greed (US) ─────────────────────────────────────────────────

def _fetch_cnn_fg() -> dict[str, Any] | None:
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.cnn.com/markets/fear-and-greed",
        }
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        fg = data.get("fear_and_greed") or {}
        score = float(fg.get("score") or 50)
        label_en = str(fg.get("rating") or "").lower()
        label_map = {
            "extreme fear": "극단적 공포",
            "fear": "공포",
            "neutral": "중립",
            "greed": "탐욕",
            "extreme greed": "극단적 탐욕",
        }
        label = label_map.get(label_en, _score_label(score))

        # 히스토리 (7일)
        history: list[dict] = []
        for item in (data.get("fear_and_greed_historical", {}).get("data") or [])[-7:]:
            ts = item.get("x")
            val = item.get("y")
            if ts and val is not None:
                date_str = datetime.fromtimestamp(float(ts) / 1000).strftime("%m/%d")
                history.append({"date": date_str, "score": round(float(val), 1)})

        # 구성요소
        components: list[dict] = []
        for comp_key, comp_name in [
            ("market_momentum_sp500_and_sp100", "시장 모멘텀"),
            ("stock_price_strength", "주가 강도"),
            ("stock_price_breadth", "시장 너비"),
            ("put_and_call_options", "풋/콜 비율"),
            ("market_volatility_vix", "VIX 변동성"),
            ("junk_bond_demand", "하이일드 수요"),
            ("safe_haven_demand", "안전자산 수요"),
        ]:
            comp = data.get(comp_key) or {}
            val = comp.get("score")
            if val is not None:
                direction = comp.get("rating", "")
                components.append({
                    "name": comp_name,
                    "score": round(float(val), 1),
                    "direction": direction,
                })

        return {
            "score": round(score, 1),
            "label": label,
            "source": "CNN Fear & Greed",
            "color": _score_color(score),
            "history": history,
            "components": components,
        }
    except Exception as exc:
        print(f"[FearGreed] CNN fetch failed: {exc}")
        return None


# ── 복합 지수 (OHLCV 기반) ──────────────────────────────────────────────

def _composite_fg(rows: list[dict], market: str) -> dict[str, Any]:
    closes = [float(r.get("close") or r.get("Close") or 0) for r in rows]
    closes = [c for c in closes if c > 0]

    if len(closes) < 20:
        return {
            "score": 50.0,
            "label": "중립",
            "source": "복합 지수 (데이터 부족)",
            "color": _score_color(50),
            "history": [],
            "components": [],
            "note": "OHLCV 데이터 20일 미만 — 기본값 반환",
        }

    current = closes[-1]

    # 1. RSI(14) — 탐욕=높음, 공포=낮음 (그대로 사용)
    rsi_score = _rsi(closes, 14)

    # 2. MA20 이격도 → 0-100 정규화
    ma20 = sum(closes[-20:]) / 20
    ma20_dist_pct = (current - ma20) / ma20 * 100
    ma_score = max(0.0, min(100.0, 50 + ma20_dist_pct * 4))

    # 3. ATR% 역수 → 높은 변동성 = 공포
    atr = _atr_pct(rows[-30:], 14)
    vol_score = max(0.0, min(100.0, 100 - atr * 12))

    # 4. MDD(60) 역수 → 깊은 하락 = 공포
    window60 = closes[-60:] if len(closes) >= 60 else closes
    peak = max(window60)
    mdd_pct = (current - peak) / peak * 100  # 음수
    mdd_score = max(0.0, min(100.0, 100 + mdd_pct * 3))

    # 5. MA60 이격도 (중기 모멘텀)
    ma60 = sum(closes[-60:]) / len(closes[-60:]) if len(closes) >= 60 else ma20
    ma60_dist = (current - ma60) / ma60 * 100
    ma60_score = max(0.0, min(100.0, 50 + ma60_dist * 3))

    composite = (
        rsi_score * 0.30
        + ma_score * 0.25
        + vol_score * 0.20
        + mdd_score * 0.15
        + ma60_score * 0.10
    )
    score = round(composite, 1)

    # 7일 히스토리
    history: list[dict] = []
    for i in range(7, 0, -1):
        idx = max(0, len(closes) - i)
        sub = closes[: idx + 1]
        if len(sub) < 15:
            continue
        sub_rsi = _rsi(sub, 14)
        sub_ma20 = sum(sub[-20:]) / 20 if len(sub) >= 20 else sub[-1]
        sub_dist = (sub[-1] - sub_ma20) / sub_ma20 * 100
        sub_ma_s = max(0.0, min(100.0, 50 + sub_dist * 4))
        sub_s = round(sub_rsi * 0.55 + sub_ma_s * 0.45, 1)
        row = rows[max(0, len(rows) - i)]
        date_str = str(row.get("date") or row.get("Date") or "")[:10][5:]  # MM-DD
        history.append({"date": date_str, "score": sub_s})

    benchmark = "KOSPI" if market == "kr" else "SPY"
    return {
        "score": score,
        "label": _score_label(score),
        "source": f"복합 지수 ({benchmark} 기반)",
        "color": _score_color(score),
        "history": history,
        "components": [
            {"name": f"RSI(14)", "score": round(rsi_score, 1), "direction": "상승" if rsi_score > 50 else "하락"},
            {"name": "MA20 이격", "score": round(ma_score, 1), "direction": f"{ma20_dist_pct:+.1f}%"},
            {"name": "변동성(ATR)", "score": round(vol_score, 1), "direction": f"ATR {atr:.1f}%"},
            {"name": "낙폭(MDD60)", "score": round(mdd_score, 1), "direction": f"MDD {mdd_pct:.1f}%"},
            {"name": "MA60 이격", "score": round(ma60_score, 1), "direction": f"{ma60_dist:+.1f}%"},
        ],
    }


# ── 공개 API ──────────────────────────────────────────────────────────────

def get_fear_greed(market: str = "us") -> dict[str, Any]:
    """market: 'kr' | 'us' | 'all'"""
    cache_key = f"fg:{market}"
    cached = _cached(cache_key)
    if cached:
        return cached

    result: dict[str, Any] = {"status": "OK", "market": market, "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    if market in ("us", "all"):
        cnn = _fetch_cnn_fg()
        if cnn:
            result["us"] = cnn
        else:
            result["us"] = _get_ohlcv_fg("us")

    if market in ("kr", "all"):
        result["kr"] = _get_ohlcv_fg("kr")

    # all 모드: 종합 점수
    if market == "all":
        scores = []
        if result.get("kr"):
            scores.append(result["kr"].get("score", 50))
        if result.get("us"):
            scores.append(result["us"].get("score", 50))
        avg = sum(scores) / len(scores) if scores else 50
        result["composite"] = {
            "score": round(avg, 1),
            "label": _score_label(avg),
            "color": _score_color(avg),
        }
    elif market in result:
        # 단일 시장 — 최상위에 올림
        result.update(result[market])

    _set_cache(cache_key, result)
    return result


def _get_ohlcv_fg(market: str) -> dict[str, Any]:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    ohlcv_dir = repo_root / "data" / "market" / "ohlcv"
    bench_sym = "KOSPI" if market == "kr" else "SPY"
    path = ohlcv_dir / f"{market}_{bench_sym}_daily.csv"

    if not path.exists():
        return {"score": 50.0, "label": "중립", "source": "데이터 없음", "color": _score_color(50), "history": [], "components": []}

    import csv
    rows: list[dict] = []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc) as f:
                rows = list(csv.DictReader(f))
            break
        except Exception:
            continue

    return _composite_fg(rows[-90:], market)
