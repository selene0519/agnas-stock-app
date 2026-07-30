#!/usr/bin/env python3
"""Deterministic portfolio risk budget for shadow TAKE decisions.

All limits only reduce positions. Removed exposure remains cash and is never
redistributed. Missing beta is conservatively treated as 1.0; missing stop
distance blocks allocation entirely.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
META_GATE = ROOT / "reports" / "shadow_meta_gate.json"
OUT = ROOT / "reports" / "shadow_risk_budget.json"

BASE_WEIGHT = 0.10
MAX_POSITION_WEIGHT = 0.10
MAX_GROSS_EXPOSURE = 0.30
MAX_SECTOR_EXPOSURE = 0.15
MAX_PORTFOLIO_BETA = 0.30
ACCOUNT_RISK_PER_TRADE = 0.005


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def allocate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    positions: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    sector_weights: dict[str, float] = {}
    gross = 0.0
    portfolio_beta = 0.0

    ranked = sorted(
        [candidate for candidate in candidates if str(candidate.get("decision") or "").upper() == "TAKE"],
        key=lambda candidate: _num(candidate.get("score")) or float("-inf"),
        reverse=True,
    )
    for candidate in ranked:
        symbol = str(candidate.get("symbol") or "").strip()
        entry = _num(candidate.get("entryPrice"))
        stop = _num(candidate.get("stopPrice"))
        if entry is None or stop is None or entry <= 0 or stop >= entry:
            rejected.append({"symbol": symbol, "reason": "INVALID_OR_MISSING_STOP_DISTANCE"})
            continue
        stop_distance = (entry - stop) / entry
        if stop_distance <= 0:
            rejected.append({"symbol": symbol, "reason": "INVALID_OR_MISSING_STOP_DISTANCE"})
            continue

        beta = abs(_num(candidate.get("beta")) or 1.0)
        sector = str(candidate.get("sector") or "UNKNOWN").strip() or "UNKNOWN"
        risk_weight = ACCOUNT_RISK_PER_TRADE / stop_distance
        requested = min(BASE_WEIGHT, MAX_POSITION_WEIGHT, risk_weight)
        remaining_gross = max(0.0, MAX_GROSS_EXPOSURE - gross)
        remaining_sector = max(0.0, MAX_SECTOR_EXPOSURE - sector_weights.get(sector, 0.0))
        remaining_beta_weight = max(0.0, MAX_PORTFOLIO_BETA - portfolio_beta) / beta if beta > 0 else 0.0
        final_weight = min(requested, remaining_gross, remaining_sector, remaining_beta_weight)
        clamps: list[str] = []
        if requested < BASE_WEIGHT:
            clamps.append("PER_TRADE_STOP_RISK")
        if final_weight < requested:
            if remaining_gross <= final_weight + 1e-12:
                clamps.append("MAX_GROSS_EXPOSURE")
            if remaining_sector <= final_weight + 1e-12:
                clamps.append("MAX_SECTOR_EXPOSURE")
            if remaining_beta_weight <= final_weight + 1e-12:
                clamps.append("MAX_PORTFOLIO_BETA")
        if final_weight <= 1e-9:
            rejected.append({"symbol": symbol, "reason": "NO_RISK_BUDGET_REMAINING", "clamps": clamps})
            continue

        gross += final_weight
        portfolio_beta += final_weight * beta
        sector_weights[sector] = sector_weights.get(sector, 0.0) + final_weight
        positions.append({
            "symbol": symbol,
            "market": candidate.get("market"),
            "sector": sector,
            "weight": round(final_weight, 6),
            "weightPct": round(final_weight * 100.0, 4),
            "stopDistancePct": round(stop_distance * 100.0, 4),
            "lossAtStopPctOfEquity": round(final_weight * stop_distance * 100.0, 4),
            "beta": round(beta, 4),
            "betaSource": "CANDIDATE" if _num(candidate.get("beta")) is not None else "CONSERVATIVE_DEFAULT_1.0",
            "clamps": clamps,
        })

    return {
        "positions": positions,
        "rejected": rejected,
        "grossExposure": round(gross, 6),
        "grossExposurePct": round(gross * 100.0, 4),
        "cashWeight": round(1.0 - gross, 6),
        "cashWeightPct": round((1.0 - gross) * 100.0, 4),
        "portfolioBeta": round(portfolio_beta, 6),
        "sectorWeights": {sector: round(weight, 6) for sector, weight in sector_weights.items()},
    }


def build() -> dict[str, Any]:
    try:
        meta = json.loads(META_GATE.read_text(encoding="utf-8"))
    except Exception:
        meta = {"take": []}
    allocation = allocate(meta.get("take") if isinstance(meta.get("take"), list) else [])
    return {
        "status": "SHADOW_ONLY",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "baseWeight": BASE_WEIGHT,
            "maxPositionWeight": MAX_POSITION_WEIGHT,
            "maxGrossExposure": MAX_GROSS_EXPOSURE,
            "maxSectorExposure": MAX_SECTOR_EXPOSURE,
            "maxPortfolioBeta": MAX_PORTFOLIO_BETA,
            "accountRiskPerTrade": ACCOUNT_RISK_PER_TRADE,
            "removedExposureStaysCash": True,
            "redistributionAllowed": False,
        },
        **allocation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    report = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "grossExposurePct", "cashWeightPct", "portfolioBeta")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
