#!/usr/bin/env python3
"""Audit persisted walk-forward outputs for temporal and universe integrity."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT = REPORTS / "walkforward_integrity.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _csv_integrity(path: Path, cutoff: date) -> dict[str, Any]:
    if not path.exists():
        return {"status": "MISSING", "totalRows": 0, "futureWindowCount": 0, "invalidWindowCount": 0}
    total = future = invalid = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total += 1
            try:
                window = datetime.fromisoformat(str(row.get("window") or "")).date()
            except (TypeError, ValueError):
                invalid += 1
                continue
            if window > cutoff:
                future += 1
    return {
        "status": "OK" if not future and not invalid else "INVALID_TEMPORAL_DATA",
        "totalRows": total,
        "futureWindowCount": future,
        "invalidWindowCount": invalid,
    }


def audit_market(market: str, reports_dir: Path = REPORTS, as_of: date | None = None) -> dict[str, Any]:
    cutoff = as_of or date.today()
    csv_check = _csv_integrity(reports_dir / f"walkforward_results_{market}.csv", cutoff)
    summary = _read_json(reports_dir / f"walkforward_summary_{market}.json")
    reasons: list[str] = []
    if csv_check["status"] != "OK":
        reasons.append("CSV_TEMPORAL_INTEGRITY_FAILED")
    combos = summary.get("combos") if isinstance(summary.get("combos"), dict) else {}
    if not combos:
        reasons.append("SUMMARY_MISSING_OR_EMPTY")
    embargo_proven = True
    survivorship_bias = False
    point_in_time_universe = True
    for result in combos.values():
        quality = result.get("dataQuality") if isinstance(result, dict) and isinstance(result.get("dataQuality"), dict) else {}
        if not bool(quality.get("lookAheadControlled")):
            reasons.append("OHLCV_LOOKAHEAD_CONTROL_NOT_PROVEN")
        if not bool(quality.get("trainingOutcomesResolvedBeforeWindow")) or not bool(quality.get("sameDayOutcomeEmbargo")):
            embargo_proven = False
        survivorship_bias = survivorship_bias or bool(quality.get("survivorshipBias"))
        point_in_time_universe = point_in_time_universe and bool(quality.get("pointInTimeListingFilter"))
    if combos and not embargo_proven:
        reasons.append("RERUN_REQUIRED_FOR_OUTCOME_EMBARGO_PROOF")
    if survivorship_bias or (combos and not point_in_time_universe):
        reasons.append("SURVIVORSHIP_BIAS_RESEARCH_ONLY")
    return {
        "market": market,
        "asOf": cutoff.isoformat(),
        "status": "OK" if not reasons else "WARN",
        "promotionGrade": not reasons,
        "blockingReasons": list(dict.fromkeys(reasons)),
        "csv": csv_check,
        "comboCount": len(combos),
        "outcomeEmbargoProven": embargo_proven if combos else False,
        "survivorshipBias": survivorship_bias,
        "pointInTimeUniverse": point_in_time_universe if combos else False,
    }


def build(reports_dir: Path = REPORTS, as_of: date | None = None) -> dict[str, Any]:
    markets = {market: audit_market(market, reports_dir, as_of) for market in ("kr", "us")}
    promotion_grade = all(row["promotionGrade"] for row in markets.values())
    return {
        "status": "OK" if promotion_grade else "WARN",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "promotionGrade": promotion_grade,
        "policy": {
            "futureWindowsForbidden": True,
            "trainingOutcomesMustResolveBeforeWindow": True,
            "sameDayOutcomesEmbargoed": True,
            "pointInTimeUniverseRequiredForPromotion": True,
        },
        "markets": markets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    report = build(args.reports_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "promotionGrade": report["promotionGrade"], "markets": report["markets"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
