"""Run the self-contained AI paper-trading operating cycle."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.services import ai_paper_trader, virtual_trade_journal as vtj  # noqa: E402


EVALUATION_PATH = ROOT / "data" / "virtual_trade_evaluations.csv"
JOURNAL_PATH = ROOT / "data" / "virtual_trade_journal.csv"
SUPERVISOR_STATUS_PATH = ROOT / "data" / "paper" / "ai_paper_supervisor_status.json"


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def _latest_evaluations(rows: list[dict[str, str]], journal_ids: set[str]) -> tuple[list[dict[str, str]], dict[str, int]]:
    latest: dict[str, dict[str, str]] = {}
    dropped_missing_id = 0
    dropped_orphan = 0
    dropped_superseded = 0
    for row in rows:
        journal_id = str(row.get("journal_id") or "").strip()
        if not journal_id:
            dropped_missing_id += 1
            continue
        if journal_id not in journal_ids:
            dropped_orphan += 1
            continue
        previous = latest.get(journal_id)
        if previous is None or str(row.get("evaluated_at") or "") >= str(previous.get("evaluated_at") or ""):
            if previous is not None:
                dropped_superseded += 1
            latest[journal_id] = row
        else:
            dropped_superseded += 1
    return list(latest.values()), {
        "droppedMissingId": dropped_missing_id,
        "droppedOrphan": dropped_orphan,
        "droppedSuperseded": dropped_superseded,
    }


def repair_evaluation_ledger() -> dict[str, Any]:
    journal_rows, _ = _read_csv(JOURNAL_PATH)
    evaluation_rows, fields = _read_csv(EVALUATION_PATH)
    journal_ids = {str(row.get("journal_id") or "").strip() for row in journal_rows}
    journal_ids.discard("")
    canonical, dropped = _latest_evaluations(evaluation_rows, journal_ids)
    canonical.sort(key=lambda row: str(row.get("journal_id") or ""))
    changed = len(canonical) != len(evaluation_rows)
    if changed:
        with EVALUATION_PATH.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(canonical)
    return {
        "status": "REPAIRED" if changed else "OK",
        "journalRows": len(journal_rows),
        "beforeRows": len(evaluation_rows),
        "afterRows": len(canonical),
        "changed": changed,
        **dropped,
    }


def run_supervisor(market: str = "all", execute: bool = False) -> dict[str, Any]:
    repair = repair_evaluation_ledger()
    evaluation = vtj.evaluate(market=market, limit=500)
    repair_after_evaluation = repair_evaluation_ledger()
    journal = vtj.ops_dashboard(market=market)
    operational = journal.get("operational") or {}
    if operational.get("recordingStatus") != "OK" or operational.get("evaluationStatus") != "OK":
        paper: dict[str, Any] = {
            "status": "SKIPPED",
            "reason": "JOURNAL_INTEGRITY_NOT_READY",
            "dryRun": not execute,
        }
    else:
        paper = ai_paper_trader.run_cycle(market=market, dry_run=not execute)

    payload = {
        "status": "OK" if paper.get("status") == "OK" else "ATTENTION",
        "lastRunAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "market": market,
        "execute": execute,
        "repair": repair,
        "repairAfterEvaluation": repair_after_evaluation,
        "evaluation": {
            "status": evaluation.get("status"),
            "evaluated": evaluation.get("evaluated", 0),
            "outcomes": evaluation.get("outcomes", {}),
        },
        "journal": {
            "status": operational.get("status"),
            "recordingStatus": operational.get("recordingStatus"),
            "evaluationStatus": operational.get("evaluationStatus"),
            "latestCapturedAt": operational.get("latestCapturedAt"),
            "latestEvaluatedAt": operational.get("latestEvaluatedAt"),
        },
        "paper": paper,
    }
    SUPERVISOR_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUPERVISOR_STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MONE AI paper-trading supervisor.")
    parser.add_argument("--market", choices=["kr", "us", "all"], default="all")
    parser.add_argument("--execute", action="store_true", help="Write eligible AI-paper trades and NAV snapshots.")
    args = parser.parse_args()
    print(json.dumps(run_supervisor(market=args.market, execute=args.execute), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
