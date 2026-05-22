"""Adjust weight_config.json from recent error_logs + validation summary (rule-based)."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import ERROR_LOGS, LEARNING_PATTERNS, WEIGHT_CONFIG


def _safe_float(x: Any, default: float = math.nan) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def run_learning_cycle(
    high_conf_threshold: float = 40.0,
    miss_rate_trigger: float = 0.52,
    weight_step: float = 0.04,
) -> dict[str, Any]:
    """
    Uses last N rows in data/decision_system/error_logs.csv:
    - If confidence > threshold and miss_rate high -> bump risk_weight, trim event_weight slightly.
    - If overall miss_rate low -> small revert toward 1.0.
    Appends a pattern record to learning_patterns.json (array root).
    """
    weights = _load_json(WEIGHT_CONFIG, {})
    if not isinstance(weights, dict) or not weights:
        return {"ok": False, "error": "weight_config.json empty or invalid"}

    if not ERROR_LOGS.exists() or ERROR_LOGS.stat().st_size < 10:
        return {"ok": True, "note": "no error_logs yet", "weights_unchanged": True}

    df = pd.read_csv(ERROR_LOGS, dtype=str).fillna("")
    if df.empty or "hit_or_miss" not in df.columns:
        return {"ok": True, "note": "error_logs empty", "weights_unchanged": True}

    tail = df.tail(300)
    conf = pd.to_numeric(tail.get("confidence_score", 0), errors="coerce")
    hits = tail["hit_or_miss"].astype(str).str.lower() == "hit"
    hi = tail[conf >= high_conf_threshold]
    hi_n = len(hi)
    hi_miss = int((hi["hit_or_miss"].astype(str).str.lower() != "hit").sum()) if hi_n else 0
    hi_miss_rate = (hi_miss / hi_n) if hi_n else 0.0

    overall_hit = float(hits.mean()) if len(tail) else 0.0
    miss_rate = 1.0 - overall_hit

    changed: dict[str, float] = {}
    if hi_n >= 8 and hi_miss_rate >= miss_rate_trigger:
        rw = _safe_float(weights.get("risk_weight"), 1.0)
        ew = _safe_float(weights.get("event_weight"), 1.0)
        nw = _safe_float(weights.get("news_weight"), 1.0)
        adj = _safe_float(weights.get("confidence_adjustment"), 0.0)
        weights["risk_weight"] = _clamp(rw + weight_step, 0.5, 2.0)
        weights["event_weight"] = _clamp(ew - weight_step * 0.5, 0.5, 2.0)
        weights["news_weight"] = _clamp(nw - weight_step * 0.25, 0.5, 2.0)
        weights["confidence_adjustment"] = _clamp(adj - 0.02, -0.5, 0.5)
        changed = {"risk_weight": weights["risk_weight"], "event_weight": weights["event_weight"]}
    elif miss_rate < 0.42 and len(tail) >= 30:
        touched = False
        for k in (
            "market_weight",
            "event_weight",
            "news_weight",
            "sector_weight",
            "momentum_weight",
            "volume_weight",
            "technical_weight",
            "risk_weight",
            "overheating_weight",
        ):
            v = _safe_float(weights.get(k), 1.0)
            if not math.isnan(v) and v != 1.0:
                weights[k] = _clamp(v * 0.98 + 0.02, 0.5, 2.0)
                touched = True
        if touched:
            changed = {"soft_revert": 1.0}

    if changed:
        _save_json(WEIGHT_CONFIG, weights)

    patterns = _load_json(LEARNING_PATTERNS, [])
    if not isinstance(patterns, list):
        patterns = []
    if changed:
        rec = (
            "tighten_risk_and_trim_event_news"
            if "risk_weight" in changed
            else "soft_revert_weights_toward_1"
        )
        patterns.append(
            {
                "pattern_id": f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "pattern_condition": f"high_conf_miss_rate>{miss_rate_trigger:.2f}|n={hi_n}",
                "historical_count": int(len(tail)),
                "win_rate": round(overall_hit, 4),
                "avg_return": 0.0,
                "avg_loss": 0.0,
                "best_market_regime": "",
                "worst_market_regime": "",
                "recommended_adjustment": rec,
            }
        )
        patterns = patterns[-200:]
        _save_json(LEARNING_PATTERNS, patterns)

    return {
        "ok": True,
        "tail_rows": len(tail),
        "high_conf_bucket_n": hi_n,
        "high_conf_miss_rate": round(hi_miss_rate, 4),
        "overall_hit_rate": round(overall_hit, 4),
        "weights_updated": bool(changed),
        "delta": changed,
    }
