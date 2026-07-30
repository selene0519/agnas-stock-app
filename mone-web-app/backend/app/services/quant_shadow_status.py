from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services import data_loader as data


REPORTS_DIR = data.REPO_ROOT / "reports"
REPORT_FILES = {
    "cohort": "strategy_cohort_audit.json",
    "alpha": "recommendation_alpha.json",
    "sleeve": "strategy_sleeve_nav_v2.json",
    "metaGate": "shadow_meta_gate.json",
    "riskBudget": "shadow_risk_budget.json",
}


def _read_report(name: str) -> dict[str, Any]:
    path = REPORTS_DIR / REPORT_FILES[name]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {**payload, "_source": f"reports/{path.name}"}
    except Exception:
        pass
    return {"status": "MISSING", "_source": f"reports/{path.name}"}


def shadow_status() -> dict[str, Any]:
    reports = {name: _read_report(name) for name in REPORT_FILES}
    meta = reports["metaGate"]
    risk = reports["riskBudget"]
    alpha = reports["alpha"]
    sleeve = reports["sleeve"]
    cohort = reports["cohort"]

    missing = [name for name, report in reports.items() if report.get("status") == "MISSING"]
    summary = meta.get("summary") if isinstance(meta.get("summary"), dict) else {}
    windows = alpha.get("windows") if isinstance(alpha.get("windows"), dict) else {}
    d20 = windows.get("D+20") if isinstance(windows.get("D+20"), dict) else {}
    ranking = sleeve.get("ranking") if isinstance(sleeve.get("ranking"), list) else []
    sleeves = sleeve.get("sleeves") if isinstance(sleeve.get("sleeves"), dict) else {}
    top_name = ranking[0] if ranking else None
    top_sleeve = sleeves.get(top_name) if top_name and isinstance(sleeves.get(top_name), dict) else None

    take = int(summary.get("take") or 0)
    decision = "ABSTAIN" if bool(summary.get("abstain", take == 0)) else "SHADOW_TAKE"
    reasons: list[str] = []
    if missing:
        reasons.append("MISSING_REPORTS")
    if not bool(d20.get("significanceUsable")):
        reasons.append("ALPHA_NOT_PROVEN")
    if not top_sleeve or float(top_sleeve.get("totalReturnPct") or 0.0) <= 0:
        reasons.append("NO_POSITIVE_SLEEVE")
    if float(risk.get("grossExposurePct") or 0.0) <= 0:
        reasons.append("NO_APPROVED_RISK_EXPOSURE")

    return {
        "status": "WARN" if reasons else "OK",
        "mode": "SHADOW_ONLY",
        "liveTradingAllowed": False,
        "decision": decision,
        "decisionReasons": reasons,
        "summary": {
            "candidates": int(summary.get("candidates") or 0),
            "take": take,
            "wait": int(summary.get("wait") or 0),
            "reject": int(summary.get("reject") or 0),
            "grossExposurePct": float(risk.get("grossExposurePct") or 0.0),
            "cashWeightPct": float(risk.get("cashWeightPct") or 100.0),
            "portfolioBeta": float(risk.get("portfolioBeta") or 0.0),
            "d20BlockMeanCarPct": d20.get("blockMeanCarPct"),
            "d20AlphaCi95": d20.get("bootstrapCi95"),
            "independentAlphaBlocks": d20.get("independentMarketDateBlocks"),
            "topSleeve": top_name,
            "topSleeveReturnPct": top_sleeve.get("totalReturnPct") if top_sleeve else None,
            "topSleeveProfitFactor": top_sleeve.get("profitFactor") if top_sleeve else None,
            "independentDecisions": (cohort.get("summary") or {}).get("independentDecisions"),
        },
        "sources": {name: report.get("_source") for name, report in reports.items()},
        "missingReports": missing,
        "reports": reports,
    }
