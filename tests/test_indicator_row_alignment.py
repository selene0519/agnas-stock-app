"""OHLCV 한 행이 깨져도 지표 계산이 어긋나거나 죽지 않는지 회귀 테스트.

`_series`는 컬럼별로 독립 파싱해서 실패값을 건너뛴다. 그래서 어느 한 컬럼만
깨진 행이 있으면 그 뒤로 high/low가 close와 하루씩 밀려 지표가 조용히 틀리고,
운이 나쁘면 `_atr`이 IndexError로 죽는다.

2026-07-27 실측: kr_007660_daily.csv 1427행(2020-02-24)이 두 행이 합쳐진 형태로
깨져 있었고(high="332020-05-14", low="kr"), 그 한 종목 때문에
generate_kr_recommendations가 통째로 크래시해 KR 추천이 7-23부터 멈춰 있었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_kr_recommendations import (  # noqa: E402
    _aligned_ohlc_rows,
    _atr,
    _series,
    indicators,
)


def _row(date: str, o: float, h: float, l: float, c: float, v: int = 1000) -> dict:
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _clean_rows(n: int = 60) -> list[dict]:
    return [_row(f"2026-01-{i % 28 + 1:02d}", 100 + i, 105 + i, 95 + i, 100 + i) for i in range(n)]


def test_corrupt_row_is_dropped_whole() -> None:
    rows = _clean_rows()
    # 실제로 발견된 형태: 두 행이 합쳐져 high에 날짜, low에 시장코드가 들어감
    rows.insert(30, {"date": "2020-02-24", "open": 100, "high": "332020-05-14",
                     "low": "kr", "close": 101, "volume": 500})
    cleaned = _aligned_ohlc_rows(rows)

    assert len(cleaned) == len(rows) - 1
    assert all(r.get("low") != "kr" for r in cleaned)


def test_series_stay_aligned_after_cleaning() -> None:
    rows = _clean_rows()
    rows.insert(30, {"date": "2020-02-24", "open": 100, "high": "332020-05-14",
                     "low": "kr", "close": 101, "volume": 500})
    cleaned = _aligned_ohlc_rows(rows)

    c = _series(cleaned, "close")
    h = _series(cleaned, "high")
    l = _series(cleaned, "low")
    assert len(c) == len(h) == len(l), "정리 후에도 시리즈 길이가 어긋난다"


def test_indicators_do_not_crash_on_corrupt_row() -> None:
    rows = _clean_rows()
    rows.insert(30, {"date": "2020-02-24", "open": 100, "high": "332020-05-14",
                     "low": "kr", "close": 101, "volume": 500})

    out = indicators(rows)  # 예전엔 여기서 IndexError로 전체 생성이 죽었다
    assert out is not None
    assert out.get("atr14") is not None


def test_atr_tolerates_ragged_input_directly() -> None:
    """다른 호출자가 생겨도 한 종목 때문에 전체가 죽지 않도록."""
    c = [float(i) for i in range(40)]
    h = [float(i) + 2 for i in range(39)]  # 하나 짧음
    l = [float(i) - 2 for i in range(39)]

    assert _atr(h, l, c) is not None


def test_atr_returns_none_when_too_short() -> None:
    assert _atr([1.0] * 5, [1.0] * 5, [1.0] * 5) is None
