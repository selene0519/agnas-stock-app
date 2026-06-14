"""
백테스트 v2 — 추천일 기준 체결 검증 엔진

규칙:
- recommendationDate(또는 generatedAt) 이후 봉만 평가
- priceSession(PREMARKET/INTRADAY)이면 추천 당일 포함, CLOSING/AFTER_MARKET이면 다음 거래일부터
- entry_window_days 안에 진입가 터치 → 체결, 이후 holding_days 동안 목표/손절/기간종료
- 목표/손절 동시 터치 → 손절 우선 (일봉 일중 순서 불명)
- slippage_pct 반영
- generatedAt/추천일 없으면 '스키마부족' 명시 반환 (silent fallback 없음)
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# horizon별 기본 설정
# 보정 근거: MISS_ENTRY_TOO_LOW 25-42% — 진입 허용 기간 확대
# short: 1→2일 (진입창), 2→3일 (보유창)
# swing: 2→3일 (진입창), 5→7일 (보유창)
# mid:   3→4일 (진입창), 20→22일 (보유창)
HORIZON_SETTINGS: dict[str, dict[str, int]] = {
    "short": {"entry_window_days": 2, "holding_days": 3},
    "swing": {"entry_window_days": 3, "holding_days": 7},
    "mid":   {"entry_window_days": 4, "holding_days": 22},
}

# priceSession 당일 포함 여부
_SAME_DAY_SESSIONS = {"PREMARKET", "INTRADAY", "PRE_MARKET", "PRE"}


def _num(v: Any) -> float | None:
    try:
        import math
        import re
        raw = re.sub(r"[,원$%]", "", str(v or "")).strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        f = float(raw)
        return None if math.isnan(f) else f
    except Exception:
        return None


def _row_date(row: pd.Series) -> str:
    return str(row.get("date") or row.get("Date") or "")[:10]


def evaluate_recommendation(
    rec: dict[str, Any],
    ohlcv: pd.DataFrame,
    settings: dict[str, Any],
    horizon: str = "swing",
) -> dict[str, Any]:
    """
    추천 1건에 대해 OHLCV로 체결/청산을 검증한다.

    Parameters
    ----------
    rec      : 추천 딕셔너리 (generatedAt 또는 recommendationDate 필수)
    ohlcv    : date/open/high/low/close 컬럼을 가진 DataFrame
    settings : TRADE_MODE_SETTINGS 항목 (slippage_pct 포함)
    horizon  : "short" / "swing" / "mid"
    """
    # ── 기본값 추출 ────────────────────────────────────────────────────────────
    entry  = _num(rec.get("entry") or rec.get("entryPrice"))
    stop   = _num(rec.get("stop")  or rec.get("stopPrice"))
    target = _num(rec.get("target") or rec.get("targetPrice"))
    market = str(rec.get("market", "kr")).lower()
    slip   = float(settings.get("slippage_pct", 0.002))

    h_cfg  = HORIZON_SETTINGS.get(horizon, HORIZON_SETTINGS["swing"])
    entry_window = h_cfg["entry_window_days"]
    holding_days = h_cfg["holding_days"]

    # ── 가격 부족 ──────────────────────────────────────────────────────────────
    if entry is None or stop is None or target is None:
        return _err("스키마부족", "진입가/목표가/손절가 없음")

    # ── 추천일 파싱 ────────────────────────────────────────────────────────────
    rec_date_str = (
        str(rec.get("generatedAt") or rec.get("recommendationDate") or "")[:10]
    )
    if not rec_date_str or len(rec_date_str) != 10:
        return _err("스키마부족", "추천일(generatedAt/recommendationDate) 없음")

    try:
        rec_ts = pd.Timestamp(rec_date_str)
    except Exception:
        return _err("스키마부족", f"추천일 파싱 실패: {rec_date_str}")

    # ── OHLCV 날짜 정규화 ──────────────────────────────────────────────────────
    if ohlcv is None or ohlcv.empty:
        return _err("데이터부족", "OHLCV 없음")

    work = ohlcv.copy()
    work["_date_ts"] = pd.to_datetime(work.get("date"), errors="coerce").dt.normalize()
    work = work.dropna(subset=["_date_ts"]).sort_values("_date_ts").reset_index(drop=True)

    # ── priceSession 기준 평가 시작일 결정 ───────────────────────────────────
    session = str(rec.get("priceSession") or rec.get("recommendationSession") or "").upper()
    if session in _SAME_DAY_SESSIONS:
        eval_start = rec_ts          # 당일 포함
    else:
        eval_start = rec_ts + pd.Timedelta(days=1)  # 다음 거래일부터 (보수적)

    # ── 평가 윈도우 구성 ───────────────────────────────────────────────────────
    future = work[work["_date_ts"] >= eval_start].reset_index(drop=True)
    if future.empty:
        return _err("데이터부족", f"추천일({rec_date_str}) 이후 OHLCV 없음")

    entry_window_df = future.head(entry_window)
    if entry_window_df.empty:
        return _err("데이터부족", "진입 허용 기간 OHLCV 없음")

    # ── 진입 체결 확인 ─────────────────────────────────────────────────────────
    fill_idx: int | None = None
    fill_date = ""
    for idx, row in entry_window_df.iterrows():
        hi = _num(row.get("high")) or _num(row.get("close"))
        lo = _num(row.get("low"))  or _num(row.get("close"))
        if hi is None or lo is None:
            continue
        if lo <= entry <= hi:
            fill_idx = int(idx)
            fill_date = _row_date(row)
            break

    if fill_idx is None:
        last = entry_window_df.iloc[-1]
        return {
            "executionStatus": "미체결",
            "executionReason": f"진입 허용 {entry_window}거래일 내 진입가 미도달",
            "filled": False,
            "excludedFromReturn": True,
            "entryDate": "",
            "exitDate": "",
            "entryPrice": entry,
            "exitPrice": None,
            "pnlPct": None,
            "grossPnlPct": None,
            "netPnlPct": None,
            "barsHeld": 0,
            "exitStatus": "미체결",
            "reason": "미체결",
            "evaluationSession": session or "CLOSING",
            "evalStartDate": str(eval_start.date()),
        }

    # ── 체결 이후 목표/손절/기간종료 판정 ────────────────────────────────────
    holding_df = future.iloc[fill_idx: fill_idx + holding_days + 1].reset_index(drop=True)

    exit_price: float | None = None
    exit_date = ""
    exit_status = "기간종료"
    bars_held = 0

    for i, row in holding_df.iterrows():
        hi = _num(row.get("high")) or _num(row.get("close"))
        lo = _num(row.get("low"))  or _num(row.get("close"))
        close = _num(row.get("close"))
        if hi is None or lo is None:
            continue

        target_hit = hi >= target
        stop_hit   = lo <= stop

        if target_hit and stop_hit:
            # 동시 터치 → 손절 우선 (일봉 일중 순서 불명)
            exit_price  = stop
            exit_status = "손절(동시터치)"
            exit_date   = _row_date(row)
            bars_held   = int(i) + 1
            break
        if target_hit:
            exit_price  = target
            exit_status = "목표도달"
            exit_date   = _row_date(row)
            bars_held   = int(i) + 1
            break
        if stop_hit:
            exit_price  = stop
            exit_status = "손절"
            exit_date   = _row_date(row)
            bars_held   = int(i) + 1
            break
        if int(i) == len(holding_df) - 1:
            exit_price  = close if close is not None else entry
            exit_status = "기간종료"
            exit_date   = _row_date(row)
            bars_held   = int(i) + 1

    if exit_price is None:
        exit_price  = entry
        exit_status = "기간종료"
        bars_held   = len(holding_df)

    blended_exit = exit_price

    # ── MFE / MAE 계산 (체결 이후 보유 구간 기준) ─────────────────────────
    # MFE: 체결 후 최대 유리한 가격 (고가 기준)
    # MAE: 체결 후 최대 불리한 가격 (저가 기준)
    mfe_pct: float | None = None
    mae_pct: float | None = None
    if entry and not holding_df.empty:
        highs = [_num(r.get("high")) or _num(r.get("close")) for _, r in holding_df.iterrows()]
        lows  = [_num(r.get("low"))  or _num(r.get("close")) for _, r in holding_df.iterrows()]
        highs_ok = [h for h in highs if h is not None]
        lows_ok  = [l for l in lows  if l is not None]
        if highs_ok:
            mfe_pct = round((max(highs_ok) - entry) / entry * 100, 3)
        if lows_ok:
            mae_pct = round((min(lows_ok)  - entry) / entry * 100, 3)

    # ── PnL 계산 (슬리피지 포함) ───────────────────────────────────────────
    gross_pnl   = (blended_exit - entry) / entry * 100 if entry else None
    actual_buy  = entry * (1 + slip)
    actual_sell = blended_exit * (1 - slip)
    net_pnl     = (actual_sell - actual_buy) / actual_buy * 100 if actual_buy else None

    return {
        "executionStatus": "체결",
        "executionReason": f"{fill_date} 진입가 도달 → {exit_date or '보유중'} {exit_status}",
        "filled": True,
        "excludedFromReturn": False,
        "entryDate": fill_date,
        "exitDate": exit_date,
        "entryPrice": round(actual_buy, 4),
        "exitPrice": round(actual_sell, 4),
        "grossPnlPct": round(gross_pnl, 3) if gross_pnl is not None else None,
        "pnlPct": round(net_pnl, 3) if net_pnl is not None else None,
        "netPnlPct": round(net_pnl, 3) if net_pnl is not None else None,
        "barsHeld": bars_held,
        "exitStatus": exit_status,
        "reason": exit_status,
        "mfePct": mfe_pct,
        "maePct": mae_pct,
        "slippagePct": slip,
        "entryWindowDays": entry_window,
        "holdingDays": holding_days,
        "evaluationSession": session or "CLOSING",
        "evalStartDate": str(eval_start.date()),
        "rule": (
            "추천일 기준 이후 봉 평가 / "
            f"진입창 {entry_window}일 / 보유창 {holding_days}일 / "
            "동시터치 손절우선 / 슬리피지 반영"
        ),
    }


def _err(status: str, reason: str) -> dict[str, Any]:
    return {
        "executionStatus": "검증 대기",
        "executionReason": reason,
        "filled": False,
        "excludedFromReturn": True,
        "entryDate": "",
        "exitDate": "",
        "entryPrice": None,
        "exitPrice": None,
        "pnlPct": None,
        "grossPnlPct": None,
        "netPnlPct": None,
        "barsHeld": 0,
        "exitStatus": status,
        "reason": reason,
        "pnlText": status,
    }
