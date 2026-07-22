"""Short-term defensive (inverse ETF) candidates for confirmed bear regimes.

This module deliberately does not turn a bear-market label into an automatic
inverse purchase.  The instrument itself must show a confirmed bullish chart
entry, because it is the traded asset; the underlying market must separately
be in a BEAR regime.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.engine.pattern_strategy import analyze, current_market_regime

_ROOT = Path(__file__).resolve().parents[4]
_CONFIG = _ROOT / "data" / "strategy" / "defensive_instruments.json"
_OHLCV = _ROOT / "data" / "market" / "ohlcv"


def _read_csv(path: Path) -> list[dict[str, Any]]:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                rows = [dict(row) for row in csv.DictReader(handle)]
                return sorted(rows, key=lambda row: str(row.get("date") or ""))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        except Exception:
            return []
    return []


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def _instruments(market: str) -> list[dict[str, Any]]:
    try:
        doc = json.loads(_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [item for item in doc.get("instruments", []) if str(item.get("market")) == market]


def defensive_candidates(market: str = "kr") -> dict[str, Any]:
    market = str(market).lower()
    regime = current_market_regime(market)
    if regime != "BEAR":
        return {
            "status": "CASH", "market": market, "marketRegime": regime,
            "items": [], "message": "Defensive inverse candidates are disabled outside a confirmed bear regime.",
        }

    items: list[dict[str, Any]] = []
    pending: list[str] = []
    for instrument in _instruments(market):
        symbol = str(instrument.get("symbol") or "").upper()
        rows = _read_csv(_OHLCV / f"{market}_{symbol}_daily.csv")
        if len(rows) < 60:
            pending.append(symbol)
            continue
        # The ETF price is expected to rise when its tracked market falls, so
        # assess its own chart as a long setup, while the index regime remains
        # the outer defensive gate.
        result = analyze(symbol, market, rows, market_regime="BULL")
        if (
            result.get("geometricPatternDirection") != "BULLISH"
            or result.get("geometricPatternStage") != "BUY_ZONE"
        ):
            continue
        trigger = _num(result.get("geometricPatternTrigger"))
        stop = _num(result.get("geometricPatternInvalidation"))
        atr = _num((result.get("indicators") or {}).get("atr20"))
        if not trigger or not stop or not atr or trigger <= stop:
            continue
        max_entry = trigger + 1.2 * atr
        target = max_entry + 2.0 * (max_entry - stop)
        items.append({
            **instrument,
            "tradeType": "DEFENSIVE_INVERSE_LONG",
            "entryRule": "confirmed close; next open only if not above maxEntry",
            "trigger": round(trigger, 4), "maxEntry": round(max_entry, 4),
            "stop": round(stop, 4), "target": round(target, 4),
            "pattern": result.get("geometricPattern"),
            "patternReason": result.get("geometricPatternReason"),
            "zones": result.get("supportResistanceZones", []),
        })
    return {
        "status": "OK", "market": market, "marketRegime": regime,
        "items": items, "dataPending": pending,
        "message": "Inverse ETF candidates require both a bear regime and a confirmed bullish entry on the ETF itself.",
    }
