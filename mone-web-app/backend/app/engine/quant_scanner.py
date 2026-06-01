from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")


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


def score_candidate(row: dict[str, Any], ohlcv_rows: list[dict[str, Any]], context: QuantContext) -> dict[str, Any]:
    if len(ohlcv_rows or []) < context.min_ohlcv_rows:
        return {
            "symbol": row.get("symbol") or row.get("ticker") or row.get("code"),
            "market": context.market,
            "mode": context.mode,
            "horizon": context.horizon,
            "score": None,
            "dataStatus": "DATA_PENDING",
            "reason": f"OHLCV {context.min_ohlcv_rows}거래일 미만",
        }
    return {
        "symbol": row.get("symbol") or row.get("ticker") or row.get("code"),
        "market": context.market,
        "mode": context.mode,
        "horizon": context.horizon,
        "score": None,
        "dataStatus": "ENGINE_PENDING",
        "reason": "3x3 정량 스코어 산식 연결 대기",
    }
