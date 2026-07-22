"""Rigorously-measured edge tier for each chart pattern, by regime.

Backed by reports/pattern_edge_map_kr.json (generated from the walk-forward
harnesses): geometric patterns are graded from train/OOS trade-simulation
(PROVEN only if they clear the promotion gate), engine/candlestick patterns
from excess return over the survivorship-biased regime baseline.

This is how the app stops treating every detected pattern as equally
investable: a proven-edge setup is surfaced/boosted, a no-measured-edge one is
labelled so, and raw survivorship drift can no longer masquerade as an edge.
It is a transparency + sizing hint, never a return forecast.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[4]

# Conservative multipliers — these are research-grade tiers, not promises.
_TIER_MULTIPLIER = {"PROVEN": 1.10, "WEAK": 1.00, "NONE": 0.90, "UNKNOWN": 1.00}

_CACHE: dict[str, dict[str, Any]] = {}


def _load(market: str) -> dict[str, Any]:
    market = str(market or "kr").strip().lower()
    if market not in _CACHE:
        path = _ROOT / "reports" / f"pattern_edge_map_{market}.json"
        try:
            _CACHE[market] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # No validated map for this market yet -> everything is UNKNOWN
            # (neutral). Never apply one market's verdicts to another.
            _CACHE[market] = {"patterns": {}}
    return _CACHE[market]


def _norm_pattern(pattern: Any) -> str:
    return str(pattern or "").strip().upper().replace(":BUY_ZONE", "")


def edge_for(pattern: Any, regime: Any, market: Any = "kr") -> dict[str, Any]:
    """Return {tier, multiplier, source, detail} for a pattern in a regime."""
    doc = _load(market)
    pat = _norm_pattern(pattern)
    reg = str(regime or "").strip().upper()
    entry = (doc.get("patterns") or {}).get(pat)
    # patterns are also keyed by lowercase engine names; try raw too
    if entry is None:
        entry = (doc.get("patterns") or {}).get(str(pattern or "").strip())
    if not isinstance(entry, dict):
        return {"tier": "UNKNOWN", "multiplier": 1.0, "source": None, "detail": None}
    cell = entry.get(reg) or {}
    tier = str(cell.get("tier") or "UNKNOWN").upper()
    return {
        "tier": tier,
        "multiplier": _TIER_MULTIPLIER.get(tier, 1.0),
        "source": cell.get("source"),
        "detail": cell,
    }


def edge_tier(pattern: Any, regime: Any, market: Any = "kr") -> str:
    return edge_for(pattern, regime, market)["tier"]


def edge_multiplier(pattern: Any, regime: Any, market: Any = "kr") -> float:
    return float(edge_for(pattern, regime, market)["multiplier"])
