"""VTJ journal CSV 과거 기술지표 소급 채우기.

virtual_trade_journal.csv에 rsi_at_entry 등이 비어있는 기존 행에 대해
OHLCV 데이터로 신호 생성 시점(as_of_date) 기준의 기술지표를 역산하여 저장.

실행: python scripts/backfill_vtj_indicators.py

효과:
- 기존 350건+ VTJ 행에 RSI/거래량 채움
- factor_attribution.py OLS 회귀 샘플이 즉시 증가
"""
from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VTJ_CSV  = ROOT / "data" / "virtual_trade_journal.csv"
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"


def _num(v: Any) -> float | None:
    try:
        x = float(str(v).replace(",", "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _read_ohlcv(market: str, symbol: str) -> list[dict]:
    path = OHLCV_DIR / f"{market}_{symbol}_daily.csv"
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _closes_before(data: list[dict], as_of: str) -> list[float]:
    """as_of_date 이전(포함)의 종가 리스트."""
    result = []
    for row in data:
        d = str(row.get("date", "") or "")[:10]
        if d and d <= as_of:
            v = _num(row.get("close") or row.get("Close"))
            if v is not None:
                result.append(v)
    return result


def _volumes_before(data: list[dict], as_of: str) -> list[float]:
    result = []
    for row in data:
        d = str(row.get("date", "") or "")[:10]
        if d and d <= as_of:
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
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l < 1e-10:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


def _ma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _compute(market: str, symbol: str, as_of: str) -> dict[str, Any]:
    data = _read_ohlcv(market, symbol)
    closes  = _closes_before(data, as_of)
    volumes = _volumes_before(data, as_of)

    if len(closes) < 15:
        return {}

    close_now = closes[-1]
    ma5  = _ma(closes, 5)
    ma20 = _ma(closes, 20)
    rsi  = _rsi(closes, 14)

    # distanceToMa20 (%)
    d20 = round((close_now - ma20) / ma20 * 100, 2) if ma20 else None

    # volumeRatio20 (당일 제외 20일 평균 대비)
    if len(volumes) >= 21:
        avg_vol = sum(volumes[-21:-1]) / 20
        vr = round(volumes[-1] / avg_vol, 2) if avg_vol > 0 else None
    else:
        vr = None

    # mdd20 (최근 20일 최대 낙폭)
    if len(closes) >= 20:
        peak = max(closes[-20:])
        mdd = round((closes[-1] - peak) / peak * 100, 2)
    else:
        mdd = None

    # momentum5
    if len(closes) >= 6:
        mom5 = round((closes[-1] - closes[-6]) / closes[-6] * 100, 2)
    else:
        mom5 = None

    # maFullAlign
    ma60 = _ma(closes, 60)
    full_align = bool(ma5 and ma20 and ma60 and ma5 > ma20 > ma60)

    # atr14Pct
    if len(data) >= 15:
        highs  = [_num(r.get("high")  or r.get("High"))  for r in data[-16:-1]]
        lows   = [_num(r.get("low")   or r.get("Low"))   for r in data[-16:-1]]
        closes2 = [_num(r.get("close") or r.get("Close")) for r in data[-16:-2]]
        trs = []
        for i in range(1, len(highs)):
            h = highs[i]; l = lows[i]; pc = closes2[i - 1] if i - 1 < len(closes2) else None
            if h is None or l is None:
                continue
            tr = h - l
            if pc is not None:
                tr = max(tr, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if trs and close_now > 0:
            atr14_pct = round(sum(trs[-14:]) / len(trs[-14:]) / close_now * 100, 2)
        else:
            atr14_pct = None
    else:
        atr14_pct = None

    return {
        "rsi_at_entry":               rsi,
        "volume_ratio_at_entry":       vr,
        "distance_to_ma20_at_entry":   d20,
        "atr14_pct_at_entry":          atr14_pct,
        "ma_full_align_at_entry":      full_align,
        "mdd20_at_entry":              mdd,
        "momentum5_at_entry":          mom5,
    }


def main() -> None:
    if not VTJ_CSV.exists():
        print(f"[backfill] VTJ CSV 없음: {VTJ_CSV}")
        return

    # 현재 CSV 읽기
    rows: list[dict] = []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with VTJ_CSV.open(encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except Exception:
            continue

    if not rows:
        print("[backfill] VTJ CSV 비어있음")
        return

    all_keys = list(rows[0].keys())
    # 새 컬럼이 없으면 추가
    new_cols = [
        "rsi_at_entry", "volume_ratio_at_entry", "distance_to_ma20_at_entry",
        "atr14_pct_at_entry", "ma_full_align_at_entry", "mdd20_at_entry", "momentum5_at_entry",
    ]
    for col in new_cols:
        if col not in all_keys:
            # raw_recommendation_json 앞에 삽입 (있으면), 없으면 마지막에
            if "raw_recommendation_json" in all_keys:
                idx = all_keys.index("raw_recommendation_json")
                all_keys.insert(idx, col)
            else:
                all_keys.append(col)

    filled = 0
    skipped = 0
    no_ohlcv = 0

    for row in rows:
        # 이미 채워진 행은 건너뜀
        if row.get("rsi_at_entry") not in (None, "", "nan", "None"):
            skipped += 1
            continue

        market  = str(row.get("market", "")).lower().strip()
        symbol  = str(row.get("symbol", "")).strip()
        as_of   = str(row.get("as_of_date", ""))[:10]

        if not (market in ("kr", "us") and symbol and as_of):
            skipped += 1
            continue

        ind = _compute(market, symbol, as_of)
        if not ind:
            no_ohlcv += 1
            continue

        for col, val in ind.items():
            row[col] = "" if val is None else val

        # 새 컬럼 기본값 보장
        for col in new_cols:
            row.setdefault(col, "")

        filled += 1

    # 덮어쓰기
    with VTJ_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"[backfill_vtj_indicators] 완료")
    print(f"  채운 행:     {filled}")
    print(f"  이미 있음:   {skipped}")
    print(f"  OHLCV 없음:  {no_ohlcv}")
    print(f"  전체 행:     {len(rows)}")


if __name__ == "__main__":
    main()
