"""
Context-Aware Candlestick Pattern Detector v3.

Two-signal combo design (이미지 기반):
  완성 신호 = SETUP 패턴 + CONFIRMATION 캔들
  - confirmed=True : 두 신호 모두 확인 → 높은 신뢰도
  - confirmed=False: 셋업만 확인, 확인봉 미출현 → 관찰 단계

  is_* 헬퍼 함수들은 geometric_patterns.py에서도 임포트해서 사용한다.

Bullish combos:
  MORNING_STAR_PINBAR       — 샛별(3봉) + 핀버 확인봉  [confirmed]
  MORNING_STAR              — 샛별(3봉) setup-only fallback
  BULLISH_ENGULFING_MARUBOZU— 음을양병 + 포병(꼬리없는강한양봉) [confirmed]
  BULLISH_ENGULFING         — 음을양병 setup-only fallback
  SPIKE_PINBAR              — 스파이크로 + 핀버 [confirmed]
  SPIKE_REVERSAL            — 스파이크로 recovery fallback
  THREE_INSIDE_UP           — 삼강법(3봉 구조적 확인, 본질적으로 confirmed)
  HARAMI_BULLISH            — 강세 하라미(2봉, setup-only)
  LION_MOUTH                — 사자 입: 연속하락 후 고거래량 핀버 [confirmed]

Bearish combos:
  EVENING_STAR_BEAR         — 저녁별(3봉) + 강한 음봉 확인봉 [confirmed]
  EVENING_STAR              — 저녁별(3봉) setup-only fallback
  THREE_BLACK_CROWS         — 흑삼병(3봉, 본질적으로 confirmed)
  BEARISH_ENGULFING_DARK_CLOUD — 두브러리 + 그늘그개 [confirmed]
  BEARISH_ENGULFING         — 두브러리 setup-only fallback
  SHOOTING_STAR_CONFIRM     — 유성형 + 확인봉
  THREE_INSIDE_DOWN         — 역삼강법(3봉, 본질적으로 confirmed)
  HARAMI_BEARISH            — 약세 하라미(2봉, setup-only)

Public exports:
  is_pinbar, is_strong_bull, is_strong_bear, is_shooting_star
    → geometric_patterns.py에서 임포트해서 캔들 확인봉 체크에 사용
  detect_contextual(rows, atr20, *, market_structure, trend_phase,
                    primary_pattern, risk_status) -> dict | None
"""
from __future__ import annotations

from typing import Any


# ── OHLC anatomy helpers ──────────────────────────────────────────────────────

def _body(o: float, c: float) -> float:
    return abs(c - o)


def _rng(h: float, l: float) -> float:
    return max(h - l, 1e-9)


def _lower_wick(o: float, h: float, l: float, c: float) -> float:
    return min(o, c) - l


def _upper_wick(o: float, h: float, l: float, c: float) -> float:
    return h - max(o, c)


def _body_ratio(o: float, h: float, l: float, c: float) -> float:
    return _body(o, c) / _rng(h, l)


def _mid(o: float, c: float) -> float:
    return (o + c) / 2.0


def _is_bull(o: float, c: float) -> bool:
    return c >= o


def _is_bear(o: float, c: float) -> bool:
    return c < o


# ── Row unpackers ─────────────────────────────────────────────────────────────

def _row(r: dict) -> tuple[float, float, float, float] | None:
    try:
        return float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
    except (KeyError, TypeError, ValueError):
        return None


def _unpack2(rows: list[dict]) -> tuple | None:
    if len(rows) < 2:
        return None
    a, b = _row(rows[-2]), _row(rows[-1])
    return (*a, *b) if a and b else None


def _unpack3(rows: list[dict]) -> tuple | None:
    if len(rows) < 3:
        return None
    a, b, c = _row(rows[-3]), _row(rows[-2]), _row(rows[-1])
    return (*a, *b, *c) if a and b and c else None


def _unpack4(rows: list[dict]) -> tuple | None:
    if len(rows) < 4:
        return None
    a, b, c, d = _row(rows[-4]), _row(rows[-3]), _row(rows[-2]), _row(rows[-1])
    return (*a, *b, *c, *d) if a and b and c and d else None


# ── Volume helper ─────────────────────────────────────────────────────────────

def _vol(r: dict) -> float | None:
    try:
        v = float(r.get("volume") or 0)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


# ── Candle type classifiers (exported for geometric_patterns.py) ──────────────

def is_pinbar(o: float, h: float, l: float, c: float, atr20: float) -> bool:
    """핀버/망치: 하단꼬리 > 2×몸통, 상단꼬리 < 몸통, 몸통 ≥ 0.08×ATR."""
    bd = _body(o, c)
    return (
        bd >= 0.08 * atr20
        and _lower_wick(o, h, l, c) >= 2.0 * bd
        and _upper_wick(o, h, l, c) < bd
    )


def is_marubozu_bull(o: float, h: float, l: float, c: float, atr20: float) -> bool:
    """포병(양봉 마루보즈): 양봉, 몸통비율 > 0.80."""
    return _is_bull(o, c) and _body_ratio(o, h, l, c) > 0.80


def is_strong_bull(o: float, h: float, l: float, c: float, atr20: float) -> bool:
    """대양선: 양봉, 몸통 ≥ 0.5×ATR."""
    return _is_bull(o, c) and _body(o, c) >= 0.5 * atr20


def is_strong_bear(o: float, h: float, l: float, c: float, atr20: float) -> bool:
    """강한 음봉: 음봉, 몸통 ≥ 0.5×ATR."""
    return _is_bear(o, c) and _body(o, c) >= 0.5 * atr20


def is_shooting_star(o: float, h: float, l: float, c: float, atr20: float) -> bool:
    """유성형/별똥별: 상단꼬리 > 2×몸통, 하단꼬리 < 몸통, 몸통 ≥ 0.08×ATR."""
    bd = _body(o, c)
    return (
        bd >= 0.08 * atr20
        and _upper_wick(o, h, l, c) >= 2.0 * bd
        and _lower_wick(o, h, l, c) < bd
    )


# ── Bullish detectors ─────────────────────────────────────────────────────────

def _detect_morning_star(rows: list[dict], atr20: float) -> dict | None:
    """
    샛별+핀버 (MORNING_STAR_PINBAR, confirmed) /
    샛별     (MORNING_STAR, setup-only).

    4-candle confirmed:
      C1(rows[-4]): 큰 음봉 (≥0.5×ATR)
      C2(rows[-3]): 소형봉  (body < 0.4×C1)
      C3(rows[-2]): 회복 양봉, C1 중간 이상
      C4(rows[-1]): 핀버(망치) 확인봉

    3-candle setup-only fallback: C1=rows[-3], C2=rows[-2], C3=rows[-1].
    """
    # ── 4-candle: confirmed ──────────────────────────────────────────────
    d4 = _unpack4(rows)
    if d4:
        o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3, o4,h4,l4,c4 = d4
        b1 = _body(o1, c1)
        if (
            _is_bear(o1, c1) and b1 >= 0.5 * atr20
            and _body(o2, c2) <= 0.4 * b1
            and _is_bull(o3, c3) and c3 >= _mid(o1, c1)
            and is_pinbar(o4, h4, l4, c4, atr20)
        ):
            return {
                "pattern": "MORNING_STAR_PINBAR",
                "direction": "BULLISH",
                "confirmed": True,
                "reason": (
                    "샛별(큰음봉→소형봉→회복양봉) 이후 핀버 확인봉까지 출현. "
                    "두 신호가 모두 확인된 강한 하락 반전 신호입니다."
                ),
            }

    # ── 3-candle: setup-only ─────────────────────────────────────────────
    d3 = _unpack3(rows)
    if d3:
        o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3 = d3
        b1 = _body(o1, c1)
        if (
            _is_bear(o1, c1) and b1 >= 0.5 * atr20
            and _body(o2, c2) <= 0.4 * b1
            and _is_bull(o3, c3) and c3 >= _mid(o1, c1)
        ):
            return {
                "pattern": "MORNING_STAR",
                "direction": "BULLISH",
                "confirmed": False,
                "reason": (
                    "샛별(큰음봉→소형봉→회복양봉) 셋업 확인. "
                    "핀버 확인봉 출현 시 신뢰도가 더욱 높아집니다."
                ),
            }
    return None


def _detect_bullish_engulfing(rows: list[dict], atr20: float) -> dict | None:
    """
    음을양병+포병 (BULLISH_ENGULFING_MARUBOZU, confirmed) /
    음을양병     (BULLISH_ENGULFING, setup-only).

    3-candle confirmed: C1 bear → C2 engulfing bull → C3 marubozu bull.
    2-candle setup-only: C1 bear → C2 engulfing bull (but not marubozu).
    """
    # ── 3-candle: confirmed ──────────────────────────────────────────────
    d3 = _unpack3(rows)
    if d3:
        o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3 = d3
        if (
            _is_bear(o1, c1)
            and _is_bull(o2, c2) and c2 > o1 and o2 < c1   # engulf
            and is_marubozu_bull(o3, h3, l3, c3, atr20)
        ):
            return {
                "pattern": "BULLISH_ENGULFING_MARUBOZU",
                "direction": "BULLISH",
                "confirmed": True,
                "reason": (
                    "음을양병(장악형 양봉) 이후 포병(꼬리없는 강한 양봉) 확인. "
                    "매수세가 2연속 압도적으로 확인된 강한 반전 신호입니다."
                ),
            }

    # ── 2-candle: setup-only ─────────────────────────────────────────────
    d2 = _unpack2(rows)
    if d2:
        o1,h1,l1,c1, o2,h2,l2,c2 = d2
        if (
            _is_bear(o1, c1)
            and _is_bull(o2, c2) and c2 > o1 and o2 < c1
        ):
            return {
                "pattern": "BULLISH_ENGULFING",
                "direction": "BULLISH",
                "confirmed": False,
                "reason": (
                    "음을양병(장악형 양봉) 셋업 확인. "
                    "포병 확인봉 출현 시 신뢰도가 더욱 높아집니다."
                ),
            }
    return None


def _detect_spike_pinbar(rows: list[dict], atr20: float) -> dict | None:
    """
    스파이크로+핀버 (SPIKE_PINBAR, confirmed) /
    스파이크로     (SPIKE_REVERSAL, recovery fallback).

    C1(rows[-2]): 하방 스파이크 (하단꼬리 ≥ 1.5×ATR)
    C2(rows[-1]):
      confirmed  → 핀버(망치) 형태
      setup-only → 그냥 시가 이상 회복
    """
    d2 = _unpack2(rows)
    if not d2:
        return None
    o1,h1,l1,c1, o2,h2,l2,c2 = d2

    spike = min(o1, c1) - l1
    if spike < 1.5 * atr20:
        return None

    if is_pinbar(o2, h2, l2, c2, atr20):
        return {
            "pattern": "SPIKE_PINBAR",
            "direction": "BULLISH",
            "confirmed": True,
            "reason": (
                f"하방 스파이크({spike:.0f}) 이후 핀버 확인봉 출현. "
                "두 신호가 결합된 하단 반전 신호입니다."
            ),
        }

    if c2 >= o1:   # recovery but not pinbar
        return {
            "pattern": "SPIKE_REVERSAL",
            "direction": "BULLISH",
            "confirmed": False,
            "reason": (
                f"하방 스파이크({spike:.0f}) 후 회복 중. "
                "핀버 형태의 확인봉 출현 시 신뢰도가 높아집니다."
            ),
        }
    return None


def _detect_three_inside_up(rows: list[dict], atr20: float) -> dict | None:
    """
    삼강법 — 큰음봉 → 내부 양봉(하라미) → 강한 확인 양봉.
    3봉 구조 자체가 setup+confirmation이므로 항상 confirmed=True.
    """
    d3 = _unpack3(rows)
    if not d3:
        return None
    o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3 = d3

    if not _is_bear(o1, c1) or _body(o1, c1) < 0.5 * atr20:
        return None
    if not (_is_bull(o2, c2) and o2 > c1 and c2 < o1):   # harami inside C1
        return None
    if not (_is_bull(o3, c3) and c3 > o1):
        return None

    return {
        "pattern": "THREE_INSIDE_UP",
        "direction": "BULLISH",
        "confirmed": True,
        "reason": (
            "큰음봉 → 내부 양봉(하라미) → 강한 확인 양봉의 삼강법 패턴. "
            "매수세 전환이 3단 구조로 검증된 높은 신뢰도 반전 신호입니다."
        ),
    }


def _detect_harami_bullish(rows: list[dict], atr20: float) -> dict | None:
    """
    강세 하라미(2봉, setup-only) — THREE_INSIDE_UP의 앞 2봉 구조.

    C1: 큰 음봉 (≥0.5×ATR)
    C2: 작은 양봉, 몸통이 C1 몸통 안에 포함
        (C2 open ≥ C1 close, C2 close ≤ C1 open, C2 body < 50% of C1 body)
    """
    d2 = _unpack2(rows)
    if not d2:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d2
    if not _is_bear(o1, c1) or _body(o1, c1) < 0.5 * atr20:
        return None
    if not _is_bull(o2, c2):
        return None
    if not (o2 >= c1 and c2 <= o1):  # C2 body inside C1 body
        return None
    if _body(o2, c2) > 0.5 * _body(o1, c1):  # C2 must be notably smaller
        return None
    return {
        "pattern": "HARAMI_BULLISH",
        "direction": "BULLISH",
        "confirmed": False,
        "reason": (
            "큰 음봉 내부에 작은 양봉(강세 하라미). "
            "매도세 약화 신호로, 다음 강한 양봉 출현 시 반전 신뢰도가 높아집니다."
        ),
    }


def _detect_lion_mouth(rows: list[dict], atr20: float) -> dict | None:
    """
    사자 입 패턴 (Lion's Mouth) — 연속 하락 후 고거래량 핀버/회복봉.

    조건:
      - 직전 4봉 중 음봉 ≥ 2 (하락 컨텍스트 확인)
      - 최종봉: 핀버 또는 강한 양봉
      - 최종봉 거래량 ≥ 10일 평균 × 1.3 (패닉 매도 + 매집 반전 볼륨)
    """
    if len(rows) < 5:
        return None
    r = rows[-1]
    try:
        o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (is_pinbar(o, h, l, c, atr20) or is_strong_bull(o, h, l, c, atr20)):
        return None
    # 직전 4봉에서 음봉 2개 이상
    bear_count = 0
    for r2 in rows[-5:-1]:
        try:
            if float(r2["close"]) < float(r2["open"]):
                bear_count += 1
        except (KeyError, TypeError, ValueError):
            pass
    if bear_count < 2:
        return None
    # 거래량: 오늘 ≥ 10일 평균 × 1.3
    vols = [v for r2 in rows[-11:-1] if (v := _vol(r2)) is not None]
    today_v = _vol(r)
    if today_v is None or not vols or today_v < (sum(vols) / len(vols)) * 1.3:
        return None
    return {
        "pattern": "LION_MOUTH",
        "direction": "BULLISH",
        "confirmed": True,
        "reason": (
            "연속 하락 후 고거래량 핀버/회복봉(사자 입 패턴). "
            "패닉 매도 바닥에서 강한 매집 반전이 거래량으로 확인된 신호입니다."
        ),
    }


# ── Bearish detectors ─────────────────────────────────────────────────────────

def _detect_evening_star(rows: list[dict], atr20: float) -> dict | None:
    """
    저녁별+강한음봉 (EVENING_STAR_BEAR, confirmed) /
    저녁별          (EVENING_STAR, setup-only).

    4-candle confirmed:
      C1(rows[-4]): 큰 양봉 (≥0.5×ATR)
      C2(rows[-3]): 소형봉  (body < 0.4×C1)
      C3(rows[-2]): 큰 음봉, C1 중간 이하
      C4(rows[-1]): 강한 음봉 확인봉 (흑삼병 첫봉 또는 강한음봉)

    3-candle setup-only fallback: C1=rows[-3], C2=rows[-2], C3=rows[-1].
    """
    # ── 4-candle: confirmed ──────────────────────────────────────────────
    d4 = _unpack4(rows)
    if d4:
        o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3, o4,h4,l4,c4 = d4
        b1 = _body(o1, c1)
        if (
            _is_bull(o1, c1) and b1 >= 0.5 * atr20
            and _body(o2, c2) <= 0.4 * b1
            and _is_bear(o3, c3) and c3 <= _mid(o1, c1)
            and is_strong_bear(o4, h4, l4, c4, atr20)
        ):
            return {
                "pattern": "EVENING_STAR_BEAR",
                "direction": "BEARISH",
                "confirmed": True,
                "reason": (
                    "저녁별(큰양봉→소형봉→큰음봉) 이후 강한 음봉 확인봉까지 출현. "
                    "두 신호가 모두 확인된 강한 상승 반전 경고입니다."
                ),
            }

    # ── 3-candle: setup-only ─────────────────────────────────────────────
    d3 = _unpack3(rows)
    if d3:
        o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3 = d3
        b1 = _body(o1, c1)
        if (
            _is_bull(o1, c1) and b1 >= 0.5 * atr20
            and _body(o2, c2) <= 0.4 * b1
            and _is_bear(o3, c3) and c3 <= _mid(o1, c1)
        ):
            return {
                "pattern": "EVENING_STAR",
                "direction": "BEARISH",
                "confirmed": False,
                "reason": (
                    "저녁별(큰양봉→소형봉→큰음봉) 셋업 확인. "
                    "추가 강한 음봉 출현 시 신뢰도가 더욱 높아집니다."
                ),
            }
    return None


def _detect_three_black_crows(rows: list[dict], atr20: float) -> dict | None:
    """
    흑삼병 — 3개 연속 강한 음봉, 각각 전봉 몸통 내부 시가.
    3봉 구조 자체가 setup+confirmation이므로 항상 confirmed=True.
    """
    d3 = _unpack3(rows)
    if not d3:
        return None
    o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3 = d3

    for o, c in [(o1,c1), (o2,c2), (o3,c3)]:
        if not _is_bear(o, c) or _body(o, c) < 0.4 * atr20:
            return None
    if not (c2 < c1 and c3 < c2):
        return None
    if not (c1 < o2 <= o1 and c2 < o3 <= o2):
        return None

    return {
        "pattern": "THREE_BLACK_CROWS",
        "direction": "BEARISH",
        "confirmed": True,
        "reason": (
            "3개 연속 강한 음봉(흑삼병). 매도세가 3봉에 걸쳐 지속 확인된 "
            "하락 추세 가속 경고입니다."
        ),
    }


def _detect_bearish_engulfing(rows: list[dict], atr20: float) -> dict | None:
    """
    두브러리+그늘그개 (BEARISH_ENGULFING_DARK_CLOUD, confirmed) /
    두브러리          (BEARISH_ENGULFING, setup-only).

    3-candle confirmed:
      C1: 양봉
      C2: 장악형 음봉 (bearish engulfing)
      C3: 먹구름형 — C1 고가 이상 시가 후 C1 중간 이하 마감
    2-candle setup-only: C1 bull → C2 engulfing bear.
    """
    # ── 3-candle: confirmed (두브러리+그늘그개) ──────────────────────────
    d3 = _unpack3(rows)
    if d3:
        o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3 = d3
        engulf_ok = _is_bull(o1,c1) and _is_bear(o2,c2) and c2 < o1 and o2 > c1
        dark_cloud = (
            _is_bear(o3, c3)
            and o3 >= h1                    # 갭 상승 출발 (vs C1 고가)
            and c3 <= _mid(o1, c1)          # C1 중간 이하 마감
        )
        if engulf_ok and dark_cloud:
            return {
                "pattern": "BEARISH_ENGULFING_DARK_CLOUD",
                "direction": "BEARISH",
                "confirmed": True,
                "reason": (
                    "두브러리(장악형 음봉) 이후 그늘그개(먹구름형) 확인. "
                    "두 신호가 결합된 강한 상승 반전 경고입니다."
                ),
            }

    # ── 2-candle: setup-only ─────────────────────────────────────────────
    d2 = _unpack2(rows)
    if d2:
        o1,h1,l1,c1, o2,h2,l2,c2 = d2
        if _is_bull(o1,c1) and _is_bear(o2,c2) and c2 < o1 and o2 > c1:
            return {
                "pattern": "BEARISH_ENGULFING",
                "direction": "BEARISH",
                "confirmed": False,
                "reason": (
                    "두브러리(장악형 음봉) 셋업 확인. "
                    "그늘그개(먹구름형) 확인봉 출현 시 신뢰도가 더욱 높아집니다."
                ),
            }
    return None


def _detect_shooting_star(rows: list[dict], atr20: float) -> dict | None:
    """
    유성형+확인봉 (SHOOTING_STAR_CONFIRM, confirmed) /
    유성형        (SHOOTING_STAR, setup-only).
    """
    d2 = _unpack2(rows)
    if not d2:
        return None
    o1,h1,l1,c1, o2,h2,l2,c2 = d2

    if not is_shooting_star(o1, h1, l1, c1, atr20):
        return None

    if _is_bear(o2, c2) and c2 < c1:
        return {
            "pattern": "SHOOTING_STAR_CONFIRM",
            "direction": "BEARISH",
            "confirmed": True,
            "reason": (
                "유성형(상단 긴 꼬리) 이후 확인 음봉 출현. "
                "상단 매도 압력이 2봉 연속 확인된 하락 전환 신호입니다."
            ),
        }

    return {
        "pattern": "SHOOTING_STAR",
        "direction": "BEARISH",
        "confirmed": False,
        "reason": (
            "유성형(상단 긴 꼬리) 셋업 확인. "
            "확인 음봉 출현 시 신뢰도가 더욱 높아집니다."
        ),
    }


def _detect_three_inside_down(rows: list[dict], atr20: float) -> dict | None:
    """
    역삼강법 (Three Inside Down) — THREE_INSIDE_UP의 약세 대칭.

    C1: 큰 양봉 (≥0.5×ATR)
    C2: 작은 음봉, 몸통이 C1 몸통 안에 포함 (약세 하라미)
    C3: 강한 음봉, C1 open 이하 마감
    """
    d3 = _unpack3(rows)
    if not d3:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2, o3, h3, l3, c3 = d3
    if not _is_bull(o1, c1) or _body(o1, c1) < 0.5 * atr20:
        return None
    if not (_is_bear(o2, c2) and o2 <= c1 and c2 >= o1):  # harami inside bull C1
        return None
    if not (_is_bear(o3, c3) and c3 < o1):  # C3 closes below C1's open (body bottom)
        return None
    return {
        "pattern": "THREE_INSIDE_DOWN",
        "direction": "BEARISH",
        "confirmed": True,
        "reason": (
            "큰양봉 → 내부 음봉(하라미) → 강한 음봉 확인의 역삼강법. "
            "매수세 전환 실패가 3단 구조로 확인된 하락 전환 신호입니다."
        ),
    }


def _detect_harami_bearish(rows: list[dict], atr20: float) -> dict | None:
    """
    약세 하라미(2봉, setup-only) — THREE_INSIDE_DOWN의 앞 2봉 구조.

    C1: 큰 양봉 (≥0.5×ATR)
    C2: 작은 음봉, 몸통이 C1 몸통 안에 포함
    """
    d2 = _unpack2(rows)
    if not d2:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d2
    if not _is_bull(o1, c1) or _body(o1, c1) < 0.5 * atr20:
        return None
    if not _is_bear(o2, c2):
        return None
    if not (o2 <= c1 and c2 >= o1):  # C2 body inside C1 body
        return None
    if _body(o2, c2) > 0.5 * _body(o1, c1):  # C2 must be notably smaller
        return None
    return {
        "pattern": "HARAMI_BEARISH",
        "direction": "BEARISH",
        "confirmed": False,
        "reason": (
            "큰 양봉 내부에 작은 음봉(약세 하라미). "
            "매수세 약화 신호로, 다음 강한 음봉 출현 시 하락 전환 신뢰도가 높아집니다."
        ),
    }


# ── Detector registry ─────────────────────────────────────────────────────────

_BULLISH_DETECTORS = [
    _detect_morning_star,
    _detect_bullish_engulfing,
    _detect_spike_pinbar,
    _detect_three_inside_up,
    _detect_lion_mouth,      # volume-confirmed bottom reversal
    _detect_harami_bullish,  # 2-candle setup (less strict than three_inside_up)
]

_BEARISH_DETECTORS = [
    _detect_evening_star,
    _detect_three_black_crows,
    _detect_bearish_engulfing,
    _detect_shooting_star,
    _detect_three_inside_down,  # 3-candle confirmed bearish reversal
    _detect_harami_bearish,     # 2-candle setup
]


# ── Context-to-direction mapping ──────────────────────────────────────────────

_STRUCTURE_PHASE_DIR: dict[tuple[str, str], str] = {
    ("TREND_UP",           "PULLBACK"):            "BULLISH",
    ("TREND_UP",           "RETEST"):              "BULLISH",
    ("TREND_UP",           "NORMAL"):              "BOTH",
    ("TREND_UP",           "EXTENDED"):            "BEARISH",
    ("TREND_DOWN",         "STRUCTURE_BREAKDOWN"): "BEARISH",
    ("TREND_DOWN",         "STALLED"):             "BOTH",
    ("BREAKOUT_CANDIDATE", "NORMAL"):              "BULLISH",
    ("BREAKOUT_CANDIDATE", "RETEST"):              "BULLISH",
    ("RANGE",              "STALLED"):             "BOTH",
    ("RANGE_DRIFT",        "STALLED"):             "BOTH",
    ("DISTRIBUTION_WATCH", "EXTENDED"):            "BEARISH",
    ("DISTRIBUTION_WATCH", "STALLED"):             "BEARISH",
    ("DISTRIBUTION_WATCH", "NORMAL"):              "BEARISH",
}

_PRIMARY_PATTERN_DIR: dict[str, str] = {
    "trend_up_pullback":          "BULLISH",
    "horizontal_support_rebound": "BULLISH",
    "range_bottom_rebound":       "BULLISH",
    "resistance_breakout":        "BULLISH",
    "breakout_retest":            "BULLISH",
    "volume_turnaround":          "BULLISH",
    "relative_strength":          "BULLISH",
    "downtrend_bounce_trap":      "BEARISH",
    "distribution_zone":          "BEARISH",
    "overheated_chase_risk":      "BEARISH",
    "false_breakout_risk":        "BEARISH",
    "structure_breakdown_risk":   "BEARISH",
    "resistance_chase_risk":      "BEARISH",
    "overheated_pullback_risk":   "BEARISH",
    "zombie_breakout":            "BEARISH",
}

_RISK_DIR: dict[str, str] = {
    "STRUCTURE_BREAKDOWN":  "BEARISH",
    "MOMENTUM_COLLAPSE":    "BEARISH",
    "FAKE_BREAKOUT":        "BEARISH",
    "OVERHEATED_EXTENSION": "BEARISH",
}


def _expected_direction(structure: str, phase: str, primary: str, risk: str) -> str:
    if risk in _RISK_DIR:
        return _RISK_DIR[risk]
    if primary in _PRIMARY_PATTERN_DIR:
        return _PRIMARY_PATTERN_DIR[primary]
    return _STRUCTURE_PHASE_DIR.get((structure, phase), "BOTH")


def _fit_score(direction: str, expected: str, confirmed: bool) -> float:
    """
    Context-fit score (0.0–1.0).

    Confirmed (setup+확인봉) → full score.
    Setup-only              → 75% score (신호는 맞지만 확인 미완료).
    Counter-context         → 0.15 (역방향 신호, 거의 억제).
    """
    if expected == "BOTH":
        base = 0.65
    elif direction == expected:
        base = 1.0
    else:
        return 0.15   # counter-context: suppressed regardless of confirmed

    return base if confirmed else base * 0.75


# ── Public API ────────────────────────────────────────────────────────────────

def detect_contextual(
    rows: list[dict],
    atr20: float,
    *,
    market_structure: str = "",
    trend_phase: str = "",
    primary_pattern: str = "",
    risk_status: str = "",
) -> dict[str, Any] | None:
    """
    Detect the single most contextually relevant candlestick pattern.

    Priority order:
      1. Direction alignment with market context (aligned > counter-context)
      2. Confirmation state (confirmed=True > confirmed=False)
      3. Proximity to current close (handled implicitly by detector order)

    Returns None if no pattern fires or all candidates score below 0.3.
    """
    if not rows or len(rows) < 2 or not atr20 or atr20 <= 0:
        return None

    expected = _expected_direction(market_structure, trend_phase, primary_pattern, risk_status)

    if expected == "BULLISH":
        ordered = _BULLISH_DETECTORS + _BEARISH_DETECTORS
    elif expected == "BEARISH":
        ordered = _BEARISH_DETECTORS + _BULLISH_DETECTORS
    else:
        ordered = _BULLISH_DETECTORS + _BEARISH_DETECTORS

    hits: list[dict] = []
    for detector in ordered:
        try:
            result = detector(rows, atr20)
        except Exception:
            result = None
        if result:
            fit = _fit_score(result["direction"], expected, result["confirmed"])
            hits.append({**result, "fit": round(fit, 2)})

    if not hits:
        return None

    # Sort: best fit first; ties broken by confirmed status
    hits.sort(key=lambda h: (-h["fit"], 0 if h["confirmed"] else 1))
    best = hits[0]

    if best["fit"] < 0.3:
        return None

    best["candidates"] = [h["pattern"] for h in hits]
    return best
