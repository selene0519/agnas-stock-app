"""Audit every virtual trade journal row against its latest realized evaluation."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
JOURNAL_CSV = ROOT / "data" / "virtual_trade_journal.csv"
EVALUATION_CSV = ROOT / "data" / "virtual_trade_evaluations.csv"
AUDIT_CSV = ROOT / "reports" / "virtual_trade_journal_audit.csv"
SUMMARY_JSON = ROOT / "reports" / "virtual_trade_journal_audit_summary.json"

VALID_MARKETS = {"kr", "us"}
VALID_MODES = {"conservative", "balanced", "aggressive"}
VALID_HORIZONS = {"short", "swing", "mid"}
LOSS_OUTCOMES = {"STOP_HIT", "STOP_FIRST"}
WIN_OUTCOMES = {"TARGET_HIT", "TARGET"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except UnicodeDecodeError:
            continue
    return []


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _latest_evaluations(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        journal_id = str(row.get("journal_id") or "").strip()
        if not journal_id:
            continue
        if journal_id not in latest or str(row.get("evaluated_at") or "") >= str(latest[journal_id].get("evaluated_at") or ""):
            latest[journal_id] = row
    return latest


def _strategy_key(row: dict[str, str]) -> str:
    return "_".join(str(row.get(key) or "").lower() for key in ("market", "mode", "horizon"))


def _audit_row(journal: dict[str, str], evaluation: dict[str, str] | None, duplicate_natural: bool) -> dict[str, Any]:
    market = str(journal.get("market") or "").lower()
    mode = str(journal.get("mode") or "").lower()
    horizon = str(journal.get("horizon") or "").lower()
    entry = _number(journal.get("entry_price"))
    stop = _number(journal.get("stop_price"))
    target = _number(journal.get("target_price"))
    flags: list[str] = []
    if market not in VALID_MARKETS or mode not in VALID_MODES or horizon not in VALID_HORIZONS:
        flags.append("INVALID_STRATEGY_SCOPE")
    if entry is None or stop is None or target is None:
        flags.append("MISSING_PRICE_LEVEL")
    elif not target > entry > stop:
        flags.append("INVALID_PRICE_LEVELS")
    if duplicate_natural:
        flags.append("DUPLICATE_NATURAL_KEY")

    status = "OPEN"
    outcome = "PENDING"
    pnl = gross = None
    failure_reason = ""
    diagnostic_reason = ""
    if evaluation is None:
        flags.append("MISSING_EVALUATION")
    else:
        status = str(evaluation.get("status") or "").upper() or "OPEN"
        outcome = str(evaluation.get("outcome") or "").upper() or "PENDING"
        pnl = _number(evaluation.get("net_pnl_pct"))
        gross = _number(evaluation.get("gross_pnl_pct"))
        failure_reason = str(evaluation.get("failureReason") or evaluation.get("failure_reason") or "").upper()
        diagnostic_reason = str(evaluation.get("diagnosticReason") or "").upper()
        if status == "EVALUATED" and pnl is None:
            flags.append("EVALUATED_WITHOUT_NET_PNL")
        if status in {"PENDING", "DATA_PENDING", "OPEN"} and pnl is not None:
            flags.append("PENDING_WITH_NET_PNL")
        if gross is not None and pnl is not None and pnl > gross + 0.05:
            flags.append("NET_RETURN_EXCEEDS_GROSS")
        if outcome in LOSS_OUTCOMES and pnl is not None and pnl >= 0:
            flags.append("LOSS_OUTCOME_WITH_NONNEGATIVE_PNL")
        if outcome in WIN_OUTCOMES and pnl is not None and pnl <= 0:
            flags.append("WIN_OUTCOME_WITH_NONPOSITIVE_PNL")
        if pnl is not None and pnl < 0 and not (failure_reason or diagnostic_reason):
            flags.append("LOSS_WITHOUT_FAILURE_REASON")

    audit_status = "INVALID" if any(flag.startswith(("INVALID", "MISSING_PRICE", "EVALUATED_WITHOUT")) for flag in flags) else "REVIEW" if flags else "PASS"
    return {
        "journal_id": journal.get("journal_id", ""),
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "symbol": journal.get("symbol", ""),
        "as_of_date": journal.get("as_of_date", ""),
        "entry_type": journal.get("entry_type", ""),
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "risk_reward_ratio": _number(journal.get("risk_reward_ratio")),
        "probability": _number(journal.get("probability")),
        "market_regime_at_signal": journal.get("market_regime_at_signal", ""),
        "status": status,
        "outcome": outcome,
        "net_pnl_pct": pnl,
        "gross_pnl_pct": gross,
        "mfe_pct": _number((evaluation or {}).get("mfe_pct")),
        "mae_pct": _number((evaluation or {}).get("mae_pct")),
        "bars_held": _number((evaluation or {}).get("bars_held")),
        "failure_reason": failure_reason,
        "diagnostic_reason": diagnostic_reason,
        "audit_status": audit_status,
        "audit_flags": "|".join(flags),
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _strategy_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["net_pnl_pct"] is not None:
            groups[_strategy_key(row)].append(row)
    output: list[dict[str, Any]] = []
    for key, items in sorted(groups.items()):
        pnls = [float(item["net_pnl_pct"]) for item in items]
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value <= 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        output.append({
            "strategy": key,
            "trades": len(pnls),
            "winRate": round(len(wins) / len(pnls) * 100, 2),
            "avgPnlPct": _mean(pnls),
            "avgWinPct": _mean(wins),
            "avgLossPct": _mean(losses),
            "profitFactor": round(gross_profit / gross_loss, 4) if gross_loss else None,
            "lossToWinMagnitude": round(abs(_mean(losses) or 0) / (_mean(wins) or 1), 4) if wins else None,
        })
    return output


def audit() -> dict[str, Any]:
    journal_rows = _read_csv(JOURNAL_CSV)
    evaluations = _latest_evaluations(_read_csv(EVALUATION_CSV))
    natural_counts = Counter(
        "|".join(str(row.get(key) or "") for key in ("source_type", "journal_session", "as_of_date", "market", "mode", "horizon", "symbol"))
        for row in journal_rows
    )
    audited = [
        _audit_row(
            row,
            evaluations.get(str(row.get("journal_id") or "")),
            natural_counts["|".join(str(row.get(key) or "") for key in ("source_type", "journal_session", "as_of_date", "market", "mode", "horizon", "symbol"))] > 1,
        )
        for row in journal_rows
    ]
    flags = Counter(flag for row in audited for flag in row["audit_flags"].split("|") if flag)
    outcomes = Counter(row["outcome"] for row in audited)
    failure_reasons = Counter(row["failure_reason"] or row["diagnostic_reason"] for row in audited if row["net_pnl_pct"] is not None and float(row["net_pnl_pct"]) < 0)
    summary = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": {"journal": str(JOURNAL_CSV.relative_to(ROOT)), "evaluations": str(EVALUATION_CSV.relative_to(ROOT))},
        "totalJournalRows": len(audited),
        "latestEvaluationRows": len(evaluations),
        "auditStatusCounts": dict(Counter(row["audit_status"] for row in audited)),
        "outcomeCounts": dict(outcomes),
        "auditFlagCounts": dict(flags),
        "lossFailureReasonCounts": dict(failure_reasons.most_common()),
        "strategyPerformance": _strategy_summary(audited),
        "policy": "Only rows with a realized net_pnl_pct are performance evidence. Pending, cancelled, and invalid rows are kept for audit but excluded from strategy returns.",
    }
    AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(audited[0].keys()) if audited else ["journal_id", "audit_status", "audit_flags"]
    with AUDIT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audited)
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    summary = audit()
    print(json.dumps({
        "totalJournalRows": summary["totalJournalRows"],
        "auditStatusCounts": summary["auditStatusCounts"],
        "auditFlagCounts": summary["auditFlagCounts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
